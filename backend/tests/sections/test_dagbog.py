"""Dagbog (0.2.0): one entry per person per day. The family (the family
accounts and the administrator) sees each other's days - since 0.3.9 the
text and photo too, of a day its author shares; a user account's days are
its own."""
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


FULL = {"day": TODAY, "mood": 4, "mental": 8, "foods": ["hjemmelavet", "Kage"],
        "alcohol": 2, "tags": ["Sport", "venner"], "highlight": "Vi vandt kampen!"}


def test_config_has_every_field_and_the_default_tags(client):
    c = client.get("/api/dagbog/config").json()
    assert [f["key"] for f in c["fields"]] == ["mood", "mental", "exercise", "foods", "soda", "alcohol",
                                                "tags", "sick", "highlight"]  # 0.3.8: motion, sodavand, sygdom
    assert c["fields"][0]["faces"][4] == "😄" and c["today"] == TODAY
    assert (c["fields"][0]["max"], c["fields"][1]["max"]) == (5, 10)     # mood 1-5, overskud 1-10
    for t in ("Sport", "Computer", "Fjernsyn", "Vedligehold af hus og have", "Børnepasning"):
        assert t in c["tags"]
    for f in ("Hjemmelavet", "Fastfood", "Kage", "Chips", "Vitaminer"):
        assert f in c["foods"]


def test_an_entry_round_trip(client):
    r = client.put("/api/dagbog/entry", json=FULL)
    assert r.status_code == 200, r.text
    e = r.json()["entry"]
    assert (e["mood"], e["alcohol"], e["tags"]) == (4, 2, ["Sport", "Venner"])   # tag case from the list
    assert e["foods"] == ["Hjemmelavet", "Kage"] and "sleep" not in e and "food" not in e
    assert e["highlight"] == "Vi vandt kampen!" and e["hasPhoto"] is False
    e = client.put("/api/dagbog/entry", json={"day": TODAY, "mood": 2}).json()["entry"]
    assert e["mood"] == 2 and e["mental"] is None and e["foods"] == [] and e["highlight"] == ""
    assert client.get(f"/api/dagbog/entry?day={TODAY}").json()["entry"]["mood"] == 2
    assert client.delete(f"/api/dagbog/entry?day={TODAY}").status_code == 200
    assert client.get(f"/api/dagbog/entry?day={TODAY}").json()["entry"] is None


def test_validation_speaks_danish(client):
    future = (date.today() + timedelta(days=1)).isoformat()
    for body, needle in (({"day": future, "mood": 3}, "ikke kommet"),
                         ({"day": TODAY, "mood": 6}, "1-5"),
                         ({"day": TODAY, "mood": True}, "1-5"),
                         ({"day": TODAY, "mental": 11}, "1-10"),
                         ({"day": TODAY, "alcohol": -1}, "genstande"),
                         ({"day": TODAY, "tags": ["Rumfart"]}, "Ukendt aktivitet"),
                         ({"day": TODAY, "foods": ["Rumfoder"]}, "Ukendt madtype"),
                         ({"day": "i går"}, "Ugyldig dato"),
                         ({"day": TODAY, "highlight": "x" * 2001}, "for lang")):
        r = client.put("/api/dagbog/entry", json=body)
        assert r.status_code == 400 and needle in r.json()["detail"], (body, r.text)


def test_the_family_sees_the_text_and_photo_of_a_shared_day(client):
    """0.3.9 (Søren): "make the text and pictures from dagbog visible to
    everyone" - in the family. A day its author keeps private stays private."""
    mor = _login(client, "mor", "familie-kode-1")
    sanne = _login(client, "sanne", "pw-sanne-12345", role="user")
    mor_id = next(u["id"] for u in client.get("/api/users").json() if u["username"] == "mor")
    e = mor.put("/api/dagbog/entry", json={**FULL, "highlight": "Vi vandt"}).json()["entry"]
    assert e["shared"] is True                                  # shared unless she says otherwise
    assert mor.post(f"/api/dagbog/photo?day={TODAY}",
                    files={"file": ("a.jpg", _jpeg(), "image/jpeg")}).status_code == 200
    mor.put("/api/dagbog/entry", json={"day": YESTERDAY, "mood": 2, "highlight": "Min hemmelighed",
                                       "shared": False})
    for viewer in (client, mor):                                # admin and family alike
        fam = viewer.get(f"/api/dagbog/family?frm={YESTERDAY}&to={TODAY}").json()["entries"]
        today = next(x for x in fam if x["day"] == TODAY)
        assert today["highlight"] == "Vi vandt" and today["hasPhoto"] is True
        assert "hemmelighed" not in str(fam)
    # The photo of her shared day, for the admin; never for a user account.
    photo = client.get(f"/api/dagbog/photo?day={TODAY}&user={mor_id}")
    assert photo.status_code == 200 and photo.content[:3] == b"\xff\xd8\xff"
    from PIL import Image
    assert 0x8825 not in Image.open(io.BytesIO(photo.content)).getexif()     # GPS stripped
    assert sanne.get(f"/api/dagbog/photo?day={TODAY}&user={mor_id}").status_code == 403
    # Without user= it is your own: the admin has none.
    assert client.get(f"/api/dagbog/photo?day={TODAY}").status_code == 404
    # She makes today private: text and photo go from the family's view.
    mor.put("/api/dagbog/entry", json={**FULL, "highlight": "Vi vandt", "shared": False})
    assert client.get(f"/api/dagbog/photo?day={TODAY}&user={mor_id}").status_code == 404
    fam = client.get(f"/api/dagbog/family?frm={TODAY}&to={TODAY}").json()["entries"][0]
    assert "highlight" not in fam and "hasPhoto" not in fam and "shared" not in fam
    own = mor.get(f"/api/dagbog/entry?day={TODAY}").json()["entry"]
    assert own["highlight"] == "Vi vandt" and own["hasPhoto"] and own["shared"] is False
    assert mor.put("/api/dagbog/entry", json={"day": TODAY, "shared": "ja"}).status_code == 400


