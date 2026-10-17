"""FamilyMap - the household's own reviews of places (2.43.0).

The family writes reviews on a Danish mobile page (/fm/); the app's
FamilyMap section is the admin. Later releases prefill places from Google
Places (place + its total rating only, never review text) and let the
family ask for day ideas in a chat that reads these reviews.

Design choices worth knowing:

* Categories and their review fields are FIXED here, in code (Søren's
  choice). The frontend reads them from `/api/fm/categories`, so this dict
  is the single source. Labels are Danish - they are shown on the family's
  page and are data, not app chrome.
* Every rating is an integer 1-100 (overall and sub-ratings).
* A place may carry a web rating (source, value, count, fetch date) that is
  kept apart from the family's own scores. Nothing here fetches it yet.
* Photos are re-encoded to JPEG (max 2048 px, EXIF stripped - a phone photo
  carries its GPS position) with a 480 px thumbnail. Pillow does that; if
  it is missing the original bytes are kept and served as both sizes, so an
  upload never fails for want of a library.
"""
from __future__ import annotations

import io
import json
import math
import secrets
import shutil
from pathlib import Path

from app.core import db

# ---- the fixed categories -------------------------------------------------
# Field kinds: rating (1-100), bool (ja/nej), choice (one of options),
# text (short free text). Every field is optional in a review; `overall`
# is the one required score and lives outside `fields`.

CATEGORIES: dict[str, dict] = {
    "restaurant": {"label": "Restaurant / café", "icon": "🍽", "fields": [
        # "Mad" is the average of the dishes below that got a score - never
        # set by hand (2.50.0, Søren: "mad scoren vil være et gennemsnit").
        # Each part has `part_of`, so the page groups them under "Mad".
        {"key": "food", "label": "Mad", "kind": "rating",
         "computed": ["meat", "salad", "fries", "rice", "pasta", "bread"]},
        {"key": "meat", "label": "Kød / stegning", "kind": "rating", "part_of": "food"},
        {"key": "salad", "label": "Salat", "kind": "rating", "part_of": "food"},
        {"key": "fries", "label": "Pommes frites", "kind": "rating", "part_of": "food"},
        {"key": "rice", "label": "Ris", "kind": "rating", "part_of": "food"},
        {"key": "pasta", "label": "Pasta", "kind": "rating", "part_of": "food"},
        {"key": "bread", "label": "Brød", "kind": "rating", "part_of": "food"},
        # Drinks the same way (2.50.1, Søren: "del gerne drikkevarer op").
        {"key": "drinks", "label": "Drikkevarer", "kind": "rating",
         "computed": ["soda", "beer", "wine", "coffee"]},
        {"key": "soda", "label": "Sodavand", "kind": "rating", "part_of": "drinks"},
        {"key": "beer", "label": "Øl", "kind": "rating", "part_of": "drinks"},
        {"key": "wine", "label": "Vin", "kind": "rating", "part_of": "drinks"},
        {"key": "coffee", "label": "Kaffe", "kind": "rating", "part_of": "drinks"},
        {"key": "service", "label": "Service", "kind": "rating"},
        {"key": "atmosphere", "label": "Stemning", "kind": "rating"},
        {"key": "price", "label": "Prisniveau", "kind": "choice",
         "options": ["Billig", "Middel", "Dyr"]},
        {"key": "kidFriendly", "label": "Børnevenlig", "kind": "bool"},
        {"key": "recommend", "label": "Ret at anbefale", "kind": "text"},
    ]},
    "hotel": {"label": "Hotel", "icon": "🛏", "fields": [
        {"key": "room", "label": "Værelse", "kind": "rating"},
        {"key": "cleanliness", "label": "Rengøring", "kind": "rating"},
        {"key": "breakfast", "label": "Morgenmad", "kind": "rating"},
        {"key": "location", "label": "Beliggenhed", "kind": "rating"},
        {"key": "price", "label": "Prisniveau", "kind": "choice",
         "options": ["Billig", "Middel", "Dyr"]},
        {"key": "kidFriendly", "label": "Børnevenlig", "kind": "bool"},
    ]},
    "city": {"label": "By", "icon": "🏙", "fields": [
        {"key": "sights", "label": "Seværdigheder", "kind": "rating"},
        {"key": "parking", "label": "Parkering", "kind": "rating"},
        {"key": "shopping", "label": "Shopping", "kind": "rating"},
        {"key": "kidFriendly", "label": "Børnevenlig", "kind": "bool"},
    ]},
    "playground": {"label": "Legeplads", "icon": "🛝", "fields": [
        {"key": "ageRange", "label": "Passer til alder", "kind": "text",
         "placeholder": "fx 3-10 år"},
        {"key": "equipment", "label": "Legeredskaber", "kind": "rating"},
        {"key": "shade", "label": "Skygge", "kind": "bool"},
        {"key": "toilets", "label": "Toiletter", "kind": "bool"},
        {"key": "fenced", "label": "Indhegnet", "kind": "bool"},
        {"key": "parking", "label": "Parkering", "kind": "rating"},
    ]},
    # Børneaktiviteter (2.49.0, Søren's choice): swimming baths, indoor play
    # and trampoline parks, cinemas, climbing, ice rinks.
    "activity": {"label": "Aktivitet", "icon": "🤸", "fields": [
        {"key": "fun", "label": "Sjov for børnene", "kind": "rating"},
        {"key": "facilities", "label": "Faciliteter", "kind": "rating"},
        {"key": "ageRange", "label": "Passer til alder", "kind": "text",
         "placeholder": "fx 3-10 år"},
        {"key": "price", "label": "Prisniveau", "kind": "choice",
         "options": ["Billig", "Middel", "Dyr"]},
        {"key": "crowds", "label": "Travlhed", "kind": "choice",
         "options": ["Roligt", "Lidt travlt", "Meget travlt"]},
        {"key": "booking", "label": "Skal bookes", "kind": "bool"},
    ]},
    "attraction": {"label": "Oplevelse", "icon": "🎡", "fields": [
        {"key": "ageRange", "label": "Passer til alder", "kind": "text",
         "placeholder": "fx 3-10 år"},
        {"key": "duration", "label": "Varighed", "kind": "text"},
        {"key": "price", "label": "Prisniveau", "kind": "choice",
         "options": ["Billig", "Middel", "Dyr"]},
        {"key": "setting", "label": "Inde / ude", "kind": "choice",
         "options": ["Inde", "Ude", "Begge"]},
        {"key": "queues", "label": "Kø", "kind": "choice",
         "options": ["Ingen", "Lidt", "Meget"]},
    ]},
    "nature": {"label": "Natur / strand / skov", "icon": "🌲", "fields": [
        {"key": "walks", "label": "Gåture", "kind": "rating"},
        {"key": "facilities", "label": "Faciliteter", "kind": "rating"},
        {"key": "dogs", "label": "Hunde tilladt", "kind": "bool"},
        {"key": "swimming", "label": "Badning", "kind": "bool"},
    ]},
}

