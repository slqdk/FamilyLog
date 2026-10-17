#!/usr/bin/env python3
"""Real-browser check against the real backend and the mock Ollama.

    cd frontend && npm run build && cd ..
    python3 tools/browser_check/run.py [tools/browser_check/check_all.py]

Copies the repo to a scratch folder (SCRATCH, default a temp dir), puts
frontend/dist in as backend/static, starts tools/mock_ollama.py and uvicorn
on free ports with a throwaway data folder, runs the check script with
(base url, mock url, screenshots dir), then stops both. Exit code is the
check's: any failed expectation, page error or console error fails it.
Needs: playwright (pip) and a Chromium (`playwright install chromium`, or
PLAYWRIGHT_BROWSERS_PATH pointing at one).
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, timeout: float = 20) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except Exception:
            time.sleep(0.2)
    raise SystemExit(f"{url} did not answer within {timeout} s")


def main() -> int:
    script = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "tools" / "browser_check" / "check_all.py").resolve()
    dist = REPO / "frontend" / "dist"
    if not all((dist / page).is_file() for page in ("index.html", "app/index.html", "fm/index.html")):
        raise SystemExit("frontend/dist is missing or incomplete - run `npm run build` in frontend/ first")
    scratch = Path(os.environ.get("SCRATCH") or tempfile.mkdtemp(prefix="familylog-bc-"))
    shutil.rmtree(scratch, ignore_errors=True)
    (scratch / "data").mkdir(parents=True)
    shots = scratch / "shots"
    shots.mkdir()
    shutil.copytree(REPO / "backend" / "app", scratch / "repo" / "backend" / "app")
    shutil.copytree(REPO / "docs", scratch / "repo" / "docs")
    shutil.copy(REPO / "VERSION", scratch / "repo" / "VERSION")
    shutil.copytree(dist, scratch / "repo" / "backend" / "static")

    mock_port, app_port = free_port(), free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("APP_")}
    env["APP_DATA_DIR"] = str(scratch / "data")
    mock = subprocess.Popen([sys.executable, str(REPO / "tools" / "mock_ollama.py"), str(mock_port)],
                            stdout=open(scratch / "mock.log", "w"), stderr=subprocess.STDOUT)
    app = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(app_port)],
                           cwd=scratch / "repo" / "backend", env=env,
                           stdout=open(scratch / "uvicorn.log", "w"), stderr=subprocess.STDOUT)
    try:
        wait_for(f"http://127.0.0.1:{mock_port}/api/version")
        wait_for(f"http://127.0.0.1:{app_port}/api/meta")
        r = subprocess.run([sys.executable, str(script), f"http://127.0.0.1:{app_port}",
                            f"http://127.0.0.1:{mock_port}", str(shots)], timeout=600)
        code = r.returncode
    finally:
        for p in (app, mock):
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
    print(f"screenshots: {shots}\nserver log: {scratch / 'uvicorn.log'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
