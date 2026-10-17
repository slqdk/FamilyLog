"""Cyklus (FamilyLog 0.3.0): a period log and cycle forecast for accounts
set to female.

She logs when a period starts and ends, and per day the flow, symptoms and
mood (and a note). From that: her cycle day and phase, the next period, the
fertile window, PMS days, and her own patterns - which symptoms and moods
she tends to log in each phase, and her Dagbog mood per phase.

Privacy, as Søren chose it: she decides who sees anything. Nobody - the
administrator included - sees her cycle unless she shares it with that
account. Sharing shows her status (phase, cycle day, next period); the
fertile window and her day's symptoms/mood/patterns only when she ticks
those too. Her note is never shared. All of this is enforced here, in what
the queries return.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from app.core import db

from . import predict
from .predict import Period

FLOWS = {"plet": "Pletblødning", "let": "Let", "middel": "Middel", "kraftig": "Kraftig"}
SYMPTOMS = ["Kramper", "Ømme bryster", "Hovedpine", "Rygsmerter", "Oppustet", "Akne",
            "Træt", "Søvnbesvær", "Trang til søde sager", "Kvalme", "Svimmel", "Ingen gener"]
MOODS = ["Glad", "Rolig", "Energisk", "Følsom", "Irritabel", "Trist", "Urolig",
         "Humørsvingninger", "Stresset"]
MAX_NOTE = 1000
MAX_DAYS_BACK = 3 * 366
MAX_RANGE = 186
MAX_DAYS_AHEAD = 366

PHASES = {
    "menstruation": {
        "label": "Menstruation",
        "self": "Kroppen bruger energi nu. Kramper og træthed er almindeligt - varme, hvile og "
                "let bevægelse hjælper mange.",
        "shared": "Energien kan være lav. Varme, ro og en hjælpende hånd i hverdagen gør en forskel."},
    "follicular": {
        "label": "Follikelfase",
        "self": "Energien stiger typisk efter menstruationen. En god tid til nye ting og mere aktivitet.",
        "shared": "Energien er typisk på vej op efter menstruationen."},
    "fertile": {
        "label": "Frugtbare dage",
        "self": "Mange har mest energi og overskud nu og har lyst til at være sociale.",
        "shared": "Mange har mest energi og overskud i de her dage."},
    "ovulation": {
        "label": "Ægløsning (anslået)",
        "self": "Ægløsning ifølge kalenderen. Nogle mærker et lille stik i den ene side.",
        "shared": "Mange har mest energi og overskud i de her dage."},
    "luteal": {
        "label": "Lutealfase",
        "self": "Efter ægløsningen falder energien ofte lidt. Søvn og faste måltider hjælper.",
        "shared": "Energien kan være lidt lavere end sidst i cyklussen."},
    "pms": {
        "label": "PMS-dage",
        "self": "De sidste dage før menstruationen: humøret kan svinge, og man kan være mere træt, "
                "følsom eller irritabel.",
        "shared": "PMS er sandsynlig: humøret kan svinge. Lidt ekstra tålmodighed og overskud hjælper."},
}
DISCLAIMER = "Beregnet ud fra kalenderen og din log - ikke prævention og ikke medicinsk rådgivning."


class Invalid(ValueError):
    pass


class NotFound(LookupError):
    pass


class Forbidden(PermissionError):
    pass


# ---- who ------------------------------------------------------------------------------------------

def is_female(user: dict) -> bool:
    return (user.get("gender") or "") == "female"


def require_female(user: dict) -> None:
    if not is_female(user):
        raise Forbidden("Cyklus er for konti, der er sat til kvinde (Indstillinger → Konti).")


def _day(s, *, future_ok: bool = False) -> date:
    try:
        d = date.fromisoformat(str(s))
    except ValueError:
        raise Invalid("Ugyldig dato.")
    today = date.today()
    if d > today and not future_ok:
        raise Invalid("Den dag er ikke kommet endnu.")
    if (d - today).days > MAX_DAYS_AHEAD:
        raise Invalid("Den dag er for langt ude i fremtiden.")
    if (today - d).days > MAX_DAYS_BACK:
        raise Invalid("Den dag er for længe siden.")
    return d


# ---- reading ----------------------------------------------------------------------------------------

def periods(user_id: int) -> list[dict]:
    with db.connect() as con:
        return [{"id": r["id"], "start": r["start"], "end": r["end"]} for r in con.execute(
            "SELECT id, start, end FROM cyklus_periods WHERE user_id=? ORDER BY start", (user_id,))]


def _periods(user_id: int) -> list[Period]:
    return [Period(date.fromisoformat(p["start"]), date.fromisoformat(p["end"]) if p["end"] else None)
            for p in periods(user_id)]


def settings(user_id: int) -> dict:
    with db.connect() as con:
        r = con.execute("SELECT * FROM cyklus_settings WHERE user_id=?", (user_id,)).fetchone()
        viewers = [x["viewer_id"] for x in con.execute(
            "SELECT viewer_id FROM cyklus_shares WHERE owner_id=? ORDER BY viewer_id", (user_id,))]
    return {"cycleLength": r["cycle_length"] if r else None,
            "periodLength": r["period_length"] if r else None,
            "shareFertile": bool(r["share_fertile"]) if r else False,
            "shareDetails": bool(r["share_details"]) if r else False,
            "viewers": viewers}


def _flow_days(user_id: int) -> set[date]:
    with db.connect() as con:
        return {date.fromisoformat(r["day"]) for r in con.execute(
            "SELECT day FROM cyklus_days WHERE user_id=? AND flow IN ('let','middel','kraftig')",
            (user_id,))}


def _day_row(r) -> dict:
    return {"day": r["day"], "flow": r["flow"], "symptoms": json.loads(r["symptoms"] or "[]"),
            "moods": json.loads(r["moods"] or "[]"), "note": r["note"]}


def get_day(user_id: int, day: str) -> dict:
    d = _day(day, future_ok=True)
    with db.connect() as con:
        r = con.execute("SELECT * FROM cyklus_days WHERE user_id=? AND day=?",
                        (user_id, d.isoformat())).fetchone()
    return _day_row(r) if r else {"day": d.isoformat(), "flow": "", "symptoms": [], "moods": [], "note": ""}


def _context(user_id: int, today: date | None = None):
    today = today or date.today()
    s = settings(user_id)
    return (_periods(user_id), today, s["cycleLength"], s["periodLength"], _flow_days(user_id), s)


def status(user_id: int, today: date | None = None) -> dict:
    ps, today, cl, pl, flows, s = _context(user_id, today)
    st = predict.status(ps, today, cl, pl, flows)
    st["today"] = today.isoformat()
    if not st["empty"] and "phase" in st:
        info = PHASES[st["phase"]]
        st["phaseLabel"], st["phaseText"] = info["label"], info["self"]
    return st


def calendar(user_id: int, frm: str, to: str, today: date | None = None) -> list[dict]:
    a, b = _day(frm, future_ok=True), _day(to, future_ok=True)
    if b < a or (b - a).days > MAX_RANGE:
        raise Invalid(f"Højst {MAX_RANGE} dage ad gangen.")
    ps, today, cl, pl, flows, _s = _context(user_id, today)
    kinds = predict.day_kinds(ps, a, b, today, cl, pl, flows)
    with db.connect() as con:
        logs = {r["day"]: r for r in con.execute(
            "SELECT * FROM cyklus_days WHERE user_id=? AND day BETWEEN ? AND ?",
            (user_id, a.isoformat(), b.isoformat()))}
    out = []
    for d, k in sorted(kinds.items()):
        r = logs.get(d.isoformat())
        out.append({"day": d.isoformat(), "kind": k, "flow": r["flow"] if r else "",
                    "logged": bool(r and (r["flow"] or r["symptoms"] != "[]" or r["moods"] != "[]"
                                          or r["note"]))})
    return out


def forecast(user_id: int, days: int = 7, today: date | None = None) -> list[dict]:
    """The coming days' phases (today first)."""
    ps, today, cl, pl, flows, _s = _context(user_id, today)
    if not ps:
        return []
    kinds = predict.day_kinds(ps, today, today + timedelta(days=days - 1), today, cl, pl, flows)
    return [{"day": d.isoformat(), "kind": k} for d, k in sorted(kinds.items())]


