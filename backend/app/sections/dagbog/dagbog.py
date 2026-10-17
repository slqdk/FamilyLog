"""Dagbog (FamilyLog 0.2.0): each person rates their day.

One entry per person per day: mood and mental readiness ("mentalt
overskud", 1-5 each), what was eaten (food categories), alcohol (units),
activities, and the day's highlight - a text and one photo. The food
categories and the activities are lists the administrator keeps.

0.2.1 (Søren): sleep and energy are gone and food is categories instead of
a 1-5 scale. The old columns stay in the table (migrations only add), are
no longer written, and are not sent.

Privacy, as Søren set it: the family sees everyone's ratings and tags; the
highlight text and photo are the author's alone. That rule is enforced here,
in the queries - no endpoint can return another person's text or photo,
the administrator's included.

Which fields a person records is set per account by the administrator (a
child need not have an alcohol field). A field that is off is neither
asked nor stored.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

from app.core import db

from ..familymap import familymap as fm

SCALES = {
    "mood": {"label": "Humør", "low": "Rigtig skidt", "high": "Rigtig godt",
             "faces": ["😞", "🙁", "😐", "🙂", "😄"]},
    "mental": {"label": "Mentalt overskud", "low": "Intet overskud", "high": "Masser af overskud"},
}
FIELDS = {
    **{k: {"kind": "scale", **v} for k, v in SCALES.items()},
    "foods": {"kind": "foods", "label": "Mad", "hint": "Hvad spiste du i dag?"},
    "alcohol": {"kind": "count", "label": "Alkohol", "unit": "genstande", "max": 30},
    "tags": {"kind": "tags", "label": "Aktiviteter", "hint": "Hvad lavede du i dag?"},
    "highlight": {"kind": "private", "label": "Dagens højdepunkt"},
}
FIELD_ORDER = list(FIELDS)
DEFAULT_TAGS = ["Skole/arbejde", "Sport", "Computer", "Gaming", "Fjernsyn", "Mobil",
                "Vedligehold af hus og have", "Rengøring", "Madlavning", "Indkøb",
                "Venner", "Familie", "Udenfor", "Læsning", "Hobby", "Fri", "Syg"]
DEFAULT_FOODS = ["Hjemmelavet", "Fastfood", "Takeaway", "Restaurant", "Kage", "Chips",
                 "Slik", "Is", "Sodavand", "Frugt og grønt", "Morgenmad", "Madpakke"]
LISTS = {"tags": DEFAULT_TAGS, "foods": DEFAULT_FOODS}
MAX_TAGS = 40
MAX_TAG = 30
MAX_HIGHLIGHT = 2000
MAX_DAYS_BACK = 366          # an entry can be filled in for the last year
MAX_RANGE = 62               # days in one family overview


class Invalid(ValueError):
    """Shown to the person as it is (Danish)."""


class NotFound(LookupError):
    pass


# ---- settings -------------------------------------------------------------------------------

def choice_list(name: str) -> list[str]:
    """The activities ("tags") or the food categories ("foods"): the
    administrator's list, else the default."""
    default = LISTS[name]
    with db.connect() as con:
        r = con.execute("SELECT value FROM dagbog_settings WHERE key = ?", (name,)).fetchone()
    if not r:
        return list(default)
    try:
        value = json.loads(r["value"])
        return [str(t) for t in value] if isinstance(value, list) else list(default)
    except json.JSONDecodeError:
        return list(default)


def tags() -> list[str]:
    return choice_list("tags")


def foods() -> list[str]:
    return choice_list("foods")


def set_tags(values: list) -> list[str]:
    return set_choice_list("tags", values)


def set_foods(values: list) -> list[str]:
    return set_choice_list("foods", values)


