"""Global settings: defaults, merge, validation, environment pins, secrets,
the model roles, and the Ollama Test button."""
from __future__ import annotations

import os


def test_defaults_and_admin_only(client):
    s = client.get("/api/settings").json()
    assert s["ollamaUrl"] == "http://30.11.0.104:11434"
    assert s["modelChat"] == s["modelVision"] == s["modelCategorise"] == ""
    assert s["comfyFreeFirst"] is True and s["timezone"] == "Europe/Copenhagen"
    assert s["envPinned"] == {} and "searchApiKey" not in s


def test_a_save_merges_and_validates(client):
    r = client.put("/api/settings", json={"modelChat": "qwen3.6:27b", "contextMax": 8192})
    assert r.status_code == 200, r.text
    r = client.put("/api/settings", json={"modelVision": "qwen3-vl:8b"})
    s = r.json()
    assert (s["modelChat"], s["modelVision"], s["contextMax"]) == ("qwen3.6:27b", "qwen3-vl:8b", 8192)
    for bad in ({"ollamaUrl": "30.11.0.104:11434"}, {"contextMax": 10}, {"searchProvider": "bing"},
                {"timezone": "Mars/Olympus"}, {"comfyFreeFirst": "yes"}, {"gpuBroker": "slq"},
                {"nonsense": 1}):
        r = client.put("/api/settings", json=bad)
        assert r.status_code == 400, (bad, r.text)
    # Nothing of the refused saves landed.
    assert client.get("/api/settings").json()["ollamaUrl"] == "http://30.11.0.104:11434"


def test_the_search_key_is_never_sent_back(client):
    s = client.put("/api/settings", json={"searchApiKey": "secret-key"}).json()
    assert "searchApiKey" not in s and s["searchApiKeySet"] is True
    assert "secret-key" not in client.get("/api/settings").text
    s = client.put("/api/settings", json={"modelChat": "x"}).json()      # absent = kept
    assert s["searchApiKeySet"] is True
    s = client.put("/api/settings", json={"searchApiKey": None}).json()  # null = cleared
    assert s["searchApiKeySet"] is False


def test_an_environment_pin_wins_and_says_so(client, monkeypatch):
    monkeypatch.setenv("APP_OLLAMA_URL", "http://ollama.example:11434")
    s = client.get("/api/settings").json()
    assert s["ollamaUrl"] == "http://ollama.example:11434"
    assert s["envPinned"] == {"ollamaUrl": "APP_OLLAMA_URL"}
    r = client.put("/api/settings", json={"ollamaUrl": "http://other:11434"})
    assert r.status_code == 400 and "APP_OLLAMA_URL" in r.json()["detail"]


def test_roles_fall_back_categorise_to_chat_but_never_vision(fresh_db):
    from app.core import settings
    assert settings.role_model("chat") == "" and settings.role_model("vision") == ""
    settings.save({"modelChat": "chat-model"})
    assert settings.role_model("categorise") == "chat-model"
    assert settings.role_model("vision") == ""
    settings.save({"modelCategorise": "small"})
    assert settings.role_model("categorise") == "small"


def test_timezone_applies_to_the_process(fresh_db):
    from app.core import settings
    settings.save({"timezone": "America/New_York"})
    assert os.environ["TZ"] == "America/New_York"
    settings.save({"timezone": "Europe/Copenhagen"})
    assert os.environ["TZ"] == "Europe/Copenhagen"


def test_users_and_family_cannot_reach_settings(client):
    from fastapi.testclient import TestClient
    from app.core import auth
    from app.main import app
    auth.create_user("sanne", "pw-sanne-12345", "user")
    auth.create_user("barn", "pw-barn-1234567", "family")
    for name, pw, code in (("sanne", "pw-sanne-12345", 403), ("barn", "pw-barn-1234567", 403)):
        c = TestClient(app)
        assert c.post("/api/auth/login", json={"username": name, "password": pw}).status_code == 200
        assert c.get("/api/settings").status_code == code
        assert c.put("/api/settings", json={"modelChat": "x"}).status_code == code
        assert c.post("/api/settings/test-ollama", json={}).status_code == code
    assert client.get("/api/settings").json()["modelChat"] == ""


def test_the_test_button_lists_the_models(client, mock_ollama):
    r = client.post("/api/settings/test-ollama", json={"url": mock_ollama}).json()
    assert r["ok"] is True and r["error"] is None
    names = [m["name"] for m in r["models"]]
    assert "qwen3.6:27b" in names and "qwen3-vl:8b" in names
    assert r["models"][0]["parameters"]
    # The unsaved address was tested; the saved one did not change.
    assert client.get("/api/settings").json()["ollamaUrl"] != mock_ollama


def test_the_test_button_says_why_it_failed(client):
    from tests_helpers import closed_port_url
    r = client.post("/api/settings/test-ollama", json={"url": closed_port_url()}).json()
    assert r["ok"] is False and r["models"] == []
    assert "not answering" in r["error"]
    r = client.post("/api/settings/test-ollama", json={"url": "ftp://x"}).json()
    assert r["ok"] is False and "http" in r["error"]


def test_comfy_test_without_an_address(client):
    r = client.post("/api/settings/test-comfy", json={}).json()
    assert r["ok"] is False and "No ComfyUI address" in r["message"]


def test_meta_is_public_and_names_the_app(fresh_db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.meta import APP_DISPLAY_NAME, APP_VERSION
    r = TestClient(app).get("/api/meta").json()
    assert r == {"name": APP_DISPLAY_NAME, "version": APP_VERSION}
    assert APP_DISPLAY_NAME == "FamilyLog"
