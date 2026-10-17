"""FamilyMap release 2 (2.44.0): OSM import, settings, near-me order, and
photo descriptions through the GPU queue."""
import io
import time

import pytest


def _el(i, name="Kroen", kind="node", tags=None, center=False, **extra_tags):
    t = {"name": name, **(tags or {}), **extra_tags} if name else dict(tags or {})
    el = {"type": kind, "id": i, "tags": t}
    if center:
        el["center"] = {"lat": 55.25, "lon": 9.49}
    else:
        el["lat"], el["lon"] = 55.25, 9.49
    return el


def _run_import(monkeypatch, by_category: dict, cats=None):
    """Run the import for real, with Overpass replaced by a dict."""
    import asyncio
    from app.sections.familymap import familymap_osm as osm
    seen_queries = []

    async def fake_fetch(url, query):
        seen_queries.append(query)
        for cat in osm.OSM_SOURCES:
            if query == osm.build_query(cat):
                return by_category.get(cat, [])
        if query == osm.locality_query():
            return by_category.get("localities", [])
        raise AssertionError(query)
    monkeypatch.setattr(osm, "fetch", fake_fetch)

    async def go():
        osm.start(cats, pause_s=0)
        await osm.wait()
    asyncio.run(go())
    return osm.state(), seen_queries


# ---- OSM --------------------------------------------------------------------------

def test_the_query_covers_the_region_and_wants_names():
    from app.sections.familymap import familymap_osm as osm
    q = osm.build_query("restaurant")
    for part in ('"ISO3166-1"="DK"', '"ISO3166-2"="DE-SH"', '"ISO3166-2"="DE-HH"',
                 'fast_food', 'ice_cream', '["name"]', 'out center qt'):
        assert part in q, part
    assert "park" in osm.build_query("nature") and "camp_site" not in osm.build_query("hotel")
    assert 'node["place"~"^(city|town)$"]' in osm.build_query("city")


def test_parse_skips_unnamed_and_reads_ways_and_addresses():
    from app.sections.familymap import familymap_osm as osm
    els = [
        _el(1, "Legeland", tags={"addr:street": "Torvet", "addr:housenumber": "3",
                                 "addr:postcode": "6500", "addr:city": "Vojens",
                                 "min_age": "3", "website": "https://x.dk", "brand": "no"}),
        _el(2, name=""),                                   # unnamed: skipped
        _el(3, "Skoven", kind="way", center=True),
        {"type": "way", "id": 4, "tags": {"name": "Uden position"}},
    ]
    rows = osm.parse(els, "attraction")      # a category that skips unnamed ones
    assert [r["sourceId"] for r in rows] == ["node/1", "way/3"]
    assert rows[0]["address"] == "Torvet 3, 6500 Vojens"
    assert rows[0]["extra"] == {"min_age": "3"} and rows[0]["website"] == "https://x.dk"
    assert (rows[1]["lat"], rows[1]["lng"]) == (55.25, 9.49)


def test_import_adds_then_updates_and_never_duplicates(client, monkeypatch):
    first = {"restaurant": [_el(1, "Kroen"), _el(2, "Isbaren", amenity="ice_cream")],
             "attraction": [_el(1, "Kroen")]}                # same feature twice
    st, queries = _run_import(monkeypatch, first)
    assert len(queries) == 8 and not st["running"]      # 7 categories + town names
    assert st["categories"]["restaurant"]["added"] == 2
    assert st["categories"]["attraction"]["added"] == 0
    places = client.get("/api/fm/places").json()
    assert sorted(p["name"] for p in places) == ["Isbaren", "Kroen"]
    assert {p["source"] for p in places} == {"osm"}
    assert client.get("/api/familymap/stats").json()["sources"] == {"osm": 2}

    # Second run: one renamed, one the same, and the category stays put.
    again = {"attraction": [_el(1, "Kroen Ny")], "restaurant": [_el(2, "Isbaren")]}
    st, _ = _run_import(monkeypatch, again, cats=["attraction", "restaurant"])
    assert st["categories"]["attraction"]["updated"] == 1
    assert st["categories"]["restaurant"]["unchanged"] == 1
    kro = [p for p in client.get("/api/fm/places").json() if p["sourceId"] == "node/1"][0]
    assert kro["name"] == "Kroen Ny" and kro["category"] == "restaurant"


def test_an_admin_correction_survives_the_next_import(client, monkeypatch):
    _run_import(monkeypatch, {"restaurant": [_el(1, "Kroen")]}, cats=["restaurant"])
    pid = client.get("/api/fm/places").json()[0]["id"]
    r = client.put(f"/api/familymap/places/{pid}", json={"name": "Kroen i Vojens"})
    assert r.json()["locked"] is True
    st, _ = _run_import(monkeypatch, {"restaurant": [_el(1, "Kroen (OSM)")]}, cats=["restaurant"])
    assert st["categories"]["restaurant"]["locked"] == 1
    assert client.get(f"/api/fm/places/{pid}").json()["name"] == "Kroen i Vojens"


