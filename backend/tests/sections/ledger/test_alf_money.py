"""Alf answers about money (0.3.12): the Økonomi page's own three steps -
understand, count exactly, answer from the count - on the asker's OWN
ledger, never anyone else's."""
from __future__ import annotations

import time

from test_ledger import _upload, big_export, mock  # noqa: F401 - fixture


def _wait(c, timeout=15.0):
    end = time.time() + timeout
    v = None
    while time.time() < end:
        v = c.get("/api/chat/state").json()
        if v["job"] and v["job"]["state"] in ("done", "failed", "stopped"):
            return v
        time.sleep(0.05)
    raise AssertionError(v)


def _ask(c, text):
    r = c.post("/api/chat/send", json={"message": text})
    assert r.status_code == 200, r.text
    v = _wait(c)
    assert v["job"]["state"] == "done", v["job"]
    return v["messages"][-1]


def test_alf_counts_in_your_own_ledger(client, mock):
    from fastapi.testclient import TestClient
    from app.main import app
    client.put("/api/settings", json={"modelChat": "gemma4:12b"})
    _upload(client, big_export()[0])
    with TestClient(app) as me:
        me.post("/api/auth/login", json={"username": "admin", "password": "test-password-1"})
        a = _ask(me, "Hvor meget har jeg brugt hos Davidsens?")
        assert a["meta"]["route"] == "money" and a["meta"]["matched"] == 31, a
        assert "From the ledger:" in a["content"] and "31 transactions" in a["content"]
        assert a["meta"]["spec"]["merchants"] == ["davidsens"]
        assert a["meta"]["counted"].startswith('penge ud, hos "davidsens"'), a["meta"]["counted"]
        # A follow-up keeps the search and changes the period.
        b = _ask(me, "og i 2025?")
        assert b["meta"]["route"] == "money" and b["meta"]["spec"]["merchants"] == ["davidsens"], b["meta"]
        assert 0 < b["meta"]["matched"] < 31
        # Someone else's Økonomi is theirs: Alf does not look.
        c = _ask(me, "Hvor meget har Mette brugt hos Netto?")
        assert c["meta"] == {"route": "money"} and "kun svare på din egen økonomi" in c["content"]


def test_without_okonomi_alf_says_why(client, mock):
    from fastapi.testclient import TestClient
    from app.main import app
    client.put("/api/settings", json={"modelChat": "gemma4:12b"})
    _upload(client, big_export()[0])                        # the admin's - never mor's to ask about
    r = client.post("/api/users", json={"username": "mor", "password": "familie-kode-1", "role": "family"})
    mor_id = r.json()["id"]
    with TestClient(app) as mor:
        mor.post("/api/auth/login", json={"username": "mor", "password": "familie-kode-1"})
        a = _ask(mor, "Hvor meget har jeg brugt hos Davidsens?")
        assert a["meta"] == {"route": "money"} and "ikke Økonomi endnu" in a["content"]
        client.put("/api/ledger/access", json={"userId": mor_id, "on": True})
        a = _ask(mor, "Hvor meget har jeg brugt hos Davidsens?")
        assert "ingen posteringer endnu" in a["content"] and "Davidsens" not in a["content"]
