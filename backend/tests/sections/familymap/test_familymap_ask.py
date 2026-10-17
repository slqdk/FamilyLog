"""Spørg Alf (2.46.0): town names, the search and its order (the family's
own reviews first), the web fallback, and the whole job."""
import json
import time

import pytest


def _run_localities(monkeypatch, elements):
    import asyncio
    from app.sections.familymap import familymap_osm as osm

    async def fetch(url, query):
        assert query == osm.locality_query()
        return elements
    monkeypatch.setattr(osm, "fetch", fetch)

    async def go():
        osm.start([osm.LOCALITIES], pause_s=0)
        await osm.wait()
    asyncio.run(go())
    return osm.state()


TOWNS = [
    {"type": "node", "id": 1, "lat": 55.246, "lon": 9.306,
     "tags": {"name": "Vojens", "place": "town"}},
    {"type": "node", "id": 2, "lat": 54.782, "lon": 9.436,
     "tags": {"name": "Flensburg", "name:da": "Flensborg", "place": "city"}},
    {"type": "node", "id": 3, "lat": 56.1, "lon": 10.0,
     "tags": {"name": "Vojens", "place": "hamlet"}},          # same name, smaller
]


def test_town_names_are_found_in_danish_and_german(client, monkeypatch):
    from app.sections.familymap import familymap_osm as osm
    st = _run_localities(monkeypatch, TOWNS)
    assert st["categories"]["localities"]["added"] == 3
    assert osm.find_locality("Flensborg")["name"] == "Flensburg"
    assert osm.find_locality("flensburg")["kind"] == "city"
    v = osm.find_locality("  VOJENS ")
    assert (v["kind"], round(v["lat"], 3)) == ("town", 55.246)   # the town, not the hamlet
    assert osm.find_locality("Atlantis") is None
    # A second import updates, it does not duplicate.
    st = _run_localities(monkeypatch, TOWNS)
    assert st["categories"]["localities"]["updated"] == 3


def _place(c, name, cat, lat=55.25, lng=9.31, **extra):
    r = c.post("/api/fm/places", json={"name": name, "category": cat, "lat": lat, "lng": lng})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    if extra:
        from app.core import db
        with db.connect() as con:
            con.execute("UPDATE fm_places SET extra = ? WHERE id = ?", (json.dumps(extra), pid))
    return pid


def test_search_puts_the_familys_own_good_reviews_first(client):
    from app.sections.familymap import familymap_ask as ask
    me = client.get("/api/fm/me").json()["id"]
    osm_near = _place(client, "Legepladsen ved Søen", "playground", 55.247, 9.307)
    reviewed_far = _place(client, "Legeland", "playground", 55.30, 9.40)
    bad = _place(client, "Kedelig Park", "playground", 55.246, 9.306)
    wished = _place(client, "Skovlegepladsen", "playground", 55.26, 9.33)
    too_old = _place(client, "Klatreparken", "attraction", 55.25, 9.31, min_age="8")
    far_away = _place(client, "København Legeplads", "playground", 55.68, 12.57)
    client.post(f"/api/fm/places/{reviewed_far}/reviews", json={"overall": 88, "text": "Super til de små"})
    client.post(f"/api/fm/places/{bad}/reviews", json={"overall": 30})
    client.put(f"/api/fm/wishlist/{wished}")
    intent = {"categories": ["playground", "attraction"], "keywords": [], "age": 4}
    g = ask.search((55.246, 9.306), 15, intent, me)
    assert [p["id"] for p in g["good"]] == [reviewed_far]          # though further away
    assert [p["id"] for p in g["warnings"]] == [bad]
    assert [p["id"] for p in g["wished"]] == [wished]
    assert [p["id"] for p in g["others"]] == [osm_near]
    ids = {p["id"] for grp in g.values() if isinstance(grp, list) for p in grp}
    assert too_old not in ids and far_away not in ids                 # age 4 < 8; 150 km
    ctx = ask.answer_context(g, [])
    assert ctx.index("Legeland") < ctx.index("Skovlegepladsen") < ctx.index("Legepladsen ved Søen")
    assert "Super til de små" in ctx and "88/100" in ctx