PLACE_SOURCES = ("family", "osm", "google", "web")
MAX_TEXT = 4000            # review text
MAX_SHORT = 200            # text fields, who, names
MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_PHOTOS_PER_UPLOAD = 10
PHOTO_MAX_PX = 2048
THUMB_PX = 480

SCHEMA = """
CREATE TABLE IF NOT EXISTS fm_places (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    category         TEXT NOT NULL,
    address          TEXT NOT NULL DEFAULT '',
    lat              REAL,
    lng              REAL,
    website          TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL DEFAULT 'family',   -- family | osm | google | web
    source_id        TEXT,                              -- e.g. a Google place id
    web_rating       REAL,                              -- the source's total rating
    web_rating_count INTEGER,
    web_rating_at    TEXT,
    created_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fm_places_category ON fm_places(category);
CREATE UNIQUE INDEX IF NOT EXISTS fm_places_source
    ON fm_places(source, source_id) WHERE source_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS fm_reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id    INTEGER NOT NULL REFERENCES fm_places(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    visited_on  TEXT NOT NULL DEFAULT '',
    who         TEXT NOT NULL DEFAULT '',
    overall     INTEGER NOT NULL,
    fields      TEXT NOT NULL DEFAULT '{}',
    text        TEXT NOT NULL DEFAULT '',
    again       INTEGER,                                -- 1 yes, 0 no, NULL unsaid
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fm_reviews_place ON fm_reviews(place_id);
CREATE TABLE IF NOT EXISTS fm_photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id   INTEGER NOT NULL REFERENCES fm_reviews(id) ON DELETE CASCADE,
    file        TEXT NOT NULL,
    thumb       TEXT NOT NULL,
    width       INTEGER,
    height      INTEGER,
    taken_at    TEXT,
    description TEXT,                                   -- vision model, later
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fm_photos_review ON fm_photos(review_id);
"""


class Invalid(ValueError):
    """A request the family page should be told about in words."""


class NotFound(LookupError):
    pass


def photos_dir() -> Path:
    return db.data_dir() / "familymap" / "photos"


def categories() -> dict:
    return CATEGORIES


# ---- validation -------------------------------------------------------------

def _short(value, what: str, limit: int = MAX_SHORT) -> str:
    s = str(value or "").strip()
    if len(s) > limit:
        raise Invalid(f"{what} er for lang (højst {limit} tegn).")
    return s


def _score(value, what: str, required: bool = False) -> int | None:
    """1-100 as a whole number. Accepts 73, 73.0 and "73"; refuses True,
    73.5 and anything outside the range."""
    if value is None or value == "":
        if required:
            raise Invalid(f"{what} mangler.")
        return None
    n = None
    if isinstance(value, bool):
        n = None
    elif isinstance(value, int):
        n = value
    elif isinstance(value, float) and value.is_integer():
        n = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        n = int(value.strip())
    if n is None or not 1 <= n <= 100:
        raise Invalid(f"{what} skal være et helt tal fra 1 til 100.")
    return n


def _category(key) -> str:
    k = str(key or "").strip()
    if k not in CATEGORIES:
        raise Invalid(f"Ukendt kategori: {k or '(ingen)'}.")
    return k


