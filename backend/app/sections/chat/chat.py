"""Alf on the front page (FamilyLog 0.2.0): a general chat for everyone in
the family, that also knows the family's places.

Each person has one running conversation (stored, so it survives a reload
and a restart); "Ny samtale" archives it and starts again. A message is one
job in the model queue:

1. **Route** - the model reads the last few turns and the new message and
   answers JSON: is this about finding places (food out, playgrounds,
   trips, things to do, where to stay, nature, towns)? It also rewrites the
   message so it stands alone ("og i Flensborg?" -> "pizza i Flensborg").
2. **Places** - Spørg Alf's own search (familymap_ask.gather: the family's
   reviews first, the wishlist, other places, the web when too few fit),
   then Alf answers from that list only, linking places as [[id]].
3. **The family** (0.3.11) - a question about someone's Dagbog or Cyklus
   (or one's own): Alf answers from what the person asking can see in the
   app themselves - see family.py.
4. **Money** (0.3.12) - a question about one's own Økonomi: the same three
   steps as the Økonomi page's own question box (ledger_ask: the model turns
   it into a search, the app counts exactly, the model writes the answer
   from the count only) - on the asker's OWN ledger, never anyone else's.
5. **Anything else** - Alf answers as a friendly general assistant, with the
   conversation so far.

From Økonomi only the asker's own ledger, from the Dagbog and Cyklus only
what the asker can see - and only when the question is about it.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date

from app.core import db, jobqueue, logs, ollama, settings

from ..familymap import familymap as fm, familymap_ask as fm_ask
from ..ledger import ledger, ledger_ask
from . import family

MAX_MESSAGE = 1000
HISTORY_TURNS = 8            # messages of context sent with a new one
QUEUE_BASE = 5_000_000       # queue keys -(QUEUE_BASE + user id): never another's

ROUTE_PROMPT = """Afgør hvad familiemedlemmets SIDSTE besked handler om. Svar KUN med JSON:
{"places": true/false, "family": true/false, "money": true/false, "person": "navnet der spørges om, eller null",
 "question": "beskeden omskrevet så den kan forstås alene"}

- places = true når der spørges efter konkrete steder at tage hen: spisesteder, caféer, is,
  legepladser, udflugter, aktiviteter, svømmehaller, museer, natur, strande, overnatning, byer.
- family = true når der spørges til hvordan en i familien (eller en selv) har det eller har haft det,
  ud fra familiens Dagbog eller Cyklus: humør, overskud, motion, alkohol, sodavand, mad, sygdom,
  hvad de har lavet, dagens tekst, statistik - eller menstruation, cyklus, menstruationen, frugtbare dage,
  ægløsning, PMS, humør/adfærd i cyklussen.
- money = true når der spørges til penge og økonomi ud fra bankens posteringer: forbrug, hvad noget
  har kostet, hvor meget der er brugt hos en butik eller på en kategori (dagligvarer, benzin, abonnementer),
  indtægt, løn, faste udgifter, betalingsservice, MobilePay, hvad pengene går til.
- person: navnet på den der spørges om, som skrevet ("Sanne", "mor"); "mig" når de spørger om sig selv;
  null når det er hele familien eller uklart. Brug samtalen ("hvad med i går?" handler om samme person).
- Højst én af places, family og money er true.
- places, family og money er false for alt andet: viden, opskrifter, lektier, planlægning, sjov.
- question: brug samtalen til at gøre beskeden fuldstændig ("og i Flensborg?" bliver
  "pizza i Flensborg"). Samme sprog som beskeden."""

GENERAL_PROMPT = """Du er Alf, en venlig hjælper i familiens app FamilyLog. Familien bor i Sønderjylland.
I dag er det %(today)s. Du taler med %(name)s.
- Svar på det sprog der skrives på (normalt dansk), kort og klart; brug lister når det hjælper.
- Du kan ikke se internettet her. Spørges der til familiens Dagbog eller Cyklus, kan de spørge direkte,
  fx "hvordan har mor haft det i denne uge?" eller "hvornår får Sanne menstruation?". Om deres egen
  økonomi kan de spørge fx "hvor meget har jeg brugt på dagligvarer i år?".
