"""The Ollama HTTP client - the only code that talks to Ollama.

Since 0.4.0 the same client talks to SLQ Hub (setting aiServer = "hub"): the
Hub speaks the Ollama API on port 11434 and wants the app's key, sent here as
`Authorization: Bearer` - never in the address, so no message, log or page
can show it.

Ported from SLQ's ollama.py, trimmed to what the sections use: list the
models (Settings → Test), and stream a chat answer (JSON format, thinking
on/off, images for the vision model). Calls are made from inside a job of
the queue (core/jobqueue.py), which decides WHEN a model runs; this module
only does the HTTP.

Every streamed call records its phases into the job's Steps (telemetry).
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from . import settings as _settings
from . import telemetry


class OllamaError(RuntimeError):
    """Raised with a message fit for the page."""


def server(s: dict | None = None) -> dict:
    """{"base", "headers", "name"} of the AI server in use."""
    s = s or _settings.load()
    if _settings.uses_hub(s):
        key = (s.get("hubKey") or "").strip()
        return {"base": _settings.hub_base(settings=s), "name": "SLQ Hub",
                "headers": {"Authorization": f"Bearer {key}"} if key else {}, "hub": True,
                "keySet": bool(key)}
    return {"base": (s.get("ollamaUrl") or "").strip().rstrip("/"), "name": "Ollama", "headers": {},
            "hub": False, "keySet": False}


def _base(url: str | None = None) -> str:
    return (url or server()["base"] or "").strip().rstrip("/")


def _headers() -> dict:
    return server()["headers"]


def status_reason(srv: dict, code: int) -> str:
    """An HTTP status from the server, in words the settings page can act on."""
    if srv["hub"] and code == 401:
        return ("SLQ Hub refused the key (missing, wrong, switched off or deleted) - "
                "make one under the Hub's Settings → Apps and keys and paste it in Settings → AI server.")
    if srv["hub"] and code == 403:
        return ("SLQ Hub refused this server's address: the model API answers only on the LAN "
                "(and from the addresses the key allows, if it limits them).")
    if srv["hub"] and code == 503:
        return "SLQ Hub's queue was full for too long (Settings → Queue on the Hub) - try again."
    return f"{srv['name']} at {srv['base']} answered {code}."


async def tags(url: str | None = None, srv: dict | None = None) -> list[dict]:
    """GET /api/tags. Raises OllamaError with the reason on failure - the
    Settings page's Test button shows it as it is."""
    srv = srv or server()
    if url is not None:
        srv = {**srv, "base": url.strip().rstrip("/")}
    base = srv["base"]
    if not base:
        raise OllamaError("No SLQ Hub address is set." if srv["hub"] else "No Ollama address is set.")
    if srv["hub"] and not srv["keySet"]:
        raise OllamaError("No SLQ Hub key is set - make one under the Hub's Settings → Apps and keys.")
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(base + "/api/tags", headers=srv["headers"])
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as exc:
        raise OllamaError(status_reason(srv, exc.response.status_code)) from None
    except Exception as exc:
        raise OllamaError(f"{srv['name']} at {base} is not answering: "
                          f"{str(exc) or exc.__class__.__name__}") from None
    out = []
    for m in data.get("models") or []:
        details = m.get("details") or {}
        out.append({"name": m.get("name") or m.get("model") or "",
                    "size": m.get("size"),
                    "family": details.get("family"),
                    "parameters": details.get("parameter_size"),
                    "quantization": details.get("quantization_level")})
    return sorted((m for m in out if m["name"]), key=lambda m: m["name"].lower())


async def list_models() -> list[str]:
    """Model names, or an empty list when Ollama is unreachable."""
    try:
        return [m["name"] for m in await tags()]
    except OllamaError:
        return []


_CTX_CACHE: dict[tuple[str, str], int] = {}


async def model_context_limit(model: str) -> int | None:
    """The model's own trained context length (POST /api/show), cached."""
    base = _base()
    if (base, model) in _CTX_CACHE:
        return _CTX_CACHE[(base, model)]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(base + "/api/show", json={"model": model}, headers=_headers())
            r.raise_for_status()
            info = r.json().get("model_info") or {}
    except Exception:
        return None
    for key, value in info.items():
        if key.endswith(".context_length") and isinstance(value, int):
            _CTX_CACHE[(base, model)] = value
            return value
    return None