def clean_fields(category: str, fields) -> dict:
    """The review's category fields, checked against the fixed definition.

    Unknown keys are refused rather than dropped: a field the page sends
    and the server silently loses is the kind of bug nobody notices."""
    if fields is None:
        return {}
    if not isinstance(fields, dict):
        raise Invalid("Felterne skal sendes som et objekt.")
    spec = {f["key"]: f for f in CATEGORIES[category]["fields"]}
    out: dict = {}
    for key, value in fields.items():
        f = spec.get(key)
        if f is None:
            raise Invalid(f"Feltet '{key}' hører ikke til kategorien.")
        if value is None or value == "":
            continue
        kind = f["kind"]
        if kind == "rating":
            out[key] = _score(value, f["label"])
        elif kind == "bool":
            if not isinstance(value, bool):
                raise Invalid(f"{f['label']} skal være ja eller nej.")
            out[key] = value
        elif kind == "choice":
            if value not in f["options"]:
                raise Invalid(f"{f['label']}: vælg en af {', '.join(f['options'])}.")
            out[key] = value
        else:
            out[key] = _short(value, f["label"])
    # Computed scores: the rounded average of the parts that got a score.
    # Without any parts, a score sent directly stands - reviews written
    # before 2.50.0 have only "Mad". (2.50.0)
    for key, f in spec.items():
        parts = [out[k] for k in f.get("computed", []) if k in out]
        if parts:
            # Half up, like the page's Math.round: Python's round() takes
            # 70.5 to 70 and the phone showed 71 until the save. (2.50.1)
            out[key] = int(sum(parts) / len(parts) + 0.5)
    return out


