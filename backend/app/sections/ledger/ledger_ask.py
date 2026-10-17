"""Økonomi: the model's two jobs (2.63.0).

**Ask** - one question at a time per person, the latest kept (as in a
library). Three steps, each a row in Steps:

1. *Understand* - the model turns the question into a small JSON search
   (merchants, words, categories, kinds, period, money in/out, per month /
   merchant / category, sum / count / list, top N). It never writes SQL.
2. *Count* - ledger.run_spec runs it: totals, groups and the matching rows,
   all exact.
3. *Answer* - the model writes a short answer from that result only. The
   rows are shown under the answer by the page, not retyped by the model,
   so every number can be checked.

A follow-up ("and in 2024?", "per month then") is understood against the
previous question and its search.

**Categorise** - merchants no rule knows are put in front of the model in
numbered batches of BATCH; it answers {"1": "groceries", ...}. Only empty
categories are filled - the person's own choice always stands. Each batch is
its own job in the queue, so a chat message can get in between two batches
instead of waiting for all of them.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date

from app.core import jobqueue, logs, ollama, telemetry
from app.meta import APP_DISPLAY_NAME

from . import ledger

ASK_QUEUE_BASE = 4_000_000        # queue keys -(base + user id)
CAT_QUEUE_BASE = 4_500_000
MAX_QUESTION = 500
BATCH = 40
CONTEXT_ROWS = 15                 # rows the answer model sees (the page shows up to 50)
CONTEXT_GROUPS = 40

_asks: dict[int, dict] = {}       # user id -> latest ask
_cats: dict[int, dict] = {}       # user id -> latest categorise run


class Busy(ValueError):
    pass


def ask_key(user_id: int) -> int:
    return -(ASK_QUEUE_BASE + user_id)


def cat_key(user_id: int) -> int:
    return -(CAT_QUEUE_BASE + user_id)


# ---- prompts ------------------------------------------------------------------------------

def _category_lines() -> str:
    return "\n".join(f"- {k}: {en} / {da}" for k, (en, da) in ledger.CATEGORIES.items())


UNDERSTAND_PROMPT = """You turn a question about the person's own bank transactions into a search.
Answer ONLY with JSON, exactly these keys:
{"merchants": [], "words": [], "categories": [], "kinds": [], "from": null, "to": null,
 "direction": "out", "group": "none", "measure": "sum", "order": "largest", "top": null,
 "includeTransfers": false}

Today is %(today)s. The ledger holds %(count)s transactions from %(first)s to %(last)s.
Accounts: %(accounts)s.

Categories (key: English / Dansk):
%(categories)s

Kinds (how it was paid): card (Dankort/Visa), mobilepay, betalingsservice (direct debit / PBS),
atm (cash withdrawal), transfer (between own accounts), interest, fee, salary, card-bill, other.

Rules:
- merchants: shop or company names the question mentions, short and lower case, as written
  ("davidsens", "netto", "proshop", "q8"). Never a category word.
- words: other words that must appear in the bank text. Usually empty.
- categories: only when the question names a type of spending ("groceries", "dagligvarer",
  "fuel", "benzin", "eating out", "subscriptions", "abonnementer" ...). Use the keys above.
- kinds: only when the question names a way of paying ("betalingsservice", "mobilepay", "cash").
- from/to as YYYY-MM-DD: "in 2025" -> 2025-01-01 / 2025-12-31; "last month" -> the previous
  calendar month; "the last 3 months" -> from 3 months before today to today; "since May" ->
  from the 1st of May. No period in the question -> both null (all data).
- direction: spent, paid, cost, expensive, brugt, betalt, dyreste -> "out"; received, income,
  earned, got paid, indtægt, fik ind -> "in"; both directions or net -> "both".
- measure and order: "how much / total / hvor meget" -> sum; "how many / hvor mange gange" ->
  count; "average / gennemsnit" -> average; "most expensive / largest / biggest / top N /
  dyreste" -> list, order largest, top N (3 if no number); "latest / newest / seneste" ->
  list, order newest; "show / list / vis alle" -> list.
- group: "per month / each month / om måneden / månedligt" -> month; "per year / om året" ->
  year; "where do I spend most / which shops / hvor bruger jeg mest" -> merchant; "what do I
  spend on / by category / hvad bruger jeg penge på" -> category; otherwise none.
- includeTransfers: true only when the question is about transfers, savings, opsparing or
  budgetkonto.