def test_a_failing_category_does_not_stop_the_rest(client, monkeypatch):
    import asyncio
    from app.sections.familymap import familymap_osm as osm

    async def fetch(url, query):
        if query == osm.build_query("hotel"):
            raise RuntimeError("Overpass is busy (429). Try again in a few minutes.")
        return [_el(5, "Stranden")] if query == osm.build_query("nature") else []
    monkeypatch.setattr(osm, "fetch", fetch)

    async def go():
        osm.start(["hotel", "nature"], pause_s=0)
        await osm.wait()
    asyncio.run(go())
    st = osm.state()
    assert st["categories"]["hotel"]["state"] == "failed" and "429" in st["categories"]["hotel"]["error"]
    assert st["categories"]["nature"]["added"] == 1


def test_import_endpoints_are_admin_only(client):
    from fastapi.testclient import TestClient
    from app.main import app
    client.post("/api/familymap/users", json={"username": "mor", "password": "familie-kode-1"})
    fam = TestClient(app)
    fam.post("/api/auth/login", json={"username": "mor", "password": "familie-kode-1"})
    for method, path in (("get", "/api/familymap/import"), ("post", "/api/familymap/import"),
                         ("get", "/api/familymap/settings"), ("post", "/api/familymap/describe")):
        assert getattr(fam, method)(path).status_code == 403, path
    info = client.get("/api/familymap/import").json()
    assert info["region"].startswith("Danmark") and "playground" in info["sources"]
    assert client.post("/api/familymap/import", json={"categories": ["spa"]}).status_code == 400


# ---- near me ------------------------------------------------------------------------

def test_near_me_orders_by_distance(client):
    for name, lat, lng in (("Esbjerg", 55.476, 8.459), ("Vojens", 55.246, 9.306),
                           ("Hamburg", 53.551, 9.994)):
        client.post("/api/fm/places", json={"name": name, "category": "city", "lat": lat, "lng": lng})
    client.post("/api/fm/places", json={"name": "Uden position", "category": "city"})
    rows = client.get("/api/fm/places?lat=55.25&lng=9.49").json()      # Haderslev
    assert [r["name"] for r in rows] == ["Vojens", "Esbjerg", "Hamburg"]
    assert 10 < rows[0]["distanceKm"] < 14
    assert client.get("/api/fm/places?lat=95&lng=9").status_code == 400
    assert "distanceKm" not in client.get("/api/fm/places").json()[0]


# ---- settings ------------------------------------------------------------------------

def test_settings_are_explicit_and_validated(client):
    s = client.get("/api/familymap/settings").json()
    assert s["chatModel"] == "" and s["visionModel"] == ""        # no fallback
    r = client.put("/api/familymap/settings", json={"visionModel": "qwen3-vl:8b"})
    assert r.json()["visionModel"] == "qwen3-vl:8b" and r.json()["chatModel"] == ""
    assert client.put("/api/familymap/settings", json={"model": "x"}).status_code == 400
    assert client.put("/api/familymap/settings",
                      json={"overpassUrl": "ftp://x"}).status_code == 400


# ---- photo descriptions ------------------------------------------------------------------

def _photo(client, size=(640, 480)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 90, 60)).save(buf, "JPEG")
    p = client.post("/api/fm/places", json={"name": "Legeland", "category": "playground"}).json()
    rid = client.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 80}).json()["id"]
    r = client.post(f"/api/fm/reviews/{rid}/photos",
                    files=[("files", ("a.jpg", buf.getvalue(), "image/jpeg"))])
    assert r.status_code == 200, r.text
    return r.json()[0]


def _wait_state(client, photo_id, states, timeout=10.0):
    from app.sections.familymap import familymap as fm
    end = time.time() + timeout
    while time.time() < end:
        ph = fm.get_photo(photo_id)
        if ph["describeState"] in states:
            return ph
        time.sleep(0.05)
    raise AssertionError(fm.get_photo(photo_id))


def test_without_a_vision_model_photos_wait(client):
    ph = _photo(client)
    assert ph["describeState"] == "nomodel"
    assert client.post("/api/familymap/describe").status_code == 400
    assert client.get("/api/familymap/stats").json()["photoStates"]["nomodel"] == 1


