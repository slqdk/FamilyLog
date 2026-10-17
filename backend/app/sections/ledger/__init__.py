"""Økonomi: bank and card exports in, exact numbers out (SLQ 2.63.x).

Every number comes from SQL, never from the model: the model turns a
question into a JSON search (checked field by field and run here), and
writes up the result it is handed."""
from __future__ import annotations

import sqlite3

from app.core.sections import Section

from . import ledger_ask
from .ledger_routes import router


def _m001_ledger(con: sqlite3.Connection) -> None:
    """SLQ _m048 (2.63.0): bank and card transactions, per person. Amounts in
    øre. A row is unique by (account, date, text, amount, occurrence) - the
    occurrence is the n-th identical row that day, so a re-upload merges
    and two identical purchases on one day both stay. Categories hang on
    the merchant, so placing a merchant places all its rows."""
    con.executescript("""
        CREATE TABLE IF NOT EXISTS ledger_imports (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            account      TEXT NOT NULL,
            filename     TEXT NOT NULL DEFAULT '',
            imported_at  TEXT NOT NULL,
            rows_in_file INTEGER NOT NULL DEFAULT 0,
            rows_added   INTEGER NOT NULL DEFAULT 0,
            rows_known   INTEGER NOT NULL DEFAULT 0,
            first_date   TEXT,
            last_date    TEXT
        );
        CREATE TABLE IF NOT EXISTS ledger_tx (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER NOT NULL,
            account          TEXT NOT NULL,
            date             TEXT NOT NULL,
            text             TEXT NOT NULL,
            amount           INTEGER NOT NULL,
            currency         TEXT NOT NULL DEFAULT 'DKK',
            occurrence       INTEGER NOT NULL DEFAULT 1,
            kind             TEXT NOT NULL DEFAULT 'other',
            merchant         TEXT NOT NULL,
            merchant_key     TEXT NOT NULL,
            foreign_amount   REAL,
            foreign_currency TEXT,
            import_id        INTEGER,
            UNIQUE (user_id, account, date, text, amount, occurrence)
        );
        CREATE INDEX IF NOT EXISTS ledger_tx_user_date ON ledger_tx (user_id, date);
        CREATE INDEX IF NOT EXISTS ledger_tx_user_merchant ON ledger_tx (user_id, merchant_key);
        CREATE TABLE IF NOT EXISTS ledger_merchants (
            user_id      INTEGER NOT NULL,
            merchant_key TEXT NOT NULL,
            name         TEXT NOT NULL,
            category     TEXT NOT NULL DEFAULT '',
            source       TEXT NOT NULL DEFAULT 'none',
            sample       TEXT NOT NULL DEFAULT '',
            updated_at   TEXT NOT NULL,
            PRIMARY KEY (user_id, merchant_key)
        );
        CREATE TABLE IF NOT EXISTS ledger_settings (
            user_id    INTEGER PRIMARY KEY,
            model      TEXT,
            updated_at TEXT NOT NULL
        );
    """)


def _m002_viewers(con: sqlite3.Connection) -> None:
    """0.3.0: a family account the administrator gives read access to one
    admin/user account's Økonomi (on the phone page)."""
    con.executescript("""
        CREATE TABLE IF NOT EXISTS ledger_viewers (
            user_id  INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
        );
    """)


SECTION = Section(
    id="ledger",
    title="Økonomi",
    router=router,
    migrations=[(1, "ledger tables (SLQ _m048)", _m001_ledger),
                (2, "family read access", _m002_viewers)],
    family_prefixes=("/api/okonomi/",),
    reset=ledger_ask.reset,
)