def test_keywords_match_osm_details_and_reviews(client):
    from app.sections.familymap import familymap_ask as ask
    me = client.get("/api/fm/me").json()["id"]
    pizza = _place(client, "Ristorante Roma", "restaurant", 54.78, 9.43, cuisine="pizza;pasta")
    said = _place(client, "Hafenbistro", "restaurant", 54.79, 9.44)
    _place(client, "Sushi Bar", "restaurant", 54.78, 9.44, cuisine="sushi")
    client.post(f"/api/fm/places/{said}/reviews", json={"overall": 75, "text": "Fin pizza til børnene"})
    g = ask.search((54.782, 9.436), 15, {"categories": [], "keywords": ["pizza"], "age": None}, me)
    assert [p["id"] for p in g["good"]] == [said]
    assert [p["id"] for p in g["others"]] == [pizza]
    assert g["fitting"] == 2


def test_the_intent_is_cleaned():
    from app.sections.familymap import familymap_ask as ask
    i = ask.clean_intent({"location": "Vojens", "categories": ["playground", "spa"],
                          "keywords": ["Pizza", "pizza", "x", "is"], "age": "4",
                          "radiusKm": 500, "nearMe": 0})
    assert i == {"location": "Vojens", "nearMe": False, "categories": ["playground"],
                 "keywords": ["pizza", "is"], "age": 4, "radiusKm": 80.0}
    assert ask.clean_intent({"location": "null", "age": 150})["location"] is None
    assert ask._json('```json\n{"a": 1}\n```') == {"a": 1}


def test_list_order_skips_quotes_and_numbers(client):
    for n in ('"Alte Schule"', "1401", "Bageriet", "Zoo"):
        _place(client, n, "restaurant")
    names = [p["name"] for p in client.get("/api/fm/places").json()]
    assert names == ['"Alte Schule"', "Bageriet", "Zoo", "1401"]


# ---- the whole job, with the model and the web replaced -------------------------------------------

def _fake_model(monkeypatch, understand, web_pick=None, answer="Prøv Legeland [[1]]."):
    from app.core import comfy, ollama
    calls = []

    async def free_vram(*a, **k):
        return True

    async def stream_chat(model, messages, **kw):
        calls.append((model, messages, kw))
        system = messages[0]["content"]
        if system.startswith("Du hjælper en familie"):
            yield json.dumps(understand)
        elif system.startswith("Nedenfor er søgeresultater"):
            yield json.dumps(web_pick or {"places": []})
        else:
            for piece in (answer[:5], answer[5:]):
                yield piece
    monkeypatch.setattr(comfy, "free_vram", free_vram)
    monkeypatch.setattr(ollama, "stream_chat", stream_chat)
    return calls