def patterns(user_id: int, today: date | None = None) -> dict:
    """What she tends to log in each phase, and her Dagbog mood per phase.
    Only what she logged at least twice and on a third of that phase's
    logged days - one bad day is not a pattern."""
    ps, today, cl, pl, flows, _s = _context(user_id, today)
    if not ps:
        return {}
    with db.connect() as con:
        logs = con.execute("SELECT day, symptoms, moods FROM cyklus_days WHERE user_id=?",
                           (user_id,)).fetchall()
        try:
            diary = con.execute("SELECT day, mood, mental FROM dagbog_entries WHERE user_id=?",
                                (user_id,)).fetchall()
        except Exception:                                     # noqa: BLE001 - no Dagbog table
            diary = []
    all_days = sorted({date.fromisoformat(r["day"]) for r in logs}
                      | {date.fromisoformat(r["day"]) for r in diary})
    phase = predict.phase_by_day(ps, all_days, today, cl, pl, flows)

    def key(p: str) -> str:
        return "fertile" if p == "ovulation" else p
    out: dict[str, dict] = {}
    for r in logs:
        p = phase.get(date.fromisoformat(r["day"]))
        items = json.loads(r["symptoms"] or "[]") + json.loads(r["moods"] or "[]")
        if p is None or not items:
            continue
        e = out.setdefault(key(p), {"days": 0, "counts": {}, "mood": [], "mental": []})
        e["days"] += 1
        for it in items:
            if it != "Ingen gener":
                e["counts"][it] = e["counts"].get(it, 0) + 1
    for r in diary:
        p = phase.get(date.fromisoformat(r["day"]))
        if p is None:
            continue
        e = out.setdefault(key(p), {"days": 0, "counts": {}, "mood": [], "mental": []})
        if r["mood"] is not None:
            e["mood"].append(r["mood"])
        if r["mental"] is not None:
            e["mental"].append(r["mental"])
    result = {}
    for p, e in out.items():
        top = sorted(((n, c) for n, c in e["counts"].items() if c >= 2 and c * 3 >= e["days"]),
                     key=lambda x: (-x[1], x[0]))[:4]
        result[p] = {"label": PHASES[p]["label"], "days": e["days"],
                     "top": [{"name": n, "count": c} for n, c in top],
                     "mood": round(sum(e["mood"]) / len(e["mood"]), 1) if len(e["mood"]) >= 3 else None,
                     "mental": round(sum(e["mental"]) / len(e["mental"]), 1) if len(e["mental"]) >= 3 else None}
    return result