def _coord(value, lo: float, hi: float, what: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise Invalid(f"{what} er ikke et tal.")
    if not lo <= v <= hi:
        raise Invalid(f"{what} er uden for området.")
    return v


def _date(value) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    import datetime as _dt
    try:
        _dt.date.fromisoformat(s)
    except ValueError:
        raise Invalid("Datoen skal skrives som ÅÅÅÅ-MM-DD.")
    return s


# ---- places -----------------------------------------------------------------

def _place_dto(r, stats: dict | None = None) -> dict:
    d = {
        "id": r["id"], "name": r["name"], "category": r["category"],
        "address": r["address"], "lat": r["lat"], "lng": r["lng"],
        "website": r["website"], "notes": r["notes"], "source": r["source"],
        "sourceId": r["source_id"], "webRating": r["web_rating"],
        "webRatingCount": r["web_rating_count"], "webRatingAt": r["web_rating_at"],
        "createdBy": r["created_by"], "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
        "locked": bool(r["locked"]), "extra": json.loads(r["extra"] or "{}"),
    }
    if stats is not None:
        d.update(stats)
    return d


_STATS_SQL = """
SELECT p.*,
       (SELECT COUNT(*) FROM fm_reviews r WHERE r.place_id = p.id) AS n_reviews,
       (SELECT AVG(r.overall) FROM fm_reviews r WHERE r.place_id = p.id) AS avg_overall,
       (SELECT ph.id FROM fm_photos ph JOIN fm_reviews r ON r.id = ph.review_id
         WHERE r.place_id = p.id ORDER BY ph.id DESC LIMIT 1) AS cover_photo,
       (SELECT MAX(r.visited_on) FROM fm_reviews r WHERE r.place_id = p.id) AS last_visit,
       (SELECT substr(r.text, 1, 140) FROM fm_reviews r
         WHERE r.place_id = p.id AND r.text != ''
         ORDER BY r.visited_on DESC, r.id DESC LIMIT 1) AS latest_text,
       (SELECT COUNT(*) FROM fm_wishlist w
         WHERE w.place_id = p.id AND w.user_id = :me) AS wished
  FROM fm_places p
"""


def _stats(r) -> dict:
    avg = r["avg_overall"]
    return {"reviewCount": r["n_reviews"],
            "familyScore": round(avg) if avg is not None else None,
            "coverPhotoId": r["cover_photo"],
            "lastVisit": r["last_visit"] or None,
            # The card's one line on the phone (2.45.0): the newest review
            # text, cut to a line's worth.
            "latestText": " ".join((r["latest_text"] or "").split()) or None,
            "wished": bool(r["wished"])}


def fold(text) -> str:
    """Lower case for every letter (not only ASCII), hyphens as spaces -
    the same form the gazetteer keeps its names in."""
    return " ".join(str(text or "").casefold().replace("-", " ").split())


def search_terms(q: str) -> list[list[str]]:
    """The search box's words, each with the texts that count as a match:
    the word itself, and when it is a town's name - in any language the
    gazetteer knows - all of that town's names. "Flensborg" -> flensborg,
    flensburg; "pizza flensborg" -> [pizza], [flensborg, flensburg]. The
    whole query is tried as one town first ("Sankt Peter-Ording"). (2.49.7)"""
    q = fold(q)
    if not q:
        return []

    def town_names(text: str) -> list[str]:
        with db.connect() as con:
            rows = con.execute("SELECT names FROM fm_localities WHERE names LIKE ? LIMIT 5",
                               (f"%|{text}|%",)).fetchall()
        names: list[str] = [text]
        for r in rows:
            for n in r["names"].strip("|").split("|"):
                if n and n not in names:
                    names.append(n)
        return names[:10]

    whole = town_names(q)
    if len(whole) > 1 or " " not in q:
        return [whole]
    return [town_names(w) for w in q.split()]


# Leading characters the A-Z order skips: quotes, punctuation, digits.
SORT_SKIP = "\"'“”„«»#%&()*+-./0123456789:;<=>?@[]_ "


def list_places(q: str = "", category: str = "", reviewed: str = "",
                limit: int = 500, near: tuple[float, float] | None = None,
                me: int | None = None, wished_only: bool = False) -> list[dict]:
    """Places with the family's stats. With `near` (lat, lng) they come
    nearest first - only places with a position - each with `distanceKm`;
    without it reviewed places first, then by name."""
    where: list[str] = []
    args: dict = {"me": me or 0}
    for i, alts in enumerate(search_terms(q)):
        # Every word must match the name or the address; a town name
        # matches in any of its names (2.49.7 - "Flensborg" found nothing,
        # the addresses say "Flensburg").
        ors = []
        for j, alt in enumerate(alts):
            args[f"t{i}_{j}"] = f"%{alt}%"
            ors.append(f"fold(p.name) LIKE :t{i}_{j} OR fold(p.address) LIKE :t{i}_{j}")
        where.append("(" + " OR ".join(ors) + ")")
    if category:
        where.append("p.category = :category")
        args["category"] = _category(category)
    if wished_only:
        where.append("EXISTS (SELECT 1 FROM fm_wishlist w"
                     " WHERE w.place_id = p.id AND w.user_id = :me)")
    if reviewed == "yes":
        where.append("EXISTS (SELECT 1 FROM fm_reviews r WHERE r.place_id = p.id)")
    elif reviewed == "no":
        where.append("NOT EXISTS (SELECT 1 FROM fm_reviews r WHERE r.place_id = p.id)")
    if near is not None:
        lat0, lng0 = near
        where.append("p.lat IS NOT NULL AND p.lng IS NOT NULL")
        # Equirectangular distance, squared: exact enough to ORDER a region
        # the size of Denmark, and SQLite has no trigonometry to do better.
        # cos(lat0) comes from Python.
        args.update(lat0=lat0, lng0=lng0, k=math.cos(math.radians(lat0)))
    sql = _STATS_SQL + (" WHERE " + " AND ".join(where) if where else "")
    if near is not None:
        sql += (" ORDER BY (p.lat - :lat0) * (p.lat - :lat0)"
                " + ((p.lng - :lng0) * :k) * ((p.lng - :lng0) * :k) LIMIT :limit")
    else:
        # Reviewed places first (the family's own knowledge is the point),
        # then by name - a stable order without a sort control.
        # By the first letter of the name: OSM names in quotes or starting
        # with a number ("Alte Schule", 1401) no longer head the list. (2.46.0)
        sql += (" ORDER BY n_reviews = 0, LTRIM(p.name, :skip) = '',"
                " LTRIM(p.name, :skip) COLLATE NOCASE, p.name COLLATE NOCASE LIMIT :limit")
        args["skip"] = SORT_SKIP
    args["limit"] = max(1, min(int(limit), 5000))
    with db.connect() as con:
        # SQLite's LIKE folds only ASCII; "østerby" must find "Østerby".
        con.create_function("fold", 1, fold, deterministic=True)
        rows = con.execute(sql, args).fetchall()
    out = [_place_dto(r, _stats(r)) for r in rows]
    if near is not None:
        for d in out:
            d["distanceKm"] = round(distance_km(near[0], near[1], d["lat"], d["lng"]), 1)
    return out


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance (haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def get_place(pid: int, me: int | None = None) -> dict:
    with db.connect() as con:
        r = con.execute(_STATS_SQL + " WHERE p.id = :pid",
                        {"pid": pid, "me": me or 0}).fetchone()
    if not r:
        raise NotFound("Stedet findes ikke.")
    return _place_dto(r, _stats(r))


def create_place(body: dict, user_id: int | None) -> dict:
    name = _short(body.get("name"), "Navnet")
    if not name:
        raise Invalid("Stedet skal have et navn.")
    category = _category(body.get("category"))
    source = str(body.get("source") or "family")
    if source not in PLACE_SOURCES:
        raise Invalid(f"Ukendt kilde: {source}.")
    now = db.utcnow()
    with db.connect() as con:
        cur = con.execute(
            "INSERT INTO fm_places (name, category, address, lat, lng, website,"
            " notes, source, source_id, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, category, _short(body.get("address"), "Adressen"),
             _coord(body.get("lat"), -90, 90, "Breddegraden"),
             _coord(body.get("lng"), -180, 180, "Længdegraden"),
             _short(body.get("website"), "Hjemmesiden", 500),
             _short(body.get("notes"), "Noten", MAX_TEXT),
             source, body.get("sourceId") or None, user_id, now, now))
        pid = cur.lastrowid
    return get_place(pid)


_PLACE_EDITABLE = {"name", "category", "address", "lat", "lng", "website", "notes"}


def update_place(pid: int, body: dict) -> dict:
    get_place(pid)
    sets, args = [], []
    for key, value in body.items():
        if key not in _PLACE_EDITABLE:
            continue
        if key == "name":
            value = _short(value, "Navnet")
            if not value:
                raise Invalid("Stedet skal have et navn.")
        elif key == "category":
            value = _category(value)
        elif key == "lat":
            value = _coord(value, -90, 90, "Breddegraden")
        elif key == "lng":
            value = _coord(value, -180, 180, "Længdegraden")
        elif key == "website":
            value = _short(value, "Hjemmesiden", 500)
        elif key == "notes":
            value = _short(value, "Noten", MAX_TEXT)
        else:
            value = _short(value, "Adressen")
        sets.append(f"{key} = ?")
        args.append(value)
    if sets:
        # An imported place the admin corrected is left alone by later
        # imports - the correction is the point. (2.44.0)
        sets.append("locked = CASE WHEN source = 'osm' THEN 1 ELSE locked END")
        sets.append("updated_at = ?")
        args += [db.utcnow(), pid]
        with db.connect() as con:
            con.execute(f"UPDATE fm_places SET {', '.join(sets)} WHERE id = ?", args)
    return get_place(pid)


def delete_place(pid: int) -> None:
    get_place(pid)
    with db.connect() as con:
        files = con.execute(
            "SELECT ph.file, ph.thumb FROM fm_photos ph"
            " JOIN fm_reviews r ON r.id = ph.review_id WHERE r.place_id = ?",
            (pid,)).fetchall()
        con.execute("DELETE FROM fm_places WHERE id = ?", (pid,))
    _unlink_files(files)


# ---- reviews ----------------------------------------------------------------

def _review_dto(r, photos: list[dict]) -> dict:
    return {
        "id": r["id"], "placeId": r["place_id"], "userId": r["user_id"],
        "author": r["author"] or "(slettet bruger)",
        "visitedOn": r["visited_on"] or None, "who": r["who"],
        "overall": r["overall"], "fields": json.loads(r["fields"] or "{}"),
        "text": r["text"],
        "again": None if r["again"] is None else bool(r["again"]),
        "createdAt": r["created_at"], "updatedAt": r["updated_at"],
        "photos": photos,
    }


def _photo_dto(r) -> dict:
    return {"id": r["id"], "width": r["width"], "height": r["height"],
            "takenAt": r["taken_at"], "description": r["description"],
            "describeState": r["describe_state"], "describeError": r["describe_error"]}


_REVIEW_SQL = """
SELECT r.*, u.username AS author, p.name AS place_name, p.category AS place_category
  FROM fm_reviews r
  LEFT JOIN users u ON u.id = r.user_id
  JOIN fm_places p ON p.id = r.place_id
"""


def _with_photos(con, rows) -> list[dict]:
    ids = [r["id"] for r in rows]
    by_review: dict[int, list[dict]] = {i: [] for i in ids}
    if ids:
        marks = ",".join("?" * len(ids))
        for ph in con.execute(
                f"SELECT * FROM fm_photos WHERE review_id IN ({marks}) ORDER BY id",
                ids):
            by_review[ph["review_id"]].append(_photo_dto(ph))
    out = []
    for r in rows:
        d = _review_dto(r, by_review[r["id"]])
        d["placeName"] = r["place_name"]
        d["placeCategory"] = r["place_category"]
        out.append(d)
    return out


def reviews_for_place(pid: int) -> list[dict]:
    with db.connect() as con:
        rows = con.execute(
            _REVIEW_SQL + " WHERE r.place_id = ?"
            " ORDER BY r.visited_on DESC, r.id DESC", (pid,)).fetchall()
        return _with_photos(con, rows)


def list_reviews(limit: int = 200) -> list[dict]:
    with db.connect() as con:
        rows = con.execute(_REVIEW_SQL + " ORDER BY r.id DESC LIMIT ?",
                           (max(1, min(int(limit), 2000)),)).fetchall()
        return _with_photos(con, rows)


def get_review(rid: int) -> dict:
    with db.connect() as con:
        rows = con.execute(_REVIEW_SQL + " WHERE r.id = ?", (rid,)).fetchall()
        if not rows:
            raise NotFound("Anmeldelsen findes ikke.")
        return _with_photos(con, rows)[0]


def _again(value) -> int | None:
    if value is None or value == "":
        return None
    if not isinstance(value, bool):
        raise Invalid("'Igen?' skal være ja eller nej.")
    return 1 if value else 0


def create_review(pid: int, body: dict, user_id: int) -> dict:
    place = get_place(pid)
    overall = _score(body.get("overall"), "Samlet karakter", required=True)
    fields = clean_fields(place["category"], body.get("fields"))
    now = db.utcnow()
    with db.connect() as con:
        cur = con.execute(
            "INSERT INTO fm_reviews (place_id, user_id, visited_on, who, overall,"
            " fields, text, again, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, user_id, _date(body.get("visitedOn")),
             _short(body.get("who"), "Hvem var med"), overall,
             json.dumps(fields, ensure_ascii=False),
             _short(body.get("text"), "Teksten", MAX_TEXT),
             _again(body.get("again")), now, now))
        rid = cur.lastrowid
    return get_review(rid)


