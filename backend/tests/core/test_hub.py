"""SLQ Hub as the AI server (0.4.0): an address and an app key in Settings.
The key goes as `Authorization: Bearer` - never in an address, a message, a
log line or the settings the page gets back. The mock speaks the Hub's
refusal (401) for a revoked key."""
from __future__ import annotations

KEY = "slqhub_test0123456789abcdef"


def test_the_key_is_stored_but_never_shown(client):
    r = client.put("/api/settings", json={"aiServer": "hub", "hubUrl": "http://30.11.0.140", "hubKey": KEY})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["aiServer"] == "hub" and s["hubKeySet"] is True and s["hubKeyHint"] == "slqhub_test…"
    assert KEY not in r.text and "hubKey" not in s
    assert KEY not in client.get("/api/settings").text
    for bad in ({"hubKey": "sk-not-a-hub-key"}, {"hubKey": "slqhub_a/b"}, {"aiServer": "claude"},
                {"hubUrl": "30.11.0.140"}):
        assert client.put("/api/settings", json=bad).status_code == 400, bad
    assert client.put("/api/settings", json={"hubKey": None}).json()["hubKeySet"] is False


def test_the_hubs_whole_ollama_line_can_be_pasted(client):
    """The Hub's Settings → Apps and keys shows http://HUB:11434/k/slqhub_.../ -
    pasted as the address, the key is split off into the key field."""
    s = client.put("/api/settings", json={"hubUrl": f"http://30.11.0.140:11434/k/{KEY}/"}).json()
    assert s["hubUrl"] == "http://30.11.0.140:11434" and s["hubKeySet"] and KEY not in str(s)


def test_the_hub_address_gets_port_11434(fresh_db):
    from app.core import settings
    assert settings.hub_base("http://30.11.0.140") == "http://30.11.0.140:11434"
    assert settings.hub_base("http://30.11.0.140/") == "http://30.11.0.140:11434"
    assert settings.hub_base("http://hub.lan:8080") == "http://hub.lan:8080"     # the same app on 8080
    assert settings.hub_base("") == ""


def test_the_test_button_with_the_hub(client, mock_ollama):
    port_url = mock_ollama                       # http://127.0.0.1:<port>
    r = client.post("/api/settings/test-ollama", json={"server": "hub", "url": port_url, "key": KEY}).json()
    assert r["ok"] is True and "qwen3.6:27b" in [m["name"] for m in r["models"]], r
    bad = client.post("/api/settings/test-ollama",
                      json={"server": "hub", "url": port_url, "key": "slqhub_revoked0123456789"}).json()
    assert bad["ok"] is False and "refused the key" in bad["error"] and "revoked" not in str(bad)
    none = client.post("/api/settings/test-ollama", json={"server": "hub", "url": port_url}).json()
    assert none["ok"] is False and "No SLQ Hub key" in none["error"]
    # The whole line pasted into the address field works for the test too.
    r = client.post("/api/settings/test-ollama", json={"server": "hub", "url": f"{port_url}/k/{KEY}/"}).json()
    assert r["ok"] is True and KEY not in str(r)


def test_alf_answers_through_the_hub(client, mock_ollama):
    """A whole model job through the Hub: the key as a header (the mock
    refuses a request with no slqhub_ key once one is sent)."""
    import time
    client.put("/api/settings", json={"aiServer": "hub", "hubUrl": mock_ollama, "hubKey": KEY,
                                      "modelChat": "gemma4:12b"})
    client.post("/api/chat/send", json={"message": "Hvad er en god aftensmad?"})
    v = None
    for _ in range(300):
        v = client.get("/api/chat/state").json()
        if v["job"] and v["job"]["state"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert v["job"]["state"] == "done", v["job"]
    assert "Hej! Det er Alf" in v["messages"][-1]["content"]
    # The key switched off in the Hub: the job says so, without the key.
    client.put("/api/settings", json={"hubKey": "slqhub_revoked0123456789"})
    client.post("/api/chat/send", json={"message": "Og en dessert?"})
    for _ in range(300):
        v = client.get("/api/chat/state").json()
        if v["job"] and v["job"]["state"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert v["job"]["state"] == "failed" and "refused the key" in v["job"]["error"]
    assert "revoked" not in v["job"]["error"]