- A follow-up question ("and in 2024?", "per month?", "og hos Netto?") keeps everything from
  the previous search except what the new question changes."""

ANSWER_PROMPT = """You answer questions about the person's own bank transactions.
The app has already searched the ledger and counted. The numbers below are exact.
Rules:
1. Use ONLY numbers, dates and names from the result. Never add up, estimate or invent amounts.
   If the result does not contain what you would need, say so.
2. Write amounts as they are given (Danish format, e.g. 9.410,50 kr).
3. Start with the direct answer in one sentence. Then a few short lines, or a small Markdown
   table when it helps. The app shows the matching transactions under your answer, so list at
   most 10 of them.
4. Say what was counted when it matters: the period, and that own transfers were left out if
   the result says so.
5. If nothing matched, say so plainly and mention the similar names if the result gives any.
6. Answer in the language of the question (Danish or English). No preamble, no sign-off."""

CATEGORISE_PROMPT = """You sort shops and payees from a Danish person's bank statement into categories.
Answer ONLY with JSON: {"1": "category-key", "2": "category-key", ...} - one entry per numbered line.

Categories (key: English / Dansk):
%s

Hints:
- People's names (MobilePay, transfers from/to a person) -> people.
- Burgers, pizza, kebab, grill, sushi-to-go, hotdogs, meal delivery -> fast-food.
  Sit-down restaurants, cafés, bars, inns (kro) -> restaurant.
- Supermarkets and butchers in Denmark -> groceries. Border shops and shops in Germany
  (Fleggaard, Calle, Edeka, Rewe, Citti, German towns) -> germany-shopping.
- AliExpress, Temu, Shein, Wish and other Chinese web shops -> china-shopping.
- Petrol stations and car parts -> car. Parking, bridges, public transport -> transport.
- Building materials, tools, garden, furniture, plumbing supplies -> home.
- Web shops for computer parts, cables, gadgets, 3D printing -> electronics.
- Netflix, Disney+, HBO, Viaplay, Spotify, YouTube Premium -> streaming. TV providers
  (TV 2, YouSee, Stofa, Boxer) -> tv. Anthropic, OpenAI, Copilot, Midjourney -> ai.
  Other software, hosting, app stores, cloud -> subscriptions.
- Mobile and broadband (Telmore, CBB, Telenor) -> phone.
- Electricity, water, heating, waste -> utilities. Rent, deposit, housing association -> rent.
  Realkredit / mortgage -> mortgage.
- Trade unions and a-kasse (3F, HK, Metal, FOA, Krifa) -> union. Insurance -> insurance.
- Dentists -> dental. Physiotherapists, chiropractors -> physio. Pharmacies, doctors,
  opticians, hospitals -> health. Hairdressers, beauty, grooming, drugstores -> personal-care.
- Clothes and shoes -> clothing. Games, cinema, tickets, betting, gyms, sports clubs,
  DAZN, F1 TV -> leisure. Hotels, flights, holidays -> travel.
- Banks and consumer-loan companies taking payments -> loans. Money in from the state,
  salary, refunds of tax -> income.
- If you cannot tell, use other. Never invent a key that is not in the list."""


# ---- shared ----------------------------------------------------------------------------------

def _json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("the model did not answer with JSON")
    return json.loads(raw[start:end + 1])


async def _ask_json(model: str, system: str, user: str) -> dict:
    raw = ""
    async for piece in ollama.stream_chat(model, [{"role": "system", "content": system},
                                                  {"role": "user", "content": user}],
                                          response_format="json", think=False):
        raw += piece
    return _json(raw)


def _detail(step, text: str) -> None:
    rec = telemetry.current()
    if step is not None and rec is not None:
        rec.update(step, detail=text)


# ---- ask -------------------------------------------------------------------------------------

def view(user_id: int) -> dict | None:
    a = _asks.get(user_id)
    if a is None:
        return None
    out = {k: v for k, v in a.items() if not k.startswith("_")}
    if a["state"] == "queued":
        out["ahead"] = jobqueue.position(ask_key(user_id))
    out["steps"] = telemetry.payload_of(a["_gen"]) if a.get("_gen") else None
    return out


def submit(user_id: int, question: str, model: str | None = None,
           ledger_uid: int | None = None) -> dict:
    """Queue a question. Must be called from a running event loop.

    `user_id` is who asks (their one ask slot and queue place);
    `ledger_uid` whose ledger is searched - another account's for a family
    member given read access to it (0.3.0), else the asker's own."""
    lu = ledger_uid if ledger_uid is not None else user_id
    question = " ".join(str(question or "").split())
    if not question:
        raise ledger.Invalid("Write a question.")
    if len(question) > MAX_QUESTION:
        raise ledger.Invalid(f"The question is too long (at most {MAX_QUESTION} characters).")
    if ledger.summary(lu)["count"] == 0:
        raise ledger.Invalid("Import a bank export first (Import).")
    model = model or ledger.get_settings(lu)["model"]
    if not model:
        raise ledger.Invalid("No model chosen - pick one beside the question box, "
                             "or set the chat model in Settings.")
    old = _asks.get(user_id)
    if old and old["state"] in ("queued", "working"):
        raise Busy("Still working on the last question - stop it or wait.")
    prev = None
    if old and old["state"] == "done" and old.get("spec"):
        prev = {"question": old["question"], "spec": old["spec"]}
    gen: dict = {"text": "", "done": False, "error": None, "model": model}
    a = {"question": question, "model": model, "state": "queued", "step": "Waiting for the card…",
         "text": "", "spec": None, "counted": None, "result": None, "error": None,
         "startedAt": db_now(), "finishedAt": None, "previous": prev["question"] if prev else None,
         "_gen": gen, "_prev": prev, "_ledger": lu}
    _asks[user_id] = a

    def factory():
        async def go():
            try:
                await run(user_id, a)
            finally:
                gen["done"] = True
                rec = gen.get("_telemetry")
                if rec is not None:
                    rec.finish()
        return go()
    jobqueue.submit(ask_key(user_id), "ledger-ask", gen, factory)
    return view(user_id)


