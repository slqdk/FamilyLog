"""SQLite storage: one app.db in the data directory.

Stdlib sqlite3, a connection per call. Every table is created by a
migration (core/migrations.py and each section's own list), never here.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def data_dir() -> Path:
    """Where the database, settings, logs and uploads live.

    APP_DATA_DIR overrides it: /data in the container, a throwaway folder in
    the test suite. Unset, it is backend/data (a dev checkout)."""
    override = os.environ.get("APP_DATA_DIR")
    return Path(override) if override else Path(__file__).resolve().parents[2] / "data"


def db_path() -> Path:
    return data_dir() / "app.db"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 10000")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> list[str]:
    """Apply every migration not yet applied (core first, then sections)."""
    from . import migrations
    with connect() as con:
        # WAL: readers never wait for the writer (the queue's job and the
        # page's polling hit the database at the same time). Persistent, so
        # once is enough.
        con.execute("PRAGMA journal_mode = WAL")
    return migrations.run()
