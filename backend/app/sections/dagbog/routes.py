"""Dagbog endpoints - /api/dagbog/... (FamilyLog 0.2.0).

Every account (family included) writes its own days and reads the family
overview. The entry and photo endpoints only ever act on the signed-in
person's own rows; /api/dagbog/admin/... is the administrator's (tags and
which fields each person records)."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from . import dagbog

router = APIRouter()


def _uid(request: Request) -> int:
    return request.state.user["id"]


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except dagbog.Invalid as exc:
        raise HTTPException(400, str(exc))
    except dagbog.NotFound as exc:
        raise HTTPException(404, str(exc))


@router.get("/api/dagbog/config")
def dagbog_config(request: Request):
    return dagbog.config(_uid(request))


@router.get("/api/dagbog/entry")
def dagbog_entry(day: str, request: Request):
    return {"entry": _call(dagbog.get_entry, _uid(request), day)}


@router.put("/api/dagbog/entry")
def dagbog_save(body: dict, request: Request):
    return {"entry": _call(dagbog.save_entry, _uid(request), body)}


@router.delete("/api/dagbog/entry")
def dagbog_delete(day: str, request: Request):
    _call(dagbog.delete_entry, _uid(request), day)
    return {"ok": True}


@router.get("/api/dagbog/family")
def dagbog_family(frm: str, to: str, request: Request):
    """The family's week - for the family (family accounts and the
    administrator); a user account keeps its own Dagbog only (0.3.7)."""
    if not dagbog.is_family(request.state.user):
        raise HTTPException(403, "Familiens uge er kun for familien.")
    return _call(dagbog.family, frm, to)


def _family_call(fn, *args):
    try:
        return _call(fn, *args)
    except dagbog.Forbidden as exc:
        raise HTTPException(403, str(exc))


@router.get("/api/dagbog/person")
def dagbog_person(user: int, request: Request, before: str = "", limit: int = 20):
    """One person's days, newest first, going back (0.3.9)."""
    return _family_call(dagbog.person_days, request.state.user, user, before or None, limit)


@router.get("/api/dagbog/person/month")
def dagbog_person_month(user: int, month: str, request: Request):
    return _family_call(dagbog.month_moods, request.state.user, user, month)


@router.get("/api/dagbog/stats")
def dagbog_stats(user: int, request: Request, frm: str = "", to: str = ""):
    """One person's statistics (0.3.9)."""
    return _family_call(dagbog.stats, request.state.user, user, frm or None, to or None)


@router.get("/api/dagbog/mine")
def dagbog_mine(frm: str, to: str, request: Request):
    """The days this person has filled in (for the calendar dots)."""
    return {"days": dagbog.filled_days(_uid(request), frm, to)}


@router.post("/api/dagbog/photo")
async def dagbog_photo(day: str, request: Request, file: UploadFile = File(...)):
    data = await file.read(dagbog.fm.MAX_PHOTO_BYTES + 1)
    return {"entry": _call(dagbog.set_photo, _uid(request), day, data)}


@router.get("/api/dagbog/photo")
def dagbog_photo_get(day: str, request: Request, user: int | None = None):
    """Your own photo, or (0.3.9) a family member's from a day they share."""
    me = request.state.user
    try:
        path = _call(dagbog.photo_file, user or me["id"], day, me)
    except dagbog.Forbidden as exc:
        raise HTTPException(403, str(exc))
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "private, no-cache"})


@router.delete("/api/dagbog/photo")
def dagbog_photo_delete(day: str, request: Request):
    _call(dagbog.remove_photo, _uid(request), day)
    return {"entry": _call(dagbog.get_entry, _uid(request), day)}


# ---- the administrator ------------------------------------------------------------------------

def _admin(request: Request) -> None:
    if request.state.user["role"] != "admin":
        raise HTTPException(403, "Administrator only.")


@router.get("/api/dagbog/admin/settings")
def dagbog_admin(request: Request):
    _admin(request)
    return dagbog.admin_settings()


@router.put("/api/dagbog/admin/settings")
def dagbog_admin_save(body: dict, request: Request):
    """{"tags": [...]}, {"foods": [...]} and/or {"members": {"<user id>": [fields]}}."""
    _admin(request)
    if "tags" in body:
        _call(dagbog.set_tags, body["tags"])
    if "foods" in body:
        _call(dagbog.set_foods, body["foods"])
    for uid, fields in (body.get("members") or {}).items():
        try:
            uid_int = int(uid)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Not a user id: {uid}")
        _call(dagbog.set_fields_for, uid_int, fields)
    return dagbog.admin_settings()
