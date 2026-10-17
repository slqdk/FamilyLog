"""FamilyMap: places from OpenStreetMap (2.44.0).

Søren chose OSM over Google: OSM data may be stored (ODbL, credited as
"© OpenStreetMap contributors"), Google's may not - only place ids, and
coordinates for 30 days, under Google's terms. So places come from OSM via
the Overpass API, one query per category, for Denmark, Schleswig-Holstein
and Hamburg. There are no ratings in OSM; the web-rating columns stay
empty. Places without a name are skipped (his choice) - which also skips
most playgrounds and beaches, because OSM rarely names them.

An import is idempotent: a place is keyed by its OSM id (`node/123`), a
second import updates what OSM changed and adds what is new. It never
deletes - a place gone from OSM may carry the family's reviews - and never
touches a place the admin corrected (`locked`).
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx

from app.core import db, logs

from . import familymap as fm

# The region, as Overpass areas: Denmark (the country relation, not
# Greenland or the Faroes, which have their own codes), Schleswig-Holstein
# and Hamburg.
REGION = ('area["ISO3166-1"="DK"][admin_level=2];'
          'area["ISO3166-2"="DE-SH"];'
          'area["ISO3166-2"="DE-HH"];')
REGION_LABEL = "Danmark, Schleswig-Holstein og Hamburg"

# Category -> the OSM selectors that feed it. Every selector also requires
# a name. The order matters once: a feature matching two categories goes
# to the first one that finds it in a run (a museum that is also tagged as
# an attraction is still one place).
OSM_SOURCES: dict[str, list[tuple[str, str, str]]] = {
    # (element types, key, value regex)
    "restaurant": [("nwr", "amenity", "restaurant|cafe|fast_food|ice_cream")],
    "hotel":      [("nwr", "tourism", "hotel|motel|guest_house|hostel")],
    "city":       [("node", "place", "city|town")],
    # Unnamed playgrounds too (2.49.1, Søren's choice): OSM rarely names
    # them. They get "Legeplads, <street>" (see parse); private ones - a
    # kindergarten's, a housing co-op's - stay out.
    "playground": [("nwr", "leisure", "playground"),
                   ("nwr", "leisure", "playground",
                    '[!"name"]["access"!~"^(private|no|customers)$"]')],
    # (kind, key, values, extra filters) - the fourth element narrows a
    # broad tag: a sports centre is only an activity here when it swims or
    # climbs, a pool only when it is not private. (2.49.0)
    "activity":   [("nwr", "leisure", "sports_centre|sports_hall", '["sport"~"swimming"]'),
                   ("nwr", "leisure", "swimming_pool", '["access"!~"^(private|no|customers)$"]'),
                   ("nwr", "leisure", "indoor_play|trampoline_park|ice_rink"),
                   ("nwr", "amenity", "cinema"),
                   ("nwr", "leisure", "sports_centre|sports_hall", '["sport"~"climbing"]')],
    "attraction": [("nwr", "tourism", "museum|zoo|aquarium|theme_park|attraction"),
                   ("nwr", "leisure", "water_park")],
    "nature":     [("nwr", "natural", "beach"),
                   ("nwr", "leisure", "nature_reserve|park"),
                   ("nwr", "boundary", "national_park")],
}

# Tags worth keeping for the model later (release 3): what a family asks
# about. Stored in the place's `extra`, never shown as-is.
KEEP_TAGS = ("cuisine", "opening_hours", "outdoor_seating", "wheelchair",
             "min_age", "max_age", "fee", "stars", "phone", "description",
             "diet:vegetarian", "diet:vegan", "takeaway", "changing_table",
             "toilets", "population")

QUERY_TIMEOUT_S = 600
PAUSE_BETWEEN_S = 5.0          # Overpass asks clients not to hammer it
# A busy public Overpass answers 429 (too many requests) or 502/503/504
# (its dispatcher gave up waiting for a free slot) - even for a tiny query:
# the first real run lost "city" and "playground" to 504s while the big
# categories went through. Those are retried after a wait; any other error
# is not. (2.44.1)
BUSY_STATUSES = (429, 502, 503, 504)
RETRY_WAITS_S = (30.0, 90.0)   # two retries: after 30 s, then 90 s


class Busy(RuntimeError):
    pass
USER_AGENT = "FamilyLog FamilyMap (self-hosted; one import at a time)"


def build_query(category: str) -> str:
    def one(sel) -> str:
        extra = sel[3] if len(sel) > 3 else ""
        # A selector asking for the UNnamed ones must not also require a name.
        named = "" if '!"name"' in extra else '["name"]'
        return f'{sel[0]}["{sel[1]}"~"^({sel[2]})$"]{extra}{named}(area.r);'
    parts = "".join(one(sel) for sel in OSM_SOURCES[category])
    # `out center` (full body, not `tags`): `tags` leaves the coordinates
    # off, and a point without a position cannot be found by distance.
    # `center` gives ways and relations one point. (2.46.0)
    return (f"[out:json][timeout:{QUERY_TIMEOUT_S}];({REGION})->.r;"
            f"({parts});out center qt;")


# ---- the gazetteer (2.46.0) ---------------------------------------------------------
# Every town, village and district name in the region with its position,
# so "omkring Vojens" and "i Flensborg" can be turned into a point. Only
# looked up, never shown as a place - villages are not places (Søren's
# choice), but they are where people live.

LOCALITIES = "localities"
LOCALITY_KINDS = ("city", "town", "village", "suburb", "hamlet")
_KIND_RANK = {k: i for i, k in enumerate(LOCALITY_KINDS)}
_NAME_TAGS = ("name", "name:da", "name:de", "name:en", "alt_name", "old_name",
              "short_name", "official_name")


def locality_query() -> str:
    kinds = "|".join(LOCALITY_KINDS)
    return (f"[out:json][timeout:{QUERY_TIMEOUT_S}];({REGION})->.r;"
            f'(node["place"~"^({kinds})$"]["name"](area.r););out body qt;')


def norm(name: str) -> str:
    return " ".join(str(name).casefold().replace("-", " ").split())


def parse_localities(elements: list[dict]) -> list[dict]:
    out = []
    for el in elements:
        tags = el.get("tags") or {}
        if el.get("lat") is None or not tags.get("name"):
            continue
        variants = set()
        for key in _NAME_TAGS:
            for v in str(tags.get(key) or "").split(";"):
                if v.strip():
                    variants.add(norm(v))
        out.append({"osmId": f"node/{el['id']}", "name": tags["name"],
                    "kind": tags.get("place", "hamlet"),
                    "lat": float(el["lat"]), "lng": float(el["lon"]),
                    "names": "|" + "|".join(sorted(variants)) + "|"})
    return out


def upsert_localities(rows: list[dict]) -> dict:
    added = updated = 0
    with db.connect() as con:
        for r in rows:
            cur = con.execute(
                "UPDATE fm_localities SET name = ?, kind = ?, lat = ?, lng = ?, names = ?"
                " WHERE osm_id = ?",
                (r["name"], r["kind"], r["lat"], r["lng"], r["names"], r["osmId"]))
            if cur.rowcount:
                updated += 1
            else:
                con.execute("INSERT INTO fm_localities (osm_id, name, kind, lat, lng, names)"
                            " VALUES (?,?,?,?,?,?)",
                            (r["osmId"], r["name"], r["kind"], r["lat"], r["lng"], r["names"]))
                added += 1
    return {"added": added, "updated": updated, "unchanged": 0, "locked": 0}


def nearest_locality(lat: float, lng: float) -> dict | None:
    """The closest town, village or hamlet to a point, within ~30 km. (2.49.0)"""
    import math
    with db.connect() as con:
        rows = con.execute("SELECT name, kind, lat, lng FROM fm_localities"
                           " WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
                           (lat - .3, lat + .3, lng - .5, lng + .5)).fetchall()
    if not rows:
        return None
    k = math.cos(math.radians(lat))
    best = min(rows, key=lambda r: (r["lat"] - lat) ** 2 + ((r["lng"] - lng) * k) ** 2)
    return {"name": best["name"], "kind": best["kind"], "lat": best["lat"], "lng": best["lng"]}


def find_locality(name: str) -> dict | None:
    """The best match for a town name: exact name variant, bigger places
    first (a city beats a hamlet of the same name)."""
    key = norm(name)
    if not key:
        return None
    with db.connect() as con:
        rows = con.execute("SELECT * FROM fm_localities WHERE names LIKE ?",
                           (f"%|{key}|%",)).fetchall()
    if not rows:
        return None
    best = min(rows, key=lambda r: _KIND_RANK.get(r["kind"], 9))
    return {"name": best["name"], "kind": best["kind"], "lat": best["lat"], "lng": best["lng"]}


def _address(tags: dict) -> str:
    street = " ".join(x for x in (tags.get("addr:street"), tags.get("addr:housenumber")) if x)
    town = " ".join(x for x in (tags.get("addr:postcode"),
                                tags.get("addr:city") or tags.get("addr:place")) if x)
    return ", ".join(x for x in (street, town) if x)


# Categories whose unnamed places are kept, with a made-up name. (2.49.1)
UNNAMED_LABEL = {"playground": "Legeplads"}


class _Towns:
    """The gazetteer in memory with a coarse grid, for naming thousands of
    unnamed places without a query each."""
    def __init__(self):
        self.cells: dict[tuple[int, int], list] = {}
        with db.connect() as con:
            for r in con.execute("SELECT name, lat, lng FROM fm_localities"):
                self.cells.setdefault((int(r["lat"] * 10), int(r["lng"] * 10)), []) \
                    .append((r["lat"], r["lng"], r["name"]))

    def nearest(self, lat: float, lng: float) -> str | None:
        ci, cj = int(lat * 10), int(lng * 10)
        best, best_d = None, 1e9
        for di in (-1, 0, 1):
            for dj in (-2, -1, 0, 1, 2):
                for la, ln, name in self.cells.get((ci + di, cj + dj), ()):
                    d = (la - lat) ** 2 + ((ln - lng) * 0.57) ** 2
                    if d < best_d:
                        best, best_d = name, d
        return best


def made_up_name(category: str, tags: dict, lat: float, lng: float,
                 towns: "_Towns | None") -> tuple[str, str]:
    """(name, how): "Legeplads, Vestergade" from the element's own street,
    else "Legeplads ved Vojens" from the nearest town, else "Legeplads".
    `how` lets the place page upgrade a town name to a street later."""
    label = UNNAMED_LABEL[category]
    street = (tags.get("addr:street") or "").strip()
    if street:
        return f"{label}, {street}", "street"
    town = towns.nearest(lat, lng) if towns else None
    if town:
        return f"{label} ved {town}", "town"
    return label, "none"


def parse(elements: list[dict], category: str, towns: "_Towns | None" = None) -> list[dict]:
    """Overpass elements -> place rows. Positionless ones are dropped; so
    are unnamed ones, except in categories that give them a made-up name."""
    out = []
    for el in elements:
        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lng = el.get("lon", (el.get("center") or {}).get("lon"))
        if lat is None or lng is None or not el.get("type") or el.get("id") is None:
            continue
        generated = None
        if not name:
            if category not in UNNAMED_LABEL:
                continue
            name, generated = made_up_name(category, tags, float(lat), float(lng), towns)
        out.append({
            "sourceId": f"{el['type']}/{el['id']}",
            "name": name[:fm.MAX_SHORT],
            "category": category,
            "address": _address(tags)[:fm.MAX_SHORT],
            "lat": float(lat), "lng": float(lng),
            "website": (tags.get("website") or tags.get("contact:website")
                        or tags.get("url") or "")[:500],
            "extra": {**{k: tags[k] for k in KEEP_TAGS if k in tags},
                      **({"nameGenerated": generated} if generated else {})},
        })
    return out


def upsert(places: list[dict], seen: set[str]) -> dict:
    """Write one category's places. `seen` carries the OSM ids already
    written in this run, so a feature in two categories lands once."""
    added = updated = unchanged = locked = 0
    now = db.utcnow()
    with db.connect() as con:
        for p in places:
            if p["sourceId"] in seen:
                continue
            seen.add(p["sourceId"])
            extra = json.dumps(p["extra"], ensure_ascii=False, sort_keys=True)
            row = con.execute(
                "SELECT id, name, category, address, lat, lng, website, extra, locked"
                " FROM fm_places WHERE source = 'osm' AND source_id = ?",
                (p["sourceId"],)).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO fm_places (name, category, address, lat, lng, website,"
                    " notes, source, source_id, extra, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,'','osm',?,?,?,?)",
                    (p["name"], p["category"], p["address"], p["lat"], p["lng"],
                     p["website"], p["sourceId"], extra, now, now))
                added += 1
            elif row["locked"]:
                locked += 1
            elif p["extra"].get("nameGenerated") and \
                    json.loads(row["extra"] or "{}").get("nameGenerated") == "lookup":
                # A made-up name the place page already improved with a real
                # street (Nominatim) is better than the import's guess. (2.49.1)
                unchanged += 1
            elif (row["name"], row["address"], row["website"], row["extra"]) == \
                    (p["name"], p["address"], p["website"], extra) and \
                    abs((row["lat"] or 0) - p["lat"]) < 1e-6 and \
                    abs((row["lng"] or 0) - p["lng"]) < 1e-6:
                unchanged += 1
            else:
                # The category is not overwritten: the first import decided
                # it, and a later one must not shuffle places between tabs.
                con.execute(
                    "UPDATE fm_places SET name = ?, address = ?, lat = ?, lng = ?,"
                    " website = ?, extra = ?, updated_at = ? WHERE id = ?",
                    (p["name"], p["address"], p["lat"], p["lng"], p["website"],
                     extra, now, row["id"]))
                updated += 1
    return {"added": added, "updated": updated, "unchanged": unchanged, "locked": locked}


# ---- the run ------------------------------------------------------------------

_state: dict = {"running": False, "startedAt": None, "finishedAt": None,
                "error": None, "categories": {}}
_task: asyncio.Task | None = None


def state() -> dict:
    return json.loads(json.dumps(_state))


async def fetch(url: str, query: str) -> list[dict]:
    """POST one Overpass query. Separate so tests replace it."""
    async with httpx.AsyncClient(timeout=QUERY_TIMEOUT_S + 30,
                                 headers={"User-Agent": USER_AGENT}) as client:
        r = await client.post(url, data={"data": query})
        if r.status_code in BUSY_STATUSES:
            raise Busy(f"Overpass is busy ({r.status_code}).")
        r.raise_for_status()
        return r.json().get("elements") or []


async def _fetch_patiently(url: str, query: str, entry: dict) -> list[dict]:
    for attempt in range(len(RETRY_WAITS_S) + 1):
        try:
            return await fetch(url, query)
        except Busy as exc:
            if attempt == len(RETRY_WAITS_S):
                raise Busy(f"{exc} Gave up after {attempt + 1} tries - "
                           "use Retry failed later.") from None
            wait = RETRY_WAITS_S[attempt]
            entry["state"] = "retrying"
            entry["error"] = f"{exc} Retrying in {int(wait)} s."
            await asyncio.sleep(wait)
            entry["state"] = "fetching"
            entry["error"] = None
    raise AssertionError("unreachable")


def overpass_url() -> str:
    """FamilyMap's own override, else the global setting (FamilyLog 0.1.0)."""
    from app.core import settings
    return (fm.get_settings()["overpassUrl"] or settings.load().get("overpassUrl")
            or settings.DEFAULTS["overpassUrl"])