def db_now() -> str:
    from app.core import db
    return db.utcnow()


def _understand_input(user_id: int, question: str, prev: dict | None) -> tuple[str, str]:
    s = ledger.summary(user_id)
    accounts = ", ".join(f"{x['account']} ({x['n']} rows)" for x in s["accounts"]) or "one"
    system = UNDERSTAND_PROMPT % {
        "today": date.today().isoformat(), "count": s["count"],
        "first": s["firstDate"], "last": s["lastDate"], "accounts": accounts,
        "categories": _category_lines()}
    user = question
    if prev:
        user = (f"Previous question: {prev['question']}\n"
                f"Previous search: {json.dumps(prev['spec'], ensure_ascii=False)}\n\n"
                f"New question: {question}")
    return system, user


def result_context(question: str, spec: dict, res: dict, summary: dict) -> str:
    """The result as text for the answer model - everything it may say."""
    kr = ledger.kr
    out_word = {"out": "money out", "in": "money in", "both": "net (in minus out)"}[spec["direction"]]
    lines = [f"Question: {question}",
             f"Searched: {ledger.describe_spec(spec)}",
             f"Ledger holds data from {summary['firstDate']} to {summary['lastDate']}.",
             ""]
    if res["count"] == 0:
        lines.append("Result: no transactions matched.")
    else:
        lines.append(
            f"Result: {res['count']} transactions, total {kr(res['total'])} ({out_word}), "
            f"average {kr(res['average'])} per transaction, first {res['firstDate']}, "
            f"last {res['lastDate']}, largest single amount {kr(res['largest'])}.")
    if res["matchedMerchants"]:
        lines.append("Merchants that matched: " + ", ".join(
            f"{m['name']} ({m['count']})" for m in res["matchedMerchants"]))
    if res["groups"]:
        lines += ["", f"Per {spec['group']} (total {out_word}, count):"]
        for g in res["groups"][:CONTEXT_GROUPS]:
            lines.append(f"- {g['group']}: {kr(g['total'])} ({g['count']})")
        if len(res["groups"]) > CONTEXT_GROUPS:
            lines.append(f"- ... {len(res['groups']) - CONTEXT_GROUPS} more groups not shown")
    if res["rows"]:
        shown = res["rows"][:CONTEXT_ROWS]
        lines += ["", f"Transactions ({spec['order']} first, {len(shown)} of {res['count']}):"]
        for r in shown:
            fx = (f" ({r['foreignCurrency']} {r['foreignAmount']:.2f})"
                  if r.get("foreignCurrency") and r.get("foreignAmount") is not None else "")
            lines.append(f"- {r['date']} | {r['merchant']} | {kr(r['amount'])}{fx} | "
                         f"{ledger.category_label(r['category'])} | {r['text']}")
    if res["excludedTransfers"]:
        et = res["excludedTransfers"]
        lines += ["", f"Own transfers left out: {et['count']} rows, {kr(et['sum'])} "
                      "(ask about transfers to include them)."]
    for n in res["notes"]:
        lines.append(f"Note: {n}")
    return "\n".join(lines)


