"""Dagbog: each person rates their day; the family sees the ratings, the
highlight text and photo stay with the author (FamilyLog 0.2.0)."""
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


SECTION = Section(
    id="dagbog",
    title="Dagbog",
    router=router,
    migrations=[(1, "dagbog entries, settings, members", _m001_dagbog),
                (2, "food categories", _m002_foods)],
    family_prefixes=("/api/dagbog/",),
    on_user_deleted=dagbog.forget_user,
)