- Bliver du spurgt om steder at tage hen, så sig at de kan spørge "find en legeplads i Vojens"
  eller lignende, så søger du i familiens egne steder.
- Er du i tvivl, så sig det ærligt."""

DAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]

_jobs: dict[int, dict] = {}


class Invalid(ValueError):
    """Shown to the person as it is (Danish)."""


class Busy(Invalid):
    pass


def queue_key(user_id: int) -> int:
    return -(QUEUE_BASE + user_id)


# ---- storage ------------------------------------------------------------------------------

def _dto(r) -> dict:
    return {"id": r["id"], "role": r["role"], "content": r["content"],
            "places": json.loads(r["places"] or "[]"), "createdAt": r["created_at"],
            "meta": json.loads(r["meta"] or "{}")}


def messages(user_id: int, limit: int = 60) -> list[dict]:
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM chat_messages WHERE user_id = ? AND archived = 0"
            " ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
    return [_dto(r) for r in reversed(rows)]


def add_message(user_id: int, role: str, content: str, places: list | None = None,
                meta: dict | None = None) -> dict:
    with db.connect() as con:
        cur = con.execute(
            "INSERT INTO chat_messages (user_id, role, content, places, meta, archived, created_at)"
            " VALUES (?,?,?,?,?,0,?)",
            (user_id, role, content, json.dumps(places or [], ensure_ascii=False),
             json.dumps(meta or {}, ensure_ascii=False), db.utcnow()))
        r = con.execute("SELECT * FROM chat_messages WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _dto(r)


def new_conversation(user_id: int) -> None:
    stop(user_id)
    with db.connect() as con:
        con.execute("UPDATE chat_messages SET archived = 1 WHERE user_id = ?", (user_id,))
    _jobs.pop(user_id, None)


# ---- the view -----------------------------------------------------------------------------

def view(user_id: int) -> dict:
    out: dict = {"messages": messages(user_id), "job": None,
                 "model": bool(settings.role_model("chat"))}
    j = _jobs.get(user_id)
    if j is not None:
        job = {k: v for k, v in j.items() if not k.startswith("_")}
        if j["state"] == "queued":
            job["ahead"] = jobqueue.position(queue_key(user_id))
        out["job"] = job
    return out


# ---- sending --------------------------------------------------------------------------------

def send(user: dict, text: str, phone: tuple[float, float] | None) -> dict:
    """Store the message and queue Alf's answer. From a running event loop."""
    uid = user["id"]
    text = (text or "").strip()
    if not text:
        raise Invalid("Skriv en besked.")
    if len(text) > MAX_MESSAGE:
        raise Invalid(f"Beskeden er for lang (højst {MAX_MESSAGE} tegn).")
    model = settings.role_model("chat")
    if not model:
        raise Invalid("Alf har ingen model endnu - bed administratoren vælge en chatmodel "
                      "under Indstillinger.")
    old = _jobs.get(uid)
    if old and old["state"] in ("queued", "working"):
        raise Busy("Alf svarer stadig på din sidste besked.")
    history = messages(uid, HISTORY_TURNS)
    add_message(uid, "user", text)
    j = {"state": "queued", "step": "Venter på sin tur…", "phase": "queue", "text": "",
         "places": [], "error": None, "route": None, "searched": None, "where": None,
         "startedAt": time.time(), "finishedAt": None}
    _jobs[uid] = j
    gen: dict = {"text": "", "done": False, "error": None, "model": model}
    j["_gen"] = gen

    def factory():
        async def go():
            try:
                await run(user, text, history, phone, model, j)
            finally:
                gen["done"] = True
        return go()
    jobqueue.submit(queue_key(uid), "chat", gen, factory)
    return view(uid)


def stop(user_id: int) -> dict:
    j = _jobs.get(user_id)
    if j and j["state"] in ("queued", "working"):
        if jobqueue.cancel_queued(queue_key(user_id)):
            j["state"], j["step"] = "stopped", ""
            j["finishedAt"] = time.time()
            j["_gen"]["done"] = True
        task = j["_gen"].get("task")
        if task is not None and not task.done():
            task.cancel()
    return view(user_id)


