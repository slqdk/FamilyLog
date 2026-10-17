"""Logging, so a crash is visible in the app instead of only in a console.

Two destinations, on purpose:

  * a rotating file under `data/logs/`, which survives restarts and can be
    read after the fact - the console window is often closed, or scrolled past
  * a small in-memory ring of recent warnings and errors, which the
    Diagnostics tab shows without anyone needing to find a file

The 1.0.1 "no such column: profile" crash is the case this exists for: the
traceback appeared only in a terminal, so the tab just said "Loading..."
forever and the cause was invisible from inside the app.

Nothing here logs request bodies, prompts or passwords: entries are the
exception, where it happened, and the traceback.
"""
from __future__ import annotations

import logging
import logging.handlers
import threading
import traceback
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from . import db

from ..meta import APP_ID

LOG_DIR = db.data_dir() / "logs"
LOG_FILE = LOG_DIR / f"{APP_ID}.log"
MAX_BYTES = 2_000_000       # per file
BACKUPS = 5                 # ~10 MB total, then the oldest is dropped
RING_SIZE = 200             # recent entries kept for the UI

_ring: deque[dict] = deque(maxlen=RING_SIZE)
_lock = threading.Lock()
_configured = False


# Warnings that are real in the log's sense but useless in the bell's:
# Python on Windows raises _ProactorBasePipeTransport._call_connection_lost
# whenever a client socket goes away mid-write, which happens every time a
# browser tab closes during a stream. Nothing failed and nothing can be
# done about it, so ringing the error bell for it teaches the user to
# ignore the bell - which costs far more than the entry is worth. (2.12.4)
_NOISE = (
    "_ProactorBasePipeTransport._call_connection_lost",
    "ConnectionResetError: [WinError 10054]",
    "WinError 64",              # "the specified network name is no longer
                                # available" - the same event, other wording
)


def _is_noise(record: logging.LogRecord) -> bool:
    try:
        text = record.getMessage()
    except Exception:
        return False
    if record.exc_info:
        try:
            text += "".join(traceback.format_exception(*record.exc_info))
        except Exception:
            pass
    return any(marker in text for marker in _NOISE)


class _RingHandler(logging.Handler):
    """Keeps recent warnings and errors in memory for the Diagnostics tab."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        if _is_noise(record):
            return
        try:
            entry = {
                "time": datetime.fromtimestamp(record.created,
                                               tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage()[:2000],
                "where": f"{record.module}.{record.funcName}:{record.lineno}",
                "traceback": ("".join(traceback.format_exception(*record.exc_info))[-4000:]
                              if record.exc_info else None),
            }
        except Exception:
            return          # logging must never raise
        with _lock:
            _ring.append(entry)


def setup() -> None:
    """Attach the file and ring handlers. Safe to call more than once."""
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s %(module)s:%(lineno)d  %(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(_RingHandler())
    _configured = True


def recent(limit: int = 100, level: str | None = None) -> list[dict]:
    with _lock:
        items = list(_ring)
    if level:
        items = [e for e in items if e["level"] == level.upper()]
    return list(reversed(items[-limit:]))


def clear() -> None:
    with _lock:
        _ring.clear()


def log_files() -> list[dict]:
    if not LOG_DIR.exists():
        return []
    out = []
    for p in sorted(LOG_DIR.glob(f"{APP_ID}.log*")):
        stat = p.stat()
        out.append({"name": p.name, "bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc).isoformat()})
    return out


def tail(lines: int = 200) -> str:
    """Last lines of the current log file, for the Diagnostics tab."""
    if not LOG_FILE.exists():
        return ""
    try:
        # Read the tail only; the file can be megabytes.
        with LOG_FILE.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 200_000))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def record_problem(where: str, message: str) -> None:
    """Log something that failed but was handled and reported to the user.

    Without this a refused render left no trace anywhere: the user saw a
    message, Diagnostics said "nothing has gone wrong", and there was nothing
    to look at afterwards. (1.24.0)
    """
    logging.getLogger(APP_ID).error("%s: %s", where, message)


def record_exception(exc: BaseException, where: str) -> None:
    """Log an exception the app caught but handled, so it is still visible."""
    logging.getLogger(APP_ID).error("%s: %s", where, exc,
                                   exc_info=(type(exc), exc, exc.__traceback__))
