"""Authentication and ownership."""
from __future__ import annotations


def test_first_run_creates_the_admin(client):
    me = client.get("/api/auth/status").json()
    assert me["user"]["username"] == "admin"
    assert me["user"]["role"] == "admin"
    assert me["needsSetup"] is False


def test_setup_cannot_be_run_twice(client):
    r = client.post("/api/auth/setup",
                    json={"username": "intruder", "password": "another-pass-1"})
    assert r.status_code >= 400


def test_wrong_password_is_refused(client, fresh_db):
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code >= 400
    assert client.get("/api/settings").status_code >= 400


def test_settings_require_a_session(client):
    client.post("/api/auth/logout")
    assert client.get("/api/settings").status_code >= 400


def test_password_is_not_stored_in_clear(client, fresh_db):
    with fresh_db.connect() as con:
        row = con.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()
    assert "test-password-1" not in row["password_hash"]
    assert len(row["password_hash"]) > 20


def test_sub_profile_cannot_see_other_peoples_data(client, fresh_db):
    """An admin sees everything; a sub-profile only its own."""
    from app.core import auth

    users = {u["username"]: u for u in auth.list_users()}
    admin = auth.get_user(users["admin"]["id"])
    sub = auth.create_user("colleague", "another-password-1", role="user")

    assert auth.can_access_user_data(admin, sub["id"])       # admin sees all
    assert auth.can_access_user_data(sub, sub["id"])         # own data: yes
    assert not auth.can_access_user_data(sub, admin["id"])   # someone else: no


def test_sub_profile_limit_is_enforced(client):
    """One admin plus two sub-profiles; the fourth is refused by the API.

    The limit lives in the endpoint rather than in auth.create_user(), so it
    is tested where it is actually enforced.
    """
    from app.core import auth

    assert client.post("/api/users",
                       json={"username": "one", "password": "another-password-1"}).status_code == 200
    assert client.post("/api/users",
                       json={"username": "two", "password": "another-password-2"}).status_code == 200
    r = client.post("/api/users",
                    json={"username": "three", "password": "another-password-3"})
    assert r.status_code >= 400
    assert auth.user_count() == auth.MAX_USERS


def test_duplicate_username_is_refused(client):
    r = client.post("/api/users",
                    json={"username": "admin", "password": "another-password-1"})
    assert r.status_code >= 400


def test_short_password_is_refused(client):
    r = client.post("/api/users", json={"username": "weak", "password": "abc"})
    assert r.status_code >= 400


def test_session_lifetime_depends_on_role(fresh_db):
    """The admin signs in monthly, everyone else every ten days. The clock
    runs from login - there is no sliding renewal - so the expiry stamped
    at creation IS the policy. (1.43.0; before, a flat 30 days for all.)"""
    import time
    from app.core import auth, db

    admin = auth.create_user("boss", "pw12345678", "admin")
    user = auth.create_user("guest", "pw12345678", "user")
    auth.create_session(admin["id"])
    auth.create_session(user["id"])

    with db.connect() as con:
        rows = {r["user_id"]: r["expires_at"] for r in con.execute(
            "SELECT user_id, expires_at FROM sessions").fetchall()}
    now = time.time()
    admin_days = (rows[admin["id"]] - now) / 86400
    user_days = (rows[user["id"]] - now) / 86400
    assert 29.9 < admin_days <= 30.0
    assert 9.9 < user_days <= 10.0


# ---- two sessions per user (2.1.5) ----------------------------------------

def test_two_devices_can_be_signed_in_at_once(fresh_db):
    """Signing in on a second device must not sign the first one out - the
    whole point of the change. (2.1.5; it used to replace the old session.)"""
    from app.core import auth

    me = auth.create_user("soren", "pw12345678", "admin")
    desktop = auth.create_session(me["id"])
    laptop = auth.create_session(me["id"])

    assert auth.session_user(desktop) is not None
    assert auth.session_user(laptop) is not None


def test_a_third_login_evicts_the_least_recently_used(fresh_db):
    """Over the limit, the device you have not touched goes - not the oldest
    by creation, or a phone you used this morning would beat the desktop you
    are sitting at."""
    import time
    from app.core import auth

    me = auth.create_user("soren", "pw12345678", "admin")
    first = auth.create_session(me["id"])
    time.sleep(0.01)
    second = auth.create_session(me["id"])
    time.sleep(0.01)
    auth.session_user(first)          # first is now the most recently used
    third = auth.create_session(me["id"])

    assert auth.session_user(first) is not None    # recently used, survives
    assert auth.session_user(second) is None       # least recent, evicted
    assert auth.session_user(third) is not None


def test_never_more_than_the_limit(fresh_db):
    from app.core import auth, db

    me = auth.create_user("soren", "pw12345678", "admin")
    for _ in range(5):
        auth.create_session(me["id"])
    with db.connect() as con:
        count = con.execute("SELECT COUNT(*) c FROM sessions WHERE user_id=?",
                            (me["id"],)).fetchone()["c"]
    assert count == auth.MAX_SESSIONS_PER_USER == 2


def test_an_expired_session_does_not_cost_a_slot(fresh_db):
    """A dead row must be cleared before counting, or an expired session on a
    device you no longer own would evict a live one."""
    import time
    from app.core import auth, db

    me = auth.create_user("soren", "pw12345678", "admin")
    dead = auth.create_session(me["id"])
    with db.connect() as con:                      # force it to be expired
        con.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?",
                    (time.time() - 10, auth._hash_token(dead)))
    live_a = auth.create_session(me["id"])
    live_b = auth.create_session(me["id"])

    assert auth.session_user(dead) is None
    assert auth.session_user(live_a) is not None   # not evicted by the corpse
    assert auth.session_user(live_b) is not None


def test_sessions_are_counted_per_user(fresh_db):
    """Two people on two devices each is four sessions, not two."""
    from app.core import auth

    a = auth.create_user("soren", "pw12345678", "admin")
    b = auth.create_user("sanne", "pw12345678", "user")
    tokens = [auth.create_session(a["id"]), auth.create_session(a["id"]),
              auth.create_session(b["id"]), auth.create_session(b["id"])]
    assert all(auth.session_user(t) is not None for t in tokens)


def test_sign_out_everywhere_still_drops_all_sessions(fresh_db):
    """Password change and the admin's revoke must clear every device."""
    from app.core import auth

    me = auth.create_user("soren", "pw12345678", "admin")
    desktop = auth.create_session(me["id"])
    laptop = auth.create_session(me["id"])
    auth.revoke_user_sessions(me["id"])

    assert auth.session_user(desktop) is None
    assert auth.session_user(laptop) is None


def test_logging_out_one_device_leaves_the_other_signed_in(fresh_db):
    from app.core import auth

    me = auth.create_user("soren", "pw12345678", "admin")
    desktop = auth.create_session(me["id"])
    laptop = auth.create_session(me["id"])
    auth.revoke_session(laptop)

    assert auth.session_user(desktop) is not None
    assert auth.session_user(laptop) is None
