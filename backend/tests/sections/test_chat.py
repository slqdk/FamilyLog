"""Alf on the front page (0.2.0): a general chat with history that uses
Spørg Alf's place search when a message is about places - against the mock
Ollama over real HTTP, through the real queue."""
from __future__ import annotations

import time


def _wait(c, timeout=15.0):
    end = time.time() + timeout
    v = None
    while time.time() < end:
        v = c.get("/api/chat/state").json()
        if v["job"] and v["job"]["state"] in ("done", "failed", "stopped"):
            return v
        time.sleep(0.05)
    raise AssertionError(v)


def _setup(client, mock_ollama):
    r = client.put("/api/settings", json={"ollamaUrl": mock_ollama, "modelChat": "gemma4:12b"})
    assert r.status_code == 200, r.text


def test_without_a_model_the_chat_says_why(client):
    r = client.post("/api/chat/send", json={"message": "hej"})
    assert r.status_code == 400 and "chatmodel" in r.json()["detail"]
    assert client.get("/api/chat/state").json()["model"] is False


def test_a_general_question_is_answered_with_the_conversation(client, mock_ollama):
    _setup(client, mock_ollama)
    client.post("/api/chat/send", json={"message": "Hvad er en god aftensmad?"})
    v = _wait(client)
    assert v["job"]["state"] == "done" and v["job"]["route"] == "chat"
    assert [m["role"] for m in v["messages"]] == ["user", "assistant"]
    assert "Hej! Det er Alf" in v["messages"][1]["content"]
    client.post("/api/chat/send", json={"message": "Og en dessert?"})
    v = _wait(client)
    assert "(2 beskeder i samtalen)" in v["messages"][-1]["content"]      # history went along
    assert len(v["messages"]) == 4


def test_a_question_about_places_uses_the_familys_places(client, mock_ollama):
    _setup(client, mock_ollama)
    p = client.post("/api/fm/places", json={"name": "Søparkens Legeplads", "category": "playground",
                                            "lat": 55.246, "lng": 9.306}).json()
    client.post("/api/chat/send", json={"message": "Find en legeplads her", "lat": 55.246, "lng": 9.306})
    v = _wait(client)
    assert v["job"]["state"] == "done" and v["job"]["route"] == "places", v["job"]
    answer = v["messages"][-1]
    assert f"[[{p['id']}]]" in answer["content"]
    assert answer["places"][0]["name"] == "Søparkens Legeplads"
    assert answer["meta"]["route"] == "places" and answer["meta"]["searched"]


def test_no_position_and_no_town_says_so(client, mock_ollama):
    _setup(client, mock_ollama)
    client.post("/api/chat/send", json={"message": "Find en legeplads"})
    v = _wait(client)
    assert "Jeg kunne ikke finde" in v["messages"][-1]["content"]


def test_one_message_at_a_time_and_stop(client, mock_ollama, monkeypatch):
    import asyncio
    from app.core import ollama
    _setup(client, mock_ollama)

    async def slow(model, messages, **kw):
        await asyncio.sleep(30)
        yield "{}"
    monkeypatch.setattr(ollama, "stream_chat", slow)
    assert client.post("/api/chat/send", json={"message": "hej"}).status_code == 200
    assert client.post("/api/chat/send", json={"message": "igen"}).status_code == 409
    client.post("/api/chat/stop")
    v = _wait(client)
    assert v["job"]["state"] == "stopped"


def test_new_conversation_and_privacy(client, mock_ollama):
    from fastapi.testclient import TestClient
    from app.main import app
    _setup(client, mock_ollama)
    client.post("/api/chat/send", json={"message": "hemmelig besked"})
    _wait(client)
    assert client.post("/api/users", json={"username": "barn", "password": "familie-kode-1",
                                           "role": "family"}).status_code == 200
    # `with`: one event loop for the client's lifetime, like uvicorn - a
    # loop per request would end the queued job with the request.
    with TestClient(app) as fc:
        fc.post("/api/auth/login", json={"username": "barn", "password": "familie-kode-1"})
        assert fc.get("/api/chat/state").json()["messages"] == []       # nobody reads another's
        fc.post("/api/chat/send", json={"message": "hej fra barnet"})
        v = _wait(fc)
        assert v["job"]["state"] == "done", v["job"]
        assert v["messages"][0]["content"] == "hej fra barnet"
        assert len(client.get("/api/chat/state").json()["messages"]) == 2
        assert client.post("/api/chat/new").json()["messages"] == []
        assert len(fc.get("/api/chat/state").json()["messages"]) == 2


def test_validation(client, mock_ollama):
    _setup(client, mock_ollama)
    assert client.post("/api/chat/send", json={"message": "  "}).status_code == 400
    assert client.post("/api/chat/send", json={"message": "x" * 1001}).status_code == 400
