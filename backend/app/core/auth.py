"""Accounts, passwords and sessions (from SLQ's auth.py).

* Roles: one `admin` (created on first run), up to MAX_USERS accounts in
  all for admin + `user`, and any number of `family` accounts. Family
  accounts reach only the family page's API (family_allows), decided once
  in the auth middleware so no endpoint has to remember.
* Passwords: stdlib scrypt, `scrypt$<salt hex>$<hash hex>` - SLQ's format,
  so an SLQ hash can be copied over by hand and keeps working.
* Sessions: random 32-byte tokens; only their SHA-256 is stored. Two
  devices per person; a third login evicts the least recently used.
* Failed logins are throttled per username.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time

from ..meta import APP_ID
from . import db

SESSION_DAYS_ADMIN = 30     # a month - the admin, and the family's phones
SESSION_DAYS_USER = 10
SESSION_COOKIE = f"{APP_ID}_session"
MAX_USERS = 3               # admin + user accounts; family does not count
FAMILY_ROLE = "family"
ROLES = ("admin", "user", FAMILY_ROLE)
GENDERS = ("", "female", "male")          # '' = not set (0.3.0)
# The API a family account may call. Sections add theirs through the
# registry (Section.family_prefixes); FamilyMap's phone page is /api/fm/.
FAMILY_API_PREFIX = "/api/fm/"
MAX_SESSIONS_PER_USER = 2
FAIL_LIMIT = 5
FAIL_WINDOW = 300
LOCKOUT_SECONDS = 300

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',   -- 'admin' | 'user' | 'family'
    prefs         TEXT,                            -- per-user UI preferences JSON
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at REAL NOT NULL,
    last_seen  REAL NOT NULL
);
"""

_failures: dict[str, list[float]] = {}


# ---- passwords ------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                            n=2 ** 14, r=8, p=1, dklen=32)
        return secrets.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def password_problem(password: str) -> str | None:
    """Minimum bar for something reachable from the internet."""
    if len(password) < 10:
        return "Password must be at least 10 characters."
    if password.lower() in {"password12", "1234567890", "qwertyuiop"}:
        return "Please choose a less predictable password."
    return None


# ---- users ----------------------------------------------------------------

def user_dto(r) -> dict:
    keys = r.keys()
    return {"id": r["id"], "username": r["username"], "role": r["role"],
            "gender": (r["gender"] or "") if "gender" in keys else "",
            "createdAt": r["created_at"]}


def user_count() -> int:
    with db.connect() as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def account_count() -> int:
    """Accounts that count towards MAX_USERS - everyone but family."""
    with db.connect() as con:
        return con.execute("SELECT COUNT(*) FROM users WHERE role != ?",
                           (FAMILY_ROLE,)).fetchone()[0]


def family_prefixes() -> tuple[str, ...]:
    from ..sections import SECTIONS
    out = [FAMILY_API_PREFIX]
    for s in SECTIONS:
        out += [p for p in s.family_prefixes if p not in out]
    return tuple(out)


def family_allows(me: dict, path: str) -> bool:
    """Whether this signed-in user may call this /api path. Everyone but
    family may call anything the endpoint itself allows; family only the
    family page's API. One rule, one place."""
    if me.get("role") != FAMILY_ROLE:
        return True
    return path.startswith(family_prefixes())


def list_users() -> list[dict]:
    with db.connect() as con:
        rows = con.execute("SELECT * FROM users ORDER BY id").fetchall()
    return [user_dto(r) for r in rows]


def get_user(uid: int) -> dict | None:
    with db.connect() as con:
        r = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return user_dto(r) if r else None


def create_user(username: str, password: str, role: str) -> dict:
    username = username.strip()
    if not username:
        raise ValueError("Username is required.")
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role}.")
    if problem := password_problem(password):
        raise ValueError(problem)
    with db.connect() as con:
        exists = con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
        if exists:
            raise ValueError("That username is already taken.")
        cur = con.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
            (username, hash_password(password), role, db.utcnow()))
        r = con.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
    return user_dto(r)