async def run(user_id: int, a: dict) -> None:
    model = a["model"]
    user_id = a.get("_ledger", user_id)          # whose ledger is searched
    try:
        a["state"], a["step"] = "working", "Understanding the question…"
        system, user = _understand_input(user_id, a["question"], a.get("_prev"))
        with telemetry.span("Understand the question", "stage", aux=True, drop_under=None) as st:
            raw = await _ask_json(model, system, user)
            spec = ledger.clean_spec(raw)
            _detail(st, ledger.describe_spec(spec))
        a["spec"], a["counted"] = spec, ledger.describe_spec(spec)

        a["step"] = "Counting…"
        with telemetry.span("Count in the ledger (SQL)", "stage", drop_under=None) as st:
            res = await asyncio.to_thread(ledger.run_spec, user_id, spec)
            _detail(st, f"{res['count']} rows, {ledger.kr(res['total'])}")
        a["result"] = res

        a["step"] = "Writing the answer…"
        context = result_context(a["question"], spec, res, ledger.summary(user_id))
        a["text"] = ""
        with telemetry.span("Answer", "stage", drop_under=None):
            async for piece in ollama.stream_chat(
                    model, [{"role": "system", "content": ANSWER_PROMPT},
                            {"role": "user", "content": context}], think=False):
                a["text"] += piece
        a["state"], a["step"] = "done", ""
    except asyncio.CancelledError:
        a["state"], a["step"] = "stopped", ""
        raise
    except Exception as exc:                                  # noqa: BLE001
        logs.record_exception(exc, "Økonomi ask")
        a["state"], a["step"] = "failed", ""
        a["error"] = f"Could not answer: {str(exc) or exc.__class__.__name__}"
    finally:
        a["finishedAt"] = db_now()


def stop(user_id: int) -> dict | None:
    a = _asks.get(user_id)
    if not a or a["state"] not in ("queued", "working"):
        return view(user_id)
    if jobqueue.cancel_queued(ask_key(user_id)):
        a["state"], a["step"] = "stopped", ""
        a["_gen"]["done"] = True
    task = a["_gen"].get("task")
    if task is not None and not task.done():
        task.cancel()
    return view(user_id)


def markdown(user_id: int, version: str) -> str:
    """The latest ask as one Markdown file, like a chat export."""
    a = _asks.get(user_id)
    if not a:
        raise ledger.Invalid("No question asked yet.")
    kr = ledger.kr
    res = a.get("result") or {}
    lines = [f"# {a['question']}", "",
             f"- Model: {a['model']}",
             f"- Asked: {a['startedAt']}",
             f"- State: {a['state']}",
             f"- Exported: {db_now()} by {APP_DISPLAY_NAME} {version}"]
    if a.get("previous"):
        lines.append(f"- Follow-up to: {a['previous']}")
    lines.append("")
    if a.get("counted"):
        lines += [f"**Counted:** {a['counted']}", ""]
    if a.get("spec"):
        lines += ["```json", json.dumps(a["spec"], ensure_ascii=False, indent=1), "```", ""]
    lines += ["## Answer", "", a.get("text") or a.get("error") or "(none)", ""]
    if res:
        lines += ["## Result (computed by the app)", "",
                  f"{res.get('count', 0)} transactions, total {kr(res.get('total'))}", ""]
        if res.get("groups"):
            lines += ["| Group | Total | Count |", "|---|---:|---:|"]
            lines += [f"| {g['group']} | {kr(g['total'])} | {g['count']} |" for g in res["groups"]]
            lines.append("")
        if res.get("rows"):
            lines += ["| Date | Merchant | Amount | Category | Text |", "|---|---|---:|---|---|"]
            lines += [f"| {r['date']} | {r['merchant']} | {kr(r['amount'])} | "
                      f"{ledger.category_label(r['category'])} | {r['text'].replace('|', '/')} |"
                      for r in res["rows"]]
            lines.append("")
        for n in res.get("notes") or []:
            lines.append(f"> {n}")
    steps = telemetry.render_text(telemetry.payload_of(a["_gen"])) if a.get("_gen") else ""
    if steps:
        lines += ["", steps]
    return "\n".join(lines) + "\n"


# ---- categorise ---------------------------------------------------------------------------------

def cat_view(user_id: int) -> dict:
    c = _cats.get(user_id)
    left = ledger.count_uncategorised(user_id)
    if c is None:
        return {"state": "none", "left": left}
    out = {k: v for k, v in c.items() if not k.startswith("_")}
    out["left"] = left
    if c["state"] == "queued":
        out["ahead"] = jobqueue.position(cat_key(user_id))
    gen = c.get("_gen")
    out["steps"] = telemetry.payload_of(gen) if gen else None
    return out


