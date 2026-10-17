"""tools/container.py (update.sh): the decisions that are pure functions,
the compose file handling, and the deployment files that go with it."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def ct():
    spec = importlib.util.spec_from_file_location("container_tool", REPO / "tools" / "container.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_names_and_paths(ct, monkeypatch):
    assert (ct.SERVICE, ct.IMAGE, ct.APP_TITLE) == ("app", "familylog", "FamilyLog")
    assert ct.HEALTH_URL == "http://127.0.0.1:8080/api/auth/status"
    monkeypatch.delenv("APP_BACKUP_DIR", raising=False)
    assert ct.backup_dir() == (REPO.parent / "familylog-backups").resolve()
    monkeypatch.setenv("APP_BACKUP_DIR", "/tmp/x-backups")
    assert ct.backup_dir() == Path("/tmp/x-backups").resolve()


def test_backup_names_sort_by_time_and_the_oldest_go(ct):
    a = ct.backup_name("0.1.0", datetime(2026, 10, 1, 12, 0, 0))
    b = ct.backup_name("0.2.0 beta", datetime(2026, 10, 2, 8, 30, 5))
    assert a == "2026-10-01_120000_0.1.0" and b == "2026-10-02_083005_0.2.0_beta"
    names = [f"2026-10-0{d}_000000_x" for d in range(1, 6)]
    assert ct.backups_to_delete(names, 3) == names[:2]
    assert ct.backups_to_delete(names[:2], 3) == []


def test_list_backups_needs_both_files(ct, tmp_path):
    (tmp_path / "2026-10-01_000000_0.1.0.json").write_text(json.dumps({"version": "0.1.0"}))
    (tmp_path / "2026-10-01_000000_0.1.0.tar.gz").write_bytes(b"x" * 10)
    (tmp_path / "2026-10-02_000000_0.1.1.json").write_text("{}")          # no tar: ignored
    got = ct.list_backups(tmp_path)
    assert [b["name"] for b in got] == ["2026-10-01_000000_0.1.0"]
    assert got[0]["size"] == 10 and got[0]["version"] == "0.1.0"


@pytest.mark.parametrize("state,answered,restarts,verdict", [
    ("running", True, 0, "ok"),
    ("running", False, 0, "wait"),
    ("restarting", False, 2, "wait"),
    ("restarting", False, 3, "failed"),
    ("exited", False, 0, "failed"),
    ("dead", False, 0, "failed"),
])
def test_health_verdict(ct, state, answered, restarts, verdict):
    assert ct.health_verdict(state, answered, restarts) == verdict


def test_human_sizes(ct):
    assert ct.human(512) == "512 B" and ct.human(2048) == "2.0 KB"
    assert ct.human(5 * 1024 ** 3) == "5.0 GB"


def test_the_override_file_is_used_when_present(ct, tmp_path, monkeypatch):
    base, over = tmp_path / "c.yml", tmp_path / "o.yml"
    base.write_text("x")
    monkeypatch.setattr(ct, "COMPOSE", base)
    monkeypatch.setattr(ct, "OVERRIDE", over)
    assert ct.compose_files() == ["-f", str(base)]
    over.write_text("y")
    assert ct.compose_files() == ["-f", str(base), "-f", str(over)]


def test_compose_passthrough_keeps_its_flags(ct, monkeypatch):
    seen = []

    class R:
        returncode = 0
    monkeypatch.setattr(ct, "run", lambda cmd, capture=True, check=False: seen.append(cmd) or R())
    assert ct.main(["compose", "logs", "-f", "--tail", "5"]) == 0
    assert seen[0][:2] == ["docker", "compose"] and seen[0][-4:] == ["logs", "-f", "--tail", "5"]


def test_a_stop_is_reported_not_raised(ct, monkeypatch, capsys):
    def preflight(need_clean=True):
        raise ct.Stop("git is not installed, or not on PATH.")
    monkeypatch.setattr(ct, "preflight", preflight)
    assert ct.main(["status"]) == 1
    assert "STOPPED: git is not installed" in capsys.readouterr().out


def test_the_deployment_files_agree():
    import yaml
    compose = yaml.safe_load((REPO / "deploy" / "container" / "docker-compose.yml").read_text())
    svc = compose["services"]["app"]
    assert compose["name"] == "familylog" and svc["image"] == "familylog:latest"
    assert svc["ports"] == ["8081:8080"] and svc["volumes"][0].endswith(":/data")
    assert svc["environment"]["APP_DATA_DIR"] == "/data"
    example = yaml.safe_load((REPO / "deploy" / "container" / "docker-compose.override.example.yml").read_text())
    assert "app" in example["services"]
    docker = (REPO / "Dockerfile").read_text()
    assert "--uid 1000" in docker and "EXPOSE 8080" in docker and "APP_DATA_DIR=/data" in docker
    assert "curl" in docker                      # update.sh's health check runs curl inside
    ignore = (REPO / ".gitignore").read_text()
    assert "deploy/container/docker-compose.override.yml" in ignore
    assert "exec python3" in (REPO / "update.sh").read_text()
    # Every APP_* variable the compose files mention is one settings.py reads.
    from app.core import settings
    known = set(settings.ENV_OVERRIDES.values()) | {"APP_DATA_DIR"}
    import re
    mentioned = set(re.findall(r"APP_[A-Z_]+", (REPO / "deploy" / "container" / "docker-compose.yml").read_text()
                               + (REPO / "deploy" / "container" / "docker-compose.override.example.yml").read_text()))
    assert mentioned <= known, mentioned - known
