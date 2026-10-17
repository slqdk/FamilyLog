"""The app's name and version - the ONE place to rename it.

The display name is what people see (title bar, login, help header). The
technical id is used for the session cookie, the log file and the like; the
repo/image/container names live in deploy/container/docker-compose.yml and
tools/container.py. Environment variables are deliberately neutral (APP_*),
so a rename never touches a deployment's override file.
"""
from __future__ import annotations

from pathlib import Path

APP_DISPLAY_NAME = "FamilyLog"
APP_ID = "familylog"

_VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"


def _read_version() -> str:
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


APP_VERSION = _read_version()