def update_review(rid: int, body: dict) -> dict:
    current = get_review(rid)
    category = current["placeCategory"]
    sets, args = [], []
    if "overall" in body:
        sets.append("overall = ?")
        args.append(_score(body["overall"], "Samlet karakter", required=True))
    if "fields" in body:
        sets.append("fields = ?")
        args.append(json.dumps(clean_fields(category, body["fields"]),
                               ensure_ascii=False))
    if "visitedOn" in body:
        sets.append("visited_on = ?")
        args.append(_date(body["visitedOn"]))
    if "who" in body:
        sets.append("who = ?")
        args.append(_short(body["who"], "Hvem var med"))
    if "text" in body:
        sets.append("text = ?")
        args.append(_short(body["text"], "Teksten", MAX_TEXT))
    if "again" in body:
        sets.append("again = ?")
        args.append(_again(body["again"]))
    if sets:
        sets.append("updated_at = ?")
        args += [db.utcnow(), rid]
        with db.connect() as con:
            con.execute(f"UPDATE fm_reviews SET {', '.join(sets)} WHERE id = ?", args)
    return get_review(rid)


def delete_review(rid: int) -> None:
    get_review(rid)
    with db.connect() as con:
        files = con.execute("SELECT file, thumb FROM fm_photos WHERE review_id = ?",
                            (rid,)).fetchall()
        con.execute("DELETE FROM fm_reviews WHERE id = ?", (rid,))
    _unlink_files(files)


