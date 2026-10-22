"""The model-call queue: order, one at a time, Steps, the broker's optional
"free ComfyUI VRAM first", and Stop while the broker is still busy."""
from __future__ import annotations

import asyncio


def test_jobs_run_one_at_a_time_in_order(fresh_db):
    from app.core import jobqueue

    async def go():
        running, order, peak = [0], [], [0]

        def job(name):
            async def run():
                running[0] += 1
                peak[0] = max(peak[0], running[0])
                await asyncio.sleep(0.02)
                order.append(name)
                running[0] -= 1
            return run
        for n in ("a", "b", "c"):
            jobqueue.submit(("t", n), "test", {"done": False}, job(n))
        assert jobqueue.position(("t", "c")) == 2
        await jobqueue.drain()
        return order, peak[0]
    order, peak = asyncio.run(go())
    assert order == ["a", "b", "c"] and peak == 1


def test_queue_attaches_a_recorder_and_records_the_wait(fresh_db):
    from app.core import jobqueue, telemetry

    async def go():
        gen_a: dict = {"done": False}
        gen_b: dict = {"done": False}
        seen = {}

        async def slow():
            await asyncio.sleep(0.45)
            gen_a["done"] = True

        async def second():
            seen["rec"] = telemetry.current()
            with telemetry.span("Work", drop_under=None):
                await asyncio.sleep(0.01)
            gen_b["done"] = True
        jobqueue.submit(9001, "chat", gen_a, slow)
        jobqueue.submit(9002, "chat", gen_b, second)
        await jobqueue.drain()
        return gen_b, seen
    gen_b, seen = asyncio.run(go())
    rec = gen_b["_telemetry"]
    assert seen["rec"] is rec
    kinds = [s["kind"] for s in rec.steps]
    assert kinds[0] == "queue" and "stage" in kinds
    queue = rec.steps[0]
    assert queue["end"] == 0 and queue["start"] <= -0.3
    assert rec.summary()["queueS"] >= 0.3 and rec.finished is not None


def test_a_shared_gen_stays_open_until_its_last_job(fresh_db):
    from app.core import jobqueue

    async def go():
        gen: dict = {"done": False}

        async def item(last):
            await asyncio.sleep(0.01)
            if last:
                gen["done"] = True
        jobqueue.submit(9100, "batch-item", gen, lambda: item(False))
        await jobqueue.drain()
        open_after_first = gen["_telemetry"].finished is None
        jobqueue.submit(9100, "batch-item", gen, lambda: item(True))
        await jobqueue.drain()
        return open_after_first, gen["_telemetry"].finished
    open_after_first, finished = asyncio.run(go())
    assert open_after_first and finished is not None


def test_cancel_queued_removes_only_that_keys_pending_jobs(fresh_db):
    from app.core import jobqueue

    async def go():
        ran = []

        def job(n):
            async def run():
                await asyncio.sleep(0.01)
                ran.append(n)
            return run
        jobqueue.submit("x", "t", {"done": False}, job("x1"))
        jobqueue.submit("y", "t", {"done": False}, job("y1"))
        jobqueue.submit("x", "t", {"done": False}, job("x2"))
        removed = jobqueue.cancel_queued("x")    # x1 may already run; x2 surely waits
        await jobqueue.drain()
        return ran, removed
    ran, removed = asyncio.run(go())
    assert "y1" in ran and "x2" not in ran and removed


def _with_free(monkeypatch, result):
    from app.core import comfy
    calls = []

    async def free_vram(*a, **k):
        calls.append(1)
        if isinstance(result, Exception):
            raise result
        await asyncio.sleep(0.4)          # long enough to stay in Steps
        return result
    monkeypatch.setattr(comfy, "free_vram", free_vram)
    return calls


def _run_one():
    from app.core import jobqueue, telemetry

    async def go():
        gen: dict = {"done": False}
        state = {}

        async def work():
            try:
                state["ran"] = True
                await asyncio.sleep(0.01)
            finally:
                gen["done"] = True
        jobqueue.submit("free-test", "t", gen, work)
        await jobqueue.drain()
        return gen, state
    gen, state = asyncio.run(go())
    return [s for s in telemetry.payload_of(gen)["steps"]], state