def _wait(client, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        v = client.get("/api/fm/ask").json()
        if v["state"] in ("done", "failed"):
            return v
        time.sleep(0.05)
    raise AssertionError(v)


def test_asking_needs_a_chosen_model(client):
    r = client.post("/api/fm/ask", json={"question": "pizza i Flensborg"})
    assert r.status_code == 400 and "chatmodel" in r.json()["detail"]
    assert client.get("/api/fm/ask").json() == {"state": "none"}


def test_a_question_is_answered_from_the_database(client, monkeypatch):
    _run_localities(monkeypatch, TOWNS)
    client.put("/api/familymap/settings", json={"chatModel": "qwen3.6:27b"})
    for i, n in enumerate(("Legeland", "Søparken", "Skovlegepladsen")):
        _place(client, n, "playground", 55.246 + i / 1000, 9.306)
    calls = _fake_model(monkeypatch, {"location": "Vojens", "categories": ["playground"],
                                      "keywords": [], "age": 4})
    r = client.post("/api/fm/ask", json={"question": "Aktivitet for mit barn på 4 år omkring Vojens"})
    assert r.status_code == 200 and r.json()["state"] in ("queued", "working", "done")
    v = _wait(client)
    assert v["state"] == "done", v
    assert v["text"] == "Prøv Legeland [[1]]." and v["where"] == "Vojens"
    assert {p["name"] for p in v["places"]} == {"Legeland", "Søparken", "Skovlegepladsen"}
    assert v["webAdded"] == 0
    assert all(c[0] == "qwen3.6:27b" for c in calls)             # FamilyMap's model, no other
    assert calls[0][2].get("response_format") == "json"
    assert "Legeland" in calls[-1][1][1]["content"]


def test_too_few_matches_go_to_the_web_and_are_saved(client, monkeypatch):
    from app.core import websearch
    _run_localities(monkeypatch, TOWNS)
    client.put("/api/familymap/settings", json={"chatModel": "m"})

    async def search(query, settings, limit=None):
        assert "pizza" in query and "Flensburg" in query
        return [{"title": "Pizzeria Napoli Flensburg", "url": "https://napoli.example",
                 "snippet": "Holm 1, Flensburg"}]
    monkeypatch.setattr(websearch, "search", search)
    _fake_model(monkeypatch, {"location": "Flensborg", "categories": ["restaurant"],
                              "keywords": ["pizza"]},
                web_pick={"places": [{"name": "Pizzeria Napoli", "category": "restaurant",
                                      "address": "Holm 1, Flensburg",
                                      "website": "https://napoli.example", "why": "pizza"},
                                     {"name": "", "category": "restaurant"},
                                     {"name": "Spa", "category": "spa"}]})
    client.post("/api/fm/ask", json={"question": "Jeg er sulten efter en pizza i Flensborg"})
    v = _wait(client)
    assert v["state"] == "done" and v["webAdded"] == 1, v
    saved = [p for p in client.get("/api/fm/places?q=Napoli").json()]
    assert len(saved) == 1 and saved[0]["source"] == "web"
    assert saved[0]["extra"]["position"].startswith("omtrentlig")
    # Asking again finds it in the database - no second copy.
    client.post("/api/fm/ask", json={"question": "Jeg er sulten efter en pizza i Flensborg"})
    _wait(client)
    assert len(client.get("/api/fm/places?q=Napoli").json()) == 1


def test_no_place_and_no_position_asks_where(client, monkeypatch):
    client.put("/api/familymap/settings", json={"chatModel": "m"})
    calls = _fake_model(monkeypatch, {"location": None, "categories": [], "keywords": ["is"]})
    client.post("/api/fm/ask", json={"question": "Hvor kan vi få is?"})
    v = _wait(client)
    assert v["state"] == "done" and "Nær mig" in v["text"]
    assert len(calls) == 1                                      # no answer call, nothing to answer from


def test_the_phones_position_is_used_when_no_town_is_named(client, monkeypatch):
    client.put("/api/familymap/settings", json={"chatModel": "m"})
    _place(client, "Isbaren", "restaurant", 55.25, 9.49, cuisine="ice_cream")
    _fake_model(monkeypatch, {"location": None, "nearMe": True, "keywords": ["ice_cream", "is"]})
    client.post("/api/fm/ask", json={"question": "is i nærheden", "lat": 55.251, "lng": 9.488})
    v = _wait(client)
    assert v["where"] == "din position" and v["radiusKm"] == 10.0
    assert [p["name"] for p in v["places"]] == ["Isbaren"]


def test_one_question_at_a_time_and_family_may_ask(client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.sections.familymap import familymap_ask as ask
    from app.main import app
    client.put("/api/familymap/settings", json={"chatModel": "m"})
    client.post("/api/familymap/users", json={"username": "mor", "password": "familie-kode-1"})
    fam = TestClient(app)
    fam.post("/api/auth/login", json={"username": "mor", "password": "familie-kode-1"})
    me = fam.get("/api/fm/me").json()["id"]
    ask._asks[me] = {"state": "working"}
    r = fam.post("/api/fm/ask", json={"question": "is?"})
    assert r.status_code == 400 and "tænker stadig" in r.json()["detail"]
    ask._asks.pop(me)
    assert fam.post("/api/fm/ask", json={"question": " "}).status_code == 400
    assert fam.post("/api/fm/ask", json={"question": "x" * 401}).status_code == 400


def test_the_pages_radius_wins(client, monkeypatch):
    """2.47.0: chosen on the Spørg Alf page; clamped to 1-80 km."""
    _run_localities(monkeypatch, TOWNS)
    client.put("/api/familymap/settings", json={"chatModel": "m"})
    _place(client, "Legeland", "playground", 55.246, 9.306)
    _fake_model(monkeypatch, {"location": "Vojens", "categories": ["playground"], "radiusKm": 30})
    client.post("/api/fm/ask", json={"question": "legeplads i Vojens", "radiusKm": 5})
    assert _wait(client)["radiusKm"] == 5.0
    client.post("/api/fm/ask", json={"question": "legeplads i Vojens"})
    assert _wait(client)["radiusKm"] == 30.0               # said in the question
    client.post("/api/fm/ask", json={"question": "legeplads i Vojens", "radiusKm": 500})
    assert _wait(client)["radiusKm"] == 80.0


def test_the_map_gets_every_place_compact_gzipped_and_cached(client):
    import gzip
    import json as _json
    a = _place(client, "Legeland", "playground", 55.2461234, 9.306)
    b = _place(client, "Kroen", "restaurant", 55.25, 9.31)
    client.post("/api/fm/places", json={"name": "Uden position", "category": "city"})
    client.post(f"/api/fm/places/{a}/reviews", json={"overall": 80})
    client.put(f"/api/fm/wishlist/{b}")
    r = client.get("/api/fm/map", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    data = r.json()                            # httpx un-gzips
    cats = data["cats"]
    assert data["points"] == [[a, 55.24612, 9.306, cats.index("playground"), 1, "Legeland"],
                              [b, 55.25, 9.31, cats.index("restaurant"), 2, "Kroen"]]
    again = client.get("/api/fm/map", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    client.post(f"/api/fm/places/{b}/reviews", json={"overall": 60})
    changed = client.get("/api/fm/map", headers={"If-None-Match": r.headers["etag"]})
    assert changed.status_code == 200 and changed.json()["points"][1][4] == 3


def test_each_step_has_a_phase_for_the_animation(client, monkeypatch):
    """2.48.0: the phone animates by phase; thinking has its own."""
    from app.sections.familymap import familymap_ask as ask
    from app.core import comfy, ollama
    _run_localities(monkeypatch, TOWNS)
    client.put("/api/familymap/settings", json={"chatModel": "m"})
    _place(client, "Legeland", "playground", 55.246, 9.306)
    me = client.get("/api/fm/me").json()["id"]
    seen = []

    async def free_vram(*a, **k):
        return True

    async def stream_chat(model, messages, **kw):
        seen.append(ask._asks[me]["phase"])
        if messages[0]["content"].startswith("Du hjælper en familie"):
            yield json.dumps({"location": "Vojens", "categories": ["playground"]})
            return
        kw["on_thinking"]("hmm")
        seen.append(ask._asks[me]["phase"])
        yield "Prøv Legeland [[1]]"
        seen.append(ask._asks[me]["phase"])
        kw["on_thinking"]("more")          # late reasoning must not flip it back
        seen.append(ask._asks[me]["phase"])
    monkeypatch.setattr(comfy, "free_vram", free_vram)
    monkeypatch.setattr(ollama, "stream_chat", stream_chat)
    client.post("/api/fm/ask", json={"question": "legeplads i Vojens"})
    v = _wait(client)
    assert v["state"] == "done"
    assert seen == ["understand", "write", "think", "write", "write"]


def test_the_answer_prompt_forbids_talking_about_the_groups():
    from app.sections.familymap import familymap_ask as ask
    assert "Nævn ALDRIG grupperne" in ask.ANSWER_PROMPT


# ---- 2.49.0: Aktivitet, and the address of a tapped point ------------------------------------

def test_activity_query_takes_swimming_and_skips_private_pools():
    from app.sections.familymap import familymap_osm as osm
    q = osm.build_query("activity")
    assert '["leisure"~"^(sports_centre|sports_hall)$"]["sport"~"swimming"]["name"]' in q
    assert '["access"!~"^(private|no|customers)$"]' in q
    for kind in ("indoor_play", "trampoline_park", "ice_rink", "cinema", "climbing"):
        assert kind in q
    assert "sport~swimming" in " ".join(osm.describe_sources()["sources"]["activity"])


NOMINATIM_POOL = {
    "category": "leisure", "type": "sports_centre", "name": "Vojens Svømmehal",
    "display_name": "Vojens Svømmehal, Vestergade, Vojens",
    "address": {"road": "Vestergade", "house_number": "12", "postcode": "6500",
                "town": "Vojens", "country": "Danmark"}}


def test_a_tapped_point_gets_address_name_and_category(client, monkeypatch):
    from app.sections.familymap import familymap_geo as geo
    monkeypatch.setattr(geo, "MIN_INTERVAL_S", 0)
    geo._cache.clear()
    calls = []

    async def nominatim(lat, lng):
        calls.append((lat, lng))
        return NOMINATIM_POOL
    monkeypatch.setattr(geo, "nominatim", nominatim)
    r = client.get("/api/fm/reverse?lat=55.25166&lng=9.31307").json()
    assert r == {"address": "Vestergade 12, 6500 Vojens", "name": "Vojens Svømmehal",
                 "category": "activity", "source": "nominatim", "road": "Vestergade"}
    client.get("/api/fm/reverse?lat=55.251661&lng=9.313071")      # same point, cached
    assert len(calls) == 1


def test_a_road_gives_an_address_but_no_name(client, monkeypatch):
    from app.sections.familymap import familymap_geo as geo
    out = geo.interpret({"category": "highway", "type": "residential", "name": "Vestergade",
                         "address": {"road": "Vestergade", "postcode": "6500", "town": "Vojens"}})
    assert out == {"address": "Vestergade, 6500 Vojens", "name": None, "category": None,
                   "source": "nominatim", "road": "Vestergade"}


def test_without_nominatim_the_nearest_town_answers(client, monkeypatch):
    from app.sections.familymap import familymap_geo as geo
    _run_localities(monkeypatch, TOWNS)
    monkeypatch.setattr(geo, "MIN_INTERVAL_S", 0)
    geo._cache.clear()

    async def down(lat, lng):
        raise OSError("offline")
    monkeypatch.setattr(geo, "nominatim", down)
    r = client.get("/api/fm/reverse?lat=55.26&lng=9.32").json()
    assert r == {"address": "nær Vojens", "name": None, "category": None, "source": "town",
                 "road": None}
    assert client.get("/api/fm/reverse?lat=95&lng=9").status_code == 400



# ---- 2.49.1: unnamed playgrounds ------------------------------------------------------------

def test_unnamed_playgrounds_get_a_street_or_town_name(client, monkeypatch):
    from app.sections.familymap import familymap_osm as osm
    _run_localities(monkeypatch, TOWNS)
    q = osm.build_query("playground")
    assert '[!"name"]["access"!~"^(private|no|customers)$"](area.r)' in q
    assert '[!"name"]["access"!~"^(private|no|customers)$"]["name"]' not in q
    els = [
        {"type": "node", "id": 1, "lat": 55.25, "lon": 9.31, "tags": {"leisure": "playground",
                                                                      "addr:street": "Vestergade"}},
        {"type": "way", "id": 2, "center": {"lat": 55.247, "lon": 9.307},
         "tags": {"leisure": "playground"}},
        {"type": "node", "id": 3, "lat": 57.7, "lon": 10.6, "tags": {"leisure": "playground"}},
        {"type": "node", "id": 4, "lat": 55.25, "lon": 9.31, "tags": {"leisure": "playground",
                                                                      "name": "Legeland"}},
    ]
    rows = osm.parse(els, "playground", osm._Towns())
    assert [(r["name"], r["extra"].get("nameGenerated")) for r in rows] == [
        ("Legeplads, Vestergade", "street"), ("Legeplads ved Vojens", "town"),
        ("Legeplads", "none"), ("Legeland", None)]


def test_opening_a_town_named_playground_gives_it_its_street_once(client, monkeypatch):
    import asyncio
    from app.sections.familymap import familymap_geo as geo, familymap_osm as osm
    _run_localities(monkeypatch, TOWNS)
    monkeypatch.setattr(geo, "MIN_INTERVAL_S", 0)
    geo._cache.clear()
    el = {"type": "way", "id": 2, "center": {"lat": 55.247, "lon": 9.307},
          "tags": {"leisure": "playground"}}

    async def fetch(url, query):
        return [el] if query == osm.build_query("playground") else []
    monkeypatch.setattr(osm, "fetch", fetch)

    async def go():
        osm.start(["playground"], pause_s=0)
        await osm.wait()
    asyncio.run(go())
    pid = client.get("/api/fm/places?category=playground").json()[0]["id"]
    calls = []

    async def nominatim(lat, lng):
        calls.append(1)
        return {"category": "leisure", "type": "playground",
                "address": {"road": "Skovvej", "postcode": "6500", "town": "Vojens"}}
    monkeypatch.setattr(geo, "nominatim", nominatim)
    p = client.get(f"/api/fm/places/{pid}").json()
    assert p["name"] == "Legeplads, Skovvej" and p["extra"]["nameGenerated"] == "lookup"
    assert p["address"] == "Skovvej, 6500 Vojens"
    geo._cache.clear()
    client.get(f"/api/fm/places/{pid}")
    assert len(calls) == 1                                   # never again
    # The next import keeps the looked-up name.
    asyncio.run(go())
    assert client.get(f"/api/fm/places/{pid}").json()["name"] == "Legeplads, Skovvej"


# ---- 2.49.2: "5 legepladser i Vojens" went to the web --------------------------------------

def test_stem_takes_danish_endings_off():
    from app.sections.familymap import familymap_ask as ask
    assert ask.stem("legepladser") == "legeplads"
    assert ask.stem("Svømmehallerne") == "svømmehal"
    assert ask.stem("pizza") == "pizza" and ask.stem("is") == "is"


def test_words_that_only_name_the_category_are_dropped():
    from app.sections.familymap import familymap_ask as ask
    i = ask.drop_category_words({"categories": ["playground"], "age": None,
                                 "keywords": ["legepladser", "playground", "gynger"]})
    assert i["keywords"] == ["gynger"]
    j = ask.drop_category_words({"categories": [], "age": None, "keywords": ["legepladser"]})
    assert j["keywords"] == ["legepladser"]                  # no category to lean on


def test_plural_words_match_and_the_web_is_not_asked(client, monkeypatch):
    from app.core import websearch
    _run_localities(monkeypatch, TOWNS)
    client.put("/api/familymap/settings", json={"chatModel": "m"})
    for i in range(5):
        _place(client, "Legeplads ved Vojens", "playground", 55.246 + i / 1000, 9.306)

    async def no_web(*a, **k):
        raise AssertionError("the web must not be asked")
    monkeypatch.setattr(websearch, "search", no_web)
    # The model's reading of "Jeg vil gerne have en liste over 5 legepladser i Vojens".
    _fake_model(monkeypatch, {"location": "Vojens", "categories": ["playground"],
                              "keywords": ["legepladser", "liste"]})
    client.post("/api/fm/ask", json={"question": "Jeg vil gerne have en liste over 5 legepladser i Vojens"})
    v = _wait(client)
    assert v["state"] == "done" and v["webAdded"] == 0, v
    assert len(v["places"]) == 5
    assert v["searched"] == "Legeplads"          # "liste" is a stop word, "legepladser" the category
    assert v["relaxed"] is False


def test_a_plural_keyword_still_finds_a_singular_place(client):
    from app.sections.familymap import familymap_ask as ask
    me = client.get("/api/fm/me").json()["id"]
    _place(client, "Vojens Svømmehal", "activity", 55.25, 9.31)
    g = ask.search((55.25, 9.31), 10, {"categories": [], "keywords": ["svømmehaller"], "age": None}, me)
    assert [p["name"] for p in g["others"]] == ["Vojens Svømmehal"]


# ---- 2.49.3: the family's own "Passer til alder" ------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("3-10 år", (3, 10)), ("3 – 10", (3, 10)), ("3 til 10 år", (3, 10)), ("10-3", (3, 10)),
    ("fra 5 år", (5, None)), ("5+", (5, None)), ("over 5", (6, None)),
    ("under 6", (None, 5)), ("op til 12 år", (None, 12)), ("højst 8", (None, 8)),
    ("4 år", None), ("alle aldre", None), ("", None),
])
def test_age_ranges_are_read(text, expected):
    from app.sections.familymap import familymap_ask as ask
    assert ask.parse_age_range(text) == expected


def test_the_familys_age_range_decides_over_osm(client):
    from app.sections.familymap import familymap_ask as ask
    me = client.get("/api/fm/me").json()["id"]
    big = _place(client, "Klatrehallen", "activity", 55.25, 9.31)          # no OSM limit
    small = _place(client, "Babysvømning", "activity", 55.251, 9.31, min_age="0", max_age="2")
    unknown = _place(client, "Biografen", "activity", 55.252, 9.31)
    client.post(f"/api/fm/places/{big}/reviews", json={"overall": 90, "fields": {"ageRange": "fra 8 år"}})
    client.post(f"/api/fm/places/{small}/reviews", json={"overall": 85, "fields": {"ageRange": "0-6 år"}})
    g = ask.search((55.25, 9.31), 10, {"categories": ["activity"], "keywords": [], "age": 4}, me)
    ids = [p["id"] for grp in ("good", "wished", "others") for p in g[grp]]
    assert big not in ids                        # the family said 8+
    assert small in ids                          # the family said 0-6, though OSM says 0-2
    assert unknown in ids                        # nobody said anything
    assert "Passer til alder: 0-6 år" in ask.answer_context(g, [])


def test_the_age_field_has_a_clear_label_and_example(client):
    cats = client.get("/api/fm/categories").json()
    for c in ("playground", "activity", "attraction"):
        f = [f for f in cats[c]["fields"] if f["key"] == "ageRange"][0]
        assert f["label"] == "Passer til alder" and f["placeholder"] == "fx 3-10 år"



# ---- 2.49.4: a word beats the model's guess at the category -------------------------------

def test_the_familys_chestnut_tree_is_found_though_filed_elsewhere(client):
    """"Kan man finde kastanjer i Vojens?" - read as Natur, while the family's
    own chestnut tree is under Oplevelse."""
    from app.sections.familymap import familymap_ask as ask
    me = client.get("/api/fm/me").json()["id"]
    tree = _place(client, "Kastanjetræ på høttepladsen", "attraction", 55.249, 9.304)
    client.post(f"/api/fm/places/{tree}/reviews", json={"overall": 100, "text": "Vi samlede kastanjer"})
    for i, n in enumerate(("Tørning voldsted", "Hjarup Mose", "Kløften", "Fjorden")):
        _place(client, n, "nature", 55.25 + i / 100, 9.31)
    g = ask.find((55.246, 9.306), 15, {"categories": ["nature"], "keywords": ["kastanjer"],
                                       "age": None}, me)
    assert [p["id"] for p in g["good"]] == [tree]
    assert g["others"] == []                         # nature places without the word are not a match


def test_word_matches_come_before_category_only_places(client):
    from app.sections.familymap import familymap_ask as ask
    me = client.get("/api/fm/me").json()["id"]
    near_plain = _place(client, "Skoven", "nature", 55.2461, 9.3061)
    far_word = _place(client, "Kastanjealléen", "nature", 55.30, 9.40)
    other_cat_word = _place(client, "Kastanjebageriet", "restaurant", 55.26, 9.33)
    for i in range(3):
        _place(client, f"Kastanjeskov {i}", "nature", 55.27 + i / 100, 9.35)
    g = ask.find((55.246, 9.306), 15, {"categories": ["nature"], "keywords": ["kastanje"],
                                       "age": None}, me)
    names = [p["name"] for p in g["others"]]
    assert near_plain not in [p["id"] for p in g["others"]]   # enough word matches: no fill-in
    assert "Kastanjebageriet" in names



# ---- 2.49.6: "græsk restaurant i Flensborg" ----------------------------------------------------

def test_danish_food_words_find_osm_cuisine_and_german_names(client):
    from app.sections.familymap import familymap_ask as ask
    me = client.get("/api/fm/me").json()["id"]
    olympia = _place(client, "Olympia", "restaurant", 54.782, 9.436, cuisine="greek")
    akropolis = _place(client, "Griechisches Restaurant Akropolis", "restaurant", 54.783, 9.437)
    _place(client, "Vertigo", "restaurant", 54.784, 9.438, cuisine="mediterranean")
    g = ask.find((54.782, 9.436), 15, {"categories": ["restaurant"], "keywords": ["græsk"],
                                       "age": None}, me)
    assert {p["id"] for p in g["others"]} == {olympia, akropolis}
    assert ask.expand(["græske"])[:3] == ["græsk", "greek", "griech"]
    assert ask.expand(["island"]) == ["island"]            # not "is" (ice cream)
    assert "ice_cream" in ask.expand(["is"])


def test_stop_words_are_not_searched_for():
    from app.sections.familymap import familymap_ask as ask
    i = ask.clean_intent({"keywords": ["liste", "forslag", "pizza", "steder"]})
    assert i["keywords"] == ["pizza"]


def test_too_few_word_matches_ask_the_web_before_the_rest_of_the_category(client, monkeypatch):
    from app.core import websearch
    _run_localities(monkeypatch, TOWNS)
    client.put("/api/familymap/settings", json={"chatModel": "m"})
    fav = _place(client, "Steakhouse", "restaurant", 54.782, 9.436)
    client.post(f"/api/fm/places/{fav}/reviews", json={"overall": 95})
    for i in range(4):
        _place(client, f"Café {i}", "restaurant", 54.783 + i / 1000, 9.437)
    asked = []

    async def search(query, settings, limit=None):
        asked.append(query)
        return [{"title": "Taverna Olympia Flensburg", "url": "https://olympia.example",
                 "snippet": "Griechisches Restaurant, Norderstraße 5"}]
    monkeypatch.setattr(websearch, "search", search)
    calls = _fake_model(monkeypatch, {"location": "Flensborg", "categories": ["restaurant"],
                                      "keywords": ["græsk"]},
                        web_pick={"places": [{"name": "Taverna Olympia", "category": "restaurant",
                                              "address": "Norderstraße 5, Flensburg"}]})
    client.post("/api/fm/ask", json={"question": "Græsk restaurant i Flensborg"})
    v = _wait(client)
    assert v["state"] == "done" and v["webAdded"] == 1, v
    assert asked == ["græsk restaurant Flensburg"]
    names = [p["name"] for p in v["places"]]
    assert names[0] == "Taverna Olympia"                      # the web find before the fill
    assert "Steakhouse" in names and v["relaxed"] is True     # offered only as "if nothing else"
    context = calls[-1][1][1]["content"]
    assert context.index("Taverna Olympia") < context.index("UDEN det der blev spurgt om")
    assert context.index("UDEN det der blev spurgt om") < context.index("Steakhouse")


def test_near_the_phone_the_web_is_asked_about_the_nearest_town(client, monkeypatch):
    from app.core import websearch
    _run_localities(monkeypatch, TOWNS)
    client.put("/api/familymap/settings", json={"chatModel": "m"})
    asked = []

    async def search(query, settings, limit=None):
        asked.append(query)
        return []
    monkeypatch.setattr(websearch, "search", search)
    _fake_model(monkeypatch, {"location": None, "nearMe": True, "categories": ["restaurant"],
                              "keywords": ["sushi"]})
    client.post("/api/fm/ask", json={"question": "sushi i nærheden", "lat": 55.247, "lng": 9.305})
    _wait(client)
    assert asked == ["sushi restaurant Vojens"]


# ---- 2.49.7: the search box knows the towns' other names ------------------------------------

def test_the_search_box_finds_flensburg_by_its_danish_name(client, monkeypatch):
    _run_localities(monkeypatch, TOWNS)
    client.post("/api/fm/places", json={"name": "Olympia", "category": "restaurant",
                                         "address": "Holm 12, 24937 Flensburg"})
    client.post("/api/fm/places", json={"name": "Pizza Roma", "category": "restaurant",
                                         "address": "Norderstraße 5, 24939 Flensburg"})
    client.post("/api/fm/places", json={"name": "Pizza Top", "category": "restaurant",
                                         "address": "Vestergade 3, 6500 Vojens"})
    names = lambda q: sorted(p["name"] for p in client.get("/api/fm/places", params={"q": q}).json())
    assert names("Flensborg") == ["Olympia", "Pizza Roma"]
    assert names("flensburg") == ["Olympia", "Pizza Roma"]
    assert names("pizza flensborg") == ["Pizza Roma"]               # every word must match
    assert names("pizza") == ["Pizza Roma", "Pizza Top"]


def test_search_folds_danish_capitals(client):
    client.post("/api/fm/places", json={"name": "Østerby Legeplads", "category": "playground"})
    assert [p["name"] for p in client.get("/api/fm/places", params={"q": "østerby"}).json()] == \
        ["Østerby Legeplads"]
