"""Dagbog (FamilyLog 0.2.0): each person rates their day.

One entry per person per day: mood (1-5) and mental readiness ("mentalt
overskud", 1-10 since 0.2.2), what was eaten (food categories), alcohol (units),
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
    "mood": {"label": "Humør", "low": "Rigtig skidt", "high": "Rigtig godt", "max": 5,
             "faces": ["😞", "🙁", "😐", "🙂", "😄"]},
    "mental": {"label": "Mentalt overskud", "low": "Intet overskud", "high": "Masser af overskud",
               "max": 10},
}
# Amounts as sliders (0.3.8, Søren): motion in half hours, sodavand and
# alkohol in glasses/units. Stored as plain numbers (motion in minutes).
SLIDERS = {
    "exercise": {"label": "Motion", "min": 0, "max": 480, "step": 30, "unit": "min", "format": "hours",
                 "hint": "Hvor længe var du i gang i dag?"},
    "soda": {"label": "Sodavand", "min": 0, "max": 10, "step": 1, "unit": "glas"},
    "alcohol": {"label": "Alkohol", "min": 0, "max": 20, "step": 1, "unit": "genstande"},
}
SICK = ["Forkølet", "Feber", "Hoste", "Ondt i halsen", "Mavepine", "Hovedpine", "Migræne",
        "Allergi", "Skadet", "Ondt i ryggen", "Andet"]
MAX_SICK_NOTE = 200
FIELDS = {
    **{k: {"kind": "scale", **v} for k, v in SCALES.items()},
    "exercise": {"kind": "slider", **SLIDERS["exercise"]},
    "foods": {"kind": "foods", "label": "Mad", "hint": "Hvad spiste du i dag?"},
    "soda": {"kind": "slider", **SLIDERS["soda"]},
    "alcohol": {"kind": "slider", **SLIDERS["alcohol"]},
    "tags": {"kind": "tags", "label": "Aktiviteter", "hint": "Hvad lavede du i dag?"},
    "sick": {"kind": "sick", "label": "Sygdom og skader", "hint": "Var du syg eller kom til skade?",
             "options": SICK},
    "highlight": {"kind": "private", "label": "Dagens højdepunkt"},
}
FIELD_ORDER = list(FIELDS)
DEFAULT_TAGS = ["Skole/arbejde", "Sport", "Computer", "Gaming", "Fjernsyn", "Mobil",
                "Vedligehold af hus og have", "Rengøring", "Madlavning", "Indkøb",
                "Børnepasning", "Venner", "Familie", "Udenfor", "Læsning", "Hobby", "Fri", "Syg"]
# Sodavand left the food list in 0.3.8 - it has its own slider now.
DEFAULT_FOODS = ["Hjemmelavet", "Fastfood", "Takeaway", "Restaurant", "Kage", "Chips",
                 "Slik", "Is", "Frugt og grønt", "Morgenmad", "Madpakke", "Vitaminer"]
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


_COLUMNS = ("mood", "mental", "alcohol", "exercise", "soda")


def _entry_dto(r, own: bool) -> dict:
    out = {"userId": r["user_id"], "day": r["day"],
           **{c: r[c] for c in _COLUMNS},
           "foods": json.loads(r["foods"] or "[]"),
           "tags": json.loads(r["tags"] or "[]"),
           "sick": json.loads(r["sick"] or "[]"), "sickNote": r["sick_note"] or "",
           "updatedAt": r["updated_at"]}
    shared = bool(r["shared"]) if "shared" in r.keys() else False
    if own or shared:
        # 0.3.9 (Søren): the family sees the text and the photo too - of a
        # day its author shares (every new day does; days written while it
        # was private stay private until the author shares them).
        out["highlight"] = r["highlight"] or ""
        out["hasPhoto"] = bool(r["photo"])
    if own:
        out["shared"] = shared
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
        top = SCALES[key]["max"]
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= top):
            raise Invalid(f"{FIELDS[key]['label']} skal være 1-{top}.")
        values[key] = v
    for key, s in SLIDERS.items():
        v = body.get(key) if key in allowed else None
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not s["min"] <= v <= s["max"]
                              or (v - s["min"]) % s["step"]):
            unit = "minutter i halve timer" if s.get("format") == "hours" else s["unit"]
            raise Invalid(f"{s['label']} skal være {s['min']}-{s['max']} {unit}.")
        values[key] = v
    sick = _picked(body, allowed, "sick", SICK, "Ukendt sygdom")
    sick_note = str(body.get("sickNote") or "").strip() if "sick" in allowed else ""
    if len(sick_note) > MAX_SICK_NOTE:
        raise Invalid(f"Sygdomsnoten er for lang (højst {MAX_SICK_NOTE} tegn).")
    chosen = _picked(body, allowed, "tags", tags(), "Ukendt aktivitet")
    eaten = _picked(body, allowed, "foods", foods(), "Ukendt madtype")
    shared = body.get("shared", True)
    if not isinstance(shared, bool):
        raise Invalid("Deling skal være til eller fra.")
    highlight = ""
    if "highlight" in allowed:
        highlight = str(body.get("highlight") or "").strip()
        if len(highlight) > MAX_HIGHLIGHT:
            raise Invalid(f"Teksten er for lang (højst {MAX_HIGHLIGHT} tegn).")
    now = db.utcnow()
    with db.connect() as con:
        con.execute(
            "INSERT INTO dagbog_entries (user_id, day, mood, mental, alcohol, exercise, soda, foods,"
            " tags, sick, sick_note, highlight, shared, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(user_id, day) DO UPDATE SET mood=excluded.mood,"
            " mental=excluded.mental, alcohol=excluded.alcohol, exercise=excluded.exercise,"
            " soda=excluded.soda, foods=excluded.foods, tags=excluded.tags, sick=excluded.sick,"
            " sick_note=excluded.sick_note, highlight=excluded.highlight, shared=excluded.shared,"
            " updated_at=excluded.updated_at",
            (user_id, day, *(values[c] for c in _COLUMNS),
             json.dumps(eaten, ensure_ascii=False), json.dumps(chosen, ensure_ascii=False),
             json.dumps(sick, ensure_ascii=False), sick_note, highlight, int(shared), now, now))
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


FAMILY_ROLES = ("admin", "family")


def is_family(user: dict) -> bool:
    """0.3.7 (Søren): the family is the family accounts and the administrator
    ("admin er automatisk familie"); a user account is not."""
    return user.get("role") in FAMILY_ROLES


def family(frm: str, to: str) -> dict:
    """The family's ratings and tags for a period - the administrator and the
    family accounts only (0.3.7) - never a highlight or a photo, not even
    the asker's own (the overview has no place for them)."""
    try:
        a, b = date.fromisoformat(frm), date.fromisoformat(to)
    except ValueError:
        raise Invalid("Ugyldig periode.")
    if b < a or (b - a).days >= MAX_RANGE:
        raise Invalid(f"Perioden skal være 1-{MAX_RANGE} dage.")
    with db.connect() as con:
        members = con.execute("SELECT id, username, role FROM users WHERE role IN (?, ?) ORDER BY id",
                              FAMILY_ROLES).fetchall()
        rows = con.execute(
            "SELECT e.* FROM dagbog_entries e JOIN users u ON u.id = e.user_id"
            " WHERE e.day BETWEEN ? AND ? AND u.role IN (?, ?) ORDER BY e.day, e.user_id",
            (a.isoformat(), b.isoformat(), *FAMILY_ROLES)).fetchall()
    return {"from": a.isoformat(), "to": b.isoformat(),
            "members": [{"id": m["id"], "username": m["username"],
                         "fields": fields_for(m["id"])} for m in members],
            "entries": [_entry_dto(r, own=False) for r in rows]}