def test_upload_describes_through_the_queue(client, monkeypatch):
    from app.sections.familymap import familymap_vision as vision
    from app.core import comfy, ollama
    calls = {}

    async def free_vram(*a, **k):
        calls["freed"] = True
        return True

    async def stream_chat(model, messages, **kw):
        calls["model"] = model
        calls["messages"] = messages
        for piece in ("Stor legeplads med ", "gynger og skygge."):
            yield piece
    monkeypatch.setattr(comfy, "free_vram", free_vram)
    monkeypatch.setattr(ollama, "stream_chat", stream_chat)
    client.put("/api/familymap/settings", json={"visionModel": "qwen3-vl:8b"})
    ph = _photo(client)
    assert ph["describeState"] in ("queued", "done")
    done = _wait_state(client, ph["id"], {"done"})
    assert done["description"] == "Stor legeplads med gynger og skygge."
    assert calls["model"] == "qwen3-vl:8b" and calls["freed"]
    user = calls["messages"][1]
    assert user["images"] and "Legeland" in user["content"]
    assert "personernes udseende" in calls["messages"][0]["content"]
    assert vision.queue_key(ph["id"]) < -vision.QUEUE_BASE + 1


def test_a_failed_description_can_be_retried(client, monkeypatch):
    from app.core import comfy, ollama

    async def free_vram(*a, **k):
        return True

    async def broken(model, messages, **kw):
        raise RuntimeError("model not found")
        yield ""  # pragma: no cover
    monkeypatch.setattr(comfy, "free_vram", free_vram)
    monkeypatch.setattr(ollama, "stream_chat", broken)
    client.put("/api/familymap/settings", json={"visionModel": "missing:1b"})
    ph = _photo(client)
    failed = _wait_state(client, ph["id"], {"failed"})
    assert "model not found" in failed["describeError"]

    async def works(model, messages, **kw):
        yield "En strand."
    monkeypatch.setattr(ollama, "stream_chat", works)
    assert client.post("/api/familymap/describe").json()["queued"] == 1
    assert _wait_state(client, ph["id"], {"done"})["description"] == "En strand."


def test_import_start_and_stop_answer_with_the_full_view(client, monkeypatch):
    """2.44.0 crashed the admin page: POST answered without `sources`."""
    from app.sections.familymap import familymap_osm as osm

    async def slow(url, query):
        import asyncio
        await asyncio.sleep(5)
        return []
    monkeypatch.setattr(osm, "fetch", slow)
    got = client.get("/api/familymap/import").json()
    started = client.post("/api/familymap/import", json={"categories": ["city"]}).json()
    stopped = client.post("/api/familymap/import/stop").json()
    for view in (got, started, stopped):
        assert set(view) >= {"running", "categories", "sources", "region"}
        assert "restaurant" in view["sources"]
    assert started["running"] is True and "city" in started["categories"]


def test_the_family_page_name_is_a_setting_and_public(client):
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)                                  # not signed in
    assert anon.get("/api/fm/brand").json() == {"name": "Alf\u2019s Atlas"}
    assert anon.get("/api/fm/categories").status_code == 401   # the rest is not public
    client.put("/api/familymap/settings", json={"appName": "Familiens Kort"})
    assert anon.get("/api/fm/brand").json()["name"] == "Familiens Kort"
    client.put("/api/familymap/settings", json={"appName": "  "})
    assert anon.get("/api/fm/brand").json()["name"] == "Alf\u2019s Atlas"   # empty = default
    assert client.put("/api/familymap/settings", json={"appName": "x" * 41}).status_code == 400


def test_a_busy_overpass_is_retried_then_given_up(client, monkeypatch):
    """The first real run lost city and playground to 504s. (2.44.1)"""
    import asyncio
    from app.sections.familymap import familymap_osm as osm
    monkeypatch.setattr(osm, "RETRY_WAITS_S", (0.0, 0.0))
    tries = {"city": 0, "playground": 0}

    async def fetch(url, query):
        cat = "city" if query == osm.build_query("city") else "playground"
        tries[cat] += 1
        if cat == "city" and tries[cat] < 3:
            raise osm.Busy("Overpass is busy (504).")
        if cat == "playground":
            raise osm.Busy("Overpass is busy (504).")
        return [_el(9, "Vojens", place="town")]
    monkeypatch.setattr(osm, "fetch", fetch)

    async def go():
        osm.start(["city", "playground"], pause_s=0)
        await osm.wait()
    asyncio.run(go())
    st = osm.state()["categories"]
    assert tries == {"city": 3, "playground": 3}
    assert st["city"]["state"] == "done" and st["city"]["added"] == 1 and not st["city"].get("error")
    assert st["playground"]["state"] == "failed" and "3 tries" in st["playground"]["error"]


def test_fetch_turns_busy_statuses_into_busy(monkeypatch):
    import asyncio
    import httpx
    from app.sections.familymap import familymap_osm as osm

    def handler(request):
        return httpx.Response(504, text="timeout")
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(osm.Busy, match="504"):
        asyncio.run(osm.fetch("https://overpass.test/api/interpreter", "[out:json];"))
