"""Steps: where an answer's seconds and tokens went. (2.58.0)

Every job the queue runs gets a Recorder on its `gen` (`gen["_telemetry"]`).
The recorder is also put in a context variable for the job's task, so code
deep in the call stack - `ollama.stream_chat` above all - can record into
it without anyone passing it down. Code outside a job (a feed, the chat
namer called from a test) finds no recorder and records nothing.

A step is a plain dict:

    {"id": 3, "parent": 1, "label": "qwen3.8:latest", "kind": "model",
     "start": 1.23, "end": 14.5, "state": "ok"|"run"|"error"|"stopped",
     "tokens": 1234, "detail": "load 3.1 s", "approx": False}

`start`/`end` are seconds since the recorder started (the job STARTED - the
queue wait before it is its own step). Steps form a tree through `parent`.

Model calls record three phases as children: "Load + prompt" (request sent
until the first chunk - Ollama sends nothing while it loads the model and
reads the prompt), "Thinking" (reasoning chunks) and "Writing" (answer
chunks). Ollama's final frame carries exact counts and nanosecond timings;
those replace the live estimates. Thinking/writing token counts are chunk
counts (Ollama streams about one token per chunk), marked approx, because
Ollama reports one eval_count for both.
"""
from __future__ import annotations

import contextlib
import contextvars
import time

_recorder: contextvars.ContextVar["Recorder | None"] = contextvars.ContextVar(
    "telemetry_recorder", default=None)
# False inside a span whose model output the person never sees (the plan
# check, a self-check, the chat namer): its text must not count as the
# answer's "first token". (2.58.1)
_visible: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "telemetry_visible", default=True)
_parent: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "telemetry_parent", default=None)

# A finished stage shorter than this is noise in the tree (a free_vram with
# nothing to free, a save with nothing to save). Model calls are always kept.
DROP_UNDER_S = 0.3


def _r(x: float) -> float:
    return round(x, 2)


class Recorder:
    def __init__(self, started: float | None = None) -> None:
        self.started = started if started is not None else time.time()
        self.steps: list[dict] = []
        self.version = 0
        self.finished: float | None = None
        self._ids = 0
        # Summary inputs, filled by model calls.
        self.first_output: float | None = None   # first chunk of any kind
        self.first_text: float | None = None     # first answer text
        self.eval_tokens = 0
        self.eval_ns = 0
        self.timed_tokens = 0     # tokens that came with a duration (t/s)
        self.prompt_tokens: int | None = None
        self.context_limit: int | None = None
        self.model: str | None = None
        # Files the job saved, for the Progress tab's Outputs. (2.59.0)
        self.outputs: list[str] = []

    # -- clock ------------------------------------------------------------
    def now(self) -> float:
        return time.time() - self.started

    # -- steps ------------------------------------------------------------
    def open(self, label: str, kind: str = "stage", *,
             parent: int | None | bool = True, detail: str | None = None,
             tokens: int | None = None, approx: bool = False,
             start: float | None = None) -> dict:
        """Start a step. parent=True means "the current span"."""
        self._ids += 1
        if parent is True:
            parent = _parent.get()
        step = {"id": self._ids, "parent": parent or None, "label": label,
                "kind": kind, "start": _r(self.now() if start is None else start),
                "end": None, "state": "run", "tokens": tokens,
                "detail": detail, "approx": approx}
        self.steps.append(step)
        self.version += 1
        return step

    def update(self, step: dict, **fields) -> None:
        step.update({k: v for k, v in fields.items()})
        self.version += 1

    def close(self, step: dict, state: str = "ok", *,
              drop_under: float | None = None, end: float | None = None,
              **fields) -> None:
        step["end"] = _r(self.now() if end is None else end)
        step["state"] = state
        step.update(fields)
        if (drop_under is not None and state == "ok"
                and step["end"] - step["start"] < drop_under
                and not any(s["parent"] == step["id"] for s in self.steps)):
            self.steps.remove(step)
        self.version += 1

    def add(self, label: str, kind: str, start: float, end: float, *,
            parent: int | None | bool = True, **fields) -> dict:
        """A step that is already over (queue wait, context breakdown)."""
        step = self.open(label, kind, parent=parent, start=start)
        self.close(step, end=end, **fields)
        return step

    def finish(self) -> None:
        """Close anything left running - a cancelled task never reaches the
        close of its inner steps."""
        if self.finished is not None:
            return
        self.finished = self.now()
        for s in self.steps:
            if s["end"] is None:
                s["end"] = _r(self.finished)
                s["state"] = "stopped"
        self.version += 1

    # -- output -----------------------------------------------------------
    def summary(self) -> dict:
        end = self.finished if self.finished is not None else self.now()
        queue = sum((s["end"] or 0) - s["start"] for s in self.steps
                    if s["kind"] == "queue")
        return {
            "totalS": _r(end),
            "queueS": _r(queue),
            "firstOutputS": _r(self.first_output) if self.first_output is not None else None,
            "firstTokenS": _r(self.first_text) if self.first_text is not None else None,
            "tokensOut": self.eval_tokens or None,
            "tps": (round(self.timed_tokens / (self.eval_ns / 1e9), 1)
                    if self.timed_tokens and self.eval_ns else None),
            "promptTokens": self.prompt_tokens,
            "contextLimit": self.context_limit,
            "model": self.model,
            "modelCalls": sum(1 for s in self.steps if s["kind"] == "model"),
            "running": self.finished is None,
        }

    def payload(self) -> dict:
        return {"startedAt": round(self.started, 3),
                "serverNow": round(time.time(), 3),
                "steps": [dict(s) for s in self.steps],
                "summary": self.summary(),
                "outputs": list(self.outputs)}


