"""Økonomi endpoints (2.63.0) - /api/ledger/...

Everything is the signed-in person's own ledger (user_id from the session);
there is nothing to share and nothing another account can read. A family
account never gets here (auth.family_allows lets it reach /api/fm only).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from . import ledger, ledger_ask

router = APIRouter()


def _uid(request: Request) -> int:
    return request.state.user["id"]


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ledger_ask.Busy as exc:
        raise HTTPException(409, str(exc))
    except ledger.Invalid as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/ledger/summary")
def ledger_summary(request: Request):
    uid = _uid(request)
    out = ledger.summary(uid)
    out["settings"] = ledger.get_settings(uid)
    out["categorise"] = ledger_ask.cat_view(uid)
    return out


@router.post("/api/ledger/import")
async def ledger_import(request: Request, file: UploadFile, account: str = ""):
    """One bank export. Rows already in the ledger are recognised and left
    alone; merchants no rule knows are handed to the model right after
    (when a model is set), one batch at a time."""
    uid = _uid(request)
    data = await file.read()
    parsed = _call(ledger.parse_file, file.filename or "", data)
    out = ledger.import_rows(uid, account or "Bank", file.filename or "", parsed["rows"])
    out["skipped"] = parsed["skipped"]
    out["columns"] = parsed["columns"]
    if out["uncategorised"] and ledger.get_settings(uid)["categoriseModel"]:
        out["categorise"] = ledger_ask.submit_categorise(uid)
    return out


@router.delete("/api/ledger/imports/{import_id}")
def ledger_delete_import(import_id: int, request: Request):
    return {"removed": ledger.delete_import(_uid(request), import_id)}


@router.delete("/api/ledger")
async def ledger_clear(request: Request):
    uid = _uid(request)
    ledger_ask.stop_categorise(uid)
    ledger_ask.stop(uid)
    ledger.clear(uid)
    ledger_ask.reset(uid)
    return {"cleared": True}


@router.get("/api/ledger/overview")
def ledger_overview(request: Request, frm: str = "", to: str = "", account: str = "",
                    top: int = 50, baseline: int = 0):
    return ledger.overview(_uid(request), frm or None, to or None, account or None,
                           top=top, baseline=max(0, min(baseline, 36)))


@router.get("/api/ledger/transactions")
def ledger_transactions(request: Request, q: str = "", category: str = "*", merchant: str = "",
                        frm: str = "", to: str = "", account: str = "", direction: str = "",
                        order: str = "newest", offset: int = 0, limit: int = 100):
    return ledger.transactions(_uid(request), q=q, category=category, merchant=merchant or None,
                               frm=frm or None, to=to or None, account=account or None,
                               direction=direction, order=order, offset=offset, limit=limit)


@router.get("/api/ledger/merchants")
def ledger_merchants(request: Request, q: str = "", category: str = "*", limit: int = 300):
    return ledger.merchants(_uid(request), q=q, category=category, limit=limit)


class MerchantBody(BaseModel):
    key: str
    category: str | None = None
    name: str | None = None


@router.put("/api/ledger/merchants")
def ledger_merchant_update(body: MerchantBody, request: Request):
    uid = _uid(request)
    if body.category is not None:
        if not _call(ledger.set_category, uid, body.key, body.category):
            raise HTTPException(404, "No such merchant.")
    if body.name is not None:
        if not _call(ledger.rename_merchant, uid, body.key, body.name):
            raise HTTPException(404, "No such merchant.")
    return {"ok": True}


class SettingsBody(BaseModel):
    model: str


@router.put("/api/ledger/settings")
def ledger_settings(body: SettingsBody, request: Request):
    return ledger.set_settings(_uid(request), body.model)


@router.post("/api/ledger/categorise")
async def ledger_categorise(request: Request):
    return _call(ledger_ask.submit_categorise, _uid(request))


@router.post("/api/ledger/categorise/stop")
async def ledger_categorise_stop(request: Request):
    return ledger_ask.stop_categorise(_uid(request))


@router.get("/api/ledger/categorise")
def ledger_categorise_state(request: Request):
    return ledger_ask.cat_view(_uid(request))


class AskBody(BaseModel):
    question: str
    model: str | None = None


@router.post("/api/ledger/ask")
async def ledger_ask_post(body: AskBody, request: Request):
    """Queue one question; the page polls GET."""
    return _call(ledger_ask.submit, _uid(request), body.question, body.model)


@router.get("/api/ledger/ask")
def ledger_ask_state(request: Request):
    return ledger_ask.view(_uid(request)) or {"state": "none"}


@router.post("/api/ledger/ask/stop")
async def ledger_ask_stop(request: Request):
    return ledger_ask.stop(_uid(request)) or {"state": "none"}


@router.get("/api/ledger/ask/export")
def ledger_ask_export(request: Request):
    from app.meta import APP_VERSION
    text = _call(ledger_ask.markdown, _uid(request), APP_VERSION)
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="okonomi-question.md"'})
