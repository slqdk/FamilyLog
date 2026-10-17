"""Where a tapped point is (2.49.0): address - and, when OSM has a place
there, its name and category - for the new-place form.

Nominatim (OpenStreetMap's own geocoder, Søren's choice): free and keyless,
with a usage policy of at most one request a second and a real
User-Agent; both are kept here, plus a small cache so a second look at the
same point costs nothing. When Nominatim cannot be reached the nearest
town from the gazetteer is the answer ("nær Vojens"), so the form never
waits on the internet to be usable.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from app.core import logs, settings

from . import familymap_osm as osm

# The Nominatim server is a global setting (nominatimUrl); /reverse is added.
USER_AGENT = "FamilyLog FamilyMap (self-hosted family app)"
MIN_INTERVAL_S = 1.1           # Nominatim's policy: at most 1 request/second
TIMEOUT_S = 8.0
CACHE_SIZE = 300

_lock = asyncio.Lock()
_last = 0.0
_cache: dict[tuple[float, float], dict] = {}

# (OSM class, type) -> FamilyMap category, the same kinds the import takes.
_GUESS = {
    ("amenity", "restaurant"): "restaurant", ("amenity", "cafe"): "restaurant",
    ("amenity", "fast_food"): "restaurant", ("amenity", "ice_cream"): "restaurant",
    ("tourism", "hotel"): "hotel", ("tourism", "motel"): "hotel",
    ("tourism", "guest_house"): "hotel", ("tourism", "hostel"): "hotel",
    ("leisure", "playground"): "playground",
    ("leisure", "sports_centre"): "activity", ("leisure", "sports_hall"): "activity",
    ("leisure", "swimming_pool"): "activity", ("leisure", "indoor_play"): "activity",
    ("leisure", "trampoline_park"): "activity", ("leisure", "ice_rink"): "activity",
    ("amenity", "cinema"): "activity",
    ("tourism", "museum"): "attraction", ("tourism", "zoo"): "attraction",
    ("tourism", "aquarium"): "attraction", ("tourism", "theme_park"): "attraction",
    ("tourism", "attraction"): "attraction", ("leisure", "water_park"): "attraction",
    ("natural", "beach"): "nature", ("leisure", "park"): "nature",
    ("leisure", "nature_reserve"): "nature", ("boundary", "national_park"): "nature",
}


def reverse_url() -> str:
    base = (settings.load().get("nominatimUrl") or settings.DEFAULTS["nominatimUrl"]).rstrip("/")
    return base if base.endswith("/reverse") else base + "/reverse"


async def nominatim(lat: float, lng: float) -> dict:
    """One reverse lookup. Separate so tests replace it."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}) as c:
        r = await c.get(reverse_url(), params={"lat": f"{lat:.6f}", "lon": f"{lng:.6f}",
                                     "format": "jsonv2", "zoom": 18, "addressdetails": 1,
                                     "accept-language": "da"})
        r.raise_for_status()
        return r.json()


def _format(addr: dict) -> str:
    street = " ".join(x for x in (addr.get("road") or addr.get("pedestrian")
                                  or addr.get("footway") or addr.get("path"),
                                  addr.get("house_number")) if x)
    town = addr.get("city") or addr.get("town") or addr.get("village") \
        or addr.get("hamlet") or addr.get("suburb") or addr.get("municipality")
    place = " ".join(x for x in (addr.get("postcode"), town) if x)
    return ", ".join(x for x in (street, place) if x)


def interpret(data: dict) -> dict:
    """Nominatim's answer -> what the form fills in."""
    cat = _GUESS.get((data.get("category") or data.get("class"), data.get("type")))
    name = (data.get("name") or "").strip() if cat else ""
    address = _format(data.get("address") or {}) or (data.get("display_name") or "")[:200]
    addr = data.get("address") or {}
    road = addr.get("road") or addr.get("pedestrian") or addr.get("footway") or addr.get("path")
    return {"address": address[:200], "name": name[:200] or None, "category": cat,
            "source": "nominatim", "road": road or None}


async def reverse(lat: float, lng: float) -> dict:
    global _last
    key = (round(lat, 5), round(lng, 5))
    if key in _cache:
        return _cache[key]
    try:
        async with _lock:
            wait = MIN_INTERVAL_S - (time.monotonic() - _last)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                data = await nominatim(lat, lng)
            finally:
                _last = time.monotonic()
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        out = interpret(data)
    except Exception as exc:
        logs.record_exception(exc, "FamilyMap address lookup (Nominatim)")
        town = osm.nearest_locality(lat, lng)
        out = {"address": f"nær {town['name']}" if town else "", "name": None,
               "category": None, "source": "town" if town else None, "road": None}
        return out                      # not cached: try Nominatim again next time
    if len(_cache) >= CACHE_SIZE:
        _cache.pop(next(iter(_cache)))
    _cache[key] = out
    return out



async def improve_made_up_name(place: dict) -> dict:
    """A playground the import named "Legeplads ved Vojens" gets its street
    the first time someone opens it: one Nominatim lookup, then never again
    ("lookup" in extra.nameGenerated). Thousands of them could not be looked
    up at import time within Nominatim's policy; this spreads the lookups
    over the places the family actually looks at. (2.49.1)"""
    from app.core import db
    from . import familymap as fm
    import json as _json
    extra = place.get("extra") or {}
    how = extra.get("nameGenerated")
    if how not in ("town", "none") or place.get("locked") or place.get("lat") is None:
        return place
    label = osm.UNNAMED_LABEL.get(place["category"])
    if not label:
        return place
    found = await reverse(place["lat"], place["lng"])
    if found.get("source") != "nominatim":
        return place                   # offline now; try again next time
    road = found.get("road")
    new_extra = {**extra, "nameGenerated": "lookup"}
    name = f"{label}, {road}" if road else place["name"]
    address = place["address"] or found.get("address") or ""
    with db.connect() as con:
        con.execute("UPDATE fm_places SET name = ?, address = ?, extra = ?, updated_at = ?"
                    " WHERE id = ?",
                    (name, address, _json.dumps(new_extra, ensure_ascii=False, sort_keys=True),
                     db.utcnow(), place["id"]))
    return {**place, "name": name, "address": address, "extra": new_extra}
