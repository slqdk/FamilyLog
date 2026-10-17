"""ComfyUI, only to ask it to free the GPU before a model job.

Ollama and ComfyUI share one card. Before the queue starts a model job it
can ask ComfyUI to drop its cached models (setting `comfyFreeFirst`), so the
Ollama model loads whole instead of half on the CPU. This is SLQ's
imagegen.free_vram (1.36.1 - 2.58.1) and its two helpers, nothing else.

Best-effort throughout: an unreachable ComfyUI never delays a job by more
than the wait below, and never fails it.
"""
from __future__ import annotations

import asyncio

import httpx

from . import settings as _settings

# Below this, ComfyUI holds no model on the card (an idle ComfyUI keeps a
# few hundred MB of CUDA/ROCm context at most). (SLQ 2.58.1)
IDLE_TORCH_VRAM = 768e6


def configured(settings: dict | None = None) -> bool:
    settings = settings or _settings.load()
    return bool((settings.get("comfyUrl") or "").strip())


def _base(settings: dict | None = None) -> str:
    settings = settings or _settings.load()
    return (settings.get("comfyUrl") or "").rstrip("/")


async def system_stats(settings: dict | None = None) -> dict:
    """ComfyUI's /system_stats. Empty when unreachable; callers treat that as
    "no information", not a fault."""
    if not configured(settings):
        return {}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(_base(settings) + "/system_stats")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


async def ping(url: str) -> tuple[bool, str]:
    """(reachable, message) for the Settings page's Test button."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return False, "No ComfyUI address is set."
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url + "/system_stats")
            r.raise_for_status()
            data = r.json()
        devices = data.get("devices") or []
        name = devices[0].get("name", "GPU") if devices else "no GPU reported"
        version = (data.get("system") or {}).get("comfyui_version", "?")
        return True, f"ComfyUI {version} - {name}"
    except Exception as exc:
        return False, f"ComfyUI is not answering: {exc}"


def _torch_vram_bytes(stats: dict) -> float | None:
    devices = (stats or {}).get("devices") or []
    if not devices or not isinstance(devices[0], dict):
        return None
    value = devices[0].get("torch_vram_total")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _free_vram_bytes(stats: dict) -> float | None:
    devices = (stats or {}).get("devices") or []
    if not devices or not isinstance(devices[0], dict):
        return None
    value = devices[0].get("vram_free")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def free_vram(settings: dict | None = None,
                    wait_s: float = 8.0,
                    patience_s: float = 1.5) -> bool:
    """Ask ComfyUI to drop its cached models, and wait until it has.

    /free returns as soon as the request is accepted, not when the memory is
    back, so this polls until free VRAM stops rising (SLQ 1.38.4). When
    ComfyUI's torch holds (almost) nothing there is nothing to wait for
    (2.58.1). Returns True when the memory was seen to come back, or there
    was nothing to free; False when ComfyUI is not configured or unreachable.
    """
    if not configured(settings):
        return False
    try:
        stats = await asyncio.wait_for(system_stats(settings), 3)
    except asyncio.TimeoutError:
        return False                      # unreachable: never delay the job
    if not stats:
        return False
    held = _torch_vram_bytes(stats)
    if held is not None and held < IDLE_TORCH_VRAM:
        return True

    async def ask() -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(_base(settings) + "/free",
                                  json={"unload_models": True, "free_memory": True})
            return True
        except Exception:
            return False

    if not await ask():
        return False
    before = _free_vram_bytes(await system_stats(settings))
    best = before if before is not None else 0.0
    waited = 0.0
    last_rise = 0.0
    rose = False
    while waited < wait_s:
        await asyncio.sleep(0.5)
        waited += 0.5
        now = _free_vram_bytes(await system_stats(settings))
        if now is None:
            return False                  # no numbers; do not stall on it
        if now > best + 256e6:            # a real rise, not measurement noise
            best, last_rise, rose = now, waited, True
            continue
        stable_for = waited - last_rise
        if rose and stable_for >= 1.5:
            return True                   # it climbed and has held still
        if not rose and stable_for >= patience_s:
            return True                   # nothing moved for the whole window
    return True
