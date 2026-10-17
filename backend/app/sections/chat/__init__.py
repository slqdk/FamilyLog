"""Alf on the front page: a general family chat that knows the family's
places (FamilyLog 0.2.0)."""
from __future__ import annotations

import sqlite3

from app.core.sections import Section

from . import chat
from .routes import router


def _m001_messages(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role       TEXT NOT NULL,              -- user | assistant
            content    TEXT NOT NULL,
            places     TEXT NOT NULL DEFAULT '[]', -- place cards for an answer about places
            meta       TEXT NOT NULL DEFAULT '{}', -- route, what was searched
            archived   INTEGER NOT NULL DEFAULT 0, -- 1 after "Ny samtale"
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS chat_messages_user ON chat_messages (user_id, archived, id);
    """)


SECTION = Section(
    id="chat",
    title="Alf",
    router=router,
    migrations=[(1, "chat messages", _m001_messages)],
    family_prefixes=("/api/chat/",),
    reset=chat.reset,
)