def set_gender(uid: int, gender: str) -> dict:
    gender = (gender or "").strip().lower()
    if gender not in GENDERS:
        raise ValueError("Gender must be female, male or empty.")
    with db.connect() as con:
        con.execute("UPDATE users SET gender=? WHERE id=?", (gender, uid))
        r = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if r is None:
        raise LookupError("No such account.")
    return user_dto(r)


def set_password(uid: int, password: str) -> None:
    if problem := password_problem(password):
        raise ValueError(problem)
    with db.connect() as con:
        con.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), uid))


def delete_user(uid: int) -> None:
    with db.connect() as con:
        con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        con.execute("DELETE FROM users WHERE id=?", (uid,))


# ---- sessions -------------------------------------------------------------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def active_sessions() -> list[dict]:
    """Live sessions with their owner, newest first."""
    now = time.time()
    with db.connect() as con:
        con.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        rows = con.execute(
            "SELECT s.token_hash, s.last_seen, u.id AS uid, u.username, u.role"
            " FROM sessions s JOIN users u ON u.id = s.user_id"
            " ORDER BY s.last_seen DESC").fetchall()
    return [{"tokenHash": r["token_hash"], "lastSeen": r["last_seen"],
             "userId": r["uid"], "username": r["username"], "role": r["role"]}
            for r in rows]


def create_session(uid: int) -> str:
    """A session whose lifetime depends on the role: admin and family a
    month (the person at the desk, and a phone), a user ten days. The clock
    runs from login; there is no sliding renewal."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    with db.connect() as con:
        row = con.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        days = (SESSION_DAYS_ADMIN
                if row and row["role"] in ("admin", FAMILY_ROLE)
                else SESSION_DAYS_USER)
        # Up to MAX_SESSIONS_PER_USER devices; room is made by dropping the
        # least recently used. Expired rows go first, or a dead session
        # would evict a live one.
        con.execute("DELETE FROM sessions WHERE user_id=? AND expires_at < ?", (uid, now))
        stale = con.execute(
            "SELECT token_hash FROM sessions WHERE user_id=?"
            " ORDER BY last_seen DESC LIMIT -1 OFFSET ?",
            (uid, MAX_SESSIONS_PER_USER - 1)).fetchall()
        for r in stale:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (r["token_hash"],))
        con.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen)"
            " VALUES (?,?,?,?,?)",
            (_hash_token(token), uid, db.utcnow(), now + days * 86400, now))
    return token


def session_user(token: str | None) -> dict | None:
    """Resolve a cookie value to a user, refreshing last_seen."""
    if not token:
        return None
    now = time.time()
    th = _hash_token(token)
    with db.connect() as con:
        r = con.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash=? AND s.expires_at > ?", (th, now)).fetchone()
        if r:
            con.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (now, th))
    return user_dto(r) if r else None


def revoke_session(token: str | None) -> None:
    if token:
        with db.connect() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))


def revoke_user_sessions(uid: int) -> None:
    with db.connect() as con:
        con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))


# ---- login ----------------------------------------------------------------

def _throttled(username: str) -> int:
    """Seconds the caller must wait, or 0 if they may try."""
    now = time.time()
    hits = [t for t in _failures.get(username, []) if now - t < FAIL_WINDOW]
    _failures[username] = hits
    if len(hits) >= FAIL_LIMIT:
        return max(int(LOCKOUT_SECONDS - (now - hits[-1])), 1)
    return 0


def _record_failure(username: str) -> None:
    _failures.setdefault(username, []).append(time.time())


def login(username: str, password: str) -> tuple[str | None, str | None]:
    """Returns (token, error)."""
    username = (username or "").strip()
    if wait := _throttled(username):
        return None, f"Too many failed attempts. Try again in {wait} seconds."
    with db.connect() as con:
        r = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not r or not verify_password(password, r["password_hash"]):
        _record_failure(username)
        return None, "Wrong username or password."
    _failures.pop(username, None)
    return create_session(r["id"]), None


# ---- ownership ------------------------------------------------------------

def can_access_user_data(me: dict, owner_id: int | None) -> bool:
    """Admin sees everything; anyone else only their own."""
    if me["role"] == "admin":
        return True
    return owner_id is not None and owner_id == me["id"]