async def _run(categories: list[str], pause_s: float) -> None:
    url = overpass_url()
    seen: set[str] = set()
    try:
        for i, cat in enumerate(categories):
            entry = _state["categories"][cat]
            if i and pause_s:
                await asyncio.sleep(pause_s)
            entry["state"] = "fetching"
            t0 = time.time()
            try:
                if cat == LOCALITIES:
                    elements = await _fetch_patiently(url, locality_query(), entry)
                    rows = parse_localities(elements)
                    entry["state"] = "saving"
                    entry["found"] = len(rows)
                    entry.update(await asyncio.to_thread(upsert_localities, rows))
                else:
                    elements = await _fetch_patiently(url, build_query(cat), entry)
                    towns = await asyncio.to_thread(_Towns) if cat in UNNAMED_LABEL else None
                    places = parse(elements, cat, towns)
                    entry["state"] = "saving"
                    entry["found"] = len(places)
                    entry.update(await asyncio.to_thread(upsert, places, seen))
                entry["state"] = "done"
            except asyncio.CancelledError:
                entry["state"] = "stopped"
                raise
            except Exception as exc:
                entry["state"] = "failed"
                entry["error"] = str(exc) or exc.__class__.__name__
                logs.record_exception(exc, f"FamilyMap OSM import: {cat}")
            entry["seconds"] = round(time.time() - t0, 1)
    except asyncio.CancelledError:
        _state["error"] = "Stopped."
        for entry in _state["categories"].values():
            if entry["state"] == "waiting":
                entry["state"] = "stopped"
    finally:
        _state["running"] = False
        _state["finishedAt"] = db.utcnow()


