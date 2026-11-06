"""Read keys: another app reads one person's data here and can change nothing.

SLQ Dashboard is the first such app. A key is `flk_` plus a random token, sent
as `Authorization: Bearer flk_...`. It acts as the person it belongs to, so the
same rules as in the app decide what comes back, with three narrower limits, all
checked in one place (`allows`), in the auth middleware:

* GET only. Anything else is refused, whatever the path.
* Only the paths in READ_PATHS. Nothing under /api/users, /api/settings,
  /api/chat, /api/cyklus or the admin app's APIs.
* Only the person's own days: the Dagbog's `user` argument must be the key's
  owner, although the family may see each other's days in the app.

One key per person: a new key replaces the old one. Only its SHA-256 is stored,
so it is shown once, when it is made.
"""
from __future__ import annotations

import hashlib
import secrets

from . import db

PREFIX = "flk_"

SCHEMA = """
CREATE TABLE IF NOT EXISTS read_keys (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    key_hash   TEXT NOT NULL UNIQUE,
    hint       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used  TEXT
);
"""

WHO_AM_I = "/api/read/me"

READ_PATHS = frozenset({
    WHO_AM_I,
    "/api/okonomi/state",
    "/api/okonomi/overview",
    "/api/okonomi/transactions",
    "/api/okonomi/merchants",
    "/api/dagbog/person",
    "/api/dagbog/stats",
    "/api/fm/places",
    "/api/fm/me/reviews",
})
OWN_DAYS_ONLY = frozenset({"/api/dagbog/person", "/api/dagbog/stats"})


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create(uid: int) -> str:
    """A new key for this person, replacing any old one. Returned once."""
    key = PREFIX + secrets.token_urlsafe(32)
    with db.connect() as con:
        con.execute("DELETE FROM read_keys WHERE user_id=?", (uid,))
        con.execute("INSERT INTO read_keys (user_id, key_hash, hint, created_at) VALUES (?,?,?,?)",
                    (uid, _hash(key), key[-4:], db.utcnow()))
    return key


def revoke(uid: int) -> None:
    with db.connect() as con:
        con.execute("DELETE FROM read_keys WHERE user_id=?", (uid,))


def info(uid: int) -> dict | None:
    with db.connect() as con:
        r = con.execute("SELECT * FROM read_keys WHERE user_id=?", (uid,)).fetchone()
    return {"hint": r["hint"], "createdAt": r["created_at"], "lastUsed": r["last_used"]} if r else None


def user_for(key: str) -> dict | None:
    """The person a key belongs to, or None. Notes that it was used."""
    from . import auth
    if not key.startswith(PREFIX):
        return None
    with db.connect() as con:
        r = con.execute("SELECT user_id FROM read_keys WHERE key_hash=?", (_hash(key),)).fetchone()
        if r is None:
            return None
        con.execute("UPDATE read_keys SET last_used=? WHERE user_id=?", (db.utcnow(), r["user_id"]))
    return auth.get_user(r["user_id"])


def allows(me: dict, method: str, path: str, user_arg: str | None) -> str | None:
    """Why this request is refused, or None when it may go through."""
    if method != "GET":
        return "A read key can only read."
    if path not in READ_PATHS:
        return "A read key cannot open this."
    if path in OWN_DAYS_ONLY and user_arg != str(me["id"]):
        return "A read key only reads its own person's days."
    return None