def test_one_persons_days_go_back_as_far_as_there_are(client):
    """0.3.9: the overview per person, newest first, a page at a time."""
    mor = _login(client, "mor", "familie-kode-1")
    sanne = _login(client, "sanne", "pw-sanne-12345", role="user")
    users = {u["username"]: u["id"] for u in client.get("/api/users").json()}
    for i in range(25):
        d = (date.today() - timedelta(days=i * 9)).isoformat()            # more than 200 days back
        assert mor.put("/api/dagbog/entry", json={"day": d, "mood": 1 + i % 5}).status_code == 200
    page = client.get(f"/api/dagbog/person?user={users['mor']}&limit=10").json()
    assert page["person"]["username"] == "mor" and not page["own"] and page["more"]
    assert len(page["entries"]) == 10 and page["entries"][0]["day"] == TODAY and page["total"] == 25
    days = [e["day"] for e in page["entries"]]
    while page["more"]:
        page = client.get(f"/api/dagbog/person?user={users['mor']}&limit=10&before={days[-1]}").json()
        days += [e["day"] for e in page["entries"]]
    assert len(days) == 25 and days == sorted(days, reverse=True) and days[-1] == page["firstDay"]
    month = mor.get(f"/api/dagbog/person/month?user={users['mor']}&month={TODAY[:7]}").json()
    assert month["days"][TODAY] == 1
    assert mor.get(f"/api/dagbog/person?user={users['admin']}").json()["own"] is False
    # A user account: only its own days, and nobody in the family sees them.
    assert sanne.get(f"/api/dagbog/person?user={users['mor']}").status_code == 403
    assert sanne.get(f"/api/dagbog/person?user={users['sanne']}").json()["own"] is True
    assert mor.get(f"/api/dagbog/person?user={users['sanne']}").status_code == 403
    assert mor.get(f"/api/dagbog/stats?user={users['sanne']}").status_code == 403
    assert client.get("/api/dagbog/person?user=999").status_code == 404
    assert client.get(f"/api/dagbog/person/month?user={users['mor']}&month=2026-13").status_code == 400


def test_statistics_for_one_person(client):
    """0.3.9 (Søren): "we need statistics for the individual"."""
    mor = _login(client, "mor", "familie-kode-1")
    uid = next(u["id"] for u in client.get("/api/users").json() if u["username"] == "mor")
    assert client.get(f"/api/dagbog/stats?user={uid}").json()["days"] == 0
    for i in range(28):
        d = (date.today() - timedelta(days=i)).isoformat()
        sport = i % 2 == 0
        mor.put("/api/dagbog/entry", json={
            "day": d, "mood": 5 if sport else 2, "mental": 8 if sport else 4,
            "exercise": 60 if sport else 0, "alcohol": 0 if sport else 2,
            "tags": ["Sport"] if sport else ["Fjernsyn"], "foods": ["Hjemmelavet"],
            "sick": ["Hoste"] if i in (3, 5) else []})
    s = mor.get(f"/api/dagbog/stats?user={uid}").json()
    assert s["days"] == 28 and s["coverage"] == 100 and s["bestStreak"] == 28
    assert s["mood"] == 3.5 and s["mental"] == 6.0 and s["sickDays"] == 2
    assert s["exerciseHoursPerWeek"] == 3.5 and s["alcoholPerWeek"] == 7.0
    assert s["topFoods"][0] == {"name": "Hjemmelavet", "days": 28}
    assert {t["name"] for t in s["topTags"]} == {"Sport", "Fjernsyn"}
    assert len(s["weekdays"]) == 7 and sum(m["days"] for m in s["months"]) == 28
    links = {x["label"]: x for x in s["links"]}
    assert links["Sport"]["diff"] == 3.0 and links["Motion 1 time eller mere"]["with"] == 5.0
    assert links["Alkohol"]["diff"] == -3.0 and "Hjemmelavet" not in links    # eaten every day: nothing to compare
    week = mor.get(f"/api/dagbog/stats?user={uid}&frm={(date.today() - timedelta(days=6)).isoformat()}").json()
    assert week["days"] == 7 and week["span"] == 7
    assert client.get(f"/api/dagbog/stats?user={uid}&frm=igår").status_code == 400