# ---- access ---------------------------------------------------------------

def current() -> Recorder | None:
    return _recorder.get()


def attach(gen: dict, enqueued_at: float | None = None) -> Recorder:
    """Give a job's gen its recorder (once) and record the queue wait."""
    rec = gen.get("_telemetry")
    if rec is None:
        rec = Recorder()
        gen["_telemetry"] = rec
        if enqueued_at is not None:
            waited = rec.started - enqueued_at
            if waited >= DROP_UNDER_S:
                rec.add("Queue wait", "queue", -waited, 0.0, parent=None)
    return rec


def activate(rec: Recorder):
    """Make `rec` current for tasks created until the token is reset."""
    return _recorder.set(rec), _parent.set(None)


def deactivate(tokens) -> None:
    rt, pt = tokens
    _parent.reset(pt)
    _recorder.reset(rt)


def add_outputs(gen: dict, paths) -> None:
    """Record files the job saved (Outputs in the Progress tab)."""
    rec = gen.get("_telemetry") or current()
    if rec is None:
        return
    for p in paths or []:
        if isinstance(p, str) and p not in rec.outputs:
            rec.outputs.append(p)
            rec.version += 1


def payload_of(gen: dict) -> dict | None:
    rec = gen.get("_telemetry")
    return rec.payload() if rec is not None else None


def persist(gen: dict, only_if_done: bool = False) -> None:
    """Finish the recorder. Safe to call twice (the job's own finally, then
    the queue). The steps live on the in-memory job, where the section's
    view reads them - SLQ also stored them on a chat turn; there is none
    here."""
    rec = gen.get("_telemetry")
    if rec is None or (only_if_done and not gen.get("done")):
        return
    rec.finish()


@contextlib.contextmanager
def span(label: str, kind: str = "stage", detail: str | None = None,
         drop_under: float | None = DROP_UNDER_S, aux: bool = False):
    """A stage of the job. Model calls inside it become its children.
    Yields the step (or None outside a job) so the caller can add detail.
    aux=True: the model output inside is not the answer the person reads."""
    rec = current()
    if rec is None:
        yield None
        return
    step = rec.open(label, kind, detail=detail)
    token = _parent.set(step["id"])
    vis_token = _visible.set(False) if aux else None
    state = "ok"
    try:
        yield step
    except BaseException as exc:
        import asyncio
        state = "stopped" if isinstance(exc, asyncio.CancelledError) else "error"
        raise
    finally:
        _parent.reset(token)
        if vis_token is not None:
            _visible.reset(vis_token)
        if step["end"] is None:
            rec.close(step, state, drop_under=drop_under if state == "ok" else None)


