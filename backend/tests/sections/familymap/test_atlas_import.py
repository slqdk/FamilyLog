"""0.3.2: Alf's Atlas from SLQ Companion - places, reviews, photos,
wishlists and towns; people by username; a dry run changes nothing; a
second run doubles nothing. All data here is made up."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

NOW = "2026-09-01T10:00:00+00:00"
LATER = "2026-10-01T10:00:00+00:00"


def _slq(tmp: Path) -> tuple[Path, Path]:
    """A small SLQ database with the Atlas tables, and its photos folder."""
    from app.sections.familymap import _m001_places, _m002_osm, _m003_wishlist, _m004_ask
    path = tmp / "slq.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,"
                " password_hash TEXT NOT NULL, role TEXT, prefs TEXT, profile TEXT, created_at TEXT)")
    for m in (_m001_places, _m002_osm, _m003_wishlist, _m004_ask):
        m(con)
    con.executemany("INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?,?,?,?,?)",
                    [(1, "admin", "x", "admin", NOW), (5, "Mor", "x", "family", NOW), (6, "kusine", "x", "family", NOW)])
    con.executemany(
        "INSERT INTO fm_places (id, name, category, address, lat, lng, source, source_id, created_by,"
        " created_at, updated_at, locked, extra) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(10, "Testparkens Legeplads", "playground", "Testvej 1", 55.2, 9.3, "family", None, 5, NOW, NOW, 0, "{}"),
         (11, "Prøvebadet", "activity", "", 55.3, 9.4, "osm", "way/123", None, NOW, LATER, 1, "{}"),
         (12, "Fantasicaféen", "cafe", "", 55.1, 9.2, "osm", "node/9", None, NOW, NOW, 0, "{}")])
    con.executemany(
        "INSERT INTO fm_reviews (id, place_id, user_id, visited_on, who, overall, fields, text, again,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(20, 10, 5, "2026-08-02", "hele familien", 5, json.dumps({"rent": 4}), "Super sted", 1, NOW, NOW),
         (21, 11, 6, "2026-08-03", "", 3, "{}", "Koldt vand", 0, NOW, NOW)])
    con.executemany("INSERT INTO fm_photos (id, review_id, file, thumb, width, height, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    [(30, 20, "aaaa1111.jpg", "aaaa1111_t.jpg", 800, 600, NOW),
                     (31, 21, "bbbb2222.jpg", "bbbb2222_t.jpg", 800, 600, NOW)])
    con.executemany("INSERT INTO fm_wishlist (user_id, place_id, created_at) VALUES (?,?,?)",
                    [(5, 12, NOW), (6, 10, NOW)])
    con.execute("INSERT INTO fm_localities (osm_id, name, kind, lat, lng, names)"
                " VALUES ('node/1', 'Testby', 'town', 55.2, 9.3, '|testby|')")
    con.execute("INSERT INTO fm_settings (key, value) VALUES ('brand', '\"Alf\"')")
    con.commit()
    con.execute("PRAGMA journal_mode = WAL")          # as SLQ keeps it
    con.close()
    photos = tmp / "photos"
    photos.mkdir()
    for n in ("aaaa1111.jpg", "aaaa1111_t.jpg"):           # the second review's photo is missing
        (photos / n).write_bytes(b"\xff\xd8\xff" + n.encode())
    return path, photos


def _count(table: str) -> int:
    from app.core import db
    with db.connect() as con:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_a_dry_run_counts_everything_and_changes_nothing(fresh_db, tmp_path):
    from app.core import auth
    from app.sections.familymap import atlas_import
    auth.create_user("mor", "familie-kode-1", "family")
    src, photos = _slq(tmp_path)
    rep = atlas_import.run(src, photos, apply=False)
    assert (rep.places_new, rep.reviews_new, rep.photos_new, rep.photos_missing) == (3, 2, 1, 1)
    assert (rep.wishes_new, rep.wishes_waiting, rep.towns_new) == (1, 1, 1)
    assert rep.unmatched == ["kusine"] and rep.matched == {"Mor": "Mor"}
    assert rep.skipped_settings == ["brand"]
    assert _count("fm_places") == 0 and _count("fm_import_map") == 0
    from app.sections.familymap import familymap as fm
    assert not fm.photos_dir().exists() or not any(fm.photos_dir().iterdir())


def test_apply_then_again_doubles_nothing_and_gives_reviews_to_new_accounts(fresh_db, tmp_path):
    from app.core import auth, db
    from app.sections.familymap import atlas_import, familymap as fm
    mor = auth.create_user("mor", "familie-kode-1", "family")
    # FamilyLog's own OSM import already has the café: merged, not doubled.
    with db.connect() as con:
        con.execute("INSERT INTO fm_places (name, category, address, source, source_id, created_at, updated_at)"
                    " VALUES ('Fantasicafeen', 'cafe', '', 'osm', 'node/9', ?, ?)", (NOW, NOW))
    src, photos = _slq(tmp_path)
    rep = atlas_import.run(src, photos, apply=True)
    assert (rep.places_new, rep.places_merged) == (2, 1)
    assert _count("fm_places") == 3 and _count("fm_reviews") == 2 and _count("fm_photos") == 1
    with db.connect() as con:
        r = con.execute("SELECT r.user_id, r.text, p.name FROM fm_reviews r JOIN fm_places p ON p.id = r.place_id"
                        " WHERE r.text = 'Super sted'").fetchone()
        assert (r["user_id"], r["name"]) == (mor["id"], "Testparkens Legeplads")
        assert con.execute("SELECT user_id FROM fm_reviews WHERE text='Koldt vand'").fetchone()[0] is None
        ph = con.execute("SELECT file FROM fm_photos").fetchone()["file"]
    assert (fm.photos_dir() / ph).read_bytes().startswith(b"\xff\xd8\xff")
    # The family page shows a review without an account as "(slettet bruger)".
    with db.connect() as con:
        pid = con.execute("SELECT id FROM fm_places WHERE name='Prøvebadet'").fetchone()[0]
    assert fm.reviews_for_place(pid)[0]["author"] == "(slettet bruger)"
    # Run again after making kusine's account: nothing doubles, her review and wish come over.
    kusine = auth.create_user("kusine", "familie-kode-2", "family")
    rep = atlas_import.run(src, photos, apply=True)
    assert (rep.places_new, rep.reviews_new, rep.photos_new) == (0, 0, 0)
    assert rep.places_same == 3 and rep.reviews_given == 1 and rep.wishes_new == 1
    assert _count("fm_places") == 3 and _count("fm_reviews") == 2 and _count("fm_wishlist") == 2
    with db.connect() as con:
        assert con.execute("SELECT user_id FROM fm_reviews WHERE text='Koldt vand'").fetchone()[0] == kusine["id"]


def test_a_place_changed_later_in_slq_is_updated_unless_familylog_changed_it_after(fresh_db, tmp_path):
    from app.core import db
    from app.sections.familymap import atlas_import
    src, photos = _slq(tmp_path)
    atlas_import.run(src, photos, apply=True)
    s = sqlite3.connect(src)
    s.execute("UPDATE fm_places SET notes='Nyt toilet', updated_at='2026-10-10T00:00:00+00:00' WHERE id=10")
    s.execute("UPDATE fm_places SET notes='Fra SLQ', updated_at='2026-10-10T00:00:00+00:00' WHERE id=12")
    s.commit()
    s.close()
    with db.connect() as con:                        # the café was edited in FamilyLog after that
        con.execute("UPDATE fm_places SET notes='Fra FamilyLog', updated_at='2026-10-15T00:00:00+00:00'"
                    " WHERE name='Fantasicaféen'")
    rep = atlas_import.run(src, photos, apply=True)
    assert rep.places_updated == 1
    with db.connect() as con:
        notes = dict(con.execute("SELECT name, notes FROM fm_places").fetchall())
    assert notes["Testparkens Legeplads"] == "Nyt toilet" and notes["Fantasicaféen"] == "Fra FamilyLog"


def test_the_command_line(fresh_db, tmp_path, capsys):
    from app.core import db
    from app.sections.familymap import atlas_import
    src, photos = _slq(tmp_path)
    assert atlas_import.main([str(src), "--photos", str(photos)]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "Places:   3 new" in out and "kusine" in out
    assert _count("fm_places") == 0
    assert atlas_import.main([str(src), "--photos", str(photos), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "IMPORTED" in out and "Backup" in out
    assert any((db.data_dir() / "backups").glob("app-*-before-atlas-import.db"))
    assert _count("fm_places") == 3
    assert atlas_import.main([str(tmp_path / "nope.db")]) == 2
    bad = tmp_path / "other.db"
    sqlite3.connect(bad).execute("CREATE TABLE x (a)").connection.close()
    assert atlas_import.main([str(bad)]) == 2
    assert "not an SLQ Companion database" in capsys.readouterr().err


def test_python_m_app_import_atlas_runs(fresh_db, tmp_path):
    import os
    import subprocess
    import sys
    src, photos = _slq(tmp_path)
    r = subprocess.run([sys.executable, "-m", "app.import_atlas", str(src), "--photos", str(photos)],
                       cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True,
                       env={**os.environ}, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "DRY RUN" in r.stdout and "Places:   3 new" in r.stdout
