"""Dagbog: each person rates their day; the family (family accounts and the
administrator, 0.3.7) sees the ratings, the highlight text and photo stay
with the author (FamilyLog 0.2.0)."""
from __future__ import annotations

import sqlite3

from app.core.sections import Section

from . import dagbog
from .routes import router


def _m001_dagbog(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS dagbog_entries (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            day        TEXT NOT NULL,              -- YYYY-MM-DD, local time
            mood       INTEGER,                    -- 1-5
            sleep      INTEGER,
            energy     INTEGER,
            mental     INTEGER,
            food       INTEGER,
            alcohol    INTEGER,                    -- units
            tags       TEXT NOT NULL DEFAULT '[]',
            highlight  TEXT NOT NULL DEFAULT '',   -- the author's only
            photo      TEXT,                       -- file under dagbog/photos/<user>/, the author's only
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (user_id, day)
        );
        CREATE INDEX IF NOT EXISTS dagbog_entries_day ON dagbog_entries (day);
        CREATE TABLE IF NOT EXISTS dagbog_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dagbog_members (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            fields  TEXT NOT NULL                  -- JSON list of field keys
        );
    """)


def _m002_foods(con: sqlite3.Connection) -> None:
    """0.2.1: food as categories (a JSON list), not a 1-5 scale; sleep and
    energy are no longer asked. The old columns stay (migrations only add).
    A person whose fields were set by hand and had "food" gets "foods"."""
    import json
    from app.core.migrations import add_column
    add_column(con, "dagbog_entries", "foods", "TEXT NOT NULL DEFAULT '[]'")
    for r in con.execute("SELECT user_id, fields FROM dagbog_members").fetchall():
        try:
            fields = json.loads(r[1])
        except ValueError:
            continue
        if "food" in fields and "foods" not in fields:
            fields.append("foods")
            con.execute("UPDATE dagbog_members SET fields = ? WHERE user_id = ?",
                        (json.dumps(fields), r[0]))


def _m003_mental_ten(con: sqlite3.Connection) -> None:
    """0.2.2: mental readiness is 1-10. Days saved on the 1-5 scale are
    doubled (3 -> 6), so old and new days compare. An activity list the
    administrator already saved gets "Børnepasning", like the default."""
    import json
    con.execute("UPDATE dagbog_entries SET mental = mental * 2"
                " WHERE mental IS NOT NULL AND mental <= 5")
    r = con.execute("SELECT value FROM dagbog_settings WHERE key = 'tags'").fetchone()
    if r:
        try:
            tags = json.loads(r[0])
        except ValueError:
            return
        if isinstance(tags, list) and not any(str(t).lower() == "børnepasning" for t in tags):
            tags.append("Børnepasning")
            con.execute("UPDATE dagbog_settings SET value = ? WHERE key = 'tags'",
                        (json.dumps(tags, ensure_ascii=False),))


SECTION = Section(
    id="dagbog",
    title="Dagbog",
    router=router,
    migrations=[(1, "dagbog entries, settings, members", _m001_dagbog),
                (2, "food categories", _m002_foods),
                (3, "mental readiness 1-10, childcare activity", _m003_mental_ten)],
    family_prefixes=("/api/dagbog/",),
    on_user_deleted=dagbog.forget_user,
)
