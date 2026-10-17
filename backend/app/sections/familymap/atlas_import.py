"""Bring Alf's Atlas over from SLQ Companion (FamilyLog 0.3.2).

Søren changed his mind about starting empty: everything in the old Atlas
comes over - places (the family's own, OSM ones and every edit), reviews,
photos, wishlists and the town names Spørg Alf uses.

    python -m app.import_atlas /tmp/atlas/atlas.db --photos /tmp/atlas/photos           (dry run)
    python -m app.import_atlas /tmp/atlas/atlas.db --photos /tmp/atlas/photos --apply

* The source is a copy of SLQ's app.db; it is only read.
* People are matched by username (case does not matter). A review whose
  author has no FamilyLog account yet comes in as "(slettet bruger)";
  run again once the account exists and it is given to them. Wishlists of
  people without an account wait for that run too.
* A dry run (the default) does the whole import inside a transaction and
  rolls it back, so its counts are exactly what --apply will do. --apply
  first saves a copy of FamilyLog's database under /data/backups.
* Running it again is safe: what came over before is recognised
  (fm_import_map) and not doubled. A place changed in SLQ since the last run
  is updated, unless it was changed in FamilyLog later. An OSM place that
  FamilyLog already has (its own OSM import) is merged, not doubled.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.core import db

from . import familymap as fm

PLACE_COLS = ("name", "category", "address", "lat", "lng", "website", "notes", "source", "source_id",
              "web_rating", "web_rating_count", "web_rating_at", "created_at", "updated_at", "locked",
              "extra")
REVIEW_COLS = ("visited_on", "who", "overall", "fields", "text", "again", "created_at", "updated_at")
PHOTO_COLS = ("width", "height", "taken_at", "description", "created_at", "describe_state",
              "describe_error")


@dataclass
class Report:
    places_new: int = 0
    places_merged: int = 0
    places_updated: int = 0
    places_same: int = 0
    reviews_new: int = 0
    reviews_known: int = 0
    reviews_given: int = 0
    reviews_no_author: int = 0
    photos_new: int = 0
    photos_known: int = 0
    photos_missing: int = 0
    wishes_new: int = 0
    wishes_waiting: int = 0
    towns_new: int = 0
    matched: dict = field(default_factory=dict)
    unmatched: list = field(default_factory=list)
    skipped_settings: list = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"Places:   {self.places_new} new, {self.places_merged} merged with FamilyLog's own OSM places, "
               f"{self.places_updated} updated, {self.places_same} already up to date",
               f"Reviews:  {self.reviews_new} new, {self.reviews_known} already here"
               + (f", {self.reviews_given} now given to their author" if self.reviews_given else "")
               + (f" ({self.reviews_no_author} new ones without a FamilyLog author yet)" if self.reviews_no_author else ""),
               f"Photos:   {self.photos_new} new, {self.photos_known} already here"
               + (f", {self.photos_missing} MISSING in the photos folder (left out)" if self.photos_missing else ""),
               f"Wishlist: {self.wishes_new} new" + (f", {self.wishes_waiting} waiting for an account" if self.wishes_waiting else ""),
               f"Towns:    {self.towns_new} new (Spørg Alf's town names)"]
        if self.matched:
            out.append("People:   " + ", ".join(f"{k} -> {v}" for k, v in sorted(self.matched.items())))
        if self.unmatched:
            out.append("No FamilyLog account (make one with the same username and run again): "
                       + ", ".join(sorted(self.unmatched)))
        if self.skipped_settings:
            out.append("Not copied (FamilyLog has its own): Atlas settings " + ", ".join(sorted(self.skipped_settings)))
        return out


class ImportError_(RuntimeError):
    pass


def _open_source(path: Path) -> sqlite3.Connection:
    """Read from a private copy: the file (and a -wal next to it) may sit in
    a folder this user cannot write to, which SQLite needs for a WAL
    database even when only reading."""
    if not path.is_file():
        raise ImportError_(f"No such file: {path}")
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="atlas-import-"))
    copy = tmp / "source.db"
    shutil.copy2(path, copy)
    for ext in ("-wal", "-shm"):
        side = path.with_name(path.name + ext)
        if side.is_file():
            shutil.copy2(side, tmp / ("source.db" + ext))
    try:
        con = sqlite3.connect(copy)
        con.execute("SELECT 1 FROM sqlite_master").fetchone()
    except sqlite3.DatabaseError as exc:
        raise ImportError_(f"{path} is not a database SQLite can read ({exc}).")
    con.row_factory = sqlite3.Row
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    need = {"users", "fm_places", "fm_reviews", "fm_photos"}
    if not need <= tables:
        raise ImportError_(f"{path} is not an SLQ Companion database with Alf's Atlas "
                           f"(missing: {', '.join(sorted(need - tables))}).")
    return con


def _cols(con, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _pick(row: sqlite3.Row, cols: tuple, have: set[str]) -> dict:
    return {c: row[c] for c in cols if c in have}


def run(source: Path, photos: Path | None, apply: bool, out=print) -> Report:
    src = _open_source(source)
    rep = Report()
    dst_photos = fm.photos_dir()
    to_copy: list[tuple[Path, Path]] = []
    with db.connect() as con:
        try:
            _import(src, con, photos, dst_photos, rep, to_copy)
            if apply:
                dst_photos.mkdir(parents=True, exist_ok=True)
                for a, b in to_copy:
                    shutil.copy2(a, b)
            else:
                con.rollback()
        except Exception:
            con.rollback()
            raise
    src.close()
    return rep


def _import(src, con, photos: Path | None, dst_photos: Path, rep: Report, to_copy: list) -> None:
    con.execute("BEGIN")
    # ---- people ---------------------------------------------------------------------------
    ours = {r["username"].lower(): r["id"] for r in con.execute("SELECT id, username FROM users")}
    users: dict[int, int | None] = {}
    names: dict[int, str] = {}
    for r in src.execute("SELECT id, username FROM users"):
        names[r["id"]] = r["username"]
        users[r["id"]] = ours.get(r["username"].lower())
    used = {r[0] for r in src.execute("SELECT DISTINCT user_id FROM fm_reviews WHERE user_id IS NOT NULL")}
    if "fm_wishlist" in {x[0] for x in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        used |= {r[0] for r in src.execute("SELECT DISTINCT user_id FROM fm_wishlist")}
    for uid in used:
        if uid in names:
            if users.get(uid):
                rep.matched[names[uid]] = names[uid]
            else:
                rep.unmatched.append(names[uid])

    def mapped(kind: str, sid: int) -> sqlite3.Row | None:
        return con.execute("SELECT dst_id, src_user FROM fm_import_map WHERE kind=? AND src_id=?",
                           (kind, sid)).fetchone()

    def remember(kind: str, sid: int, did: int, user: str | None = None) -> None:
        con.execute("INSERT OR REPLACE INTO fm_import_map (kind, src_id, dst_id, src_user) VALUES (?,?,?,?)",
                    (kind, sid, did, user))

    # ---- places ---------------------------------------------------------------------------
    s_cols, d_cols = _cols(src, "fm_places"), _cols(con, "fm_places")
    cols = tuple(c for c in PLACE_COLS if c in s_cols and c in d_cols)
    place_map: dict[int, int] = {}
    for p in src.execute("SELECT * FROM fm_places ORDER BY id"):
        vals = _pick(p, cols, s_cols)
        vals["created_by"] = users.get(p["created_by"]) if "created_by" in s_cols else None
        m = mapped("place", p["id"])
        target = None
        if m and con.execute("SELECT 1 FROM fm_places WHERE id=?", (m["dst_id"],)).fetchone():
            target = m["dst_id"]
        elif p["source_id"] is not None:
            r = con.execute("SELECT id FROM fm_places WHERE source=? AND source_id=?",
                            (p["source"], p["source_id"])).fetchone()
            if r:
                target = r["id"]
                rep.places_merged += 1
        if target is None:
            keys = list(vals)
            cur = con.execute(f"INSERT INTO fm_places ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                              [vals[k] for k in keys])
            target = cur.lastrowid
            rep.places_new += 1
        else:
            d = con.execute("SELECT * FROM fm_places WHERE id=?", (target,)).fetchone()
            src_locked = bool(vals.get("locked"))
            dst_locked = bool(d["locked"]) if "locked" in d.keys() else False
            newer = (vals.get("updated_at") or "") > (d["updated_at"] or "")
            wins = (src_locked and not dst_locked) or (newer and not (dst_locked and not src_locked))
            changed = any(d[k] != vals[k] for k in cols if k not in ("created_at",))
            if wins and changed:
                keys = [k for k in cols if k != "created_at"]
                con.execute(f"UPDATE fm_places SET {', '.join(f'{k}=?' for k in keys)} WHERE id=?",
                            [vals[k] for k in keys] + [target])
                if m:
                    rep.places_updated += 1
            elif m:
                rep.places_same += 1
        remember("place", p["id"], target)
        place_map[p["id"]] = target

    # ---- reviews ---------------------------------------------------------------------------
    s_cols, d_cols = _cols(src, "fm_reviews"), _cols(con, "fm_reviews")
    cols = tuple(c for c in REVIEW_COLS if c in s_cols and c in d_cols)
    review_map: dict[int, int] = {}
    for r in src.execute("SELECT * FROM fm_reviews ORDER BY id"):
        author = users.get(r["user_id"])
        m = mapped("review", r["id"])
        if m and con.execute("SELECT 1 FROM fm_reviews WHERE id=?", (m["dst_id"],)).fetchone():
            rep.reviews_known += 1
            review_map[r["id"]] = m["dst_id"]
            # An author who has an account now gets the review back.
            if author and con.execute("SELECT user_id FROM fm_reviews WHERE id=?",
                                      (m["dst_id"],)).fetchone()[0] is None:
                con.execute("UPDATE fm_reviews SET user_id=? WHERE id=?", (author, m["dst_id"]))
                rep.reviews_given += 1
            continue
        vals = _pick(r, cols, s_cols)
        vals["place_id"] = place_map[r["place_id"]]
        vals["user_id"] = author
        keys = list(vals)
        cur = con.execute(f"INSERT INTO fm_reviews ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                          [vals[k] for k in keys])
        remember("review", r["id"], cur.lastrowid, names.get(r["user_id"]))
        review_map[r["id"]] = cur.lastrowid
        rep.reviews_new += 1
        if author is None:
            rep.reviews_no_author += 1

    # ---- photos ---------------------------------------------------------------------------
    s_cols, d_cols = _cols(src, "fm_photos"), _cols(con, "fm_photos")
    cols = tuple(c for c in PHOTO_COLS if c in s_cols and c in d_cols)
    taken = {x.name for x in dst_photos.iterdir()} if dst_photos.is_dir() else set()
    for ph in src.execute("SELECT * FROM fm_photos ORDER BY id"):
        m = mapped("photo", ph["id"])
        if m and con.execute("SELECT 1 FROM fm_photos WHERE id=?", (m["dst_id"],)).fetchone():
            rep.photos_known += 1
            continue
        names_ = [Path(ph["file"]).name, Path(ph["thumb"]).name]
        files = [(photos / n) if photos else None for n in names_]
        if not all(f is not None and f.is_file() for f in files):
            rep.photos_missing += 1
            continue
        new = []
        for f, n in zip(files, names_):
            stem, ext = Path(n).stem, Path(n).suffix
            k, cand = 1, n
            while cand in taken:                 # never overwrite a photo already here
                cand, k = f"{stem}_{k}{ext}", k + 1
            taken.add(cand)
            to_copy.append((f, dst_photos / cand))
            new.append(cand)
        vals = _pick(ph, cols, s_cols)
        vals.update(review_id=review_map[ph["review_id"]], file=new[0], thumb=new[1])
        keys = list(vals)
        cur = con.execute(f"INSERT INTO fm_photos ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                          [vals[k] for k in keys])
        remember("photo", ph["id"], cur.lastrowid)
        rep.photos_new += 1

    # ---- wishlists, towns, settings ---------------------------------------------------------
    s_tables = {x[0] for x in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "fm_wishlist" in s_tables:
        for w in src.execute("SELECT * FROM fm_wishlist"):
            uid = users.get(w["user_id"])
            if uid is None:
                rep.wishes_waiting += 1
                continue
            cur = con.execute("INSERT OR IGNORE INTO fm_wishlist (user_id, place_id, created_at) VALUES (?,?,?)",
                              (uid, place_map[w["place_id"]], w["created_at"]))
            rep.wishes_new += cur.rowcount
    if "fm_localities" in s_tables:
        for t in src.execute("SELECT osm_id, name, kind, lat, lng, names FROM fm_localities"):
            cur = con.execute("INSERT OR IGNORE INTO fm_localities (osm_id, name, kind, lat, lng, names)"
                              " VALUES (?,?,?,?,?,?)", tuple(t))
            rep.towns_new += cur.rowcount
    if "fm_settings" in s_tables:
        rep.skipped_settings = [r[0] for r in src.execute("SELECT key FROM fm_settings")]


def backup() -> Path:
    from datetime import datetime
    folder = db.data_dir() / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"app-{datetime.now():%Y%m%d-%H%M%S}-before-atlas-import.db"
    with db.connect() as con:
        out = sqlite3.connect(path)
        con.backup(out)
        out.close()
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.import_atlas",
                                 description="Import Alf's Atlas from an SLQ Companion database copy.")
    ap.add_argument("source", type=Path, help="copy of SLQ's app.db")
    ap.add_argument("--photos", type=Path, help="SLQ's familymap/photos folder")
    ap.add_argument("--apply", action="store_true", help="really import (default: a dry run)")
    a = ap.parse_args(argv)
    try:
        db.init_db()
        if a.photos is not None and not a.photos.is_dir():
            raise ImportError_(f"No such folder: {a.photos}")
        if a.apply:
            print(f"Backup of FamilyLog's database: {backup()}")
        rep = run(a.source, a.photos, a.apply)
    except ImportError_ as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 2
    print(("IMPORTED" if a.apply else "DRY RUN - nothing changed. Add --apply to import.") + "\n")
    for line in rep.lines():
        print(line)
    if a.photos is None:
        print("\nNo --photos folder given: photos are left out.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