def _transcript(history: list[dict]) -> str:
    lines = []
    for m in history[-HISTORY_TURNS:]:
        who = "Familiemedlem" if m["role"] == "user" else "Alf"
        lines.append(f"{who}: {m['content'][:600]}")
    return "\n".join(lines)


async def _ask_json(model: str, system: str, user: str) -> dict:
    raw = ""
    async for piece in ollama.stream_chat(model, [{"role": "system", "content": system},
                                                  {"role": "user", "content": user}],
                                          response_format="json", think=False):
        raw += piece
    return fm_ask._json(raw)


async def route(model: str, history: list[dict], text: str) -> dict:
    """{"places": bool, "family": bool, "person": str | None, "question": str}.
    A broken answer means "neither, as written" - the general answer can still help."""
    convo = _transcript(history)
    prompt = (f"Samtalen indtil nu:\n{convo}\n\n" if convo else "") + f"Sidste besked: {text}"
    try:
        out = await _ask_json(model, ROUTE_PROMPT, prompt)
    except Exception as exc:                                  # noqa: BLE001
        logs.record_exception(exc, "Alf chat route")
        return {"places": False, "family": False, "money": False, "person": None, "question": text}
    question = " ".join(str(out.get("question") or "").split())[:MAX_MESSAGE] or text
    person = out.get("person")
    person = " ".join(str(person).split())[:60] if isinstance(person, str) and person.strip() else None
    places = bool(out.get("places"))
    fam = bool(out.get("family")) and not places
    money = bool(out.get("money")) and not places and not fam
    return {"places": places, "family": fam, "money": money, "person": person, "question": question}


async def run(user: dict, text: str, history: list[dict], phone: tuple[float, float] | None,
              model: str, j: dict) -> None:
    uid = user["id"]

    def step(s: str, phase: str):
        j["state"], j["step"], j["phase"] = "working", s, phase

    def thinking(_t: str) -> None:
        if not j["text"]:
            j["step"], j["phase"] = "Tænker over svaret…", "think"
    try:
        step("Forstår beskeden…", "understand")
        r = await route(model, history, text)
        j["route"] = ("places" if r["places"] else "family" if r["family"] else
                      "money" if r["money"] else "chat")
        if r["money"]:
            await _money(user, r, history, model, j, step)
            return
        if r["family"]:
            step("Kigger i Dagbog og Cyklus…", "search")
            found = family.gather(user, r["person"])
            j["searched"] = ", ".join(found["people"]) or None
            step("Skriver svaret…", "write")
            j["text"] = ""
            today = date.today()
            system = family.ANSWER_PROMPT % {"today": f"{DAYS[today.weekday()]} {today:%d.%m.%Y}",
                                             "name": user["username"]}
            msgs = [{"role": "system", "content": system}]
            msgs += [{"role": m["role"], "content": m["content"]} for m in history[-4:]]
            msgs.append({"role": "user", "content": f"{found['context']}\n\nSpørgsmål: {r['question']}"})
        elif r["places"]:
            found = await fm_ask.gather(uid, r["question"], phone, None, j, model, step)
            if found is None:
                # No town and no position: the search says so itself.
                add_message(uid, "assistant", j["text"], [], {"route": "places"})
                j["state"] = "done"
                return
            step("Skriver svaret…", "write")
            j["text"] = ""
            where, radius = found["where"], found["radius"]
            msgs = [{"role": "system", "content": fm_ask.ANSWER_PROMPT}]
            msgs += [{"role": m["role"], "content": m["content"]} for m in history[-4:]]
            msgs.append({"role": "user", "content":
                         f"Spørgsmål: {r['question']}\nOmråde: {where['name']}, radius {radius:g} km."
                         f"\n\n{found['context']}"})
        else:
            step("Skriver svaret…", "write")
            j["text"] = ""
            today = date.today()
            system = GENERAL_PROMPT % {"today": f"{DAYS[today.weekday()]} {today:%d.%m.%Y}",
                                       "name": user["username"]}
            msgs = [{"role": "system", "content": system}]
            msgs += [{"role": m["role"], "content": m["content"]} for m in history]
            msgs.append({"role": "user", "content": text})
        async for piece in ollama.stream_chat(model, msgs, on_thinking=thinking):
            if not j["text"]:
                j["step"], j["phase"] = "Skriver svaret…", "write"
            j["text"] += piece
        meta = {"route": j["route"]}
        if j["route"] == "family":
            meta["searched"] = j.get("searched")
        if j["route"] == "places":
            meta.update(searched=j.get("searched"), where=j.get("where"))
        add_message(uid, "assistant", j["text"].strip(), j["places"], meta)
        j["state"], j["step"] = "done", ""
    except asyncio.CancelledError:
        j["state"], j["step"] = "stopped", ""
        if j["text"].strip():
            add_message(uid, "assistant", j["text"].strip() + " …", j["places"],
                        {"route": j["route"], "stopped": True})
        raise
    except Exception as exc:                                  # noqa: BLE001
        logs.record_exception(exc, "Alf chat")
        j["state"], j["step"] = "failed", ""
        j["error"] = f"Alf kunne ikke svare: {str(exc) or exc.__class__.__name__}"
    finally:
        j["finishedAt"] = time.time()


