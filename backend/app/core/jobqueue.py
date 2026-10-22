"""The model-call queue: one job at a time, because there is one GPU.

Every piece of model work - an Økonomi question, a categorise batch, a
Spørg Alf answer, a photo description - is submitted here and runs strictly
in arrival order. This is SLQ's jobqueue.py (one worker, in memory, a
restart clears it) with one addition: a BROKER that every job passes
through before it starts.

The broker is the seam for sharing the card with other apps:

* LocalBroker (now): optionally asks ComfyUI to free its VRAM before the
  job (setting `comfyFreeFirst`), then lets it run. This app's own queue is
  the only ordering.
* An SLQ broker (later, when SLQ's GPU-job API exists): `acquire()` asks
  SLQ for the card and waits for its turn there, `release()` hands it back.
  The sections do not change - they keep calling submit().

A job's work is a coroutine factory; the coroutine owns its own error
handling and state (each one has the try/except/finally that marks its
view done/failed/stopped). The worker only decides WHEN it runs and
survives whatever the job does.

Keys: any hashable per job owner (the sections use negative ints, as in
SLQ). position() / cancel_queued() work per key.
"""
from __future__ import annotations

import asyncio
import itertools
import time

from . import comfy, logs, settings, telemetry

_counter = itertools.count(1)

_pending: list[dict] = []
_current: dict | None = None
_worker: asyncio.Task | None = None
# The loop the worker belongs to. A different running loop means the old
# worker is an orphan (the test suite makes a fresh loop per test client) -
# its jobs can never run, so they are dropped rather than left queued.
_loop: asyncio.AbstractEventLoop | None = None
_wake: asyncio.Event | None = None


# ---- the broker -------------------------------------------------------------

class LocalBroker:
    """This app alone decides. Frees ComfyUI's VRAM first when asked to."""
    name = "local"

    async def acquire(self, job: dict):
        s = settings.load()
        if settings.uses_hub(s) or not s.get("comfyFreeFirst", True):
            # 0.4.0: SLQ Hub's own queue owns the GPU and frees ComfyUI itself.
            return None
        with telemetry.span("Free GPU (ComfyUI)", "stage") as step:
            try:
                freed = await comfy.free_vram()
            except asyncio.CancelledError:
                raise
            except Exception as exc:          # never let it fail the job
                logs.record_exception(exc, "freeing ComfyUI VRAM")
                freed = None
                rec = telemetry.current()
                if step is not None and rec is not None:
                    # Closed here, so a quick failure is not dropped as noise.
                    rec.close(step, "ok", detail=f"failed: {exc}"[:200], flag="warn")
            if step is not None and freed is False and not step.get("detail"):
                step["detail"] = ("ComfyUI not set" if not comfy.configured()
                                  else "ComfyUI did not answer")
        return None

    async def release(self, lease) -> None:
        return None


_BROKERS = {"local": LocalBroker}


def broker():
    name = settings.load().get("gpuBroker") or "local"
    return _BROKERS.get(name, LocalBroker)()


# ---- the queue ----------------------------------------------------------------

def _ensure_worker() -> None:
    global _worker, _loop, _wake, _current
    loop = asyncio.get_running_loop()
    if _loop is not loop:
        _pending.clear()
        _current = None
        _worker = None
        _wake = asyncio.Event()
        _loop = loop
    if _worker is None or _worker.done():
        _worker = loop.create_task(_run())


def submit(key, kind: str, gen: dict, factory) -> dict:
    """Queue a piece of work. `factory` is a no-argument callable returning
    the coroutine to run. Marks `gen` as queued; the worker clears the flag
    when the job starts. Must be called from a running event loop."""
    _ensure_worker()
    job = {"id": next(_counter), "key": key, "kind": kind,
           "enqueuedAt": time.time(), "startedAt": None, "state": "queued",
           "gen": gen, "factory": factory}
    gen["queued"] = True
    _pending.append(job)
    assert _wake is not None
    _wake.set()
    return job