def review_owner(rid: int) -> int | None:
    with db.connect() as con:
        r = con.execute("SELECT user_id FROM fm_reviews WHERE id = ?", (rid,)).fetchone()
    if not r:
        raise NotFound("Anmeldelsen findes ikke.")
    return r["user_id"]


# ---- photos -----------------------------------------------------------------

def _sniff(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _process(data: bytes) -> tuple[bytes, bytes, int | None, int | None, str | None, str]:
    """(full, thumb, width, height, taken_at, extension).

    With Pillow: upright (EXIF orientation applied), at most PHOTO_MAX_PX,
    re-encoded as JPEG so EXIF - GPS included - is gone. Without it: the
    original, as both sizes."""
    ext = _sniff(data)
    if ext is None:
        raise Invalid("Billedet skal være JPEG, PNG eller WebP.")
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return data, data, None, None, None, ext
    try:
        img = Image.open(io.BytesIO(data))
        taken = None
        try:
            exif = img.getexif()
            raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
            if raw:
                d, _, t = str(raw).partition(" ")
                taken = d.replace(":", "-") + ("T" + t if t else "")
        except Exception:
            taken = None
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        full = img.copy()
        full.thumbnail((PHOTO_MAX_PX, PHOTO_MAX_PX))
        thumb = img.copy()
        thumb.thumbnail((THUMB_PX, THUMB_PX))
        b1, b2 = io.BytesIO(), io.BytesIO()
        full.save(b1, "JPEG", quality=85, optimize=True)
        thumb.save(b2, "JPEG", quality=80, optimize=True)
        return b1.getvalue(), b2.getvalue(), full.width, full.height, taken, ".jpg"
    except Invalid:
        raise
    except Exception:
        raise Invalid("Billedet kunne ikke læses.")


def add_photos(rid: int, uploads: list[bytes]) -> list[dict]:
    get_review(rid)
    if not uploads:
        raise Invalid("Ingen billeder modtaget.")
    if len(uploads) > MAX_PHOTOS_PER_UPLOAD:
        raise Invalid(f"Højst {MAX_PHOTOS_PER_UPLOAD} billeder ad gangen.")
    for data in uploads:
        if len(data) > MAX_PHOTO_BYTES:
            raise Invalid(f"Et billede er større end {MAX_PHOTO_BYTES // 1024 // 1024} MB.")
    processed = [_process(d) for d in uploads]       # all or nothing
    folder = photos_dir()
    folder.mkdir(parents=True, exist_ok=True)
    added = []
    for full, thumb, w, h, taken, ext in processed:
        stem = secrets.token_hex(8)
        f_name, t_name = f"{stem}{ext}", f"{stem}_t{ext}"
        (folder / f_name).write_bytes(full)
        (folder / t_name).write_bytes(thumb)
        with db.connect() as con:
            cur = con.execute(
                "INSERT INTO fm_photos (review_id, file, thumb, width, height,"
                " taken_at, created_at) VALUES (?,?,?,?,?,?,?)",
                (rid, f_name, t_name, w, h, taken, db.utcnow()))
            row = con.execute("SELECT * FROM fm_photos WHERE id = ?",
                              (cur.lastrowid,)).fetchone()
        added.append(_photo_dto(row))
    return added


def photo_file(photo_id: int, thumb: bool = False) -> Path:
    with db.connect() as con:
        r = con.execute("SELECT file, thumb FROM fm_photos WHERE id = ?",
                        (photo_id,)).fetchone()
    if not r:
        raise NotFound("Billedet findes ikke.")
    p = photos_dir() / Path(r["thumb"] if thumb else r["file"]).name
    if not p.is_file():
        raise NotFound("Billedfilen mangler.")
    return p


def get_photo(photo_id: int) -> dict:
    with db.connect() as con:
        r = con.execute("SELECT * FROM fm_photos WHERE id = ?", (photo_id,)).fetchone()
    if not r:
        raise NotFound("Billedet findes ikke.")
    return _photo_dto(r)


def photo_owner(photo_id: int) -> int | None:
    with db.connect() as con:
        r = con.execute(
            "SELECT r.user_id FROM fm_photos ph JOIN fm_reviews r ON r.id = ph.review_id"
            " WHERE ph.id = ?", (photo_id,)).fetchone()
    if not r:
        raise NotFound("Billedet findes ikke.")
    return r["user_id"]


def delete_photo(photo_id: int) -> None:
    with db.connect() as con:
        r = con.execute("SELECT file, thumb FROM fm_photos WHERE id = ?",
                        (photo_id,)).fetchone()
        if not r:
            raise NotFound("Billedet findes ikke.")
        con.execute("DELETE FROM fm_photos WHERE id = ?", (photo_id,))
    _unlink_files([r])


def _unlink_files(rows) -> None:
    folder = photos_dir()
    for r in rows:
        for name in (r["file"], r["thumb"]):
            try:
                (folder / Path(name).name).unlink(missing_ok=True)
            except OSError:
                pass


def stats() -> dict:
    with db.connect() as con:
        places = con.execute("SELECT COUNT(*) FROM fm_places").fetchone()[0]
        reviewed = con.execute(
            "SELECT COUNT(DISTINCT place_id) FROM fm_reviews").fetchone()[0]
        reviews = con.execute("SELECT COUNT(*) FROM fm_reviews").fetchone()[0]
        photos = con.execute("SELECT COUNT(*) FROM fm_photos").fetchone()[0]
        states = dict(con.execute(
            "SELECT COALESCE(describe_state, 'pending'), COUNT(*) FROM fm_photos"
            " GROUP BY 1").fetchall())
        by_source = dict(con.execute(
            "SELECT source, COUNT(*) FROM fm_places GROUP BY source").fetchall())
    return {"places": places, "reviewedPlaces": reviewed,
            "reviews": reviews, "photos": photos,
            "photoStates": {k: states.get(k, 0) for k in
                            ("pending", "queued", "done", "failed", "nomodel")},
            "sources": by_source}


def wipe_files() -> None:
    """Tests only: photo files live on disk beside the database."""
    shutil.rmtree(db.data_dir() / "familymap", ignore_errors=True)


# ---- settings (2.44.0) -----------------------------------------------------------
# FamilyMap's own. In SLQ the models were chosen here only (no falling back
# to the app's). In FamilyLog the app's Settings choose a model per role, and
# these two are optional overrides: empty = the role from Settings
# (chat_model() / vision_model()). Stored values are returned as they are.

DEFAULT_APP_NAME = "Alf’s Atlas"
MAX_APP_NAME = 40

SETTINGS_DEFAULTS = {
    # What the family page calls itself - title, login, header. "FamilyMap"
    # stays the name of the admin section. (2.44.1)
    "appName": DEFAULT_APP_NAME,
    "chatModel": "",            # day ideas (release 3)
    "visionModel": "",          # photo descriptions
    "overpassUrl": "",          # empty = the global Overpass address (Settings)
}


def get_settings() -> dict:
    out = dict(SETTINGS_DEFAULTS)
    with db.connect() as con:
        for r in con.execute("SELECT key, value FROM fm_settings"):
            if r["key"] in out:
                out[r["key"]] = r["value"]
    return out


def chat_model() -> str:
    """Spørg Alf's model: FamilyMap's own choice, else Settings → chat."""
    from app.core import settings
    return get_settings()["chatModel"] or settings.role_model("chat")


def vision_model() -> str:
    """Photo descriptions: FamilyMap's own choice, else Settings → vision.
    Never the chat model - a text model cannot see."""
    from app.core import settings
    return get_settings()["visionModel"] or settings.role_model("vision")


def set_settings(patch: dict) -> dict:
    """Writes only the keys given - one at a time, never a stale snapshot
    of the whole set."""
    for key, value in patch.items():
        if key not in SETTINGS_DEFAULTS:
            raise Invalid(f"Unknown FamilyMap setting: {key}.")
        value = str(value or "").strip()
        if key == "appName":
            value = value or DEFAULT_APP_NAME
            if len(value) > MAX_APP_NAME:
                raise Invalid(f"The name can be at most {MAX_APP_NAME} characters.")
        if key == "overpassUrl" and value and not value.startswith(("http://", "https://")):
            raise Invalid("The Overpass address must start with http:// or https://.")
        with db.connect() as con:
            con.execute("INSERT INTO fm_settings (key, value) VALUES (?, ?)"
                        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, value))
    return get_settings()


