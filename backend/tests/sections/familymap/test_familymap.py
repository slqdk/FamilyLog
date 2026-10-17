"""FamilyMap, release 1 (2.43.0): data, validation, photos, and the family
role's central lockout."""
import io

import pytest


def _family_client(client, name="mor", password="familie-kode-1"):
    """A second TestClient signed in as a family account made by the admin."""
    from fastapi.testclient import TestClient
    from app.main import app
    r = client.post("/api/familymap/users", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    fam = TestClient(app)
    r = fam.post("/api/auth/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    return fam, r.json()["user"]


def _jpeg(w=3000, h=2000, exif_date=True) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (w, h), (40, 120, 90))
    buf = io.BytesIO()
    if exif_date:
        exif = Image.Exif()
        exif[306] = "2026:07:14 13:05:00"
        exif[0x8825] = {1: "N", 2: (55.0, 15.0, 0.0)}    # GPS - must not survive
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


# ---- the lockout -----------------------------------------------------------------

def test_family_reaches_only_the_family_api(client):
    fam, user = _family_client(client)
    assert user["role"] == "family"
    assert fam.get("/api/fm/categories").status_code == 200
    assert fam.get("/api/fm/places").status_code == 200
    # A sample of the app's endpoints, plus the admin half of FamilyMap.
    for path in ("/api/projects", "/api/settings", "/api/users", "/api/feeds",
                 "/api/libraries", "/api/familymap/stats", "/api/help"):
        r = fam.get(path)
        assert r.status_code == 403, (path, r.status_code)
    assert fam.post("/api/projects", json={"name": "x"}).status_code == 403
    # Public auth endpoints still work (status drives the page, logout too).
    assert fam.get("/api/auth/status").json()["user"]["role"] == "family"


def test_every_api_route_outside_fm_refuses_family(client):
    """Not a sample: every registered /api route, by the middleware rule."""
    from app.core import auth
    from app.main import app
    fam_user = {"id": 99, "role": "family"}
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        allowed = auth.family_allows(fam_user, path)
        assert allowed == path.startswith("/api/fm/"), path


def test_family_accounts_do_not_count_towards_the_user_limit(client):
    from app.core import auth
    for i in range(4):
        r = client.post("/api/familymap/users",
                        json={"username": f"barn{i}", "password": "familie-kode-1"})
        assert r.status_code == 200, r.text
    assert auth.account_count() == 1
    r = client.post("/api/users", json={"username": "sub", "password": "test-password-2"})
    assert r.status_code == 200, r.text
    names = [u["username"] for u in client.get("/api/familymap/users").json()]
    assert names == ["barn0", "barn1", "barn2", "barn3"]


def test_family_admin_endpoints_refuse_family(client):
    fam, _ = _family_client(client)
    assert fam.post("/api/familymap/users",
                    json={"username": "x", "password": "familie-kode-1"}).status_code == 403


# ---- places and reviews ------------------------------------------------------------

def _place(c, **kw):
    body = {"name": "Legeland", "category": "playground", "address": "Vojens",
            "lat": 55.25, "lng": 9.30, **kw}
    r = c.post("/api/fm/places", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_categories_are_fixed_and_complete(client):
    cats = client.get("/api/fm/categories").json()
    assert set(cats) == {"restaurant", "hotel", "city", "playground", "activity",
                         "attraction", "nature"}
    for c in cats.values():
        assert c["label"] and c["fields"]
        for f in c["fields"]:
            assert f["kind"] in {"rating", "bool", "choice", "text"}
            assert (f["kind"] == "choice") == ("options" in f)


def test_review_round_trip_and_family_score(client):
    fam, user = _family_client(client)
    p = _place(fam)
    assert p["source"] == "family" and p["reviewCount"] == 0 and p["familyScore"] is None
    r = fam.post(f"/api/fm/places/{p['id']}/reviews", json={
        "overall": 80, "visitedOn": "2026-07-14", "who": "alle fire",
        "fields": {"equipment": 90, "shade": True, "ageRange": "3-10"},
        "text": "God til de små.", "again": True})
    assert r.status_code == 200, r.text
    rev = r.json()
    assert rev["author"] == "mor" and rev["fields"]["shade"] is True
    fam.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 61})
    place = fam.get(f"/api/fm/places/{p['id']}").json()
    assert place["reviewCount"] == 2 and place["familyScore"] == 70   # (80+61)/2 rounded
    assert [x["overall"] for x in place["reviews"]][0] == 80          # dated first


