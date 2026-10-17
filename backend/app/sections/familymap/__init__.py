"""FamilyMap: the family's own reviews of places, the Danish phone page at
/fm/ for family accounts, and the admin view (SLQ 2.43 - 2.49)."""
from __future__ import annotations

import sqlite3

from app.core.sections import Section

from . import familymap as fm, familymap_ask
from .familymap_routes import router


def _m001_places(con: sqlite3.Connection) -> None:
    """SLQ _m040 (2.43.0): places, reviews and photos."""
    con.executescript(fm.SCHEMA)


def _m002_osm(con: sqlite3.Connection) -> None:
    """SLQ _m041 (2.44.0): OSM import, settings, photo descriptions."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(fm_places)")}
    if "locked" not in cols:
        con.execute("ALTER TABLE fm_places ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
    if "extra" not in cols:
        con.execute("ALTER TABLE fm_places ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'")
    pcols = {r[1] for r in con.execute("PRAGMA table_info(fm_photos)")}
    if "describe_state" not in pcols:
        con.execute("ALTER TABLE fm_photos ADD COLUMN describe_state TEXT")
    if "describe_error" not in pcols:
        con.execute("ALTER TABLE fm_photos ADD COLUMN describe_error TEXT")
    con.execute("CREATE TABLE IF NOT EXISTS fm_settings ("
                " key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def _m003_wishlist(con: sqlite3.Connection) -> None:
    """SLQ _m042 (2.45.0): each person's "Vil gerne besøge" list."""
    con.execute("CREATE TABLE IF NOT EXISTS fm_wishlist ("
                " user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
                " place_id INTEGER NOT NULL REFERENCES fm_places(id) ON DELETE CASCADE,"
                " created_at TEXT NOT NULL, PRIMARY KEY (user_id, place_id))")


def _m004_ask(con: sqlite3.Connection) -> None:
    """SLQ _m043 (2.46.0): a gazetteer of town and village names, and
    position indexes for the radius search."""
    con.executescript("""
        CREATE TABLE IF NOT EXISTS fm_localities (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            osm_id    TEXT NOT NULL UNIQUE,
            name      TEXT NOT NULL,
            kind      TEXT NOT NULL,            -- city, town, village, suburb, hamlet
            lat       REAL NOT NULL,
            lng       REAL NOT NULL,
            names     TEXT NOT NULL             -- |every|lower-cased|name|variant|
        );
        CREATE INDEX IF NOT EXISTS fm_places_lat ON fm_places(lat);
        CREATE INDEX IF NOT EXISTS fm_places_lng ON fm_places(lng);
    """)


def _m005_import_map(con: sqlite3.Connection) -> None:
    """0.3.2: what came over from SLQ's Alf's Atlas (atlas_import.py), so a
    second run neither doubles nor loses anything."""
    con.execute("CREATE TABLE IF NOT EXISTS fm_import_map ("
                " kind TEXT NOT NULL, src_id INTEGER NOT NULL, dst_id INTEGER NOT NULL,"
                " src_user TEXT, PRIMARY KEY (kind, src_id))")


def _reset() -> None:
    familymap_ask._asks.clear()


SECTION = Section(
    id="familymap",
    title="FamilyMap",
    router=router,
    migrations=[
        (1, "places, reviews and photos (SLQ _m040)", _m001_places),
        (2, "osm import, settings, photo descriptions (SLQ _m041)", _m002_osm),
        (3, "wishlist (SLQ _m042)", _m003_wishlist),
        (4, "localities and position indexes (SLQ _m043)", _m004_ask),
        (5, "import map for SLQ's Alf's Atlas", _m005_import_map),
    ],
    public_paths=("/api/fm/brand",),
    family_prefixes=("/api/fm/",),
    reset=_reset,
)
