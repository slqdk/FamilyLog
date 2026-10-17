"""0.3.0: Økonomi on the phone page, and read access for chosen family
accounts. Read only: a family account can never reach /api/ledger."""
from __future__ import annotations

import time

from test_ledger import _upload, _wait, big_export, mock  # noqa: F401 - fixture


def _login(client, name, pw, role="family"):
    from fastapi.testclient import TestClient
    from app.main import app
    r = client.post("/api/users", json={"username": name, "password": pw, "role": role})
    assert r.status_code == 200, r.text
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": name, "password": pw}).status_code == 200
    return c, r.json()["id"]


def _wait_phone(c, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        a = c.get("/api/okonomi/ask").json()["ask"]
        if a and a["state"] in ("done", "failed", "stopped"):
            return a
        time.sleep(0.05)
    raise AssertionError(a)


def test_the_owner_reads_their_own_month(client):
    _upload(client, big_export()[0])
    s = client.get("/api/okonomi/state").json()
    assert s["access"] and s["own"] and s["owner"] == "admin" and s["count"] > 1000
    month = s["months"][-1]
    m = client.get(f"/api/okonomi/month?month={month}").json()
    assert m["spent"] > 0 and m["categories"] and all(c["name"] for c in m["categories"])
    assert client.get("/api/okonomi/month?month=2026-13").status_code == 400
    t = client.get(f"/api/okonomi/transactions?month={month}").json()
    assert t["total"] > 0 and t["rows"][0]["date"].startswith(month)


def test_a_family_account_needs_access_and_then_only_reads(client):
    _upload(client, big_export()[0])
    mor, mor_id = _login(client, "mor", "familie-kode-1")
    barn, _ = _login(client, "barn", "familie-kode-2")
    admin_id = client.get("/api/auth/status").json()["user"]["id"]
    # Nothing until the administrator gives access.
    assert mor.get("/api/okonomi/state").json() == {"access": False}
    assert mor.get("/api/okonomi/month?month=2026-07").status_code == 403
    r = client.put("/api/ledger/viewers", json={"userId": mor_id, "ownerId": admin_id})
    assert r.status_code == 200 and r.json() == [{"userId": mor_id, "ownerId": admin_id}]
    s = mor.get("/api/okonomi/state").json()
    assert s["access"] and not s["own"] and s["owner"] == "admin"
    assert mor.get(f"/api/okonomi/month?month={s['months'][-1]}").json()["spent"] > 0
    # Read only: the owner's API stays shut, for reading and writing alike.
    for method, path in (("get", "/api/ledger/summary"), ("get", "/api/ledger/transactions"),
                         ("delete", "/api/ledger"), ("put", "/api/ledger/merchants"),
                         ("get", "/api/ledger/viewers")):
        assert getattr(mor, method)(path).status_code == 403, path
    # The other child was not given access.
    assert barn.get("/api/okonomi/state").json() == {"access": False}
    assert mor.put("/api/ledger/viewers", json={"userId": mor_id, "ownerId": None}).status_code == 403
    # Taking it away again.
    client.put("/api/ledger/viewers", json={"userId": mor_id, "ownerId": None})
    assert mor.get("/api/okonomi/state").json() == {"access": False}


def test_access_is_only_for_family_to_an_owners_ledger(client):
    _, mor_id = _login(client, "mor", "familie-kode-1")
    _, sanne_id = _login(client, "sanne", "pw-sanne-12345", role="user")
    assert client.put("/api/ledger/viewers", json={"userId": sanne_id, "ownerId": 1}).status_code == 400
    assert client.put("/api/ledger/viewers", json={"userId": mor_id, "ownerId": mor_id}).status_code == 400
    assert client.put("/api/ledger/viewers", json={"userId": mor_id, "ownerId": sanne_id}).status_code == 200
    # Deleting the owner takes the access with it.
    client.delete(f"/api/users/{sanne_id}")
    assert client.get("/api/ledger/viewers").json() == []


def test_a_viewer_asks_alf_about_the_owners_ledger_in_their_own_slot(client, mock):
    client.put("/api/ledger/settings", json={"model": "qwen3.6:27b"})
    _upload(client, big_export()[0])
    _wait(client, "/api/ledger/categorise")
    _, mor_id = _login(client, "mor", "familie-kode-1")
    client.put("/api/ledger/viewers", json={"userId": mor_id, "ownerId": 1})
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as mor:       # one event loop for the job (as the browser's server has)
        mor.post("/api/auth/login", json={"username": "mor", "password": "familie-kode-1"})
        _ask_as_viewer(client, mor)


def _ask_as_viewer(client, mor):
    r = mor.post("/api/okonomi/ask", json={"question": "How much did I spend at Davidsens?"})
    assert r.status_code == 200, r.text
    a = _wait_phone(mor)
    assert a["state"] == "done" and a["count"] == 31 and a["rows"][0]["categoryName"]
    # The owner's own ask slot is untouched.
    assert client.get("/api/ledger/ask").json() == {"state": "none"}
    assert mor.post("/api/okonomi/ask", json={"question": ""}).json()["detail"] == "Skriv et spørgsmål."


def test_gender_is_set_by_the_administrator(client):
    r = client.post("/api/users", json={"username": "mor", "password": "familie-kode-1",
                                        "role": "family", "gender": "female"})
    assert r.status_code == 200 and r.json()["gender"] == "female"
    uid = r.json()["id"]
    assert client.patch(f"/api/users/{uid}", json={"gender": "male"}).json()["gender"] == "male"
    assert client.patch(f"/api/users/{uid}", json={"gender": "x"}).status_code == 400
    assert client.patch(f"/api/users/999", json={"gender": ""}).status_code == 404
    users = {u["username"]: u for u in client.get("/api/users").json()}
    assert users["mor"]["gender"] == "male" and users["admin"]["gender"] == ""
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "mor", "password": "familie-kode-1"})
    assert c.get("/api/auth/status").json()["user"]["gender"] == "male"
    assert c.patch(f"/api/users/{uid}", json={"gender": "female"}).status_code == 403