# ---- photo descriptions (2.44.0) -----------------------------------------------------

def set_describe_state(photo_id: int, state: str, description: str | None = None,
                       error: str | None = None) -> None:
    with db.connect() as con:
        if state == "done":
            con.execute("UPDATE fm_photos SET describe_state = ?, description = ?,"
                        " describe_error = NULL WHERE id = ?",
                        (state, description, photo_id))
        else:
            con.execute("UPDATE fm_photos SET describe_state = ?, describe_error = ?"
                        " WHERE id = ?", (state, error, photo_id))


def photos_to_describe() -> list[int]:
    """Photos without a description that are not already waiting in the
    queue: new, failed, or uploaded while no vision model was chosen."""
    with db.connect() as con:
        return [r[0] for r in con.execute(
            "SELECT id FROM fm_photos WHERE COALESCE(describe_state, 'pending')"
            " IN ('pending', 'failed', 'nomodel') ORDER BY id")]


def photo_context(photo_id: int) -> dict | None:
    """What the vision prompt is told about a photo: the place it is from."""
    with db.connect() as con:
        r = con.execute(
            "SELECT p.name, p.category FROM fm_photos ph"
            " JOIN fm_reviews r ON r.id = ph.review_id"
            " JOIN fm_places p ON p.id = r.place_id WHERE ph.id = ?",
            (photo_id,)).fetchone()
    if not r:
        return None
    return {"placeName": r["name"],
            "category": CATEGORIES.get(r["category"], {}).get("label", r["category"])}