def position(key) -> int:
    """How many jobs must finish before this key's next one starts.
    0 = running now, 1 = next."""
    if _current is not None and _current["key"] == key:
        return 0
    ahead = 1 if _current is not None else 0
    for job in _pending:
        if job["key"] == key:
            return ahead
        if job["state"] == "queued":
            ahead += 1
    return ahead


def running_for(key) -> dict | None:
    if _current is not None and _current["key"] == key:
        return _current
    return None


def cancel_queued(key) -> list[dict]:
    """Remove a key's jobs that have not started. A running job is stopped
    by cancelling gen["task"] - the caller's affair."""
    removed = [j for j in _pending if j["key"] == key]
    for job in removed:
        job["state"] = "cancelled"
    _pending[:] = [j for j in _pending if j["key"] != key]
    return removed


def pending_count(key=None) -> int:
    if key is None:
        return len(_pending)
    return sum(1 for j in _pending if j["key"] == key)


def snapshot() -> dict:
    """For Settings → Diagnostics: what is on the card and what waits."""
    def dto(j):
        return {"id": j["id"], "kind": j["kind"], "state": j["state"],
                "enqueuedAt": j["enqueuedAt"], "startedAt": j["startedAt"]}
    return {"broker": broker().name,
            "running": dto(_current) if _current else None,
            "pending": [dto(j) for j in _pending if j["state"] == "queued"]}


async def drain() -> None:
    """Wait until the queue is empty and idle. Test helper."""
    while _pending or _current is not None:
        await asyncio.sleep(0.005)


async def _gated(job: dict):
    """The job behind the broker. The job's coroutine is always started -
    even when Stop arrives while the broker is still busy - because its own
    try/finally is what marks the section's view stopped; a coroutine that
    never ran would leave the page saying "working" forever."""
    b = broker()
    lease = None
    cancelled = False
    try:
        lease = await b.acquire(job)
    except asyncio.CancelledError:
        cancelled = True
    except Exception as exc:                 # pragma: no cover - belt and braces
        logs.record_exception(exc, "GPU broker")
    inner = asyncio.get_running_loop().create_task(job["factory"]())
    try:
        if cancelled:
            await asyncio.sleep(0)           # let it enter its try block
            inner.cancel()
        # Awaiting the task directly: cancelling this (outer) task cancels
        # the inner one too, so Stop reaches the job's own handler.
        return await inner
    finally:
        # A second Stop that lands between the two cancels above must not
        # leave the job running beside the next one: the worker moves on
        # when this task ends, so the job ends with it.
        if not inner.done():
            inner.cancel()
            await asyncio.wait({inner})
        try:
            await b.release(lease)
        except Exception as exc:             # pragma: no cover
            logs.record_exception(exc, "GPU broker release")


async def _run() -> None:
    """The one worker. Jobs run strictly in order, one at a time."""
    global _current
    assert _wake is not None
    while True:
        job: dict | None = None
        while _pending:
            head = _pending.pop(0)
            if head["state"] == "queued":
                job = head
                break
        if job is None:
            _wake.clear()
            await _wake.wait()
            continue

        _current = job
        gen = job["gen"]
        job["state"] = "running"
        job["startedAt"] = time.time()
        gen["queued"] = False
        try:
            # Every job gets a recorder, current for its task, so model calls
            # deep in the stack record into it (Steps).
            rec = telemetry.attach(gen, job["enqueuedAt"])
            tokens = telemetry.activate(rec)
            try:
                task = asyncio.get_running_loop().create_task(_gated(job))
            finally:
                telemetry.deactivate(tokens)
            gen["task"] = task               # Stop cancels this
            await asyncio.wait({task})
        except asyncio.CancelledError:
            raise                            # the worker itself is shutting down
        except Exception as exc:             # pragma: no cover
            logs.record_exception(exc, "job queue worker")
        finally:
            try:
                telemetry.persist(gen, only_if_done=True)
            except Exception as exc:         # pragma: no cover
                logs.record_exception(exc, "job queue steps")
            job["state"] = "done"
            _current = None
