"""Migrations per owner, the section registry, and the account endpoints."""
from __future__ import annotations


def test_every_list_is_recorded_under_its_owner(fresh_db):
    from app.core import db, migrations
    with db.connect() as con:
        rows = {(r["section"], r["version"]) for r in con.execute(
            "SELECT section, version FROM schema_migrations")}
    assert ("core", 1) in rows and ("ledger", 1) in rows
    assert {("familymap", v) for v in (1, 2, 3, 4)} <= rows
    assert migrations.run() == []                    # nothing runs twice


def test_the_section_tables_exist(fresh_db):
    from app.core import db
    with db.connect() as con:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "sessions", "ledger_tx", "ledger_merchants", "ledger_imports",
            "ledger_settings", "fm_places", "fm_reviews", "fm_photos", "fm_settings",
            "fm_wishlist", "fm_localities"} <= names


def test_a_list_out_of_order_is_refused():
    import pytest
    from app.core import migrations
    with pytest.raises(RuntimeError):
        migrations._check([("x", [(2, "b", None), (1, "a", None)])])


def test_sections_come_from_the_registry(client):
    ids = [s["id"] for s in client.get("/api/sections").json()]
    assert ids == ["ledger", "familymap", "chat", "dagbog", "cyklus"]


def test_the_admin_makes_users_and_family_accounts(client):
    r = client.post("/api/users", json={"username": "sanne", "password": "pw-sanne-12345"})
    assert r.status_code == 200 and r.json()["role"] == "user"
    r = client.post("/api/users", json={"username": "barn", "password": "pw-barn-1234567",
                                        "role": "family"})
    assert r.status_code == 200 and r.json()["role"] == "family"
    assert client.post("/api/users", json={"username": "boss", "password": "pw-boss-1234567",
                                           "role": "admin"}).status_code == 400
    users = {u["username"]: u for u in client.get("/api/users").json()}
    assert users["admin"]["online"] is True and users["sanne"]["online"] is False


def test_a_user_changes_only_their_own_password(client):
    from fastapi.testclient import TestClient
    from app.core import auth
    from app.main import app
    sanne = auth.create_user("sanne", "pw-sanne-12345", "user")
    other = auth.create_user("ole", "pw-ole-1234567", "user")
    uc = TestClient(app)
    uc.post("/api/auth/login", json={"username": "sanne", "password": "pw-sanne-12345"})
    assert uc.patch(f"/api/users/{other['id']}/password",
                    json={"password": "new-password-1"}).status_code == 403
    assert uc.patch(f"/api/users/{sanne['id']}/password",
                    json={"password": "new-password-1"}).status_code == 200
    assert auth.login("sanne", "new-password-1")[0]
    assert uc.get("/api/users").status_code == 403


def test_family_reaches_neither_models_nor_help(client):
    from fastapi.testclient import TestClient
    from app.core import auth
    from app.main import app
    auth.create_user("barn", "pw-barn-1234567", "family")
    fc = TestClient(app)
    fc.post("/api/auth/login", json={"username": "barn", "password": "pw-barn-1234567"})
    for path in ("/api/ollama/models", "/api/help", "/api/sections", "/api/roles",
                 "/api/diagnostics", "/api/ledger/summary"):
        assert fc.get(path).status_code == 403, path
    assert fc.get("/api/fm/categories").status_code == 200


def test_the_session_cookie_carries_the_app_id(client):
    from app.core import auth
    assert auth.SESSION_COOKIE == "familylog_session"
    assert auth.SESSION_COOKIE in client.cookies


def test_diagnostics_show_the_queue_and_recent_errors(client):
    d = client.get("/api/diagnostics").json()
    assert d["queue"]["broker"] == "local" and isinstance(d["recent"], list)