def set_choice_list(name: str, values: list) -> list[str]:
    if not isinstance(values, list):
        raise Invalid(f"{name} must be a list.")
    out: list[str] = []
    for v in values:
        t = " ".join(str(v or "").split())
        if not t:
            continue
        if len(t) > MAX_TAG:
            raise Invalid(f"A tag can be at most {MAX_TAG} characters: {t[:40]}")
        if t.lower() not in {x.lower() for x in out}:
            out.append(t)
    if len(out) > MAX_TAGS:
        raise Invalid(f"At most {MAX_TAGS} tags.")
    with db.connect() as con:
        con.execute("INSERT INTO dagbog_settings (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (name, json.dumps(out, ensure_ascii=False)))
    return out


def fields_for(user_id: int) -> list[str]:
    """The fields this person records, in display order. Default: all."""
    with db.connect() as con:
        r = con.execute("SELECT fields FROM dagbog_members WHERE user_id = ?", (user_id,)).fetchone()
    if not r:
        return list(FIELD_ORDER)
    try:
        chosen = set(json.loads(r["fields"]))
    except json.JSONDecodeError:
        return list(FIELD_ORDER)
    return [f for f in FIELD_ORDER if f in chosen]


def set_fields_for(user_id: int, fields: list) -> list[str]:
    if not isinstance(fields, list) or any(f not in FIELDS for f in fields):
        raise Invalid(f"Fields must be some of: {', '.join(FIELD_ORDER)}.")
    if not fields:
        raise Invalid("At least one field.")
    with db.connect() as con:
        con.execute("INSERT INTO dagbog_members (user_id, fields) VALUES (?, ?)"
                    " ON CONFLICT(user_id) DO UPDATE SET fields = excluded.fields",
                    (user_id, json.dumps([f for f in FIELD_ORDER if f in fields])))
    return fields_for(user_id)


def config(user_id: int) -> dict:
    mine = fields_for(user_id)
    return {"fields": [{"key": k, **FIELDS[k]} for k in mine], "tags": tags(), "foods": foods(),
            "today": date.today().isoformat(), "maxDaysBack": MAX_DAYS_BACK}


# ---- entries --------------------------------------------------------------------------------

def _day(value) -> str:
    try:
        d = date.fromisoformat(str(value or ""))
    except ValueError:
        raise Invalid("Ugyldig dato.")
    today = date.today()
    if d > today:
        raise Invalid("Dagen er ikke kommet endnu.")
    if d < today - timedelta(days=MAX_DAYS_BACK):
        raise Invalid("Dagen er for langt tilbage.")
    return d.isoformat()


_COLUMNS = ("mood", "mental", "alcohol")


def _entry_dto(r, own: bool) -> dict:
    out = {"userId": r["user_id"], "day": r["day"],
           **{c: r[c] for c in _COLUMNS},
           "foods": json.loads(r["foods"] or "[]"),
           "tags": json.loads(r["tags"] or "[]"), "updatedAt": r["updated_at"]}
    if own:
        # Only the author ever gets these keys (the privacy rule).
        out["highlight"] = r["highlight"] or ""
        out["hasPhoto"] = bool(r["photo"])
    return out


def get_entry(user_id: int, day: str) -> dict | None:
    day = _day(day)
    with db.connect() as con:
        r = con.execute("SELECT * FROM dagbog_entries WHERE user_id = ? AND day = ?",
                        (user_id, day)).fetchone()
    return _entry_dto(r, own=True) if r else None


def save_entry(user_id: int, body: dict) -> dict:
    """Create or replace this person's entry for a day. Only the fields set
    for the person are taken; a field left empty is stored empty."""
    day = _day(body.get("day"))
    allowed = set(fields_for(user_id))
    values: dict = {}
    for key in SCALES:
        v = body.get(key) if key in allowed else None
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 5):
            raise Invalid(f"{FIELDS[key]['label']} skal være 1-5.")
        values[key] = v
    a = body.get("alcohol") if "alcohol" in allowed else None
    if a is not None and (not isinstance(a, int) or isinstance(a, bool)
                          or not 0 <= a <= FIELDS["alcohol"]["max"]):
        raise Invalid(f"Alkohol skal være 0-{FIELDS['alcohol']['max']} genstande.")
    values["alcohol"] = a
    chosen = _picked(body, allowed, "tags", tags(), "Ukendt aktivitet")
    eaten = _picked(body, allowed, "foods", foods(), "Ukendt madtype")
    highlight = ""
    if "highlight" in allowed:
        highlight = str(body.get("highlight") or "").strip()
        if len(highlight) > MAX_HIGHLIGHT:
            raise Invalid(f"Teksten er for lang (højst {MAX_HIGHLIGHT} tegn).")
    now = db.utcnow()
    with db.connect() as con:
        con.execute(
            "INSERT INTO dagbog_entries (user_id, day, mood, mental, alcohol, foods,"
            " tags, highlight, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(user_id, day) DO UPDATE SET mood=excluded.mood,"
            " mental=excluded.mental, alcohol=excluded.alcohol, foods=excluded.foods,"
            " tags=excluded.tags, highlight=excluded.highlight, updated_at=excluded.updated_at",
            (user_id, day, *(values[c] for c in _COLUMNS),
             json.dumps(eaten, ensure_ascii=False), json.dumps(chosen, ensure_ascii=False),
             highlight, now, now))
    return get_entry(user_id, day)


def _picked(body: dict, allowed: set, field: str, known_list: list[str], unknown: str) -> list[str]:
    """The chosen items of a list field, spelled as in the list, no repeats."""
    if field not in allowed:
        return []
    known = {t.lower(): t for t in known_list}
    out: list[str] = []
    for t in body.get(field) or []:
        k = str(t).lower()
        if k not in known:
            raise Invalid(f"{unknown}: {t}")
        if known[k] not in out:
            out.append(known[k])
    return out


def delete_entry(user_id: int, day: str) -> None:
    day = _day(day)
    remove_photo(user_id, day, missing_ok=True)
    with db.connect() as con:
        con.execute("DELETE FROM dagbog_entries WHERE user_id = ? AND day = ?", (user_id, day))


