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
3. **Anything else** - Alf answers as a friendly general assistant, with the
   conversation so far.

Only the person's own messages are ever sent; nothing from Økonomi or the
Dagbog is shared with the model.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date

from app.core import db, jobqueue, logs, ollama, settings

from ..familymap import familymap as fm, familymap_ask as fm_ask

MAX_MESSAGE = 1000
HISTORY_TURNS = 8            # messages of context sent with a new one
QUEUE_BASE = 5_000_000       # queue keys -(QUEUE_BASE + user id): never another's

ROUTE_PROMPT = """Afgør hvad familiemedlemmets SIDSTE besked handler om. Svar KUN med JSON:
{"places": true/false, "question": "beskeden omskrevet så den kan forstås alene"}

- places = true når der spørges efter konkrete steder at tage hen: spisesteder, caféer, is,
  legepladser, udflugter, aktiviteter, svømmehaller, museer, natur, strande, overnatning, byer.
- places = false for alt andet: viden, opskrifter, lektier, planlægning, hverdagsspørgsmål, sjov.
- question: brug samtalen til at gøre beskeden fuldstændig ("og i Flensborg?" bliver
  "pizza i Flensborg"). Samme sprog som beskeden."""

GENERAL_PROMPT = """Du er Alf, en venlig hjælper i familiens app FamilyLog. Familien bor i Sønderjylland.
I dag er det %(today)s. Du taler med %(name)s.
- Svar på det sprog der skrives på (normalt dansk), kort og klart; brug lister når det hjælper.
- Du kender ikke familiens private oplysninger, og du kan ikke se internettet her.
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
    """{"places": bool, "question": str}. A broken answer means "not places,
    as written" - the general answer can still help."""
    convo = _transcript(history)
    prompt = (f"Samtalen indtil nu:\n{convo}\n\n" if convo else "") + f"Sidste besked: {text}"
    try:
        out = await _ask_json(model, ROUTE_PROMPT, prompt)
    except Exception as exc:                                  # noqa: BLE001
        logs.record_exception(exc, "Alf chat route")
        return {"places": False, "question": text}
    question = " ".join(str(out.get("question") or "").split())[:MAX_MESSAGE] or text
    return {"places": bool(out.get("places")), "question": question}


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
        j["route"] = "places" if r["places"] else "chat"
        if r["places"]:
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


def reset() -> None:
    _jobs.clear()
