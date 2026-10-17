"""Schema migrations: one numbered list for the core, one per section.

From SLQ's migrations.py (one ordered list, `schema_migrations` records what
ran, so nothing runs twice), with one change: each list is recorded under
its owner (`core`, or the section id). A new section brings its own list
starting at 1 and never renumbers anyone else's.

Order: the core list first (users and sessions, which section tables refer
to), then each section in registry order.

Rules for adding one:
  * append to the end of the owner's list, never renumber or edit an
    applied migration
  * additive only - no dropping columns or tables
  * idempotent anyway, so a half-applied database can be re-run safely
"""
from __future__ import annotations

import sqlite3

from . import db

VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    section    TEXT NOT NULL,
    version    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    PRIMARY KEY (section, version)
);
"""


def add_column(con: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """Add a column when it is missing; refuse if the table does not exist
    (a column migration ordered before its CREATE TABLE is a bug)."""
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    if not cols:
        raise RuntimeError(f"migration tried to alter '{table}' before it was created")
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# ---- the core's own list ------------------------------------------------------

def _c001_auth(con: sqlite3.Connection) -> None:
    from . import auth
    con.executescript(auth.AUTH_SCHEMA)


def _c002_gender(con: sqlite3.Connection) -> None:
    """0.3.0: a gender per account ('' = not set, 'female', 'male'). The
    cycle section is for accounts set to female."""
    add_column(con, "users", "gender", "TEXT NOT NULL DEFAULT ''")


CORE: list[tuple[int, str, callable]] = [
    (1, "users and sessions", _c001_auth),
    (2, "gender per account", _c002_gender),
]


def all_lists() -> list[tuple[str, list]]:
    from ..sections import SECTIONS
    return [("core", CORE)] + [(s.id, s.migrations) for s in SECTIONS]


def _check(lists) -> None:
    for owner, items in lists:
        versions = [v for v, _n, _f in items]
        if versions != sorted(set(versions)):
            raise RuntimeError(f"migrations of {owner!r} must be unique and ascending")


def applied() -> set[tuple[str, int]]:
    with db.connect() as con:
        con.executescript(VERSION_TABLE)
        return {(r["section"], r["version"])
                for r in con.execute("SELECT section, version FROM schema_migrations")}


def run() -> list[str]:
    """Apply everything not yet applied. Returns what ran, for the log."""
    lists = all_lists()
    _check(lists)
    done = applied()
    ran: list[str] = []
    for owner, items in lists:
        for version, name, fn in items:
            if (owner, version) in done:
                continue
            with db.connect() as con:
                fn(con)
                con.execute(
                    "INSERT OR REPLACE INTO schema_migrations (section, version, name, applied_at)"
                    " VALUES (?,?,?,?)", (owner, version, name, db.utcnow()))
            ran.append(f"{owner} {version:03d} {name}")
    return ran