def submit_categorise(user_id: int, model: str | None = None) -> dict:
    model = model or ledger.get_settings(user_id)["categoriseModel"]
    if not model:
        raise ledger.Invalid("No model chosen for Økonomi - set the categorise or chat "
                             "model in Settings, or pick one here.")
    old = _cats.get(user_id)
    if old and old["state"] in ("queued", "working"):
        return cat_view(user_id)
    todo = ledger.count_uncategorised(user_id)
    if todo == 0:
        return cat_view(user_id)
    c = {"state": "queued", "model": model, "total": todo, "placed": 0, "batches": 0,
         "error": None, "startedAt": db_now(), "finishedAt": None, "_stop": False,
         "_tried": set()}
    _cats[user_id] = c
    _queue_batch(user_id, c)
    return cat_view(user_id)


def _queue_batch(user_id: int, c: dict) -> None:
    gen: dict = {"text": "", "done": False, "error": None, "model": c["model"]}
    c["_gen"] = gen

    def factory():
        async def go():
            more = False
            try:
                more = await run_batch(user_id, c)
            finally:
                gen["done"] = True
                rec = gen.get("_telemetry")
                if rec is not None:
                    rec.finish()
            if more and not c["_stop"]:
                c["state"] = "queued"
                _queue_batch(user_id, c)
        return go()
    jobqueue.submit(cat_key(user_id), "ledger-categorise", gen, factory)


def batch_prompt(items: list[dict]) -> str:
    lines = []
    for i, m in enumerate(items, start=1):
        lines.append(f"{i}. {m['name']} | {m['sample'][:90]} | {m['count']} payments, "
                     f"{ledger.kr(m['total'])}")
    return "\n".join(lines)


async def run_batch(user_id: int, c: dict) -> bool:
    """One batch. True when there is more to do."""
    try:
        c["state"] = "working"
        todo = [m for m in ledger.uncategorised(user_id, limit=2000) if m["key"] not in c["_tried"]]
        if not todo:
            c["state"] = "done"
            return False
        items = todo[:BATCH]
        c["batches"] += 1
        with telemetry.span(f"Categorise {len(items)} merchants", "stage", drop_under=None) as st:
            answer = await _ask_json(c["model"], CATEGORISE_PROMPT % _category_lines(),
                                     batch_prompt(items))
            placed = 0
            for i, m in enumerate(items, start=1):
                c["_tried"].add(m["key"])
                cat = str(answer.get(str(i)) or "").strip().lower()
                if cat in ledger.CATEGORIES and ledger.set_category(user_id, m["key"], cat,
                                                                     source="model"):
                    placed += 1
            c["placed"] += placed
            _detail(st, f"{placed} placed")
        more = len(todo) > len(items)
        if not more:
            c["state"] = "done"
        return more
    except asyncio.CancelledError:
        c["state"] = "stopped"
        raise
    except Exception as exc:                                  # noqa: BLE001
        logs.record_exception(exc, "Økonomi categorise")
        c["state"] = "failed"
        c["error"] = f"Categorising stopped: {str(exc) or exc.__class__.__name__}"
        return False
    finally:
        if c["state"] in ("done", "failed", "stopped"):
            c["finishedAt"] = db_now()


def stop_categorise(user_id: int) -> dict:
    c = _cats.get(user_id)
    if c and c["state"] in ("queued", "working"):
        c["_stop"] = True
        if jobqueue.cancel_queued(cat_key(user_id)):
            c["state"] = "stopped"
            c["finishedAt"] = db_now()
            c["_gen"]["done"] = True
        task = (c.get("_gen") or {}).get("task")
        if task is not None and not task.done():
            task.cancel()
    return cat_view(user_id)


def ledger_of(user_id: int) -> int | None:
    """Whose ledger this person's latest ask searched (0.3.0)."""
    a = _asks.get(user_id)
    return a.get("_ledger", user_id) if a else None


def forget(user_id: int) -> None:
    """Drop a person's ask - stopped first if it is running. Used when a
    family account's Økonomi access changes, so an answer about one
    ledger never outlives the access to it."""
    stop(user_id)
    _asks.pop(user_id, None)


def forget_viewers_of(ledger_uid: int) -> None:
    """Other people's asks about this ledger (it was cleared)."""
    for uid in [u for u, a in _asks.items() if u != ledger_uid and a.get("_ledger") == ledger_uid]:
        forget(uid)


def reset(user_id: int | None = None) -> None:
    """Tests and 'clear the ledger'."""
    if user_id is None:
        _asks.clear()
        _cats.clear()
    else:
        _asks.pop(user_id, None)
        _cats.pop(user_id, None)
