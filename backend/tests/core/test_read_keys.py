"""Read keys (0.5.0): another app reads one person's data and changes nothing."""
from __future__ import annotations

from datetime import date

import pytest

TODAY = date.today().isoformat()


def _reader(key: str):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, headers={"Authorization": f"Bearer {key}"})


def _new_family(client, name="mor"):
    r = client.post("/api/users", json={"username": name, "password": "another-password-1", "role": "family"})
    assert r.status_code == 200
    return r.json()["id"]


def _key(client, uid):
    r = client.post(f"/api/users/{uid}/read-key")
    assert r.status_code == 200
    return r.json()["key"]


def _admin_id(client):
    return client.get("/api/auth/status").json()["user"]["id"]


def test_a_key_says_who_it_belongs_to(client):
    uid = _new_family(client)
    me = _reader(_key(client, uid)).get("/api/read/me")
    assert me.status_code == 200 and me.json()["username"] == "mor"
    assert set(me.json()) == {"id", "username", "name"}


def test_unknown_keys_are_refused(client):
    assert _reader("flk_gaettet").get("/api/read/me").status_code == 401
    assert _reader("slqhub_noget_andet").get("/api/okonomi/state").status_code == 401


@pytest.mark.parametrize("method,path", [
    ("post", "/api/okonomi/ask"),
    ("post", "/api/okonomi/import"),
    ("put", "/api/okonomi/merchant"),
    ("put", "/api/dagbog/entry"),
    ("delete", "/api/dagbog/entry"),
    ("post", "/api/fm/places"),
    ("post", "/api/chat/send"),
])
def test_a_key_can_never_change_anything(client, method, path):
    assert getattr(_reader(_key(client, _admin_id(client))), method)(path).status_code == 403


@pytest.mark.parametrize("path", [
    "/api/users", "/api/settings", "/api/diagnostics", "/api/ledger/data",
    "/api/chat/state", "/api/cyklus/state", "/api/dagbog/family?frm=2026-01-01&to=2026-01-02",
    "/api/fm/places/1", "/api/help", "/api/sections", "/api/okonomi/ask", "/api/okonomi/data",
])
def test_even_an_admins_key_only_reaches_the_read_paths(client, path):
    assert _reader(_key(client, _admin_id(client))).get(path).status_code == 403


def test_a_key_reads_its_own_dagbog_not_the_familys(client):
    admin = _admin_id(client)
    mor = _new_family(client)
    client.put("/api/dagbog/entry", json={"day": TODAY, "mood": 4, "highlight": "God dag"})
    own = _reader(_key(client, admin)).get("/api/dagbog/person", params={"user": admin})
    assert own.status_code == 200 and own.json()["entries"][0]["highlight"] == "God dag"
    other = _reader(_key(client, mor))
    assert other.get("/api/dagbog/person", params={"user": admin}).status_code == 403
    assert other.get("/api/dagbog/stats", params={"user": admin}).status_code == 403
    assert other.get("/api/dagbog/person").status_code == 403


def test_a_key_follows_the_persons_okonomi(client):
    uid = _new_family(client)
    reader = _reader(_key(client, uid))
    assert reader.get("/api/okonomi/state").json() == {"access": False}
    assert reader.get("/api/okonomi/overview").status_code == 403
    assert _reader(_key(client, _admin_id(client))).get("/api/okonomi/overview").status_code == 200


def test_a_new_key_replaces_the_old_and_removal_stops_it(client):
    uid = _new_family(client)
    old = _key(client, uid)
    new = _key(client, uid)
    assert _reader(old).get("/api/read/me").status_code == 401
    assert _reader(new).get("/api/read/me").status_code == 200
    assert client.delete(f"/api/users/{uid}/read-key").status_code == 200
    assert _reader(new).get("/api/read/me").status_code == 401


def test_the_key_is_not_stored_and_not_shown_again(client, fresh_db):
    uid = _new_family(client)
    key = _key(client, uid)
    with fresh_db.connect() as con:
        row = con.execute("SELECT * FROM read_keys WHERE user_id=?", (uid,)).fetchone()
    assert key not in tuple(row)
    listed = next(u for u in client.get("/api/users").json() if u["id"] == uid)
    assert listed["readKey"]["hint"] == key[-4:] and key not in str(listed)


def test_only_the_admin_makes_keys(client):
    from fastapi.testclient import TestClient
    from app.main import app
    uid = _new_family(client)
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": "mor", "password": "another-password-1"}).status_code == 200
    assert c.post(f"/api/users/{uid}/read-key").status_code >= 400
    assert c.delete(f"/api/users/{uid}/read-key").status_code >= 400


def test_a_deleted_account_takes_its_key_along(client):
    uid = _new_family(client)
    key = _key(client, uid)
    assert client.delete(f"/api/users/{uid}").status_code == 200
    assert _reader(key).get("/api/read/me").status_code == 401