@pytest.mark.parametrize("body,needle", [
    ({}, "mangler"),
    ({"overall": 0}, "1 til 100"),
    ({"overall": 101}, "1 til 100"),
    ({"overall": 50.5}, "1 til 100"),
    ({"overall": True}, "1 til 100"),
    ({"overall": 50, "fields": {"food": 50}}, "hører ikke til"),
    ({"overall": 50, "fields": {"equipment": 150}}, "1 til 100"),
    ({"overall": 50, "fields": {"shade": "ja"}}, "ja eller nej"),
    ({"overall": 50, "visitedOn": "14/7"}, "ÅÅÅÅ-MM-DD"),
    ({"overall": 50, "again": "ja"}, "ja eller nej"),
])
def test_review_validation_speaks_danish(client, body, needle):
    p = _place(client)
    r = client.post(f"/api/fm/places/{p['id']}/reviews", json=body)
    assert r.status_code == 400 and needle in r.json()["detail"], r.text


def test_choice_fields_take_only_their_options(client):
    p = _place(client, name="Kroen", category="restaurant")
    ok = client.post(f"/api/fm/places/{p['id']}/reviews",
                     json={"overall": 70, "fields": {"price": "Middel"}})
    assert ok.status_code == 200
    bad = client.post(f"/api/fm/places/{p['id']}/reviews",
                      json={"overall": 70, "fields": {"price": "Gratis"}})
    assert bad.status_code == 400 and "Billig" in bad.json()["detail"]


def test_only_the_author_or_admin_changes_a_review(client):
    mor, _ = _family_client(client, "mor")
    far, _ = _family_client(client, "far")
    p = _place(mor)
    rid = mor.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 50}).json()["id"]
    assert far.put(f"/api/fm/reviews/{rid}", json={"overall": 10}).status_code == 403
    assert far.delete(f"/api/fm/reviews/{rid}").status_code == 403
    assert mor.put(f"/api/fm/reviews/{rid}", json={"overall": 55}).json()["overall"] == 55
    assert client.put(f"/api/fm/reviews/{rid}", json={"text": "admin"}).status_code == 200
    assert client.delete(f"/api/fm/reviews/{rid}").status_code == 200


def test_family_cannot_set_the_source(client):
    fam, _ = _family_client(client)
    p = _place(fam, source="google", sourceId="abc")
    assert p["source"] == "family"


def test_list_filters_and_reviewed_first(client):
    a = _place(client, name="Aabenraa Strand", category="nature")
    _place(client, name="Billund", category="city")
    client.post(f"/api/fm/places/{_place(client, name='Zoo', category='attraction')['id']}"
                "/reviews", json={"overall": 90})
    names = [p["name"] for p in client.get("/api/fm/places").json()]
    assert names == ["Zoo", "Aabenraa Strand", "Billund"]
    assert [p["id"] for p in client.get("/api/fm/places?category=nature").json()] == [a["id"]]
    assert [p["name"] for p in client.get("/api/fm/places?q=bill").json()] == ["Billund"]
    assert [p["name"] for p in client.get("/api/fm/places?reviewed=yes").json()] == ["Zoo"]
    assert client.get("/api/fm/places?category=spa").status_code == 400


def test_admin_edits_and_deletes_places(client):
    p = _place(client)
    r = client.put(f"/api/familymap/places/{p['id']}",
                   json={"name": "Legeland Vojens", "lat": "", "website": "https://x.dk"})
    assert r.status_code == 200
    assert r.json()["name"] == "Legeland Vojens" and r.json()["lat"] is None
    assert client.put(f"/api/familymap/places/{p['id']}",
                      json={"category": "spa"}).status_code == 400
    assert client.delete(f"/api/familymap/places/{p['id']}").status_code == 200
    assert client.get(f"/api/fm/places/{p['id']}").status_code == 404


# ---- photos ---------------------------------------------------------------------

def _upload(c, rid, *blobs):
    files = [("files", (f"p{i}.jpg", b, "image/jpeg")) for i, b in enumerate(blobs)]
    return c.post(f"/api/fm/reviews/{rid}/photos", files=files)


def test_photos_are_resized_stripped_and_served(client):
    from PIL import Image
    from app.sections.familymap import familymap as fm
    p = _place(client)
    rid = client.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 80}).json()["id"]
    r = _upload(client, rid, _jpeg())
    assert r.status_code == 200, r.text
    ph = r.json()[0]
    assert (ph["width"], ph["height"]) == (2048, 1365)
    assert ph["takenAt"] == "2026-07-14T13:05:00"
    full = client.get(f"/api/fm/photos/{ph['id']}")
    thumb = client.get(f"/api/fm/photos/{ph['id']}?thumb=1")
    assert full.headers["content-type"] == "image/jpeg"
    assert "private" in full.headers["cache-control"]
    img = Image.open(io.BytesIO(full.content))
    assert not img.getexif().get_ifd(0x8825)           # GPS gone
    assert max(Image.open(io.BytesIO(thumb.content)).size) == fm.THUMB_PX
    place = client.get(f"/api/fm/places/{p['id']}").json()
    assert place["coverPhotoId"] == ph["id"]
    assert place["reviews"][0]["photos"][0]["id"] == ph["id"]


