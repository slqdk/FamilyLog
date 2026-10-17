"""Shared test fixtures.

Every test runs against a throwaway data directory (APP_DATA_DIR), so the
suite can never touch a real database or settings file. The variable is set
before `app` is imported. Environment overrides from the host (APP_OLLAMA_URL
and friends) are removed, so a developer's shell cannot change a result.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
_ENV_VARS = ("APP_OLLAMA_URL", "APP_COMFY_URL", "APP_SEARXNG_URL", "APP_NOMINATIM_URL",
             "APP_OVERPASS_URL", "APP_TIMEZONE")


@pytest.fixture(scope="session", autouse=True)
def _isolate_data(tmp_path_factory):
    data = tmp_path_factory.mktemp("app-data")
    os.environ["APP_DATA_DIR"] = str(data)
    for var in _ENV_VARS:
        os.environ.pop(var, None)
    sys.path.insert(0, str(BACKEND))
    yield data
    os.environ.pop("APP_DATA_DIR", None)


@pytest.fixture
def fresh_db(_isolate_data):
    """A database with the schema applied and nothing in it."""
    from app.core import auth, db
    from app.sections import SECTIONS

    data = Path(os.environ["APP_DATA_DIR"])
    for name in ("app.db", "app.db-wal", "app.db-shm", "settings.json"):
        (data / name).unlink(missing_ok=True)
    # FamilyMap photos are files named by the database's rows.
    shutil.rmtree(data / "familymap", ignore_errors=True)
    # In-memory state must reset with the database.
    auth._failures.clear()
    for s in SECTIONS:
        if s.reset:
            s.reset()
    db.init_db()
    return db


@pytest.fixture
def client(fresh_db):
    """FastAPI test client with a signed-in admin."""
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/auth/setup",
                   json={"username": "admin", "password": "test-password-1"})
        assert r.status_code == 200, r.text
        yield c


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def mock_ollama():
    """The stand-in Ollama server (tools/mock_ollama.py) on a free port.

    A missing or silent mock FAILS the fixture instead of skipping: a test
    that cannot run is not a test that passed (SLQ learned this when 49
    tests quietly skipped for a release)."""
    script = REPO / "tools" / "mock_ollama.py"
    if not script.is_file():
        pytest.fail("tools/mock_ollama.py is missing - the suite cannot run without it")
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(script), str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail(f"mock_ollama.py did not start on {port}")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=5)