def test_the_broker_frees_comfy_first_when_set(fresh_db, monkeypatch):
    calls = _with_free(monkeypatch, True)
    steps, state = _run_one()
    assert calls and state["ran"]
    assert steps[0]["label"] == "Free GPU (ComfyUI)" and steps[0]["state"] == "ok"


def test_the_broker_skips_it_when_switched_off(fresh_db, monkeypatch):
    from app.core import settings
    settings.save({"comfyFreeFirst": False})
    calls = _with_free(monkeypatch, True)
    steps, state = _run_one()
    assert not calls and state["ran"]
    assert all(s["label"] != "Free GPU (ComfyUI)" for s in steps)


def test_with_slq_hub_comfy_is_never_touched(fresh_db, monkeypatch):
    """0.4.0: the Hub's own queue owns the GPU - this app does not free ComfyUI."""
    from app.core import settings
    settings.save({"aiServer": "hub", "hubUrl": "http://hub.lan", "comfyFreeFirst": True})
    calls = _with_free(monkeypatch, True)
    steps, state = _run_one()
    assert not calls and state["ran"]
    assert all(s["label"] != "Free GPU (ComfyUI)" for s in steps)


def test_a_failing_free_does_not_stop_the_job(fresh_db, monkeypatch):
    calls = _with_free(monkeypatch, RuntimeError("comfy exploded"))
    steps, state = _run_one()
    assert calls and state["ran"]
    free = [s for s in steps if s["label"] == "Free GPU (ComfyUI)"]
    assert free and "comfy exploded" in free[0]["detail"] and free[0].get("flag") == "warn"


def test_stop_while_the_broker_waits_still_runs_the_jobs_cleanup(fresh_db, monkeypatch):
    """Stop during "free VRAM" must reach the job's own handler - otherwise
    the page would say "working" forever."""
    from app.core import comfy, jobqueue

    async def slow_free(*a, **k):
        await asyncio.sleep(5)
        return True
    monkeypatch.setattr(comfy, "free_vram", slow_free)

    async def go():
        gen: dict = {"done": False}
        view = {"state": "queued"}

        async def work():
            try:
                view["state"] = "working"
                await asyncio.sleep(5)
                view["state"] = "done"
            except asyncio.CancelledError:
                view["state"] = "stopped"
                raise
            finally:
                gen["done"] = True
        jobqueue.submit("stop-test", "t", gen, work)
        for _ in range(100):
            if gen.get("task"):
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)              # inside free_vram now
        gen["task"].cancel()
        await jobqueue.drain()
        return view, gen
    view, gen = asyncio.run(go())
    assert view["state"] == "stopped" and gen["done"] is True


def test_snapshot_names_the_broker(fresh_db):
    from app.core import jobqueue
    snap = jobqueue.snapshot()
    assert snap["broker"] == "local" and "pending" in snap


def test_a_second_stop_during_the_broker_does_not_leave_the_job_running(fresh_db, monkeypatch):
    """Review finding (0.1.0): Stop during "free VRAM", then a second Stop in
    the one loop step before the job is cancelled, used to let the job run
    on beside the next one."""
    from app.core import comfy, jobqueue

    async def slow_free(*a, **k):
        await asyncio.sleep(5)
        return True
    monkeypatch.setattr(comfy, "free_vram", slow_free)

    async def go():
        gen: dict = {"done": False}
        log: list[str] = []

        async def first():
            try:
                log.append("first started")
                await asyncio.sleep(0.3)
                log.append("first finished")
            finally:
                gen["done"] = True

        async def second():
            log.append("second started")
        jobqueue.submit("a", "t", gen, first)
        jobqueue.submit("b", "t", {"done": False}, second)
        for _ in range(100):
            if gen.get("task"):
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        gen["task"].cancel()                 # Stop while freeing VRAM
        await asyncio.sleep(0)
        gen["task"].cancel()                 # and again, right after
        await jobqueue.drain()
        await asyncio.sleep(0.4)
        return log
    log = asyncio.run(go())
    assert "first finished" not in log
    assert log.index("second started") > log.index("first started") if "first started" in log else True
