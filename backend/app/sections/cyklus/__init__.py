"""Cyklus: period log and cycle forecast for accounts set to female; she
chooses who sees her status (FamilyLog 0.3.0)."""
from __future__ import annotations

import sqlite3

from app.core.sections import Section

from .routes import router


def _m001_cyklus(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS cyklus_periods (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            start      TEXT NOT NULL,              -- YYYY-MM-DD
            end        TEXT,                       -- NULL = not ended yet
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (user_id, start)
        );
        CREATE TABLE IF NOT EXISTS cyklus_days (
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            day        TEXT NOT NULL,
            flow       TEXT NOT NULL DEFAULT '',   -- '' | plet | let | middel | kraftig
            symptoms   TEXT NOT NULL DEFAULT '[]',
            moods      TEXT NOT NULL DEFAULT '[]',
            note       TEXT NOT NULL DEFAULT '',   -- never shared
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, day)
        );
        CREATE TABLE IF NOT EXISTS cyklus_settings (
            user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            cycle_length  INTEGER,
            period_length INTEGER,
            share_fertile INTEGER NOT NULL DEFAULT 0,
            share_details INTEGER NOT NULL DEFAULT 0,
            updated_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cyklus_shares (
            owner_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            viewer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (owner_id, viewer_id)
        );
    """)


SECTION = Section(
    id="cyklus",
    title="Cyklus",
    router=router,
    migrations=[(1, "periods, days, settings, shares", _m001_cyklus)],
    family_prefixes=("/api/cyklus/",),
)