def test_migration_5_keeps_old_texts_private(fresh_db):
    """Days written while "kun du kan se teksten og billedet" was the promise
    stay private until their author shares them."""
    from app.core import auth, db
    from app.sections.dagbog import _m005_shared, dagbog
    u = auth.create_user("mor", "familie-kode-1", "family")
    dagbog.set_foods(["Pizza"])
    with db.connect() as con:
        for d, text in ((TODAY, "Gammel tekst"), (YESTERDAY, "")):
            con.execute("INSERT INTO dagbog_entries (user_id, day, mood, tags, highlight, created_at,"
                        " updated_at) VALUES (?, ?, 3, '[]', ?, 'x', 'x')", (u["id"], d, text))
        _m005_shared(con)
    assert dagbog.get_entry(u["id"], TODAY)["shared"] is False
    assert dagbog.get_entry(u["id"], YESTERDAY)["shared"] is True
    assert dagbog.foods() == ["Pizza", "Vitaminer"]                  # added to a saved list too
    with db.connect() as con:
        _m005_shared(con)                                             # once only
    assert dagbog.foods() == ["Pizza", "Vitaminer"]


def test_the_admin_sets_tags_and_fields_per_person(client):
    barn = _login(client, "barn", "familie-kode-2")
    s = client.get("/api/dagbog/admin/settings").json()
    uid = next(m["id"] for m in s["members"] if m["username"] == "barn")
    r = client.put("/api/dagbog/admin/settings", json={
        "tags": ["Skole", " Fodbold ", "skole", ""], "foods": ["Pizza", "Grød"],
        "members": {str(uid): ["mood", "foods", "tags", "highlight"]}})
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == ["Skole", "Fodbold"] and r.json()["foods"] == ["Pizza", "Grød"]
    cfg = barn.get("/api/dagbog/config").json()
    assert [f["key"] for f in cfg["fields"]] == ["mood", "foods", "tags", "highlight"]
    assert cfg["foods"] == ["Pizza", "Grød"]
    # A field that is off is not stored, even when sent.
    e = barn.put("/api/dagbog/entry", json={"day": TODAY, "mood": 3, "alcohol": 4,
                                            "tags": ["Fodbold"]}).json()["entry"]
    assert e["alcohol"] is None and e["tags"] == ["Fodbold"]
    assert barn.get("/api/dagbog/admin/settings").status_code == 403
    assert barn.put("/api/dagbog/admin/settings", json={"tags": []}).status_code == 403
    assert client.put("/api/dagbog/admin/settings",
                      json={"members": {str(uid): ["nonsense"]}}).status_code == 400
    assert client.put("/api/dagbog/admin/settings",
                      json={"members": {str(uid): ["sleep"]}}).status_code == 400     # gone in 0.2.1


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


def test_migration_2_keeps_hand_set_food_and_adds_the_column(fresh_db):
    """A database from 0.2.0: a person with "food" chosen by hand gets
    "foods"; the old values stay in their columns but are not sent."""
    import json
    from app.core import auth, db
    from app.sections.dagbog import _m002_foods, dagbog
    u = auth.create_user("mor", "familie-kode-1", "family")
    with db.connect() as con:
        con.execute("INSERT INTO dagbog_members (user_id, fields) VALUES (?, ?)",
                    (u["id"], json.dumps(["mood", "sleep", "food"])))
        con.execute("INSERT INTO dagbog_entries (user_id, day, mood, sleep, food, tags, highlight,"
                    " created_at, updated_at) VALUES (?, ?, 3, 4, 5, '[]', '', 'x', 'x')",
                    (u["id"], TODAY))
        _m002_foods(con)                                  # idempotent: the column exists already
    assert dagbog.fields_for(u["id"]) == ["mood", "foods"]
    e = dagbog.get_entry(u["id"], TODAY)
    assert e["mood"] == 3 and e["foods"] == [] and "sleep" not in e