class Forbidden(PermissionError):
    pass


def _may_see(viewer: dict, user_id: int) -> dict:
    """One family member looking at another's days: both must be family.
    Returns the person looked at."""
    with db.connect() as con:
        r = con.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if r is None:
        raise NotFound("Den person findes ikke.")
    if viewer["id"] != user_id and not (is_family(viewer) and r["role"] in FAMILY_ROLES):
        raise Forbidden("Kun familien kan se hinandens dagbog.")
    return {"id": r["id"], "username": r["username"]}


def person_days(viewer: dict, user_id: int, before: str | None = None, limit: int = 20) -> dict:
    """One person's days, newest first, `limit` at a time going back (0.3.9:
    the family's overview per person, as far back as there are days)."""
    who = _may_see(viewer, user_id)
    limit = max(1, min(int(limit), 60))
    params: list = [user_id]
    where = "user_id = ?"
    if before:
        where += " AND day < ?"
        params.append(_day(before))
    with db.connect() as con:
        rows = con.execute(f"SELECT * FROM dagbog_entries WHERE {where} ORDER BY day DESC LIMIT ?",
                           params + [limit + 1]).fetchall()
        first = con.execute("SELECT MIN(day), COUNT(*) FROM dagbog_entries WHERE user_id = ?",
                            (user_id,)).fetchone()
    own = viewer["id"] == user_id
    return {"person": who, "own": own, "fields": fields_for(user_id),
            "entries": [_entry_dto(r, own=own) for r in rows[:limit]],
            "more": len(rows) > limit, "firstDay": first[0], "total": first[1]}


