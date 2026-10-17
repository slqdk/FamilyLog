"""Økonomi on the front page - /api/okonomi/... (FamilyLog 0.3.0).

The phone page reads one ledger: an admin/user account's own, or - for a
family account the administrator gave access - that account's. Read only:
the month's overview, its transactions, and asking Alf. Importing,
categories and clearing are the owner's, in the admin app under
/api/ledger, which a family account cannot reach at all.

Family accounts reach this prefix (Section.family_prefixes); whether a
given one may read anything is decided here, per request.
"""
from __future__ import annotations

import calendar
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core import db

from . import ledger, ledger_ask

router = APIRouter()

NO_ACCESS = "Du har ikke adgang til Økonomi. Administratoren kan give adgang under Indstillinger."

# The ask pipeline speaks English to the admin app; the phone page is Danish.
_STEPS = {"Waiting for the card…": "Venter i køen…",
          "Understanding the question…": "Forstår spørgsmålet…",
          "Counting…": "Tæller i posteringerne…",
          "Writing the answer…": "Skriver svaret…"}


def _ledger(request: Request) -> int:
    lu = ledger.ledger_for(request.state.user)
    if lu is None:
        raise HTTPException(403, NO_ACCESS)
    return lu


def _owner_name(uid: int) -> str:
    with db.connect() as con:
        r = con.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    return r["username"] if r else "?"


def _month_range(month: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise HTTPException(400, "Ugyldig måned.")
    y, m = int(month[:4]), int(month[5:])
    return f"{month}-01", f"{month}-{calendar.monthrange(y, m)[1]:02d}"


def _row(r: dict) -> dict:
    return {"date": r["date"], "merchant": r["merchant"], "text": r["text"],
            "amount": r["amount"], "category": r["category"],
            "categoryName": ledger.category_da(r["category"]), "merchantKey": r["merchantKey"]}


def _ask(user_id: int, lu: int | None) -> dict | None:
    """The person's latest ask - only while it is about the ledger they may
    read now (access moved or removed: the old answer is dropped)."""
    if ledger_ask.ledger_of(user_id) not in (None, lu):
        ledger_ask.forget(user_id)
        return None
    v = ledger_ask.view(user_id)
    if not v:
        return None
    res = v.get("result") or {}
    err = v.get("error")
    return {"question": v["question"], "state": v["state"],
            "step": _STEPS.get(v.get("step") or "", v.get("step") or ""),
            "text": v.get("text") or "", "error": err, "counted": v.get("counted"),
            "count": res.get("count"), "total": res.get("total"),
            "rows": [_row(r) for r in (res.get("rows") or [])[:30]],
            "ahead": v.get("ahead")}


@router.get("/api/okonomi/state")
def okonomi_state(request: Request):
    """Whether this person has an Økonomi on the phone page, and whose."""
    me = request.state.user
    lu = ledger.ledger_for(me)
    if lu is None:
        _ask(me["id"], None)
        return {"access": False}
    s = ledger.summary(lu)
    months = []
    if s["firstDate"] and s["lastDate"]:
        m, last = s["firstDate"][:7], s["lastDate"][:7]
        while m <= last and len(months) < 240:
            months.append(m)
            m = ledger._month_add(m, 1)
    return {"access": True, "own": lu == me["id"], "owner": _owner_name(lu),
            "count": s["count"], "firstDate": s["firstDate"], "lastDate": s["lastDate"],
            "uncategorised": s["uncategorised"], "months": months,
            "model": bool(ledger.get_settings(lu)["model"]), "ask": _ask(me["id"], lu)}


@router.get("/api/okonomi/month")
def okonomi_month(month: str, request: Request):
    lu = _ledger(request)
    frm, to = _month_range(month)
    o = ledger.overview(lu, frm, to, top=8, baseline=6)
    base = (o["baseline"] or {}).get("categories", {})
    return {
        "month": month, "count": o["count"], "spent": o["spent"], "income": o["income"],
        "otherIn": o["otherIn"], "transfersOut": o["transfersOut"],
        "baselinePerMonth": (o["baseline"] or {}).get("perMonth"),
        "baselineMonths": (o["baseline"] or {}).get("months"),
        "days": o["days"],
        "categories": [{"key": c["key"], "name": ledger.category_da(c["key"]), "spent": c["spent"],
                        "count": c["count"], "usual": base.get(c["key"])} for c in o["categories"]],
        "topMerchants": [{"key": m["key"], "name": m["name"], "spent": m["spent"], "count": m["count"],
                          "categoryName": ledger.category_da(m["category"])} for m in o["topMerchants"]],
        "recurring": [{"name": r["name"], "typical": r["typical"], "yearly": r["yearly"],
                       "categoryName": ledger.category_da(r["category"])} for r in o["recurring"][:12]],
    }


@router.get("/api/okonomi/transactions")
def okonomi_transactions(month: str, request: Request, category: str = "*", merchant: str = "",
                         offset: int = 0):
    lu = _ledger(request)
    frm, to = _month_range(month)
    t = ledger.transactions(lu, category=category, merchant=merchant or None, frm=frm, to=to,
                            offset=offset, limit=50)
    return {"total": t["total"], "sum": t["sum"], "rows": [_row(r) for r in t["rows"]]}


class AskBody(BaseModel):
    question: str


def _danish(msg: str) -> str:
    if msg.startswith("Import a bank export"):
        return "Der er ingen posteringer endnu."
    if msg.startswith("No model chosen"):
        return "Der er ikke valgt en model til Økonomi - administratoren vælger den under Indstillinger."
    if msg.startswith("Still working"):
        return "Alf arbejder stadig på det sidste spørgsmål - stop det eller vent."
    if msg.startswith("Write a question"):
        return "Skriv et spørgsmål."
    if msg.startswith("The question is too long"):
        return f"Spørgsmålet er for langt (højst {ledger_ask.MAX_QUESTION} tegn)."
    return msg


@router.post("/api/okonomi/ask")
async def okonomi_ask(body: AskBody, request: Request):
    lu = _ledger(request)
    me = request.state.user
    try:
        ledger_ask.submit(me["id"], body.question, ledger_uid=lu)
    except (ledger.Invalid, ledger_ask.Busy) as exc:
        raise HTTPException(409 if isinstance(exc, ledger_ask.Busy) else 400, _danish(str(exc)))
    return {"ask": _ask(me["id"], lu)}


@router.get("/api/okonomi/ask")
def okonomi_ask_state(request: Request):
    lu = _ledger(request)
    return {"ask": _ask(request.state.user["id"], lu)}


@router.post("/api/okonomi/ask/stop")
async def okonomi_ask_stop(request: Request):
    lu = _ledger(request)
    ledger_ask.stop(request.state.user["id"])
    return {"ask": _ask(request.state.user["id"], lu)}
