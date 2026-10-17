"""FamilyMap endpoints (2.43.0).

Two halves:

* `/api/fm/...` - the family's mobile page. Any signed-in user may call it;
  a `family` user may call nothing else (auth.family_allows, enforced in
  the auth middleware). Reviews and photos can be changed by their author
  or the admin.
* `/api/familymap/...` - the admin section in the app. Admin only.

Messages are Danish on the family half (they are shown on the phone as
they are) and English on the admin half.
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.core import auth

from . import familymap as fm, familymap_ask as ask, familymap_osm as osm
from . import familymap_geo as geo, familymap_vision as vision

router = APIRouter()


def _me(request: Request) -> dict:
    return request.state.user


def _admin(request: Request) -> dict:
    me = _me(request)
    if me["role"] != "admin":
        raise HTTPException(403, "Administrator only.")
    return me


def _may_change(me: dict, owner_id: int | None) -> None:
    if me["role"] == "admin" or (owner_id is not None and owner_id == me["id"]):
        return
    raise HTTPException(403, "Du kan kun ændre dine egne anmeldelser.")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except fm.Invalid as exc:
        raise HTTPException(400, str(exc))
    except fm.NotFound as exc:
        raise HTTPException(404, str(exc))


# ---- the family's page -------------------------------------------------------

@router.get("/api/fm/me")
def fm_me(request: Request):
    me = _me(request)
    return {"id": me["id"], "username": me["username"], "role": me["role"]}


@router.get("/api/fm/brand")
def fm_brand():
    """The family page's name, before anyone signs in - the login screen
    shows it. Public (auth.PUBLIC_PATHS); it is only the name. (2.44.1)"""
    return {"name": fm.get_settings()["appName"]}


@router.post("/api/fm/ask")
async def fm_ask(body: dict, request: Request):
    """Spørg Alf (2.46.0): queue one question; the phone polls GET."""
    phone = None
    lat, lng = body.get("lat"), body.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)) \
            and -90 <= lat <= 90 and -180 <= lng <= 180:
        phone = (float(lat), float(lng))
    # The radius chosen on the page (2.47.0); none means Alf decides.
    radius = body.get("radiusKm")
    radius = float(radius) if isinstance(radius, (int, float)) and radius > 0 else None
    return _call(ask.submit, _me(request)["id"], body.get("question"), phone, radius)


@router.get("/api/fm/ask")
def fm_ask_state(request: Request):
    return ask.view(_me(request)["id"]) or {"state": "none"}


@router.get("/api/fm/map")
def fm_map(request: Request):
    """All places for the phone's map (2.47.0). Gzipped here (the app has no
    compression of its own, and 27,000 places are ~1.2 MB as JSON), with an
    ETag so an unchanged map costs one round trip and no body."""
    import gzip
    import hashlib
    import json as _json
    body = _json.dumps(fm.map_points(_me(request)["id"]), ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")
    etag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache", "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(gzip.compress(body, 6), media_type="application/json",
                        headers={**headers, "Content-Encoding": "gzip"})
    return Response(body, media_type="application/json", headers=headers)


@router.get("/api/fm/reverse")
async def fm_reverse(lat: float, lng: float):
    """Address (and, when OSM has a place there, its name and category) for
    a point tapped on the map - the new-place form fills them in. (2.49.0)"""
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(400, "Positionen er uden for kortet.")
    return await geo.reverse(lat, lng)


@router.get("/api/fm/categories")
def fm_categories():
    return fm.categories()


@router.get("/api/fm/places")
def fm_places(request: Request, q: str = "", category: str = "", reviewed: str = "",
              lat: float | None = None, lng: float | None = None, limit: int = 500,
              wished: int = 0):
    """With lat/lng (the phone's position): nearest first, each with its
    distance. Without: reviewed first, then by name. (2.44.0)"""
    near = None
    if lat is not None and lng is not None:
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise HTTPException(400, "Positionen er uden for kortet.")
        near = (lat, lng)
    return _call(fm.list_places, q=q, category=category, reviewed=reviewed,
                 limit=limit, near=near, me=_me(request)["id"], wished_only=bool(wished))


@router.post("/api/fm/places")
def fm_create_place(body: dict, request: Request):
    body = {k: v for k, v in body.items() if k != "source"}   # family = family
    return _call(fm.create_place, body, _me(request)["id"])


@router.get("/api/fm/places/{pid}")
async def fm_place(pid: int, request: Request):
    place = _call(fm.get_place, pid, me=_me(request)["id"])
    # An unnamed playground's "ved <town>" becomes its street. (2.49.1)
    place = await geo.improve_made_up_name(place)
    place["reviews"] = fm.reviews_for_place(pid)
    return place


@router.put("/api/fm/wishlist/{pid}")
def fm_wish(pid: int, request: Request):
    return _call(fm.set_wished, _me(request)["id"], pid, True)


@router.delete("/api/fm/wishlist/{pid}")
def fm_unwish(pid: int, request: Request):
    return _call(fm.set_wished, _me(request)["id"], pid, False)


@router.get("/api/fm/me/reviews")
def fm_my_reviews(request: Request):
    return fm.my_reviews(_me(request)["id"])


@router.get("/api/fm/me/places")
def fm_my_places(request: Request):
    """The places this person created - to find and correct them. (2.49.5)"""
    return fm.my_places(_me(request)["id"])


def _may_change_place(me: dict, pid: int) -> None:
    owner = _call(fm.place_owner, pid)
    if me["role"] == "admin" or (owner is not None and owner == me["id"]):
        return
    raise HTTPException(403, "Du kan kun rette steder, du selv har oprettet.")


@router.put("/api/fm/places/{pid}")
def fm_update_place(pid: int, body: dict, request: Request):
    """The creator (or the admin) corrects a place. Imported places belong
    to nobody here - only the admin section changes those. (2.49.5)"""
    me = _me(request)
    _may_change_place(me, pid)
    return _call(fm.update_place, pid, body)


@router.delete("/api/fm/places/{pid}")
def fm_delete_place(pid: int, request: Request):
    """The creator deletes their place - not when someone else has reviewed
    it: that review is theirs. The admin may always. (2.49.5)"""
    me = _me(request)
    _may_change_place(me, pid)
    if me["role"] != "admin" and fm.others_reviewed(pid, me["id"]):
        raise HTTPException(400, "Andre har anmeldt stedet, så det kan ikke slettes. "
                                 "Ret det i stedet, eller bed administratoren slette det.")
    _call(fm.delete_place, pid)
    return {"ok": True}


@router.get("/api/fm/me/photos")
def fm_my_photos(request: Request):
    return fm.my_photos(_me(request)["id"])


@router.post("/api/fm/places/{pid}/reviews")
def fm_create_review(pid: int, body: dict, request: Request):
    return _call(fm.create_review, pid, body, _me(request)["id"])


@router.put("/api/fm/reviews/{rid}")
def fm_update_review(rid: int, body: dict, request: Request):
    _may_change(_me(request), _call(fm.review_owner, rid))
    return _call(fm.update_review, rid, body)


@router.delete("/api/fm/reviews/{rid}")
def fm_delete_review(rid: int, request: Request):
    _may_change(_me(request), _call(fm.review_owner, rid))
    _call(fm.delete_review, rid)
    return {"ok": True}


@router.post("/api/fm/reviews/{rid}/photos")
async def fm_add_photos(rid: int, request: Request,
                        files: list[UploadFile] = File(...)):
    _may_change(_me(request), _call(fm.review_owner, rid))
    if len(files) > fm.MAX_PHOTOS_PER_UPLOAD:
        raise HTTPException(400, f"Højst {fm.MAX_PHOTOS_PER_UPLOAD} billeder ad gangen.")
    datas = []
    for f in files:
        # Read one byte past the cap: enough to know it is too big without
        # holding a runaway upload in memory.
        data = await f.read(fm.MAX_PHOTO_BYTES + 1)
        datas.append(data)
    added = _call(fm.add_photos, rid, datas)
    # Straight into the GPU queue (or marked 'nomodel' when FamilyMap has no
    # vision model chosen). The upload does not wait for it. (2.44.0)
    vision.enqueue([p["id"] for p in added])
    return [fm.get_photo(p["id"]) for p in added]


@router.get("/api/fm/photos/{photo_id}")
def fm_photo(photo_id: int, thumb: int = 0):
    path = _call(fm.photo_file, photo_id, thumb=bool(thumb))
    media = {".jpg": "image/jpeg", ".png": "image/png",
             ".webp": "image/webp"}.get(path.suffix, "application/octet-stream")
    # Photos never change under an id (a new photo is a new id), so the
    # phone may keep them - private, because they sit behind a login.
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "private, max-age=2592000"})


@router.delete("/api/fm/photos/{photo_id}")
def fm_delete_photo(photo_id: int, request: Request):
    _may_change(_me(request), _call(fm.photo_owner, photo_id))
    _call(fm.delete_photo, photo_id)
    return {"ok": True}


# ---- the admin section ---------------------------------------------------------

@router.get("/api/familymap/stats")
def admin_stats(request: Request):
    _admin(request)
    return fm.stats()


@router.put("/api/familymap/places/{pid}")
def admin_update_place(pid: int, body: dict, request: Request):
    _admin(request)
    return _call(fm.update_place, pid, body)


@router.delete("/api/familymap/places/{pid}")
def admin_delete_place(pid: int, request: Request):
    _admin(request)
    _call(fm.delete_place, pid)
    return {"ok": True}


@router.get("/api/familymap/reviews")
def admin_reviews(request: Request, limit: int = 200):
    _admin(request)
    return fm.list_reviews(limit)


class FamilyUserBody(BaseModel):
    username: str
    password: str


@router.get("/api/familymap/users")
def admin_family_users(request: Request):
    _admin(request)
    online = {s["userId"] for s in auth.active_sessions()}
    users = [u for u in auth.list_users() if u["role"] == auth.FAMILY_ROLE]
    for u in users:
        u["online"] = u["id"] in online
    return users


@router.post("/api/familymap/users")
def admin_create_family_user(body: FamilyUserBody, request: Request):
    _admin(request)
    try:
        return auth.create_user(body.username, body.password, auth.FAMILY_ROLE)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ---- settings, OSM import, photo descriptions (2.44.0) ------------------------------

@router.get("/api/familymap/settings")
def admin_settings(request: Request):
    _admin(request)
    return fm.get_settings()


@router.put("/api/familymap/settings")
def admin_set_settings(body: dict, request: Request):
    _admin(request)
    return _call(fm.set_settings, body)


def _import_view() -> dict:
    """The one shape every import endpoint answers with. 2.44.0's start and
    stop returned the run state without `sources`, and the admin page -
    which draws its table from `sources` - crashed the moment Import was
    pressed. (2.44.1)"""
    return {**osm.state(), **osm.describe_sources()}


@router.get("/api/familymap/import")
def admin_import_state(request: Request):
    _admin(request)
    return _import_view()


@router.post("/api/familymap/import")
async def admin_import_start(request: Request, body: dict | None = None):
    _admin(request)
    cats = (body or {}).get("categories") or None
    _call(osm.start, cats)
    return _import_view()


@router.post("/api/familymap/import/stop")
async def admin_import_stop(request: Request):
    _admin(request)
    osm.stop()
    return _import_view()


@router.post("/api/familymap/describe")
async def admin_describe_waiting(request: Request):
    """Queue every photo still without a description - after choosing a
    vision model, after a failure, or after a restart emptied the queue."""
    _admin(request)
    if not fm.vision_model():
        raise HTTPException(400, "Choose a vision model in Settings (or FamilyMap → Settings) first.")
    return vision.enqueue(fm.photos_to_describe())
