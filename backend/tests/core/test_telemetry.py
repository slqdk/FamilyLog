"""Steps (from SLQ 2.58.0): the recorder, the model-call phases from
Ollama's stream, and the text form used by the Økonomi export."""
import asyncio
import json

import httpx


def _mock_client(monkeypatch, module, handler):
    real = httpx.AsyncClient

    def make(*a, **kw):
        kw.pop("timeout", None)
        return real(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(module.httpx, "AsyncClient", make)


def _kids(payload, parent_id):
    return [s for s in payload["steps"] if s["parent"] == parent_id]


def test_span_nests_and_drops_short_empty_stages():
    from app.core import telemetry
    rec = telemetry.Recorder()
    tokens = telemetry.activate(rec)
    try:
        with telemetry.span("Outer", drop_under=None) as outer:
            with telemetry.span("Quick, nothing inside"):   # dropped: < 0.3 s
                pass
            inner = rec.open("Inner", "stage")
            rec.close(inner)
    finally:
        telemetry.deactivate(tokens)
    labels = [s["label"] for s in rec.steps]
    assert labels == ["Outer", "Inner"]
    assert inner["parent"] == outer["id"]
    assert outer["state"] == "ok" and outer["end"] is not None


def test_span_outside_a_job_records_nothing():
    from app.core import telemetry
    with telemetry.span("Nobody listening") as step:
        assert step is None
    call = telemetry.ModelCall("m", 10)
    call.thinking()
    call.text()
    call.done(eval_tokens=3)             # all no-ops, no error


def test_span_marks_errors_and_finish_closes_running_steps():
    from app.core import telemetry
    rec = telemetry.Recorder()
    tokens = telemetry.activate(rec)
    try:
        try:
            with telemetry.span("Breaks"):
                raise ValueError("x")
        except ValueError:
            pass
        left = rec.open("Never closed", "stage")
    finally:
        telemetry.deactivate(tokens)
    assert rec.steps[0]["state"] == "error"
    rec.finish()
    assert left["state"] == "stopped" and left["end"] is not None
    assert rec.summary()["running"] is False


def test_ollama_stream_records_load_prompt_thinking_and_writing(monkeypatch, fresh_db):
    from app.core import ollama, telemetry

    def handler(req):
        lines = [
            {"message": {"thinking": "hmm", "content": ""}},
            {"message": {"thinking": " ok", "content": ""}},
            {"message": {"content": "Hel"}},
            {"message": {"content": "lo"}},
            {"message": {"content": ""}, "done": True, "done_reason": "stop",
             "prompt_eval_count": 1200, "prompt_eval_duration": int(2e9),
             "load_duration": int(3e9), "eval_count": 10,
             "eval_duration": int(5e8)},
        ]
        return httpx.Response(200, text="\n".join(json.dumps(l) for l in lines))
    _mock_client(monkeypatch, ollama, handler)

    async def go():
        rec = telemetry.Recorder()
        tokens = telemetry.activate(rec)
        try:
            with telemetry.span("Answer", drop_under=None):
                out = [f async for f in ollama.stream_chat(
                    "qwen3.8:latest", [{"role": "user", "content": "hi " * 40}],
                    context_length=65536, usage={}, on_thinking=lambda _t: None)]
        finally:
            telemetry.deactivate(tokens)
        return rec, out
    rec, out = asyncio.run(go())
    assert "".join(out) == "Hello"
    p = rec.payload()
    answer = p["steps"][0]
    model = _kids(p, answer["id"])[0]
    assert model["kind"] == "model" and model["label"] == "qwen3.8:latest"
    assert model["tokens"] == 10 and model["state"] == "ok"
    phases = {s["kind"]: s for s in _kids(p, model["id"])}
    assert set(phases) == {"prompt", "thinking", "writing"}
    assert phases["prompt"]["tokens"] == 1200 and not phases["prompt"]["approx"]
    assert "load 3.0 s" in phases["prompt"]["detail"]
    assert "prefill 2.0 s (600 t/s)" in phases["prompt"]["detail"]
    assert phases["thinking"]["tokens"] == 2
    assert phases["writing"]["tokens"] == 8          # eval 10 - 2 thinking chunks
    assert phases["writing"]["detail"] == "20.0 t/s"
    sm = p["summary"]
    assert sm["promptTokens"] == 1200 and sm["contextLimit"] == 65536
    assert sm["tokensOut"] == 10 and sm["tps"] == 20.0


def test_ollama_failure_marks_the_call(monkeypatch, fresh_db):
    from app.core import ollama, telemetry

    def handler(req):
        return httpx.Response(500, json={"error": "runner crashed"})
    _mock_client(monkeypatch, ollama, handler)

    async def go():
        rec = telemetry.Recorder()
        tokens = telemetry.activate(rec)
        try:
            try:
                [f async for f in ollama.stream_chat(
                    "m", [{"role": "user", "content": "x"}], context_length=4096)]
            except RuntimeError:
                pass
        finally:
            telemetry.deactivate(tokens)
        return rec
    rec = asyncio.run(go())
    model = [s for s in rec.steps if s["kind"] == "model"][0]
    assert model["state"] == "error" and "runner crashed" in model["detail"]


def test_render_text_draws_the_tree():
    from app.core import telemetry
    rec = telemetry.Recorder()
    a = rec.open("qwen3.8:latest", "model", parent=None)
    b = rec.open("Load + prompt", "prompt", parent=a["id"], tokens=28300)
    rec.close(b, end=12.0)
    c = rec.open("Writing", "writing", parent=a["id"], tokens=410, approx=True)
    rec.close(c, end=20.0, detail="29.4 t/s")
    rec.close(a, end=20.0, tokens=410)
    rec.finish()
    text = telemetry.render_text(rec.payload())
    assert text.startswith("*Steps: ")
    assert "    └ qwen3.8:latest  410 tok" in text
    assert "       ├ Load + prompt  28.3k tok  12.0 s" in text
    assert "       └ Writing  ≈410 tok" in text and "29.4 t/s" in text
    assert telemetry.render_text(None) == ""


def test_keep_alive_and_context_follow_the_settings(monkeypatch, fresh_db):
    """keep_alive: empty = Ollama's own default (not sent); the context is
    the model's own length capped at contextMax."""
    from app.core import ollama, settings
    seen = []

    def handler(req):
        if req.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"x.context_length": 131072}})
        seen.append(json.loads(req.content))
        return httpx.Response(200, text=json.dumps({"message": {"content": "ok"}, "done": True}))
    _mock_client(monkeypatch, ollama, handler)
    ollama._CTX_CACHE.clear()

    async def collect():
        return [x async for x in ollama.stream_chat("m", [{"role": "user", "content": "x"}])]

    asyncio.run(collect())
    assert "keep_alive" not in seen[-1] and seen[-1]["options"]["num_ctx"] == 16384
    settings.save({"ollamaKeepAlive": "30m", "contextMax": 8192})
    asyncio.run(collect())
    assert seen[-1]["keep_alive"] == "30m" and seen[-1]["options"]["num_ctx"] == 8192
    settings.save({"ollamaKeepAlive": "-1"})
    asyncio.run(collect())
    assert seen[-1]["keep_alive"] == -1


def test_no_model_is_an_error_not_a_request(fresh_db):
    import pytest
    from app.core import ollama

    async def go():
        return [x async for x in ollama.stream_chat("", [{"role": "user", "content": "x"}])]
    with pytest.raises(ollama.OllamaError):
        asyncio.run(go())
