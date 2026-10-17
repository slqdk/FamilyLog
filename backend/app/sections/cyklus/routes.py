"""Cyklus endpoints - /api/cyklus/... (FamilyLog 0.3.0).

Every account may call /api/cyklus/state and /api/cyklus/shared (what is
shared with them). Everything else acts on the signed-in person's own cycle
and needs an account set to female. There is no endpoint that reads another
person's cycle except through shared_with(), which returns only what she
chose to share - and no administrator exception."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from . import cyklus

router = APIRouter()


def _me(request: Request, female: bool = True) -> dict:
    me = request.state.user
    if female:
        try:
            cyklus.require_female(me)
        except cyklus.Forbidden as exc:
            raise HTTPException(403, str(exc))
    return me


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except cyklus.Invalid as exc:
        raise HTTPException(400, str(exc))
    except cyklus.NotFound as exc:
        raise HTTPException(404, str(exc))


@router.get("/api/cyklus/state")
def cyklus_state(request: Request):
    """The front page's view: her own cycle when she is set to female, and
    the cycles shared with this account."""
    me = _me(request, female=False)
    out = {"enabled": cyklus.is_female(me), "shared": cyklus.shared_with(me["id"]),
           "options": cyklus.options()}
    if out["enabled"]:
        out["own"] = cyklus.own(me["id"])
    return out


@router.get("/api/cyklus/shared/calendar")
def cyklus_shared_calendar(owner: int, frm: str, to: str, request: Request):
    """Her days ahead as she shares them (any account she shares with)."""
    me = _me(request, female=False)
    try:
        return {"days": _call(cyklus.shared_calendar, me["id"], owner, frm, to)}
    except cyklus.Forbidden as exc:
        raise HTTPException(403, str(exc))


@router.get("/api/cyklus/shared/day")
def cyklus_shared_day(owner: int, day: str, request: Request):
    me = _me(request, female=False)
    try:
        return _call(cyklus.shared_day, me["id"], owner, day)
    except cyklus.Forbidden as exc:
        raise HTTPException(403, str(exc))


@router.get("/api/cyklus/calendar")
def cyklus_calendar(frm: str, to: str, request: Request):
    return {"days": _call(cyklus.calendar, _me(request)["id"], frm, to)}


@router.get("/api/cyklus/dayinfo")
def cyklus_dayinfo(day: str, request: Request):
    return _call(cyklus.day_info, _me(request)["id"], day)


@router.post("/api/cyklus/period/toggle")
def cyklus_toggle(body: dict, request: Request):
    uid = _me(request)["id"]
    _call(cyklus.toggle_period_day, uid, body.get("day"))
    return cyklus.own(uid)


@router.get("/api/cyklus/day")
def cyklus_day(day: str, request: Request):
    return {"day": _call(cyklus.get_day, _me(request)["id"], day)}


@router.put("/api/cyklus/day")
def cyklus_day_save(body: dict, request: Request):
    uid = _me(request)["id"]
    _call(cyklus.save_day, uid, body)
    return cyklus.own(uid)


@router.post("/api/cyklus/period/start")
def cyklus_start(body: dict, request: Request):
    uid = _me(request)["id"]
    _call(cyklus.start_period, uid, body.get("day"))
    return cyklus.own(uid)


@router.post("/api/cyklus/period/end")
def cyklus_end(body: dict, request: Request):
    uid = _me(request)["id"]
    _call(cyklus.end_period, uid, body.get("day"))
    return cyklus.own(uid)


@router.put("/api/cyklus/period/{pid}")
def cyklus_edit(pid: int, body: dict, request: Request):
    uid = _me(request)["id"]
    _call(cyklus.edit_period, uid, pid, body)
    return cyklus.own(uid)


@router.delete("/api/cyklus/period/{pid}")
def cyklus_delete(pid: int, request: Request):
    uid = _me(request)["id"]
    _call(cyklus.delete_period, uid, pid)
    return cyklus.own(uid)


@router.get("/api/cyklus/settings")
def cyklus_settings(request: Request):
    uid = _me(request)["id"]
    return {"settings": cyklus.settings(uid), "candidates": cyklus.candidates(uid)}


@router.put("/api/cyklus/settings")
def cyklus_settings_save(body: dict, request: Request):
    uid = _me(request)["id"]
    return {"settings": _call(cyklus.save_settings, uid, body), "candidates": cyklus.candidates(uid)}
