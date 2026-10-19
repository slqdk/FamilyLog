"""Alf on the family's Dagbog and Cyklus (FamilyLog 0.3.11).

Søren: "Kan Alf også svare på spørgsmål til Sannes cyklus eller dagbogen?"

Alf gets exactly what the person asking can see in the app themselves, and
nothing more - the same functions the pages use, with the same checks:

- **Dagbog**: their own days; a family account or the administrator also
  the family's days (text and photo only of a shared day). A user account
  sees only its own.
- **Cyklus**: her own cycle, when she logs one; someone else's only when
  she shares it with the person asking - and only what she shares (the
  fertile days with "share fertile", her symptoms with "details"; never
  her note).

The model is the app's own (Ollama on the family's server); the text is
built here and goes with the one question. Nothing is stored beyond the
conversation itself.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.core import db

from ..cyklus import cyklus
from ..dagbog import dagbog

DAYS_BACK = 21             # the days written out in full
STATS_DAYS = 90            # the period the summary covers
WEEKDAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
SELF_WORDS = {"mig", "jeg", "min", "mit", "mine", "selv", "me", "i", "my", "myself"}

ANSWER_PROMPT = """Du er Alf, en venlig hjælper i familiens app FamilyLog. I dag er det %(today)s.
Du taler med %(name)s. Nedenfor står det fra familiens Dagbog og Cyklus, som %(name)s selv kan se i appen.
- Svar KUN ud fra oplysningerne nedenfor. Står svaret ikke der, så sig det - gæt aldrig.
- Kald folk ved deres navn. Svar kort, varmt og på det sprog der spørges på.
- Tal og datoer skal passe præcist med oplysningerne. Nævn hvor mange dage et snit bygger på, når det er få.
- Cyklus er beregnet ud fra kalenderen: sig at det er et skøn, aldrig prævention eller medicinsk rådgivning.
- Vær diskret og respektfuld: beskriv, døm ikke. Ved bekymring for helbredet: foreslå at tale med personen
  eller en læge.
