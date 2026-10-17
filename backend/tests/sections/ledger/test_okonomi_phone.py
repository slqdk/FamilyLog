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




# ---- 0.3.5: periods, accounts, search, shops, trends on the phone ------------------------

def test_any_period_and_account(client):
    _upload(client, big_export()[0], account="Lønkonto")
    _upload(client, _unknown_shops(), name="kort.csv", account="MasterCard")
    whole = client.get("/api/okonomi/overview").json()
    assert whole["months"] > 30 and whole["perMonth"] > 0 and whole["baselinePerMonth"] is None
    year = client.get("/api/okonomi/overview?frm=2025-01-01&to=2025-12-31").json()
    assert year["months"] == 12 and not year["isMonth"]
    month = client.get("/api/okonomi/overview?frm=2026-05-01&to=2026-05-31").json()
    assert month["isMonth"] and month["baselineMonths"] == 6
    card = client.get("/api/okonomi/overview?frm=2026-09-01&to=2026-09-30&account=MasterCard").json()
    assert card["count"] == 3 and card["spent"] == 112.5 + 212.5 + 312.5
    assert client.get("/api/okonomi/overview?frm=2026-9-1").status_code == 400


def test_search_filter_and_sort_transactions(client):
    _upload(client, big_export()[0])
    t = client.get("/api/okonomi/transactions?q=davidsens&order=largest").json()
    assert t["total"] == 31 and t["rows"][0]["amount"] <= t["rows"][-1]["amount"]
    inn = client.get("/api/okonomi/transactions?direction=in&frm=2025-01-01&to=2025-12-31").json()
    assert inn["total"] > 0 and all(r["amount"] > 0 for r in inn["rows"])
    more = client.get("/api/okonomi/transactions?offset=50").json()
    assert len(more["rows"]) == 50
    assert client.get("/api/okonomi/transactions?order=random").status_code == 400


def test_move_and_rename_any_shop(client):
    _upload(client, big_export()[0])
    shops = client.get("/api/okonomi/merchants?q=netto").json()
    netto = shops["merchants"][0]
    assert netto["categoryName"] == "Dagligvarer" and shops["categories"][0]["group"] == "Hus & bolig"
    r = client.put("/api/okonomi/merchant", json={"key": netto["key"], "category": "shopping", "name": "Netto Skagen"})
    assert r.status_code == 200
    again = client.get("/api/okonomi/merchants?q=netto").json()["merchants"][0]
    assert (again["name"], again["category"], again["source"]) == ("Netto Skagen", "shopping", "user")
    assert client.get("/api/okonomi/transactions?merchant=" + netto["key"]).json()["rows"][0]["merchant"] == "Netto Skagen"
    assert client.put("/api/okonomi/merchant", json={"key": netto["key"], "name": "  "}).json()["detail"] \
        == "Butikken skal have et navn."


def test_month_by_month(client):
    _upload(client, big_export()[0])
    tr = client.get("/api/okonomi/trend?months=12").json()
    last = client.get("/api/okonomi/state").json()["lastDate"][:7]
    assert len(tr["months"]) == 12 and tr["months"][-1]["month"] == last
    assert all("groceries" in m["byCategory"] or m["spent"] >= 0 for m in tr["months"])
    assert tr["categories"][0]["name"]
    assert len(client.get("/api/okonomi/trend?months=0").json()["months"]) > 30