# ---- model calls ----------------------------------------------------------

def _tok(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _fmt_s(ns: int | None) -> str:
    return f"{(ns or 0) / 1e9:.1f} s"


class ModelCall:
    """Live recording of one streamed model call. Every method is a no-op
    when there is no recorder, so callers never need to check."""

    def __init__(self, model: str, prompt_estimate: int | None = None,
                 context_limit: int | None = None, engine: str = "Ollama") -> None:
        self.rec = current()
        self.context_limit = context_limit
        self.step = self.phase = None
        self.kind = None          # "prompt" | "thinking" | "writing"
        self.think_chunks = self.text_chunks = 0
        self.thinking_step = self.writing_step = None
        if self.rec is None:
            return
        self.rec.model = model
        self.context_limit = context_limit
        if context_limit and self.rec.context_limit is None:
            self.rec.context_limit = context_limit
        self.step = self.rec.open(model, "model",
                                  detail=None if engine == "Ollama" else engine)
        est = f"≈{prompt_estimate:,} tokens" if prompt_estimate else None
        self.phase = self.rec.open("Load + prompt", "prompt",
                                   parent=self.step["id"], detail=est,
                                   tokens=prompt_estimate, approx=True)
        self.kind = "prompt"

    def _switch(self, kind: str, label: str) -> dict:
        now = self.rec.now()
        if self.phase is not None and self.phase["end"] is None:
            self.rec.close(self.phase, end=now)
        if self.rec.first_output is None and _visible.get():
            self.rec.first_output = now
        self.phase = self.rec.open(label, kind, parent=self.step["id"],
                                   start=now, approx=True, tokens=0)
        self.kind = kind
        return self.phase

    def thinking(self) -> None:
        if self.rec is None:
            return
        if self.kind != "thinking":
            self.thinking_step = self._switch("thinking", "Thinking")
        self.think_chunks += 1
        self.thinking_step["tokens"] = self.think_chunks
        self.rec.version += 1

    def text(self) -> None:
        if self.rec is None:
            return
        if self.kind != "writing":
            self.writing_step = self._switch("writing", "Writing")
            if self.rec.first_text is None and _visible.get():
                self.rec.first_text = self.rec.now()
        self.text_chunks += 1
        self.writing_step["tokens"] = self.text_chunks
        self.rec.version += 1

    def done(self, *, prompt_tokens: int | None = None,
             prompt_ns: int | None = None, load_ns: int | None = None,
             cached_tokens: int | None = None,
             eval_tokens: int | None = None, eval_ns: int | None = None,
             done_reason: str | None = None) -> None:
        if self.rec is None or self.step is None:
            return
        rec = self.rec
        now = rec.now()
        # The prompt phase: exact numbers replace the estimate.
        prompt_step = next((s for s in rec.steps if s["parent"] == self.step["id"]
                            and s["kind"] == "prompt"), None)
        if prompt_step is not None:
            bits = []
            if load_ns and load_ns >= 5e8:
                bits.append(f"load {_fmt_s(load_ns)}")
            if cached_tokens is not None and prompt_tokens:
                # Ollama says how much came from the cache (2.59.7): the
                # number that decides whether the start was fast.
                read = max(0, prompt_tokens - cached_tokens)
                bits.append(f"cached {_tok(cached_tokens)} · read {_tok(read)}")
                if prompt_ns and read:
                    bits.append(f"in {_fmt_s(prompt_ns)} "
                                f"({read / (prompt_ns / 1e9):,.0f} t/s)")
            elif prompt_tokens and prompt_ns:
                rate = prompt_tokens / (prompt_ns / 1e9)
                bits.append(f"prefill {_fmt_s(prompt_ns)} ({rate:,.0f} t/s)")
            elif prompt_tokens and not prompt_ns:
                bits.append("prompt cached")
            prompt_step.update(tokens=prompt_tokens, approx=prompt_tokens is None,
                               detail=" · ".join(bits) or None)
            if prompt_step["end"] is None:
                rec.close(prompt_step, end=now)
        if self.phase is not None and self.phase["end"] is None:
            rec.close(self.phase, end=now)
        if eval_tokens is not None:
            # Ollama counts thinking and answer together; give the answer the
            # exact remainder when both ran, keep chunk counts otherwise.
            if self.writing_step is not None:
                if self.thinking_step is not None:
                    self.writing_step["tokens"] = max(0, eval_tokens - self.think_chunks)
                else:
                    self.writing_step["tokens"] = eval_tokens
                    self.writing_step["approx"] = False
            elif self.thinking_step is not None:
                self.thinking_step["tokens"] = eval_tokens
                self.thinking_step["approx"] = False
            rec.eval_tokens += eval_tokens
            # A token or two in a few microseconds is not a speed.
            if eval_ns and eval_ns >= 1e7:
                rec.timed_tokens += eval_tokens
                rec.eval_ns += eval_ns
        if self.writing_step is not None and eval_tokens and eval_ns:
            self.writing_step["detail"] = f"{eval_tokens / (eval_ns / 1e9):.1f} t/s"
        # The fullest window of the job is the one worth a bar: the chat
        # namer's small prompt must not replace the answer's.
        if prompt_tokens and prompt_tokens > (rec.prompt_tokens or 0):
            rec.prompt_tokens = prompt_tokens
            if self.context_limit:
                rec.context_limit = self.context_limit
        detail = self.step.get("detail")
        if done_reason == "length":
            detail = " · ".join(x for x in (detail, "hit the length limit") if x)
        rec.close(self.step, "ok", end=now, tokens=eval_tokens, detail=detail)
        self.step = None

    def failed(self, exc: BaseException) -> None:
        if self.rec is None or self.step is None:
            return
        import asyncio
        state = ("stopped" if isinstance(exc, (asyncio.CancelledError, GeneratorExit))
                 else "error")
        now = self.rec.now()
        for s in (self.phase, self.step):
            if s is not None and s["end"] is None:
                self.rec.close(s, state, end=now)
        if state == "error":
            self.step["detail"] = str(exc)[:200]
        self.step = None


# ---- text form (export) ---------------------------------------------------

def _num(n: int | None) -> str:
    if n is None:
        return ""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def render_text(payload: dict | None) -> str:
    """The step tree as plain text, for the Markdown export."""
    if not payload or not payload.get("steps"):
        return ""
    steps = payload["steps"]
    sm = payload.get("summary") or {}
    head = [f"{sm.get('totalS', 0):.1f} s"]
    if sm.get("firstTokenS") is not None:
        head.append(f"first token {sm['firstTokenS']:.1f} s")
    if sm.get("tokensOut"):
        head.append(f"{_num(sm['tokensOut'])} tokens out")
    if sm.get("tps"):
        head.append(f"{sm['tps']} t/s")
    if sm.get("promptTokens") and sm.get("contextLimit"):
        head.append(f"context {_num(sm['promptTokens'])}/{_num(sm['contextLimit'])}")
    lines = ["*Steps: " + " · ".join(head) + "*", ""]
    children: dict[int | None, list[dict]] = {}
    for s in steps:
        children.setdefault(s.get("parent"), []).append(s)

    def walk(pid: int | None, prefix: str) -> None:
        kids = children.get(pid, [])
        for i, s in enumerate(kids):
            last = i == len(kids) - 1
            dur = (s["end"] - s["start"]) if s.get("end") is not None else None
            bits = [s["label"]]
            if s.get("tokens") is not None:
                bits.append(("≈" if s.get("approx") else "") + _num(s["tokens"]) + " tok")
            if dur is not None and s.get("kind") != "info":
                bits.append(f"{dur:.1f} s")
            if s.get("detail"):
                bits.append(s["detail"])
            if s.get("state") not in (None, "ok"):
                bits.append(f"[{s['state']}]")
            if s.get("flag") == "warn":
                bits.insert(0, "⚠")
            lines.append(prefix + ("└ " if last else "├ ") + "  ".join(bits))
            walk(s["id"], prefix + ("   " if last else "│  "))

    walk(None, "    ")
    return "\n".join(lines)
