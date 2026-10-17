"""Both sections against the mock Ollama over real HTTP, with the models
chosen ONLY by role in Settings (no section override): the path a fresh
install takes. Through the real queue, broker and ollama client."""
from __future__ import annotations

import io
import time


def _wait(client, path, until, timeout=15.0):
    end = time.time() + timeout
    v = None
    while time.time() < end:
        v = client.get(path).json()
        if v.get("state") in until:
            return v
        time.sleep(0.05)
    raise AssertionError(f"{path}: {v}")


def _roles(client, mock_ollama, **models):
    r = client.put("/api/settings", json={"ollamaUrl": mock_ollama, **models})
    assert r.status_code == 200, r.text


def test_okonomi_runs_on_the_settings_roles(client, mock_ollama):
    _roles(client, mock_ollama, modelChat="qwen3.6:27b")
    s = client.get("/api/ledger/summary").json()
    assert s["settings"]["model"] == "qwen3.6:27b" and s["settings"]["override"] == ""
    rows = ["01-09-2026;Betalingsservice DAVIDSENS TØMMERHANDEL A/S;-1.250,00;DKK",
            "02-09-2026;kontaktløs Dankort Zxq Shop Nota C1;-89,00;DKK",
            "03-09-2026;Betalingsservice DAVIDSENS TØMMERHANDEL A/S;-750,50;DKK"]
    r = client.post("/api/ledger/import?account=Test",
                    files={"file": ("x.csv", io.BytesIO("\n".join(rows).encode()), "text/csv")})
    assert r.status_code == 200, r.text
    cat = _wait(client, "/api/ledger/categorise", {"done", "failed", "stopped"})
    assert cat["state"] == "done" and cat["model"] == "qwen3.6:27b"   # categorise -> chat role
    client.post("/api/ledger/ask", json={"question": "How much at Davidsens?"})
    v = _wait(client, "/api/ledger/ask", {"done", "failed", "stopped"})
    assert v["state"] == "done", v
    assert v["result"]["count"] == 2 and v["result"]["total"] == 2000.5
    assert "2 transactions" in v["text"]
    labels = [st["label"] for st in v["steps"]["steps"] if st["parent"] is None]
    assert "Count in the ledger (SQL)" in labels


def test_a_categorise_role_is_used_when_set(client, mock_ollama):
    _roles(client, mock_ollama, modelChat="qwen3.6:27b", modelCategorise="gemma4:12b")
    s = client.get("/api/ledger/summary").json()["settings"]
    assert s["categoriseModel"] == "gemma4:12b" and s["model"] == "qwen3.6:27b"
    client.put("/api/ledger/settings", json={"model": "qwen3-vl:8b"})      # override wins
    s = client.get("/api/ledger/summary").json()["settings"]
    assert s["categoriseModel"] == s["model"] == "qwen3-vl:8b"


def test_without_any_model_the_page_is_told_why(client):
    r = client.post("/api/ledger/import?account=Test", files={"file": (
        "x.csv", io.BytesIO(b"01-09-2026;kontaktloes Dankort Zxq Nota 1;-10,00;DKK\n"), "text/csv")})
    assert r.status_code == 200 and "categorise" not in r.json()
    r = client.post("/api/ledger/ask", json={"question": "how much"})
    assert r.status_code == 400 and "chat model in Settings" in r.json()["detail"]
    r = client.post("/api/fm/ask", json={"question": "legeplads"})
    assert r.status_code == 400 and "chatmodel" in r.json()["detail"]


def _jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (30, 90, 60)).save(buf, "JPEG")
    return buf.getvalue()


def test_familymap_photos_and_alf_run_on_the_settings_roles(client, mock_ollama):
    from app.sections.familymap import familymap as fm
    _roles(client, mock_ollama, modelChat="gemma4:12b", modelVision="qwen3-vl:8b")
    assert fm.get_settings()["visionModel"] == ""              # no section override
    p = client.post("/api/fm/places", json={"name": "Søparken", "category": "playground",
                                            "lat": 55.246, "lng": 9.306}).json()
    rid = client.post(f"/api/fm/places/{p['id']}/reviews", json={"overall": 85}).json()["id"]
    r = client.post(f"/api/fm/reviews/{rid}/photos", files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))])
    assert r.status_code == 200, r.text
    pid = r.json()[0]["id"]
    end = time.time() + 15
    while time.time() < end and fm.get_photo(pid)["describeState"] != "done":
        time.sleep(0.05)
    ph = fm.get_photo(pid)
    assert ph["describeState"] == "done" and "legeplads" in ph["description"].lower()

    r = client.post("/api/fm/ask", json={"question": "En legeplads her", "lat": 55.246, "lng": 9.306})
    assert r.status_code == 200, r.text
    v = _wait(client, "/api/fm/ask", {"done", "failed"})
    assert v["state"] == "done", v
    assert f"[[{p['id']}]]" in v["text"]
