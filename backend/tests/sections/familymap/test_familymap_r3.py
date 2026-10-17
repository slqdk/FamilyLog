"""Alf's Atlas design release (2.45.0): the card's line of text, each
person's wishlist, and the burger menu's "mine" lists."""


def _family(client, name):
    from fastapi.testclient import TestClient
    from app.main import app
    client.post("/api/familymap/users", json={"username": name, "password": "familie-kode-1"})
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": name, "password": "familie-kode-1"}).status_code == 200
    return c


def _place(c, name="Legeland", category="playground"):
    return c.post("/api/fm/places", json={"name": name, "category": category,
                                          "lat": 55.25, "lng": 9.3}).json()


def test_the_card_line_is_the_newest_review_text(client):
    p = _place(client)
    assert client.get("/api/fm/places").json()[0]["latestText"] is None
    client.post(f"/api/fm/places/{p['id']}/reviews",
                json={"overall": 70, "visitedOn": "2026-05-01", "text": "Gammel tekst"})
    client.post(f"/api/fm/places/{p['id']}/reviews",
                json={"overall": 80, "visitedOn": "2026-07-14", "text": "Ny   tekst\nmed linjeskift"})
    client.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 90, "visitedOn": "2026-08-01"})
    assert client.get("/api/fm/places").json()[0]["latestText"] == "Ny tekst med linjeskift"


def test_the_wishlist_is_per_person(client):
    mor, far = _family(client, "mor"), _family(client, "far")
    p = _place(mor)
    assert mor.put(f"/api/fm/wishlist/{p['id']}").json()["wished"] is True
    assert mor.put(f"/api/fm/wishlist/{p['id']}").status_code == 200          # idempotent
    assert mor.get(f"/api/fm/places/{p['id']}").json()["wished"] is True
    assert far.get(f"/api/fm/places/{p['id']}").json()["wished"] is False
    assert [x["id"] for x in mor.get("/api/fm/places?wished=1").json()] == [p["id"]]
    assert far.get("/api/fm/places?wished=1").json() == []
    assert mor.delete(f"/api/fm/wishlist/{p['id']}").json()["wished"] is False
    assert mor.put("/api/fm/wishlist/9999").status_code == 404


def test_wished_near_me_combines(client):
    p = _place(client)
    _place(client, "Andet sted")
    client.put(f"/api/fm/wishlist/{p['id']}")
    rows = client.get("/api/fm/places?wished=1&lat=55.2&lng=9.3").json()
    assert [r["id"] for r in rows] == [p["id"]] and rows[0]["distanceKm"] is not None


def test_mine_lists_only_my_own(client):
    import io
    from PIL import Image
    mor, far = _family(client, "mor"), _family(client, "far")
    p = _place(mor)
    rid = mor.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 88, "visitedOn": "2026-07-01"}).json()["id"]
    far.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 40})
    buf = io.BytesIO()
    Image.new("RGB", (300, 200)).save(buf, "JPEG")
    mor.post(f"/api/fm/reviews/{rid}/photos", files=[("files", ("a.jpg", buf.getvalue(), "image/jpeg"))])
    mine = mor.get("/api/fm/me/reviews").json()
    assert [r["overall"] for r in mine] == [88] and mine[0]["placeName"] == "Legeland"
    photos = mor.get("/api/fm/me/photos").json()
    assert len(photos) == 1 and photos[0]["placeId"] == p["id"] and photos[0]["placeName"] == "Legeland"
    assert far.get("/api/fm/me/photos").json() == []


# ---- 2.49.5: the family's own places ----------------------------------------------------------

def _fam(client, name):
    from fastapi.testclient import TestClient
    from app.main import app
    client.post("/api/familymap/users", json={"username": name, "password": "familie-kode-1"})
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": name, "password": "familie-kode-1"})
    return c


def test_my_places_lists_only_what_i_created(client):
    mor, far = _fam(client, "mor"), _fam(client, "far")
    a = mor.post("/api/fm/places", json={"name": "Kastanjetræet", "category": "attraction"}).json()
    far.post("/api/fm/places", json={"name": "Fars sted", "category": "nature"})
    mine = mor.get("/api/fm/me/places").json()
    assert [p["id"] for p in mine] == [a["id"]] and mine[0]["createdBy"] is not None