def month_moods(viewer: dict, user_id: int, month: str) -> dict:
    """A month's mood per day, for the calendar on a person's page."""
    _may_see(viewer, user_id)
    try:
        start = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise Invalid("Ugyldig måned.")
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    with db.connect() as con:
        rows = con.execute("SELECT day, mood FROM dagbog_entries WHERE user_id = ? AND day BETWEEN ? AND ?",
                           (user_id, start.isoformat(), end.isoformat())).fetchall()
    return {"month": month, "days": {r["day"]: r["mood"] for r in rows}}


WEEK_FROM = 7      # days filled in before an amount is shown per week


def stats(viewer: dict, user_id: int, frm: str | None, to: str | None) -> dict:
    """One person's statistics for a period (0.3.9): how much is filled in,
    averages, months and weekdays, what they do and eat most, and which
    activities, foods and habits go with a better or worse mood."""
    from collections import Counter, defaultdict
    from statistics import mean
    who = _may_see(viewer, user_id)
    params: list = [user_id]
    where = "user_id = ?"
    if frm:
        where += " AND day >= ?"
        params.append(_day(frm))
    if to:
        where += " AND day <= ?"
        params.append(_day(to))
    with db.connect() as con:
        rows = con.execute(f"SELECT * FROM dagbog_entries WHERE {where} ORDER BY day", params).fetchall()
        started = con.execute("SELECT MIN(day) FROM dagbog_entries WHERE user_id = ?", (user_id,)).fetchone()[0]
    entries = [_entry_dto(r, own=True) for r in rows]
    out: dict = {"person": who, "from": frm, "to": to, "days": len(entries), "fields": fields_for(user_id)}
    if not entries:
        return out
    # The share of days written counts from the period's start - or from the
    # person's first day, when they began later (0.3.10: 2 days of 2 is 100%,
    # not 7% of 30).
    first = max(date.fromisoformat(frm), date.fromisoformat(started)) if frm else date.fromisoformat(started)
    last = min(date.fromisoformat(to) if to else date.today(), date.today())
    span = max(1, (last - first).days + 1)

    def amount(key):
        # Motion, alcohol, sodavand over the days it was filled in (a day left
        # empty is not a day of none). A week's figure only from 7 such days
        # on (0.3.10): two days, one of them 8 hours, are not "31,5 t a week".
        v = [e[key] for e in entries if e.get(key) is not None]
        if not v:
            return None
        return {"total": sum(v), "days": len(v), "perDay": round(mean(v), 1),
                "perWeek": round(mean(v) * 7, 1) if len(v) >= WEEK_FROM else None}

    def avg(key):
        v = [e[key] for e in entries if e.get(key) is not None]
        return round(mean(v), 1) if v else None

    out.update({
        "span": span, "coverage": round(len(entries) / span * 100),
        "mood": avg("mood"), "mental": avg("mental"),
        "amounts": {k: amount(k) for k in ("exercise", "alcohol", "soda")},
        "sickDays": sum(1 for e in entries if e.get("sick")),
    })
    # Months: mood, overskud, motion hours, alcohol.
    by_month: dict[str, list] = defaultdict(list)
    for e in entries:
        by_month[e["day"][:7]].append(e)
    out["months"] = [{
        "month": m,
        "days": len(es),
        "mood": round(mean([e["mood"] for e in es if e["mood"] is not None]), 1)
        if any(e["mood"] is not None for e in es) else None,
        "mental": round(mean([e["mental"] for e in es if e["mental"] is not None]), 1)
        if any(e["mental"] is not None for e in es) else None,
        "exerciseHours": round(sum(e.get("exercise") or 0 for e in es) / 60, 1),
        "alcohol": sum(e["alcohol"] or 0 for e in es),
    } for m, es in sorted(by_month.items())]
    # Weekdays (Monday first): mood.
    wd: dict[int, list] = defaultdict(list)
    for e in entries:
        if e["mood"] is not None:
            wd[date.fromisoformat(e["day"]).weekday()].append(e["mood"])
    out["weekdays"] = [round(mean(wd[i]), 1) if wd.get(i) else None for i in range(7)]
    tags_c = Counter(t for e in entries for t in e["tags"])
    foods_c = Counter(t for e in entries for t in e["foods"])
    sick_c = Counter(t for e in entries for t in e.get("sick") or [])
    out["topTags"] = [{"name": n, "days": c} for n, c in tags_c.most_common(8)]
    out["topFoods"] = [{"name": n, "days": c} for n, c in foods_c.most_common(8)]
    out["topSick"] = [{"name": n, "days": c} for n, c in sick_c.most_common(5)]
    # What goes with a better or worse mood: days with vs. without, when
    # there are at least 3 of each.
    rated = [e for e in entries if e["mood"] is not None]
    found = []

    def compare(label: str, kind: str, has) -> None:
        yes = [e["mood"] for e in rated if has(e)]
        no = [e["mood"] for e in rated if not has(e)]
        if len(yes) >= 3 and len(no) >= 3:
            d = mean(yes) - mean(no)
            if abs(d) >= 0.3:
                found.append({"label": label, "kind": kind, "with": round(mean(yes), 1),
                              "without": round(mean(no), 1), "diff": round(d, 1), "days": len(yes)})
    for t in tags_c:
        compare(t, "Aktivitet", lambda e, t=t: t in e["tags"])
    for f in foods_c:
        compare(f, "Mad", lambda e, f=f: f in e["foods"])
    compare("Motion 1 time eller mere", "Vane", lambda e: (e.get("exercise") or 0) >= 60)
    compare("Alkohol", "Vane", lambda e: (e["alcohol"] or 0) > 0)
    compare("Sodavand", "Vane", lambda e: (e.get("soda") or 0) > 0)
    compare("Syg eller skadet", "Sundhed", lambda e: bool(e.get("sick")))
    found.sort(key=lambda x: -abs(x["diff"]))
    out["links"] = found[:8]
    # Streaks of days in a row with something filled in.
    days = sorted(date.fromisoformat(e["day"]) for e in entries)
    best = cur = 1
    for a, b in zip(days, days[1:]):
        cur = cur + 1 if (b - a).days == 1 else 1
        best = max(best, cur)
    out["bestStreak"] = best
    return out


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


def photo_file(user_id: int, day: str, viewer: dict | None = None) -> Path:
    """A day's photo: the author's own, or (0.3.9) a family member's from a
    day they share - for someone in the family."""
    day = _day(day)
    if viewer is not None and viewer["id"] != user_id:
        _may_see(viewer, user_id)
    with db.connect() as con:
        r = con.execute("SELECT photo, shared FROM dagbog_entries WHERE user_id = ? AND day = ?",
                        (user_id, day)).fetchone()
    if not r or not r["photo"] or (viewer is not None and viewer["id"] != user_id and not r["shared"]):
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