def _say(uid: int, j: dict, text: str, meta: dict) -> None:
    """An answer Alf gives without the model (no Økonomi, someone else's)."""
    j["text"] = text
    add_message(uid, "assistant", text, [], meta)
    j["state"], j["step"] = "done", ""


def _previous_money(history: list[dict]) -> dict | None:
    """The last money question and its search, for a follow-up ("og i 2024?")."""
    for i in range(len(history) - 1, 0, -1):
        m = history[i]
        if m["role"] == "assistant" and m["meta"].get("route") == "money" and m["meta"].get("spec"):
            q = history[i - 1]["content"] if history[i - 1]["role"] == "user" else ""
            return {"question": q, "spec": m["meta"]["spec"]}
    return None


async def _money(user: dict, r: dict, history: list[dict], model: str, j: dict, step) -> None:
    """Økonomi through Alf (0.3.12): the asker's own ledger only."""
    uid = user["id"]
    meta: dict = {"route": "money"}
    who = (r.get("person") or "").lower()
    if who and who not in family.SELF_WORDS and who not in (user["username"].lower(),
                                                             (user.get("name") or "").lower()):
        # Everyone's Økonomi is their own - Alf does not look in another's.
        return _say(uid, j, f"Jeg kan kun svare på din egen økonomi - {r['person']}s Økonomi er "
                            f"{r['person']}s egen.", meta)
    lu = ledger.ledger_for(user)
    if lu is None:
        return _say(uid, j, "Du har ikke Økonomi endnu. Bed administratoren slå den til for dig "
                            "(Indstillinger → Konti), så kan du læse din bankudskrift ind og spørge mig.", meta)
    if ledger.summary(lu)["count"] == 0:
        return _say(uid, j, "Der er ingen posteringer endnu. Læs en bankudskrift ind under "
                            "Økonomi → Dine data, så kan jeg svare.", meta)
    step("Forstår spørgsmålet…", "understand")
    system, prompt = ledger_ask._understand_input(lu, r["question"], _previous_money(history))
    spec = ledger.clean_spec(await ledger_ask._ask_json(model, system, prompt))
    step("Tæller i dine posteringer…", "search")
    res = await asyncio.to_thread(ledger.run_spec, lu, spec)
    counted = ledger.describe_spec_da(spec)
    step("Skriver svaret…", "write")
    j["text"] = ""
    context = ledger_ask.result_context(r["question"], spec, res, ledger.summary(lu))
    async for piece in ollama.stream_chat(model, [{"role": "system", "content": ledger_ask.ANSWER_PROMPT},
                                                  {"role": "user", "content": context}], think=False):
        j["text"] += piece
    meta.update(counted=counted, spec=spec, matched=res["count"])
    add_message(uid, "assistant", j["text"].strip(), [], meta)
    j["state"], j["step"] = "done", ""


def reset() -> None:
    _jobs.clear()