# ---- Alf's Atlas: the person's own things (2.45.0) --------------------------------------

def set_wished(user_id: int, pid: int, wished: bool) -> dict:
    get_place(pid)
    with db.connect() as con:
        if wished:
            con.execute("INSERT OR IGNORE INTO fm_wishlist (user_id, place_id, created_at)"
                        " VALUES (?, ?, ?)", (user_id, pid, db.utcnow()))
        else:
            con.execute("DELETE FROM fm_wishlist WHERE user_id = ? AND place_id = ?",
                        (user_id, pid))
    return get_place(pid, me=user_id)


def my_reviews(user_id: int) -> list[dict]:
    with db.connect() as con:
        rows = con.execute(_REVIEW_SQL + " WHERE r.user_id = ?"
                           " ORDER BY r.visited_on DESC, r.id DESC", (user_id,)).fetchall()
        return _with_photos(con, rows)


def my_photos(user_id: int) -> list[dict]:
    with db.connect() as con:
        rows = con.execute(
            "SELECT ph.*, r.place_id, p.name AS place_name, r.visited_on"
            " FROM fm_photos ph JOIN fm_reviews r ON r.id = ph.review_id"
            " JOIN fm_places p ON p.id = r.place_id"
            " WHERE r.user_id = ? ORDER BY ph.id DESC", (user_id,)).fetchall()
    return [{**_photo_dto(r), "placeId": r["place_id"], "placeName": r["place_name"],
             "visitedOn": r["visited_on"] or None} for r in rows]


# ---- the map (2.47.0) ----------------------------------------------------------------

def map_points(me: int) -> dict:
    """Every place with a position, compact: [id, lat, lng, category index,
    flags, name]. flags: 1 = the family reviewed it, 2 = on this person's
    wishlist. About 45 bytes a place before gzip - the whole region in one
    response, so the phone can cluster and pan without asking again."""
    keys = list(CATEGORIES)
    idx = {k: i for i, k in enumerate(keys)}
    with db.connect() as con:
        reviewed = {r[0] for r in con.execute("SELECT DISTINCT place_id FROM fm_reviews")}
        wished = {r[0] for r in con.execute(
            "SELECT place_id FROM fm_wishlist WHERE user_id = ?", (me,))}
        rows = con.execute("SELECT id, lat, lng, category, name FROM fm_places"
                           " WHERE lat IS NOT NULL AND lng IS NOT NULL ORDER BY id").fetchall()
    points = [[r["id"], round(r["lat"], 5), round(r["lng"], 5), idx.get(r["category"], 0),
               (1 if r["id"] in reviewed else 0) | (2 if r["id"] in wished else 0), r["name"]]
              for r in rows]
    return {"cats": keys, "points": points}


# ---- the family's own places (2.49.5) ------------------------------------------------------

def my_places(user_id: int) -> list[dict]:
    """Places this person created, newest first."""
    with db.connect() as con:
        rows = con.execute(_STATS_SQL + " WHERE p.created_by = :me ORDER BY p.id DESC",
                           {"me": user_id}).fetchall()
    return [_place_dto(r, _stats(r)) for r in rows]


def place_owner(pid: int) -> int | None:
    with db.connect() as con:
        r = con.execute("SELECT created_by FROM fm_places WHERE id = ?", (pid,)).fetchone()
    if not r:
        raise NotFound("Stedet findes ikke.")
    return r["created_by"]


def others_reviewed(pid: int, user_id: int) -> int:
    with db.connect() as con:
        return con.execute("SELECT COUNT(*) FROM fm_reviews WHERE place_id = ?"
                           " AND (user_id IS NULL OR user_id != ?)", (pid, user_id)).fetchone()[0]