def test_migration_3_doubles_old_overskud_and_adds_childcare(fresh_db):
    import json
    from app.core import auth, db
    from app.sections.dagbog import _m003_mental_ten, dagbog
    u = auth.create_user("mor", "familie-kode-1", "family")
    dagbog.set_tags(["Sport", "Fri"])
    with db.connect() as con:
        con.execute("INSERT INTO dagbog_entries (user_id, day, mental, tags, highlight, created_at,"
                    " updated_at) VALUES (?, ?, 3, '[]', '', 'x', 'x')", (u["id"], TODAY))
        _m003_mental_ten(con)
    assert dagbog.get_entry(u["id"], TODAY)["mental"] == 6
    assert dagbog.tags() == ["Sport", "Fri", "Børnepasning"]
    with db.connect() as con:
        assert json.loads(con.execute("SELECT value FROM dagbog_settings WHERE key='tags'")
                          .fetchone()[0]).count("Børnepasning") == 1


def test_the_family_week_is_the_family_only(client):
    """0.3.7 (Søren): only the family in "Familien" - the family accounts and
    the administrator, who is family; a user account is not, and its own
    Dagbog stays its own."""
    mor = _login(client, "mor", "familie-kode-1")
    sanne = _login(client, "sanne", "pw-sanne-12345", role="user")
    client.put("/api/dagbog/entry", json={"day": TODAY, "mood": 5})
    sanne.put("/api/dagbog/entry", json={"day": TODAY, "mood": 1})
    fam = mor.get(f"/api/dagbog/family?frm={TODAY}&to={TODAY}").json()
    assert [m["username"] for m in fam["members"]] == ["admin", "mor"]
    assert [e["mood"] for e in fam["entries"]] == [5]                 # the admin's day, not sanne's
    assert sanne.get(f"/api/dagbog/family?frm={TODAY}&to={TODAY}").status_code == 403
    assert sanne.get(f"/api/dagbog/entry?day={TODAY}").json()["entry"]["mood"] == 1


def test_motion_sodavand_alkohol_as_sliders_and_sickness(client):
    """0.3.8 (Søren): motion in half hours, sodavand and alkohol as sliders,
    sickness and injuries as a field - the family sees them, not the note's
    owner only (it is not the private highlight)."""
    mor = _login(client, "mor", "familie-kode-1")
    c = mor.get("/api/dagbog/config").json()
    f = {x["key"]: x for x in c["fields"]}
    assert (f["exercise"]["kind"], f["exercise"]["step"], f["exercise"]["max"]) == ("slider", 30, 480)
    assert f["alcohol"]["kind"] == "slider" and f["soda"]["unit"] == "glas" and "Feber" in f["sick"]["options"]
    e = mor.put("/api/dagbog/entry", json={"day": TODAY, "exercise": 90, "soda": 2, "alcohol": 0,
                                           "sick": ["feber", "Hoste"], "sickNote": "Lagt i seng"}).json()["entry"]
    assert (e["exercise"], e["soda"], e["alcohol"], e["sick"], e["sickNote"]) == (90, 2, 0, ["Feber", "Hoste"], "Lagt i seng")
    for body, needle in (({"exercise": 45}, "halve timer"), ({"exercise": 510}, "halve timer"),
                         ({"soda": 11}, "glas"), ({"alcohol": 21}, "genstande"),
                         ({"sick": ["Pest"]}, "Ukendt sygdom"), ({"sickNote": "x" * 201, "sick": []}, "for lang")):
        r = mor.put("/api/dagbog/entry", json={"day": TODAY, **body})
        assert r.status_code == 400 and needle in r.json()["detail"], (body, r.text)
    fam = client.get(f"/api/dagbog/family?frm={TODAY}&to={TODAY}").json()["entries"][0]
    assert (fam["exercise"], fam["sick"]) == (90, ["Feber", "Hoste"])


def test_migration_4_gives_hand_set_people_the_new_fields(fresh_db):
    import json
    from app.core import auth, db
    from app.sections.dagbog import _m004_more_fields, dagbog
    u = auth.create_user("barn", "familie-kode-1", "family")
    dagbog.set_foods(["Pizza", "Sodavand", "Kage"])
    with db.connect() as con:
        con.execute("INSERT INTO dagbog_members (user_id, fields) VALUES (?, ?)",
                    (u["id"], json.dumps(["mood", "tags"])))
        _m004_more_fields(con)                           # idempotent: the columns exist already
    assert dagbog.fields_for(u["id"]) == ["mood", "exercise", "soda", "tags", "sick"]
    assert dagbog.foods() == ["Pizza", "Kage"]
