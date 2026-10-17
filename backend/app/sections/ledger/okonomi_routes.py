"""Økonomi on the front page - /api/okonomi/... (FamilyLog 0.3.0; 0.3.3).

Since 0.3.3 every person with Økonomi has their own ledger (Søren: "every
user with access needs its own data"): admin and user accounts always,
family accounts when the administrator turns it on. Everything here acts on
the signed-in person's own ledger only - the month, its transactions,
asking Alf, and (0.3.3) importing bank exports, placing merchants in a
category and letting the model place the rest. A family account cannot
reach the admin app's /api/ledger at all.

Family accounts reach this prefix (Section.family_prefixes); whether a
given one has an Økonomi is decided here, per request.
"""
from __future__ import annotations

import calendar
import re

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.core import db

from . import ledger, ledger_ask

router = APIRouter()

NO_ACCESS = "Du har ikke Økonomi. Administratoren kan slå det til for dig under Indstillinger."

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
            "accounts": [a["account"] for a in s["accounts"]],
            "model": bool(ledger.get_settings(lu)["model"]), "ask": _ask(me["id"], lu)}


def _day_arg(s: str, what: str) -> str | None:
    if not s:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise HTTPException(400, f"Ugyldig dato ({what}).")
    return s


def _whole_month(frm: str | None, to: str | None) -> bool:
    if not frm or not to or frm[:7] != to[:7] or frm[8:] != "01":
        return False
    return (frm, to) == _month_range(frm[:7])


def _overview(lu: int, frm: str | None, to: str | None, account: str | None) -> dict:
    """The phone's overview for any period (0.3.5): a whole month is compared
    with the six before; a longer one shows its average month."""
    month = _whole_month(frm, to)
    o = ledger.overview(lu, frm, to, account or None, top=10, baseline=6 if month else 0)
    base = (o["baseline"] or {}).get("categories", {})
    n_months = max(1, len(o["months"]))
    return {
        "from": frm, "to": to, "account": account or None, "isMonth": month,
        "count": o["count"], "spent": o["spent"], "income": o["income"],
        "otherIn": o["otherIn"], "transfersOut": o["transfersOut"],
        "perMonth": o["perMonth"], "months": n_months,
        "baselinePerMonth": (o["baseline"] or {}).get("perMonth"),
        "baselineMonths": (o["baseline"] or {}).get("months"),
        "days": o["days"],
        "categories": [{"key": c["key"], "name": ledger.category_da(c["key"]), "spent": c["spent"],
                        "count": c["count"], "usual": base.get(c["key"])} for c in o["categories"]],
        "topMerchants": [{"key": m["key"], "name": m["name"], "spent": m["spent"], "count": m["count"],
                          "category": m["category"], "categoryName": ledger.category_da(m["category"])}
                         for m in o["topMerchants"]],
        "recurring": [{"key": r["key"], "name": r["name"], "typical": r["typical"], "yearly": r["yearly"],
                       "category": r["category"], "categoryName": ledger.category_da(r["category"])}
                      for r in o["recurring"][:12]],
    }


@router.get("/api/okonomi/month")
def okonomi_month(month: str, request: Request, account: str = ""):
    lu = _ledger(request)
    frm, to = _month_range(month)
    out = _overview(lu, frm, to, account)
    out["month"] = month
    return out


@router.get("/api/okonomi/overview")
def okonomi_overview(request: Request, frm: str = "", to: str = "", account: str = ""):
    """Any period (empty = all) and account (empty = all)."""
    lu = _ledger(request)
    return _overview(lu, _day_arg(frm, "fra"), _day_arg(to, "til"), account)


@router.get("/api/okonomi/trend")
def okonomi_trend(request: Request, months: int = 12, account: str = ""):
    """Month by month (0.3.5): spending, income and each category, for the
    last `months` months of data (0 = all)."""
    lu = _ledger(request)
    s = ledger.summary(lu)
    if not s["lastDate"]:
        return {"months": [], "categories": []}
    last = s["lastDate"][:7]
    frm = None if months <= 0 else f"{ledger._month_add(last, -(max(1, min(months, 240)) - 1))}-01"
    o = ledger.overview(lu, frm, _month_range(last)[1], account or None, top=1)
    return {"months": [{"month": m["month"], "spent": m["spent"], "income": m["income"],
                        "byCategory": m["byCategory"]} for m in o["months"]],
            "categories": [{"key": c["key"], "name": ledger.category_da(c["key"]), "spent": c["spent"]}
                           for c in o["categories"]]}