def test_the_creator_edits_and_others_may_not(client):
    mor, far = _fam(client, "mor"), _fam(client, "far")
    pid = mor.post("/api/fm/places", json={"name": "Kastanjetræ", "category": "nature"}).json()["id"]
    r = mor.put(f"/api/fm/places/{pid}", json={"name": "Kastanjetræ på høttepladsen",
                                               "category": "attraction", "notes": "Om efteråret"})
    assert r.status_code == 200 and r.json()["category"] == "attraction"
    assert far.put(f"/api/fm/places/{pid}", json={"name": "x"}).status_code == 403
    assert client.put(f"/api/fm/places/{pid}", json={"name": "Admin"}).status_code == 200


def test_imported_places_are_not_the_familys_to_edit(client):
    from app.core import db
    mor = _fam(client, "mor")
    pid = client.post("/api/fm/places", json={"name": "OSM-sted", "category": "nature"}).json()["id"]
    with db.connect() as con:
        con.execute("UPDATE fm_places SET created_by = NULL, source = 'osm' WHERE id = ?", (pid,))
    assert mor.put(f"/api/fm/places/{pid}", json={"name": "x"}).status_code == 403
    assert mor.delete(f"/api/fm/places/{pid}").status_code == 403


def test_the_creator_deletes_unless_someone_else_reviewed_it(client):
    mor, far = _fam(client, "mor"), _fam(client, "far")
    lone = mor.post("/api/fm/places", json={"name": "Kun mit", "category": "nature"}).json()["id"]
    mor.post(f"/api/fm/places/{lone}/reviews", json={"overall": 70})     # her own review goes too
    assert mor.delete(f"/api/fm/places/{lone}").status_code == 200
    shared = mor.post("/api/fm/places", json={"name": "Delt", "category": "nature"}).json()["id"]
    far.post(f"/api/fm/places/{shared}/reviews", json={"overall": 90})
    r = mor.delete(f"/api/fm/places/{shared}")
    assert r.status_code == 400 and "Andre har anmeldt" in r.json()["detail"]
    assert client.delete(f"/api/fm/places/{shared}").status_code == 200    # the admin may


# ---- 2.50.0: "Mad" as the average of the dishes ----------------------------------------------

def test_food_is_the_average_of_the_scored_dishes(client):
    p = client.post("/api/fm/places", json={"name": "Kroen", "category": "restaurant"}).json()
    r = client.post(f"/api/fm/places/{p['id']}/reviews", json={
        "overall": 70, "fields": {"meat": 80, "salad": 61, "fries": 90, "drinks": 55,
                                  "rice": None, "food": 10}})          # a sent "food" is ignored
    f = r.json()["fields"]
    assert f["food"] == 77                                          # (80 + 61 + 90) / 3 = 77
    assert f["drinks"] == 55 and "rice" not in f
    # Removing a dish recomputes.
    r = client.put(f"/api/fm/reviews/{r.json()['id']}", json={"fields": {"meat": 80, "salad": 61}})
    assert r.json()["fields"]["food"] == 71                         # 70.5 rounds up, as on the phone


def test_an_old_review_keeps_its_food_score(client):
    p = client.post("/api/fm/places", json={"name": "Kroen", "category": "restaurant"}).json()
    r = client.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 70, "fields": {"food": 64}})
    assert r.json()["fields"] == {"food": 64}


def test_the_dishes_are_grouped_under_food(client):
    fields = client.get("/api/fm/categories").json()["restaurant"]["fields"]
    food = [f for f in fields if f["key"] == "food"][0]
    parts = [f["key"] for f in fields if f.get("part_of") == "food"]
    assert food["computed"] == parts == ["meat", "salad", "fries", "rice", "pasta", "bread"]
    assert "drinks" in [f["key"] for f in fields]



def test_drinks_are_the_average_of_the_drinks(client):
    """2.50.1"""
    p = client.post("/api/fm/places", json={"name": "Kroen", "category": "restaurant"}).json()
    f = client.post(f"/api/fm/places/{p['id']}/reviews", json={
        "overall": 70, "fields": {"soda": 60, "coffee": 91, "meat": 80}}).json()["fields"]
    assert f["drinks"] == 76 and f["food"] == 80                  # (60 + 91) / 2 = 75.5 -> 76
    fields = client.get("/api/fm/categories").json()["restaurant"]["fields"]
    assert [x["key"] for x in fields if x.get("part_of") == "drinks"] == ["soda", "beer", "wine", "coffee"]
