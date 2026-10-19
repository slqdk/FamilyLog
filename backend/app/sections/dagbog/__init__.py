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


def _m004_more_fields(con: sqlite3.Connection) -> None:
    """0.3.8: motion (minutes, in half hours), sodavand, sickness and
    injuries. A person whose fields were set by hand gets the new ones too
    (the administrator turns them off per person). Sodavand leaves a saved
    food list - it is its own slider now."""
    import json
    from app.core.migrations import add_column
    add_column(con, "dagbog_entries", "exercise", "INTEGER")
    add_column(con, "dagbog_entries", "soda", "INTEGER")
    add_column(con, "dagbog_entries", "sick", "TEXT NOT NULL DEFAULT '[]'")
    add_column(con, "dagbog_entries", "sick_note", "TEXT NOT NULL DEFAULT ''")
    for r in con.execute("SELECT user_id, fields FROM dagbog_members").fetchall():
        try:
            fields = json.loads(r[1])
        except ValueError:
            continue
        added = [f for f in ("exercise", "soda", "sick") if f not in fields]
        if added and isinstance(fields, list):
            con.execute("UPDATE dagbog_members SET fields = ? WHERE user_id = ?",
                        (json.dumps(fields + added), r[0]))
    # Sodavand has its own slider now: off the food list (days that had it keep it).
    r = con.execute("SELECT value FROM dagbog_settings WHERE key = 'foods'").fetchone()
    if r:
        try:
            foods = json.loads(r[0])
        except ValueError:
            foods = None
        if isinstance(foods, list) and any(str(x).lower() == "sodavand" for x in foods):
            con.execute("UPDATE dagbog_settings SET value = ? WHERE key = 'foods'",
                        (json.dumps([x for x in foods if str(x).lower() != "sodavand"], ensure_ascii=False),))


def _m005_shared(con: sqlite3.Connection) -> None:
    """0.3.9 (Søren): the family sees each other's text and photo. A day
    says whether its author shares it - new days do by default. Days that
    already have a text or photo were written while "kun du kan se" was the
    promise, so they stay private until their author shares them."""
    from app.core.migrations import add_column
    add_column(con, "dagbog_entries", "shared", "INTEGER NOT NULL DEFAULT 1")
    con.execute("UPDATE dagbog_entries SET shared = 0 WHERE highlight <> '' OR photo IS NOT NULL")
    # Vitaminer on the food list (Søren, 0.3.9) - also on a list already saved.
    import json
    r = con.execute("SELECT value FROM dagbog_settings WHERE key = 'foods'").fetchone()
    if r:
        foods = json.loads(r[0])
        if not any(f.lower() == "vitaminer" for f in foods):
            foods.append("Vitaminer")
            con.execute("UPDATE dagbog_settings SET value = ? WHERE key = 'foods'",
                        (json.dumps(foods, ensure_ascii=False),))


def _m006_share_old_days(con: sqlite3.Connection) -> None:
    """0.3.11 (Søren): "the days people have written in shall also show text
    and photos to the others" - the days migration 5 kept private are shared.
    A day its author has saved since 0.3.9 keeps the choice made then."""
    r = con.execute("SELECT applied_at FROM schema_migrations WHERE section = 'dagbog' AND version = 5").fetchone()
    if r is not None:
        con.execute("UPDATE dagbog_entries SET shared = 1 WHERE shared = 0 AND updated_at <= ?", (r[0],))


SECTION = Section(
    id="dagbog",
    title="Dagbog",
    router=router,
    migrations=[(1, "dagbog entries, settings, members", _m001_dagbog),
                (2, "food categories", _m002_foods),
                (3, "mental readiness 1-10, childcare activity", _m003_mental_ten),
                (4, "motion, sodavand, sickness", _m004_more_fields),
                (5, "text and photo shared with the family", _m005_shared),
                (6, "the old days shared too", _m006_share_old_days)],
    family_prefixes=("/api/dagbog/",),
    on_user_deleted=dagbog.forget_user,
)