def own(user_id: int) -> dict:
    s = settings(user_id)
    return {"status": status(user_id), "forecast": forecast(user_id), "patterns": patterns(user_id),
            "periods": history(user_id), "settings": s, "today": get_day(user_id, date.today().isoformat())}


def history(user_id: int) -> list[dict]:
    """Her periods, newest first, with each cycle's length."""
    ps = periods(user_id)
    out = []
    for i, p in enumerate(ps):
        nxt = ps[i + 1]["start"] if i + 1 < len(ps) else None
        cyc = (date.fromisoformat(nxt) - date.fromisoformat(p["start"])).days if nxt else None
        days = ((date.fromisoformat(p["end"]) - date.fromisoformat(p["start"])).days + 1
                if p["end"] else None)
        out.append({**p, "periodDays": days, "cycleLength": cyc})
    return out[::-1]


# ---- writing ----------------------------------------------------------------------------------------

def _clean_list(values, allowed: list[str], what: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise Invalid(f"{what} skal være en liste.")
    by = {a.lower(): a for a in allowed}
    out: list[str] = []
    for v in values:
        a = by.get(str(v).strip().lower())
        if a is None:
            raise Invalid(f"Ukendt {what.lower()}: {v}")
        if a not in out:
            out.append(a)
    return out


def save_day(user_id: int, body: dict) -> dict:
    d = _day(body.get("day"))
    flow = body.get("flow") or ""
    if not isinstance(flow, str) or (flow not in FLOWS and flow != ""):
        raise Invalid("Ukendt blødning.")
    symptoms = _clean_list(body.get("symptoms"), SYMPTOMS, "Symptom")
    moods = _clean_list(body.get("moods"), MOODS, "Humør")
    note = str(body.get("note") or "").strip()
    if len(note) > MAX_NOTE:
        raise Invalid(f"Noten er for lang (højst {MAX_NOTE} tegn).")
    with db.connect() as con:
        if not (flow or symptoms or moods or note):
            con.execute("DELETE FROM cyklus_days WHERE user_id=? AND day=?", (user_id, d.isoformat()))
        else:
            con.execute(
                "INSERT INTO cyklus_days (user_id, day, flow, symptoms, moods, note, updated_at)"
                " VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_id, day) DO UPDATE SET flow=excluded.flow,"
                " symptoms=excluded.symptoms, moods=excluded.moods, note=excluded.note,"
                " updated_at=excluded.updated_at",
                (user_id, d.isoformat(), flow, json.dumps(symptoms, ensure_ascii=False),
                 json.dumps(moods, ensure_ascii=False), note, db.utcnow()))
    return get_day(user_id, d.isoformat())


def start_period(user_id: int, day: str) -> dict:
    """A period started on `day`. One still un-ended and started within
    MAX_OPEN days before is the same period (refused - end it, or delete
    it); an older un-ended one is closed at her usual length."""
    d = _day(day)
    plen = predict.averages(_periods(user_id))["period"]
    with db.connect() as con:
        rows = con.execute("SELECT id, start, end FROM cyklus_periods WHERE user_id=? ORDER BY start",
                           (user_id,)).fetchall()
        for r in rows:
            s = date.fromisoformat(r["start"])
            e = date.fromisoformat(r["end"]) if r["end"] else None
            if s == d or (e and s <= d <= e):
                raise Invalid("Der er allerede en menstruation den dag.")
            if e is None and s < d < s + timedelta(days=predict.MAX_OPEN):
                raise Invalid(f"Menstruationen fra {s.strftime('%d.%m')} er ikke afsluttet endnu.")
            if s > d and (s - d).days < predict.MIN_CYCLE:
                raise Invalid(f"Den ligger for tæt på menstruationen fra {s.strftime('%d.%m')}.")
        for r in rows:
            s = date.fromisoformat(r["start"])
            if r["end"] is None and s < d:
                end = min(s + timedelta(days=plen - 1), d - timedelta(days=1))
                con.execute("UPDATE cyklus_periods SET end=?, updated_at=? WHERE id=?",
                            (end.isoformat(), db.utcnow(), r["id"]))
        later = [date.fromisoformat(r["start"]) for r in rows if date.fromisoformat(r["start"]) > d]
        end = None
        if later:                    # a past period logged between two others is closed
            end = min(d + timedelta(days=plen - 1), later[0] - timedelta(days=1)).isoformat()
        con.execute("INSERT INTO cyklus_periods (user_id, start, end, created_at, updated_at)"
                    " VALUES (?,?,?,?,?)", (user_id, d.isoformat(), end, db.utcnow(), db.utcnow()))
    return status(user_id)


def end_period(user_id: int, day: str) -> dict:
    """The latest period that started on or before `day` ended on `day`."""
    d = _day(day)
    with db.connect() as con:
        r = con.execute("SELECT id, start FROM cyklus_periods WHERE user_id=? AND start<=?"
                        " ORDER BY start DESC LIMIT 1", (user_id, d.isoformat())).fetchone()
        if r is None:
            raise Invalid("Der er ingen menstruation, der startede før den dag.")
        if (d - date.fromisoformat(r["start"])).days >= predict.MAX_OPEN + 4:
            raise Invalid("Det er længe efter, menstruationen startede - start en ny i stedet.")
        con.execute("UPDATE cyklus_periods SET end=?, updated_at=? WHERE id=?",
                    (d.isoformat(), db.utcnow(), r["id"]))
    return status(user_id)


def edit_period(user_id: int, pid: int, body: dict) -> dict:
    s = _day(body.get("start"))
    e = _day(body["end"]) if body.get("end") else None
    if e and (e < s or (e - s).days >= predict.MAX_OPEN + 4):
        raise Invalid("Slutdatoen passer ikke til starten.")
    with db.connect() as con:
        if con.execute("SELECT 1 FROM cyklus_periods WHERE id=? AND user_id=?",
                       (pid, user_id)).fetchone() is None:
            raise NotFound("Ingen sådan menstruation.")
        others = [date.fromisoformat(r["start"]) for r in con.execute(
            "SELECT start FROM cyklus_periods WHERE user_id=? AND id<>?", (user_id, pid))]
        if any(abs((o - s).days) < predict.MIN_CYCLE for o in others):
            raise Invalid("Den ligger for tæt på en anden menstruation.")
        con.execute("UPDATE cyklus_periods SET start=?, end=?, updated_at=? WHERE id=?",
                    (s.isoformat(), e.isoformat() if e else None, db.utcnow(), pid))
    return status(user_id)


def delete_period(user_id: int, pid: int) -> None:
    with db.connect() as con:
        n = con.execute("DELETE FROM cyklus_periods WHERE id=? AND user_id=?", (pid, user_id)).rowcount
    if not n:
        raise NotFound("Ingen sådan menstruation.")


def save_settings(user_id: int, body: dict) -> dict:
    cur = settings(user_id)

    def num(key, lo, hi):
        v = body.get(key, cur[key])
        if v in (None, ""):
            return None
        if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
            raise Invalid(f"{'Cykluslængde' if key == 'cycleLength' else 'Menstruationslængde'} "
                          f"skal være {lo}-{hi} dage.")
        return v
    cl = num("cycleLength", predict.MIN_CYCLE + 5, predict.MAX_CYCLE)
    pl = num("periodLength", 1, predict.MAX_OPEN)
    sf = body.get("shareFertile", cur["shareFertile"])
    sd = body.get("shareDetails", cur["shareDetails"])
    if not isinstance(sf, bool) or not isinstance(sd, bool):
        raise Invalid("Deling skal være til eller fra (true/false).")
    viewers = body.get("viewers", cur["viewers"])
    if not isinstance(viewers, list):
        raise Invalid("Viewers skal være en liste.")
    with db.connect() as con:
        ids = {r["id"] for r in con.execute("SELECT id FROM users WHERE id<>?", (user_id,))}
        vs = []
        for v in viewers:
            if not isinstance(v, int) or isinstance(v, bool) or v not in ids:
                raise Invalid(f"Ukendt konto: {v}")
            if v not in vs:
                vs.append(v)
        con.execute(
            "INSERT INTO cyklus_settings (user_id, cycle_length, period_length, share_fertile,"
            " share_details, updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET"
            " cycle_length=excluded.cycle_length, period_length=excluded.period_length,"
            " share_fertile=excluded.share_fertile, share_details=excluded.share_details,"
            " updated_at=excluded.updated_at",
            (user_id, cl, pl, int(sf), int(sd), db.utcnow()))
        con.execute("DELETE FROM cyklus_shares WHERE owner_id=?", (user_id,))
        for v in vs:
            con.execute("INSERT INTO cyklus_shares (owner_id, viewer_id) VALUES (?,?)", (user_id, v))
    return settings(user_id)


def candidates(user_id: int) -> list[dict]:
    """The accounts she can share with."""
    with db.connect() as con:
        return [{"id": r["id"], "username": r["username"], "gender": r["gender"] or ""}
                for r in con.execute("SELECT id, username, gender FROM users WHERE id<>? ORDER BY username",
                                     (user_id,))]


# ---- what the people she shares with see -------------------------------------------------------------

def shared_with(viewer_id: int, today: date | None = None) -> list[dict]:
    """Every woman who shares her cycle with this account - only what she
    chose to share. An account no longer set to female shares nothing."""
    today = today or date.today()
    with db.connect() as con:
        owners = con.execute(
            "SELECT u.id, u.username FROM cyklus_shares s JOIN users u ON u.id = s.owner_id"
            " WHERE s.viewer_id=? AND u.gender='female' ORDER BY u.username", (viewer_id,)).fetchall()
    return [_shared_card(o["id"], o["username"], today) for o in owners]


def _shared_card(owner_id: int, name: str, today: date) -> dict:
    s = settings(owner_id)
    st = status(owner_id, today)
    card: dict = {"id": owner_id, "name": name, "today": today.isoformat(),
                  "shareFertile": s["shareFertile"], "shareDetails": s["shareDetails"],
                  "empty": st["empty"]}
    if st["empty"] or "phase" not in st:
        card["stale"] = bool(st.get("stale"))
        return card
    phase = st["phase"]
    if not s["shareFertile"] and phase in ("fertile", "ovulation"):
        # Not shared: the fertile days read as the phase around them, so
        # no label gives the window away.
        phase = "follicular" if today <= date.fromisoformat(st["ovulation"]) else "luteal"
    card.update({"cycleDay": st["cycleDay"], "phase": phase, "phaseLabel": PHASES[phase]["label"],
                 "phaseText": PHASES[phase]["shared"], "inPeriod": st["inPeriod"],
                 "periodDay": st["periodDay"], "nextStart": st["nextStart"],
                 "daysUntilNext": st["daysUntilNext"], "late": st["late"]})
    if s["shareFertile"]:
        card.update({"fertileFrom": st["fertileFrom"], "fertileTo": st["fertileTo"],
                     "ovulation": st["ovulation"], "fertileToday": st["fertileToday"]})
    week = forecast(owner_id, 7, today)
    if not s["shareFertile"]:
        week = [{**w, "kind": "" if w["kind"] in ("fertile", "ovulation") else w["kind"]} for w in week]
    card["week"] = week
    if s["shareDetails"]:
        d = get_day(owner_id, today.isoformat())
        card["todayLog"] = {"flow": d["flow"], "symptoms": d["symptoms"], "moods": d["moods"]}
        pat = patterns(owner_id, today).get("fertile" if phase in ("fertile", "ovulation") else phase)
        # Her Dagbog scores per phase stay hers; the symptoms and moods she
        # logged here are what "details" shares.
        card["pattern"] = {"label": pat["label"], "days": pat["days"], "top": pat["top"]} if pat else None
    return card


def options() -> dict:
    return {"flows": [{"key": k, "label": v} for k, v in FLOWS.items()], "symptoms": SYMPTOMS,
            "moods": MOODS, "disclaimer": DISCLAIMER,
            "phases": {k: v["label"] for k, v in PHASES.items()}}