def test_photo_upload_refuses_non_images_all_or_nothing(client):
    p = _place(client)
    rid = client.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 80}).json()["id"]
    r = _upload(client, rid, _jpeg(exif_date=False), b"%PDF-1.4 not a photo")
    assert r.status_code == 400 and "JPEG" in r.json()["detail"]
    assert client.get(f"/api/fm/places/{p['id']}").json()["reviews"][0]["photos"] == []


def test_deleting_a_place_removes_its_photo_files(client):
    from app.sections.familymap import familymap as fm
    p = _place(client)
    rid = client.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 80}).json()["id"]
    _upload(client, rid, _jpeg(800, 600, exif_date=False))
    assert len(list(fm.photos_dir().iterdir())) == 2
    client.delete(f"/api/familymap/places/{p['id']}")
    assert list(fm.photos_dir().iterdir()) == []


def test_photos_of_another_family_member_cannot_be_deleted(client):
    mor, _ = _family_client(client, "mor")
    far, _ = _family_client(client, "far")
    p = _place(mor)
    rid = mor.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 50}).json()["id"]
    pid = _upload(mor, rid, _jpeg(640, 480, exif_date=False)).json()[0]["id"]
    assert _upload(far, rid, _jpeg(640, 480, exif_date=False)).status_code == 403
    assert far.delete(f"/api/fm/photos/{pid}").status_code == 403
    assert far.get(f"/api/fm/photos/{pid}").status_code == 200     # viewing is shared
    assert mor.delete(f"/api/fm/photos/{pid}").status_code == 200


def test_without_pillow_the_original_is_kept(client, monkeypatch):
    import builtins
    blob = _jpeg(640, 480, exif_date=False)       # made while Pillow is still there
    real = builtins.__import__

    def no_pil(name, *a, **kw):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no Pillow")
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", no_pil)
    p = _place(client)
    rid = client.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 80}).json()["id"]
    r = _upload(client, rid, blob)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/fm/photos/{r.json()[0]['id']}").content == blob


def test_admin_reviews_and_stats(client):
    p = _place(client)
    client.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 80})
    revs = client.get("/api/familymap/reviews").json()
    assert revs[0]["placeName"] == "Legeland"
    st = client.get("/api/familymap/stats").json()
    assert (st["places"], st["reviewedPlaces"], st["reviews"], st["photos"]) == (1, 1, 1, 0)
    assert st["sources"] == {"family": 1}


def test_deleting_a_family_account_keeps_its_reviews(client):
    fam, user = _family_client(client, "barn")
    p = _place(fam)
    fam.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 95})
    assert client.delete(f"/api/users/{user['id']}").status_code == 200
    rev = client.get(f"/api/fm/places/{p['id']}").json()["reviews"][0]
    assert rev["overall"] == 95 and rev["userId"] is None
    assert rev["author"] == "(slettet bruger)"
    assert fam.get("/api/fm/places").status_code == 401          # session gone


def test_the_family_page_is_served_at_fm():
    """dist/fm/index.html is where the second Vite page lands; the static
    mount serves a folder's index.html, so /fm/ needs no route of its own."""
    import pathlib
    vite = (pathlib.Path(__file__).resolve().parents[4] / "frontend" / "vite.config.ts").read_text()
    assert "./fm/index.html" in vite
    assert (pathlib.Path(__file__).resolve().parents[4] / "frontend" / "fm" / "index.html").is_file()


def test_family_sessions_last_a_month_like_the_admin(client):
    """2.43.1: a phone should not ask for the password every ten days."""
    from app.core import auth, db
    _family_client(client, "mor")
    client.post("/api/users", json={"username": "sub", "password": "test-password-2"})
    auth.login("sub", "test-password-2")
    with db.connect() as con:
        rows = {r["username"]: r["expires_at"] - r["created"] for r in con.execute(
            "SELECT u.username, s.expires_at, s.last_seen AS created"
            " FROM sessions s JOIN users u ON u.id = s.user_id")}
    day = 86400
    assert round(rows["mor"] / day) == auth.SESSION_DAYS_ADMIN == 30
    assert round(rows["admin"] / day) == auth.SESSION_DAYS_ADMIN
    assert round(rows["sub"] / day) == auth.SESSION_DAYS_USER == 10