def start(categories: list[str] | None = None, pause_s: float = PAUSE_BETWEEN_S) -> dict:
    global _task
    if _state["running"]:
        raise fm.Invalid("An import is already running.")
    # Town names first: the unnamed playgrounds are named after the nearest
    # town, so the gazetteer should be fresh before they are. (2.49.1)
    cats = categories or [LOCALITIES, *OSM_SOURCES]
    for c in cats:
        if c not in OSM_SOURCES and c != LOCALITIES:
            raise fm.Invalid(f"Unknown category: {c}.")
    _state.update({"running": True, "startedAt": db.utcnow(), "finishedAt": None,
                   "error": None,
                   "categories": {c: {"state": "waiting", "found": None} for c in cats}})
    _task = asyncio.get_running_loop().create_task(_run(cats, pause_s))
    return state()


def stop() -> dict:
    if _task is not None and not _task.done():
        _task.cancel()
    return state()


async def wait() -> None:
    """Test helper."""
    if _task is not None:
        try:
            await _task
        except asyncio.CancelledError:
            pass


def describe_sources() -> dict:
    """What the admin page shows about where places come from."""
    with db.connect() as con:
        n_loc = con.execute("SELECT COUNT(*) FROM fm_localities").fetchone()[0]
    return {"region": REGION_LABEL,
            "sources": {**{c: [f"{s[0]} {s[1]}={s[2].replace('|', ', ')}"
                               + (" " + s[3].replace('"', '') if len(s) > 3 else "")
                               for s in sel]
                           for c, sel in OSM_SOURCES.items()},
                        LOCALITIES: [f"node place={', '.join(LOCALITY_KINDS)} "
                                     f"(town names for Spørg Alf - {n_loc} stored, "
                                     "not shown as places)"]}}