@router.get("/api/okonomi/transactions")
def okonomi_transactions(request: Request, month: str = "", frm: str = "", to: str = "",
                         category: str = "*", merchant: str = "", q: str = "", account: str = "",
                         direction: str = "", order: str = "newest", offset: int = 0):
    lu = _ledger(request)
    if month:
        frm, to = _month_range(month)
    else:
        frm, to = _day_arg(frm, "fra") or "", _day_arg(to, "til") or ""
    if direction not in ("", "in", "out") or order not in ("newest", "oldest", "largest", "smallest", "income"):
        raise HTTPException(400, "Ugyldigt filter.")
    t = ledger.transactions(lu, q=q[:100], category=category, merchant=merchant or None, frm=frm or None,
                            to=to or None, account=account or None, direction=direction, order=order,
                            offset=max(0, offset), limit=50)
    return {"total": t["total"], "sum": t["sum"], "rows": [_row(r) for r in t["rows"]]}


@router.get("/api/okonomi/merchants")
def okonomi_merchants(request: Request, q: str = "", category: str = "*"):
    """Your shops and payees (0.3.5), the most money first - to move one to
    another category or give it a better name."""
    lu = _ledger(request)
    rows = ledger.merchants(lu, q=q[:100], category=category, limit=300)
    return {"merchants": [{"key": m["key"], "name": m["name"], "category": m["category"],
                           "categoryName": ledger.category_da(m["category"]), "source": m["source"],
                           "sample": m["sample"], "count": m["count"], "total": m["total"],
                           "last": m["last"]} for m in rows],
            "categories": _categories()}


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
    if msg.startswith("A merchant needs a name"):
        return "Butikken skal have et navn."
    if msg.startswith("Unknown category"):
        return "Ukendt kategori."
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


# ---- your own data (0.3.3) ------------------------------------------------------------------------

def _categories() -> list[dict]:
    return [{"key": k, "name": ledger.CATEGORIES[k][1], "group": g}
            for g, keys in ledger.CATEGORY_GROUPS for k in keys]


@router.get("/api/okonomi/data")
def okonomi_data(request: Request):
    """Imports, accounts, the merchants still without a category, and the
    model's categorising - for the phone page's "Dine data"."""
    lu = _ledger(request)
    s = ledger.summary(lu)
    c = ledger_ask.cat_view(lu)
    return {"imports": s["imports"], "accounts": s["accounts"], "count": s["count"],
            "uncategorised": ledger.uncategorised(lu, limit=60), "left": s["uncategorised"],
            "categorise": {"state": c["state"], "left": c.get("left", 0), "placed": c.get("placed"),
                           "error": c.get("error"), "ahead": c.get("ahead")},
            "model": bool(ledger.get_settings(lu)["categoriseModel"]), "categories": _categories()}


@router.post("/api/okonomi/import")
async def okonomi_import(request: Request, file: UploadFile, account: str = ""):
    """A bank export into your own ledger. Rows already there are known
    again; merchants no rule knows go to the model when one is set."""
    lu = _ledger(request)
    data = await file.read(ledger.MAX_FILE_BYTES + 1)
    if len(data) > ledger.MAX_FILE_BYTES:
        raise HTTPException(400, f"Filen er for stor (højst {ledger.MAX_FILE_BYTES // 1024 // 1024} MB).")
    try:
        parsed = ledger.parse_file(file.filename or "", data)
    except ledger.Invalid as exc:
        raise HTTPException(400, str(exc))
    name = " ".join(account.split())[:60] or "Bank"
    out = ledger.import_rows(lu, name, file.filename or "", parsed["rows"])
    out["skipped"] = parsed["skipped"]
    if out["uncategorised"] and ledger.get_settings(lu)["categoriseModel"]:
        try:
            ledger_ask.submit_categorise(lu)
        except (ledger.Invalid, ledger_ask.Busy):
            pass                         # already running: it picks the new ones up
    return out


@router.delete("/api/okonomi/imports/{import_id}")
def okonomi_delete_import(import_id: int, request: Request):
    return {"removed": ledger.delete_import(_ledger(request), import_id)}


class CategoryBody(BaseModel):
    key: str
    category: str | None = None
    name: str | None = None


@router.put("/api/okonomi/merchant")
def okonomi_merchant(body: CategoryBody, request: Request):
    """Move a shop to another category and/or rename it - all its
    purchases follow. Your choice is never overwritten by the model."""
    lu = _ledger(request)
    try:
        if body.category is not None and not ledger.set_category(lu, body.key, body.category):
            raise HTTPException(404, "Den butik findes ikke.")
        if body.name is not None and not ledger.rename_merchant(lu, body.key, body.name):
            raise HTTPException(404, "Den butik findes ikke.")
    except ledger.Invalid as exc:
        raise HTTPException(400, _danish(str(exc)))
    return {"ok": True}


@router.post("/api/okonomi/categorise")
async def okonomi_categorise(request: Request):
    lu = _ledger(request)
    try:
        ledger_ask.submit_categorise(lu)
    except (ledger.Invalid, ledger_ask.Busy) as exc:
        raise HTTPException(409 if isinstance(exc, ledger_ask.Busy) else 400, _danish(str(exc)))
    return okonomi_data(request)