def family(frm: str, to: str) -> dict:
    """Everyone's ratings and tags for a period - never a highlight or a
    photo, not even the asker's own (the overview has no place for them)."""
    try:
        a, b = date.fromisoformat(frm), date.fromisoformat(to)
    except ValueError:
        raise Invalid("Ugyldig periode.")
    if b < a or (b - a).days >= MAX_RANGE:
        raise Invalid(f"Perioden skal være 1-{MAX_RANGE} dage.")
    with db.connect() as con:
        members = con.execute("SELECT id, username, role FROM users ORDER BY id").fetchall()
        rows = con.execute(
            "SELECT * FROM dagbog_entries WHERE day BETWEEN ? AND ? ORDER BY day, user_id",
            (a.isoformat(), b.isoformat())).fetchall()
    return {"from": a.isoformat(), "to": b.isoformat(),
            "members": [{"id": m["id"], "username": m["username"],
                         "fields": fields_for(m["id"])} for m in members],
            "entries": [_entry_dto(r, own=False) for r in rows]}


def filled_days(user_id: int, frm: str, to: str) -> list[str]:
    with db.connect() as con:
        return [r[0] for r in con.execute(
            "SELECT day FROM dagbog_entries WHERE user_id = ? AND day BETWEEN ? AND ? ORDER BY day",
            (user_id, frm, to))]


# ---- the photo (private) ----------------------------------------------------------------------

def photos_dir(user_id: int) -> Path:
    return db.data_dir() / "dagbog" / "photos" / str(int(user_id))


def set_photo(user_id: int, day: str, data: bytes) -> dict:
    day = _day(day)
    if "highlight" not in fields_for(user_id):
        raise Invalid("Dagens højdepunkt er slået fra for dig.")
    if len(data) > fm.MAX_PHOTO_BYTES:
        raise Invalid(f"Billedet er større end {fm.MAX_PHOTO_BYTES // 1024 // 1024} MB.")
    try:
        full, _thumb, _w, _h, _taken, ext = fm._process(data)   # upright, resized, EXIF gone
    except fm.Invalid as exc:
        raise Invalid(str(exc))
    with db.connect() as con:
        r = con.execute("SELECT id, photo FROM dagbog_entries WHERE user_id = ? AND day = ?",
                        (user_id, day)).fetchone()
        if not r:
            now = db.utcnow()
            con.execute("INSERT INTO dagbog_entries (user_id, day, tags, foods, highlight, created_at,"
                        " updated_at) VALUES (?, ?, '[]', '[]', '', ?, ?)", (user_id, day, now, now))
    remove_photo(user_id, day, missing_ok=True)
    folder = photos_dir(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{day}{ext}"
    (folder / name).write_bytes(full)
    with db.connect() as con:
        con.execute("UPDATE dagbog_entries SET photo = ?, updated_at = ? WHERE user_id = ? AND day = ?",
                    (name, db.utcnow(), user_id, day))
    return get_entry(user_id, day)


def photo_file(user_id: int, day: str) -> Path:
    """The author's own photo - user_id is always the signed-in person."""
    day = _day(day)
    with db.connect() as con:
        r = con.execute("SELECT photo FROM dagbog_entries WHERE user_id = ? AND day = ?",
                        (user_id, day)).fetchone()
    if not r or not r["photo"]:
        raise NotFound("Intet billede.")
    path = photos_dir(user_id) / r["photo"]
    if not path.is_file():
        raise NotFound("Billedfilen mangler.")
    return path


def remove_photo(user_id: int, day: str, missing_ok: bool = False) -> None:
    day = _day(day)
    with db.connect() as con:
        r = con.execute("SELECT photo FROM dagbog_entries WHERE user_id = ? AND day = ?",
                        (user_id, day)).fetchone()
        if not r or not r["photo"]:
            if missing_ok:
                return
            raise NotFound("Intet billede.")
        con.execute("UPDATE dagbog_entries SET photo = NULL WHERE user_id = ? AND day = ?",
                    (user_id, day))
    (photos_dir(user_id) / r["photo"]).unlink(missing_ok=True)


def forget_user(user_id: int) -> None:
    """After an account is deleted: its rows went by ON DELETE CASCADE; its
    private photos go here."""
    shutil.rmtree(photos_dir(user_id), ignore_errors=True)


# ---- the administrator's view -------------------------------------------------------------------

def admin_settings() -> dict:
    with db.connect() as con:
        users = con.execute("SELECT id, username, role FROM users ORDER BY id").fetchall()
    return {"tags": tags(), "foods": foods(),
            "fields": [{"key": k, "label": FIELDS[k]["label"], "kind": FIELDS[k]["kind"]}
                       for k in FIELD_ORDER],
            "members": [{"id": u["id"], "username": u["username"], "role": u["role"],
                         "fields": fields_for(u["id"])} for u in users]}