def test_an_answer_does_not_outlive_the_access_it_was_asked_under(client, mock):
    """Review finding (0.3.0): a viewer's last answer (and its rows) must go
    when the access moves to another ledger, is removed, or the owner
    clears the ledger."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.sections.ledger import ledger_ask
    client.put("/api/ledger/settings", json={"model": "qwen3.6:27b"})
    _upload(client, big_export()[0])
    _wait(client, "/api/ledger/categorise")
    _, mor_id = _login(client, "mor", "familie-kode-1")
    _, sanne_id = _login(client, "sanne", "pw-sanne-12345", role="user")
    client.put("/api/ledger/viewers", json={"userId": mor_id, "ownerId": 1})
    with TestClient(app) as mor:
        mor.post("/api/auth/login", json={"username": "mor", "password": "familie-kode-1"})
        assert mor.post("/api/okonomi/ask", json={"question": "How much at Davidsens?"}).status_code == 200
        assert _wait_phone(mor)["count"] == 31
        client.put("/api/ledger/viewers", json={"userId": mor_id, "ownerId": sanne_id})
        assert mor.get("/api/okonomi/state").json()["ask"] is None           # moved: the old answer is gone
        assert ledger_ask.ledger_of(mor_id) is None
        client.put("/api/ledger/viewers", json={"userId": mor_id, "ownerId": 1})
        mor.post("/api/okonomi/ask", json={"question": "How much at Davidsens?"})
        _wait_phone(mor)
        client.delete("/api/ledger")                                         # the owner clears it
        assert mor.get("/api/okonomi/ask").json()["ask"] is None
        client.put("/api/ledger/viewers", json={"userId": mor_id, "ownerId": None})
        for path in ("/api/okonomi/ask", "/api/okonomi/transactions?month=2026-07"):
            assert mor.get(path).status_code == 403, path
        assert mor.post("/api/okonomi/ask", json={"question": "hi"}).status_code == 403