async def resolve_context_length(model: str) -> int:
    """The model's own length, capped at contextMax (a 128k model must not
    try to allocate a KV cache bigger than the card)."""
    cap = int(_settings.load().get("contextMax") or 16384)
    native = await model_context_limit(model)
    return min(native, cap) if native else cap


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


async def stream_chat(model: str, messages: list[dict],
                      context_length: int | None = None,
                      usage: dict | None = None,
                      on_thinking=None,
                      response_format: str | dict | None = None,
                      think: bool | None = None) -> AsyncIterator[str]:
    """POST /api/chat with stream:true, yielding answer text.

    Thinking models split their output: reasoning arrives in message.thinking
    and is handed to `on_thinking`; only the answer is yielded. `messages`
    may carry `images` (base64) for a vision model."""
    if not model:
        raise OllamaError("No model chosen.")
    s = _settings.load()
    srv = server(s)
    url = srv["base"] + "/api/chat"
    payload: dict = {"model": model, "stream": True, "messages": messages}
    ctx = context_length or await resolve_context_length(model)
    payload["options"] = {"num_ctx": int(ctx)}
    if usage is not None:
        usage["contextLimit"] = int(ctx)
    keep = str(s.get("ollamaKeepAlive") or "").strip()
    if keep and not srv["hub"]:          # the Hub's scheduler decides what stays loaded
        payload["keep_alive"] = -1 if keep == "-1" else keep
    if response_format is not None:
        # Ollama constrains sampling to valid JSON - extraction is reliable
        # rather than hoping for tidy markdown.
        payload["format"] = response_format
    if think is not None:
        payload["think"] = think

    call = telemetry.ModelCall(
        model, sum(_estimate_tokens(m.get("content") or "")
                   for m in messages if isinstance(m.get("content"), str)), int(ctx),
        engine=srv["name"] if srv["hub"] else "Ollama")
    try:
        async for piece in _stream(url, payload, model, usage, on_thinking, call, srv):
            yield piece
    except BaseException as exc:
        call.failed(exc)
        raise


async def _stream(url: str, payload: dict, model: str, usage: dict | None,
                  on_thinking, steps: "telemetry.ModelCall", srv: dict | None = None) -> AsyncIterator[str]:
    srv = srv or server()
    try:
        client_cm = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10))
        async with client_cm as client:
            async with client.stream("POST", url, json=payload, headers=srv["headers"]) as resp:
                if resp.status_code == 404:
                    raise OllamaError(
                        f"The model '{model}' is not on the {srv['name']} server. "
                        "Pick another one in Settings.")
                if resp.status_code in (401, 403, 503) and srv["hub"]:
                    raise OllamaError(status_reason(srv, resp.status_code))
                if resp.status_code >= 400:
                    # Ollama's error body carries the real reason ("model
                    # requires more system memory"); keep it. (SLQ 1.52.4)
                    detail = ""
                    try:
                        body = (await resp.aread()).decode("utf-8", "replace")
                        try:
                            detail = str(json.loads(body).get("error") or body)
                        except json.JSONDecodeError:
                            detail = body
                    except Exception:
                        pass
                    raise OllamaError(
                        f"{srv['name']} answered {resp.status_code} for {model}"
                        + (f": {detail[:400]}" if detail.strip() else ""))
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if err := obj.get("error"):
                        raise OllamaError(str(err))
                    message = obj.get("message") or {}
                    reasoning = message.get("thinking")
                    if reasoning:
                        steps.thinking()
                        if on_thinking is not None:
                            on_thinking(reasoning)
                    text = message.get("content")
                    if text:
                        steps.text()
                        yield text
                    if obj.get("done"):
                        steps.done(prompt_tokens=obj.get("prompt_eval_count"),
                                   prompt_ns=obj.get("prompt_eval_duration"),
                                   load_ns=obj.get("load_duration"),
                                   cached_tokens=obj.get("prompt_eval_cached_count"),
                                   eval_tokens=obj.get("eval_count"),
                                   eval_ns=obj.get("eval_duration"),
                                   done_reason=obj.get("done_reason"))
                        if usage is not None:
                            usage["promptTokens"] = obj.get("prompt_eval_count")
                            usage["responseTokens"] = obj.get("eval_count")
                            usage["evalDurationNs"] = obj.get("eval_duration")
                            usage["doneReason"] = obj.get("done_reason")
                        return
    except httpx.ConnectError as exc:
        raise OllamaError(f"{srv['name']} at {url.rsplit('/api/', 1)[0]} is not answering "
                          f"({exc.__class__.__name__}).") from None