- Står der at noget ikke deles, så sig at personen ikke deler det."""


# ---- who may be asked about ----------------------------------------------------------------------

def _people(asker: dict) -> list[dict]:
    """Everyone whose Dagbog or Cyklus the asker can see, the asker first."""
    with db.connect() as con:
        rows = con.execute("SELECT * FROM users ORDER BY username").fetchall()
    shares = {c["id"] for c in cyklus.shared_with(asker["id"])}
    out = []
    for r in rows:
        keys = r.keys()
        u = {"id": r["id"], "username": r["username"], "role": r["role"],
             "name": (r["name"] if "name" in keys else "") or "", "gender": r["gender"] or ""}
        own = u["id"] == asker["id"]
        diary = own or (dagbog.is_family(asker) and u["role"] in dagbog.FAMILY_ROLES)
        cycle = (own and cyklus.is_female(asker)) or u["id"] in shares
        if diary or cycle:
            out.append({**u, "own": own, "diary": diary, "cycle": cycle})
    out.sort(key=lambda p: (not p["own"], p["username"].lower()))
    return out


def _label(p: dict) -> str:
    if p["name"]:
        return f"{p['name']} (konto {p['username']})"
    return p["username"]


def match(people: list[dict], person: str | None) -> tuple[list[dict], str | None]:
    """The people the question is about: one named (name, username, or the
    start of either), "mig", or - when none is named - everyone visible.
    Returns (people, a name that matched no one)."""
    want = " ".join(str(person or "").lower().split())
    if not want or want in ("null", "none", "alle", "familien", "everyone", "all"):
        return people, None
    if want in SELF_WORDS:
        return [p for p in people if p["own"]], None
    for test in (lambda s: s == want, lambda s: s.startswith(want), lambda s: want in s):
        hit = [p for p in people
               if any(test(s) for s in (p["name"].lower(), p["username"].lower()) if s)
               or any(test(w) for w in p["name"].lower().split())]
        if hit:
            return hit, None
    return [], person


# ---- what they can see -----------------------------------------------------------------------------

def _hours(minutes: int) -> str:
    h, half = divmod(minutes, 60)
    return f"{h}{',5' if half >= 30 else ''} t"


def _day_line(e: dict) -> str:
    d = date.fromisoformat(e["day"])
    bits = [f"{e['day']} ({WEEKDAYS[d.weekday()]})"]
    if e.get("mood") is not None:
        bits.append(f"humør {e['mood']}/5")
    if e.get("mental") is not None:
        bits.append(f"mentalt overskud {e['mental']}/10")
    if e.get("exercise") is not None:
        bits.append(f"motion {_hours(e['exercise'])}")
    if e.get("soda") is not None:
        bits.append(f"sodavand {e['soda']} glas")
    if e.get("alcohol") is not None:
        bits.append(f"alkohol {e['alcohol']} {'genstand' if e['alcohol'] == 1 else 'genstande'}")
    if e.get("tags"):
        bits.append("lavede: " + ", ".join(e["tags"]))
    if e.get("foods"):
        bits.append("spiste: " + ", ".join(e["foods"]))
    if e.get("sick"):
        bits.append("syg/skadet: " + ", ".join(e["sick"]) + (f" ({e['sickNote']})" if e.get("sickNote") else ""))
    if e.get("highlight"):
        bits.append(f'dagens tekst: "{e["highlight"][:400]}"')
    if e.get("hasPhoto"):
        bits.append("har et billede")
    return "- " + "; ".join(bits)


def _diary(asker: dict, p: dict) -> list[str]:
    page = dagbog.person_days(asker, p["id"], None, DAYS_BACK)
    if not page["total"]:
        return ["Dagbog: ingen dage skrevet endnu."]
    lines = [f"Dagbog: {page['total']} dage skrevet i alt, den første {page['firstDay']}."]
    frm = (date.today() - timedelta(days=STATS_DAYS - 1)).isoformat()
    s = dagbog.stats(asker, p["id"], frm, None)
    if s["days"]:
        sums = [f"de sidste {STATS_DAYS} dage: {s['days']} dage skrevet ({s['coverage']}% af dagene)"]
        if s.get("mood") is not None:
            sums.append(f"humør {s['mood']}/5 i snit")
        if s.get("mental") is not None:
            sums.append(f"mentalt overskud {s['mental']}/10 i snit")
        for key, what, unit in (("exercise", "motion", "min"), ("alcohol", "alkohol", "genstande"),
                                ("soda", "sodavand", "glas")):
            a = (s.get("amounts") or {}).get(key)
            if a:
                total = _hours(a["total"]) if key == "exercise" else f"{a['total']} {unit}"
                week = (f", {_hours(round(a['perWeek']))} om ugen i snit" if key == "exercise" else
                        f", {a['perWeek']} {unit} om ugen i snit") if a["perWeek"] is not None else ""
                sums.append(f"{what} {total} i alt på {a['days']} {'dag' if a['days'] == 1 else 'dage'}{week}")
        if s.get("sickDays"):
            sums.append(f"{s['sickDays']} dage syg eller skadet")
        lines.append("Opsummering " + "; ".join(sums) + ".")
        if s.get("topTags"):
            lines.append("Mest lavet: " + ", ".join(f"{t['name']} ({t['days']} dage)" for t in s["topTags"][:6]) + ".")
        if s.get("topFoods"):
            lines.append("Mest spist: " + ", ".join(f"{t['name']} ({t['days']} dage)" for t in s["topFoods"][:6]) + ".")
        if s.get("months") and len(s["months"]) > 1:
            lines.append("Humør pr. måned: " + ", ".join(
                f"{m['month']} {m['mood']}" for m in s["months"] if m["mood"] is not None) + ".")
        if s.get("links"):
            lines.append("Går sammen med humøret (ikke nødvendigvis årsag): " + "; ".join(
                f"{x['label']}: {x['with']} med mod {x['without']} uden" for x in s["links"][:5]) + ".")
    lines.append(f"De seneste {len(page['entries'])} dage:")
    lines += [_day_line(e) for e in page["entries"]]
    return lines


def _cycle_own(user_id: int) -> list[str]:
    st = cyklus.status(user_id)
    if st["empty"]:
        return ["Cyklus: intet logget endnu."]
    lines = []
    if "phase" in st:
        lines.append(f"Cyklus i dag: cyklusdag {st['cycleDay']}, {st['phaseLabel']}"
                     + (f" (menstruationsdag {st['periodDay']})" if st.get("inPeriod") else "") + ".")
    avg = st.get("averages") or {}
    if avg.get("cycle"):
        lines.append(f"Cykluslængde {avg['cycle']} dage i snit, menstruation {avg.get('period')} dage"
                     f" ({avg.get('cyclesMeasured', 0)} cyklusser målt).")
    if st.get("nextStart"):
        lines.append(f"Næste menstruation ventes {st['nextStart']}"
                     + (f" (den er {st['late']} dage forsinket)" if st.get("late") else "") + ".")
    if st.get("fertileFrom"):
        lines.append(f"Frugtbare dage {st['fertileFrom']} til {st['fertileTo']}, ægløsning omkring {st['ovulation']}.")
    if st.get("phase"):
        f = cyklus.forecast_for(st["phase"], cyklus.patterns(user_id).get(
            "fertile" if st["phase"] in ("fertile", "ovulation") else st["phase"]))
        lines += _forecast_lines(f)
    week = cyklus.forecast(user_id, 14)
    lines.append("De næste 14 dage: " + _week(week) + ".")
    return lines


KINDS = {"period": "menstruation", "predicted": "ventet menstruation", "possible": "mulig menstruation",
         "fertile": "frugtbar", "ovulation": "ægløsning", "pms": "PMS", "": "-"}


def _week(days: list[dict]) -> str:
    return ", ".join(f"{w['day']} {KINDS.get(w['kind'], w['kind'])}" for w in days)


def _forecast_lines(f: dict) -> list[str]:
    out = []
    if f.get("items"):
        out.append("Forventet i dag (skøn): " + ", ".join(f"{i['label']} {i['value']}/5" for i in f["items"]) + ".")
    if f.get("behaviour"):
        out.append(f"Forventet adfærd: {f['behaviour']}")
    if f.get("expect"):
        out.append("Kan opleve: " + ", ".join(f["expect"]) + ".")
    return out


def _cycle_shared(card: dict) -> list[str]:
    if card["empty"] or "phase" not in card:
        return ["Cyklus (delt): intet at vise endnu."]
    lines = [f"Cyklus (delt med dig): cyklusdag {card['cycleDay']}, {card['phaseLabel']}"
             + (f" (menstruationsdag {card['periodDay']})" if card.get("inPeriod") else "") + "."]
    if card.get("nextStart"):
        lines.append(f"Næste menstruation ventes {card['nextStart']}"
                     + (f" (den er {card['late']} dage forsinket)" if card.get("late") else "") + ".")
    if card.get("fertileFrom"):
        lines.append(f"Frugtbare dage {card['fertileFrom']} til {card['fertileTo']}.")
    else:
        lines.append("Hun deler ikke de frugtbare dage.")
    lines += _forecast_lines(card.get("forecast") or {})
    if card.get("todayLog"):
        t = card["todayLog"]
        logged = [x for x in (t.get("flow"), ", ".join(t.get("symptoms") or []), ", ".join(t.get("moods") or [])) if x]
        if logged:
            lines.append("Logget i dag: " + "; ".join(logged) + ".")
    elif not card.get("shareDetails"):
        lines.append("Hun deler ikke sine symptomer og humør fra cyklus-loggen.")
    if card.get("week"):
        lines.append("De næste 7 dage: " + _week(card["week"]) + ".")
    return lines


def gather(asker: dict, person: str | None) -> dict:
    """The text Alf answers from: {"context", "people", "missing"}."""
    people = _people(asker)
    chosen, missing = match(people, person)
    cards = {c["id"]: c for c in cyklus.shared_with(asker["id"])}
    blocks = []
    for p in chosen[:6]:
        lines = [f"## {_label(p)}" + (" - det er dig selv" if p["own"] else "")]
        if p["diary"]:
            lines += _diary(asker, p)
        else:
            lines.append("Dagbog: ikke synlig for dig.")
        if p["own"] and p["cycle"]:
            lines += _cycle_own(p["id"])
        elif p["id"] in cards:
            lines += _cycle_shared(cards[p["id"]])
        blocks.append("\n".join(lines))
    visible = ", ".join(_label(p) for p in people) or "ingen"
    head = f"Personer {asker['username']} kan se: {visible}."
    if missing:
        head += (f'\nDer blev spurgt om "{missing}", men det passer ikke på nogen af dem - '
                 "enten findes personen ikke, eller også kan den der spørger ikke se personens Dagbog/Cyklus.")
    return {"context": head + "\n\n" + "\n\n".join(blocks), "people": [p["name"] or p["username"] for p in chosen],
            "missing": missing}
