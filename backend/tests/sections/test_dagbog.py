"""Dagbog (0.2.0): one entry per person per day; the family sees ratings
and tags, the highlight text and photo stay with the author - the
administrator included."""
from __future__ import annotations

import io
from datetime import date, timedelta

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def _login(client, name, pw, role="family"):
    from fastapi.testclient import TestClient
    from app.main import app
    assert client.post("/api/users", json={"username": name, "password": pw,
                                           "role": role}).status_code == 200
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": name, "password": pw}).status_code == 200
    return c


def _jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (55.0, 15.0, 0.0)}        # GPS - must not survive
    Image.new("RGB", (800, 600), (200, 120, 60)).save(buf, "JPEG", exif=exif)
    return buf.getvalue()


FULL = {"day": TODAY, "mood": 4, "sleep": 3, "energy": 5, "mental": 2, "food": 4,
        "alcohol": 2, "tags": ["Sport", "venner"], "highlight": "Vi vandt kampen!"}


def test_config_has_every_field_and_the_default_tags(client):
    c = client.get("/api/dagbog/config").json()
    assert [f["key"] for f in c["fields"]] == ["mood", "sleep", "energy", "mental", "food",
                                                "alcohol", "tags", "highlight"]
    assert c["fields"][0]["faces"][4] == "😄" and "Sport" in c["tags"] and c["today"] == TODAY


def test_an_entry_round_trip(client):
    r = client.put("/api/dagbog/entry", json=FULL)
    assert r.status_code == 200, r.text
    e = r.json()["entry"]
    assert (e["mood"], e["alcohol"], e["tags"]) == (4, 2, ["Sport", "Venner"])   # tag case from the list
    assert e["highlight"] == "Vi vandt kampen!" and e["hasPhoto"] is False
    e = client.put("/api/dagbog/entry", json={"day": TODAY, "mood": 2}).json()["entry"]
    assert e["mood"] == 2 and e["sleep"] is None and e["highlight"] == ""        # a save replaces
    assert client.get(f"/api/dagbog/entry?day={TODAY}").json()["entry"]["mood"] == 2
    assert client.delete(f"/api/dagbog/entry?day={TODAY}").status_code == 200
    assert client.get(f"/api/dagbog/entry?day={TODAY}").json()["entry"] is None


def test_validation_speaks_danish(client):
    future = (date.today() + timedelta(days=1)).isoformat()
    for body, needle in (({"day": future, "mood": 3}, "ikke kommet"),
                         ({"day": TODAY, "mood": 6}, "1-5"),
                         ({"day": TODAY, "mood": True}, "1-5"),
                         ({"day": TODAY, "alcohol": -1}, "genstande"),
                         ({"day": TODAY, "tags": ["Rumfart"]}, "Ukendt aktivitet"),
                         ({"day": "i går"}, "Ugyldig dato"),
                         ({"day": TODAY, "highlight": "x" * 2001}, "for lang")):
        r = client.put("/api/dagbog/entry", json=body)
        assert r.status_code == 400 and needle in r.json()["detail"], (body, r.text)


def test_the_family_sees_ratings_but_never_the_text_or_photo(client):
    mor = _login(client, "mor", "familie-kode-1")
    assert mor.put("/api/dagbog/entry", json={**FULL, "highlight": "Min hemmelighed"}).status_code == 200
    assert mor.post(f"/api/dagbog/photo?day={TODAY}",
                    files={"file": ("a.jpg", _jpeg(), "image/jpeg")}).status_code == 200
    client.put("/api/dagbog/entry", json={"day": YESTERDAY, "mood": 5, "highlight": "Admins tekst"})
    for viewer in (client, mor):                              # admin and family alike
        fam = viewer.get(f"/api/dagbog/family?frm={YESTERDAY}&to={TODAY}")
        assert fam.status_code == 200
        assert "hemmelighed" not in fam.text and "Admins tekst" not in fam.text
        rows = fam.json()["entries"]
        assert {(e["day"], e["mood"]) for e in rows} == {(TODAY, 4), (YESTERDAY, 5)}
        assert all("highlight" not in e and "hasPhoto" not in e for e in rows)
    # The photo is the author's: the admin asking for "their" photo gets their own - none.
    assert client.get(f"/api/dagbog/photo?day={TODAY}").status_code == 404
    photo = mor.get(f"/api/dagbog/photo?day={TODAY}")
    assert photo.status_code == 200 and photo.content[:3] == b"\xff\xd8\xff"
    from PIL import Image
    assert 0x8825 not in Image.open(io.BytesIO(photo.content)).getexif()     # GPS stripped
    assert mor.get(f"/api/dagbog/entry?day={TODAY}").json()["entry"]["highlight"] == "Min hemmelighed"
    assert client.get(f"/api/dagbog/entry?day={TODAY}").json()["entry"] is None


def test_the_admin_sets_tags_and_fields_per_person(client):
    barn = _login(client, "barn", "familie-kode-2")
    s = client.get("/api/dagbog/admin/settings").json()
    uid = next(m["id"] for m in s["members"] if m["username"] == "barn")
    r = client.put("/api/dagbog/admin/settings", json={
        "tags": ["Skole", " Fodbold ", "skole", ""],
        "members": {str(uid): ["mood", "sleep", "tags", "highlight"]}})
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == ["Skole", "Fodbold"]
    cfg = barn.get("/api/dagbog/config").json()
    assert [f["key"] for f in cfg["fields"]] == ["mood", "sleep", "tags", "highlight"]
    # A field that is off is not stored, even when sent.
    e = barn.put("/api/dagbog/entry", json={"day": TODAY, "mood": 3, "alcohol": 4,
                                            "tags": ["Fodbold"]}).json()["entry"]
    assert e["alcohol"] is None and e["tags"] == ["Fodbold"]
    assert barn.get("/api/dagbog/admin/settings").status_code == 403
    assert barn.put("/api/dagbog/admin/settings", json={"tags": []}).status_code == 403
    assert client.put("/api/dagbog/admin/settings",
                      json={"members": {str(uid): ["nonsense"]}}).status_code == 400


def test_deleting_an_account_removes_its_days_and_photos(client):
    from app.core import db
    mor = _login(client, "mor", "familie-kode-1")
    mor.put("/api/dagbog/entry", json={"day": TODAY, "mood": 3})
    mor.post(f"/api/dagbog/photo?day={TODAY}", files={"file": ("a.jpg", _jpeg(), "image/jpeg")})
    uid = next(u["id"] for u in client.get("/api/users").json() if u["username"] == "mor")
    folder = db.data_dir() / "dagbog" / "photos" / str(uid)
    assert any(folder.iterdir())
    assert client.delete(f"/api/users/{uid}").status_code == 200
    assert not folder.exists()
    fam = client.get(f"/api/dagbog/family?frm={TODAY}&to={TODAY}").json()
    assert fam["entries"] == [] and all(m["username"] != "mor" for m in fam["members"])


def test_the_family_overview_range_is_bounded(client):
    far = (date.today() - timedelta(days=80)).isoformat()
    assert client.get(f"/api/dagbog/family?frm={far}&to={TODAY}").status_code == 400
    assert client.get(f"/api/dagbog/family?frm={TODAY}&to={YESTERDAY}").status_code == 400
    mine = client.get(f"/api/dagbog/mine?frm={YESTERDAY}&to={TODAY}").json()
    assert mine == {"days": []}
