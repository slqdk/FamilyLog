"""Økonomi on the phone page (0.3.0); each person their own (0.3.3). A family
account can never reach /api/ledger."""
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


def test_every_person_has_their_own_okonomi(client):
    """0.3.3 (Søren): "every user with access needs its own data"."""
    _upload(client, big_export()[0])                         # the admin's own ledger
    mor, mor_id = _login(client, "mor", "familie-kode-1")
    barn, _ = _login(client, "barn", "familie-kode-2")
    sanne, _ = _login(client, "sanne", "pw-sanne-12345", role="user")
    # A family account has none until the administrator turns it on.
    assert mor.get("/api/okonomi/state").json() == {"access": False}
    assert mor.get("/api/okonomi/month?month=2026-07").status_code == 403
    assert mor.post("/api/okonomi/import", files={"file": ("e.csv", b"x", "text/csv")}).status_code == 403
    r = client.put("/api/ledger/access", json={"userId": mor_id, "on": True})
    assert r.status_code == 200 and r.json() == [mor_id]
    # Her own, empty ledger - not the admin's.
    s = mor.get("/api/okonomi/state").json()
    assert s["access"] and s["own"] and s["count"] == 0
    assert "Davidsens" not in mor.get("/api/okonomi/transactions?month=2026-07").text
    # A user account has its own too, also empty.
    assert sanne.get("/api/okonomi/state").json()["count"] == 0
    # She imports her own export on the phone page; the admin's stays as it was.
    before = client.get("/api/okonomi/state").json()["count"]
    r = mor.post("/api/okonomi/import?account=Min konto",
                 files={"file": ("mor.csv", big_export(n_filler=40, seed=3)[0], "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["added"] > 40 and r.json()["account"] == "Min konto"
    assert mor.get("/api/okonomi/state").json()["count"] == r.json()["added"]
    assert client.get("/api/okonomi/state").json()["count"] == before
    # The owner's admin-app API stays shut for her.
    for method, path in (("get", "/api/ledger/summary"), ("delete", "/api/ledger"),
                         ("get", "/api/ledger/access")):
        assert getattr(mor, method)(path).status_code == 403, path
    assert barn.get("/api/okonomi/state").json() == {"access": False}
    # Turned off again: no Økonomi (her data stays, for when it is turned on).
    client.put("/api/ledger/access", json={"userId": mor_id, "on": False})
    assert mor.get("/api/okonomi/state").json() == {"access": False}


def _unknown_shops() -> bytes:
    """Three made-up shops no rule knows."""
    lines = [f"0{d}-09-2026;kontaktløs Dankort Zxq Butik {n} Nota C1234{d};-{d}12,50;DKK"
             for d, n in ((1, "Alfa"), (2, "Beta"), (3, "Gamma"))]
    return ("\ufeff" + "\r\n".join(lines) + "\r\n").encode("utf-8")


def test_she_places_merchants_and_deletes_an_import(client):
    mor, mor_id = _login(client, "mor", "familie-kode-1")
    client.put("/api/ledger/access", json={"userId": mor_id, "on": True})
    imp = mor.post("/api/okonomi/import", files={"file": ("mor.csv", _unknown_shops(), "text/csv")}).json()
    assert imp["added"] == 3, imp
    d = mor.get("/api/okonomi/data").json()
    assert d["left"] == 3 and len(d["uncategorised"]) == 3 and len(d["categories"]) == 40
    assert d["imports"][0]["id"] == imp["importId"]
    key = d["uncategorised"][0]["key"]
    assert mor.put("/api/okonomi/merchant", json={"key": key, "category": "groceries"}).status_code == 200
    assert mor.get("/api/okonomi/data").json()["left"] == d["left"] - 1
    assert mor.put("/api/okonomi/merchant", json={"key": key, "category": "rumfart"}).status_code == 400
    assert mor.put("/api/okonomi/merchant", json={"key": "nope", "category": "groceries"}).status_code == 404
    # No model set in this test: asking the model to place the rest says so.
    r = mor.post("/api/okonomi/categorise")
    assert r.status_code == 400 and "model" in r.json()["detail"].lower()
    assert mor.delete(f"/api/okonomi/imports/{imp['importId']}").json()["removed"] == imp["added"]
    assert mor.get("/api/okonomi/state").json()["count"] == 0


def test_access_is_for_family_accounts(client):
    _, sanne_id = _login(client, "sanne", "pw-sanne-12345", role="user")
    _, mor_id = _login(client, "mor", "familie-kode-1")
    assert client.put("/api/ledger/access", json={"userId": sanne_id, "on": True}).status_code == 400
    assert client.put("/api/ledger/access", json={"userId": 999, "on": True}).status_code == 400
    client.put("/api/ledger/access", json={"userId": mor_id, "on": True})
    client.delete(f"/api/users/{mor_id}")
    assert client.get("/api/ledger/access").json() == []


def test_she_asks_alf_about_her_own_ledger(client, mock):
    from fastapi.testclient import TestClient
    from app.main import app
    _, mor_id = _login(client, "mor", "familie-kode-1")
    client.put("/api/ledger/access", json={"userId": mor_id, "on": True})
    from app.sections.ledger import ledger
    ledger.set_settings(mor_id, "qwen3.6:27b")
    with TestClient(app) as mor:       # one event loop for the job (as the browser's server has)
        mor.post("/api/auth/login", json={"username": "mor", "password": "familie-kode-1"})
        assert mor.post("/api/okonomi/ask", json={"question": "hej"}).json()["detail"] \
            == "Der er ingen posteringer endnu."
        mor.post("/api/okonomi/import", files={"file": ("mor.csv", big_export()[0], "text/csv")})
        r = mor.post("/api/okonomi/ask", json={"question": "How much did I spend at Davidsens?"})
        assert r.status_code == 200, r.text
        a = _wait_phone(mor)
        assert a["state"] == "done" and a["count"] == 31
    assert client.get("/api/ledger/ask").json() == {"state": "none"}          # the admin's slot untouched
    # Turning her access off drops her last answer.
    client.put("/api/ledger/access", json={"userId": mor_id, "on": False})
    from app.sections.ledger import ledger_ask
    assert ledger_ask.ledger_of(mor_id) is None


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


