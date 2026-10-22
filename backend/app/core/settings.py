"""Global settings: one JSON file in the data directory, admin only.

Shape and rules from SLQ's ollama.load_settings/save_settings:

* defaults below, then settings.json, then environment overrides
  (ENV_OVERRIDES) - a deployment pins a value from the compose override
  file and it wins over whatever was saved in the UI. The UI shows such a
  value as locked and names the variable, so a save that cannot take
  effect never looks as if it did.
* a save merges: only the keys it carries change.
* every value is validated; an unknown key is an error, not a silent drop.

The models are chosen per ROLE (chat, vision, categorise). A section may
keep its own override for a role (Økonomi per person, FamilyMap per
section); empty there means "use the role from here".
"""
from __future__ import annotations

import json
import os
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import db

DEFAULTS: dict = {
    # ---- the AI server (0.4.0) ----
    # "hub": SLQ Hub on the LAN (github.com/slqdk/SLQ-Hub) - its Ollama-format
    # API on port 11434 with an app key; the Hub's own queue owns the GPU, so
    # ComfyUI is not touched. "ollama": a plain Ollama (the old way).
    "aiServer": "ollama",
    "hubUrl": "",               # the Hub's LAN address, e.g. http://30.11.0.140
    "hubKey": "",               # slqhub_...; never sent back to the browser
    # ---- Ollama ----
    "ollamaUrl": "http://30.11.0.104:11434",
    "modelChat": "",            # answers: Økonomi ask, Spørg Alf
    "modelVision": "",          # photo descriptions (FamilyMap)
    "modelCategorise": "",      # Økonomi merchants; empty = the chat model
    # How long Ollama keeps a model loaded after a call. Empty = Ollama's
    # own default (5 min). The GPU is shared with SLQ and ComfyUI, so short.
    "ollamaKeepAlive": "",
    # Upper bound for the context window asked for. The model's own trained
    # length is used when it is smaller.
    "contextMax": 16384,
    # ---- the GPU ----
    "comfyUrl": "",
    "comfyFreeFirst": True,     # ask ComfyUI to free VRAM before a model job
    "gpuBroker": "local",       # local (this app's own queue). "slq" later.
    # ---- web search (Spørg Alf) ----
    "searchProvider": "duckduckgo",   # duckduckgo | searxng | brave
    "searxngUrl": "",
    "searchApiKey": "",               # Brave; never sent back to the browser
    "searchResults": 4,
    "searchFetch": 3,
    "searchBlockedRanges": "",
    # ---- maps ----
    "nominatimUrl": "https://nominatim.openstreetmap.org",
    "overpassUrl": "https://overpass-api.de/api/interpreter",
    # ---- general ----
    "timezone": "Europe/Copenhagen",
}

ENV_OVERRIDES = {
    "aiServer": "APP_AI_SERVER",
    "hubUrl": "APP_HUB_URL",
    "hubKey": "APP_HUB_KEY",
    "ollamaUrl": "APP_OLLAMA_URL",
    "comfyUrl": "APP_COMFY_URL",
    "searxngUrl": "APP_SEARXNG_URL",
    "nominatimUrl": "APP_NOMINATIM_URL",
    "overpassUrl": "APP_OVERPASS_URL",
    "timezone": "APP_TIMEZONE",
}

ROLES = {"chat": "modelChat", "vision": "modelVision", "categorise": "modelCategorise"}
SECRET_KEYS = {"searchApiKey", "hubKey"}
URL_KEYS = {"ollamaUrl", "hubUrl", "comfyUrl", "searxngUrl", "nominatimUrl", "overpassUrl"}
AI_SERVERS = ("hub", "ollama")
HUB_OLLAMA_PORT = 11434
_HUB_KEY = re.compile(r"^slqhub_[A-Za-z0-9_\-]{10,200}$")
_PATH_KEY = re.compile(r"/k/(slqhub_[A-Za-z0-9_\-]+)/?.*$")
SEARCH_PROVIDERS = ("duckduckgo", "searxng", "brave")
BROKERS = ("local",)


class Invalid(ValueError):
    """A value the settings page sent that cannot be stored."""


def path():
    return db.data_dir() / "settings.json"


def _env_pins() -> dict[str, str]:
    """{key: variable} for every key an environment variable pins now."""
    return {k: v for k, v in ENV_OVERRIDES.items() if (os.environ.get(v) or "").strip()}


def _saved() -> dict:
    p = path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if k in DEFAULTS}
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def load() -> dict:
    out = {**DEFAULTS, **_saved()}
    for key, var in _env_pins().items():
        out[key] = os.environ[var].strip()
    return out


def public() -> dict:
    """What the settings page gets: no secrets, plus which keys are pinned."""
    s = load()
    out = {k: v for k, v in s.items() if k not in SECRET_KEYS}
    out["searchApiKeySet"] = bool(s.get("searchApiKey"))
    key = s.get("hubKey") or ""
    out["hubKeySet"] = bool(key)
    # The start of the key, as the Hub's own key list shows it - enough to
    # tell which key is in use, never enough to use it.
    out["hubKeyHint"] = key[:11] + "…" if key else ""
    out["envPinned"] = _env_pins()
    return out


def _clean(key: str, value):
    if key in URL_KEYS:
        value = str(value or "").strip()
        if value and not value.startswith(("http://", "https://")):
            raise Invalid(f"{key}: the address must start with http:// or https://.")
        return value.rstrip("/") if key != "overpassUrl" else value
    if key in ("modelChat", "modelVision", "modelCategorise", "ollamaKeepAlive",
               "searchBlockedRanges"):
        return str(value or "").strip()[:200]
    if key == "searchApiKey":
        return str(value or "").strip()[:200]
    if key == "hubKey":
        value = str(value or "").strip()
        if value and not _HUB_KEY.match(value):
            raise Invalid("The SLQ Hub key starts with slqhub_ - copy it from the Hub's "
                          "Settings → Apps and keys (it is shown once, when the key is made).")
        return value
    if key == "aiServer":
        value = str(value or "").strip().lower()
        if value not in AI_SERVERS:
            raise Invalid("aiServer must be hub or ollama.")
        return value
    if key == "contextMax":
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise Invalid("contextMax must be a whole number.")
        if not 2048 <= n <= 262144:
            raise Invalid("contextMax must be between 2048 and 262144.")
        return n
    if key in ("searchResults", "searchFetch"):
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise Invalid(f"{key} must be a whole number.")
        if not 0 <= n <= 10:
            raise Invalid(f"{key} must be between 0 and 10.")
        return n
    if key == "comfyFreeFirst":
        if not isinstance(value, bool):
            raise Invalid("comfyFreeFirst must be true or false.")
        return value
    if key == "searchProvider":
        value = str(value or "").strip().lower()
        if value not in SEARCH_PROVIDERS:
            raise Invalid(f"searchProvider must be one of {', '.join(SEARCH_PROVIDERS)}.")
        return value
    if key == "gpuBroker":
        value = str(value or "").strip().lower()
        if value not in BROKERS:
            raise Invalid("Only the local queue exists so far.")
        return value
    if key == "timezone":
        value = str(value or "").strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise Invalid(f"Unknown time zone: {value!r}.")
        return value
    raise Invalid(f"Unknown setting: {key}.")      # pragma: no cover


def save(patch: dict) -> dict:
    """Merge `patch` into the saved settings and return the public view.

    `searchApiKey`: absent = unchanged, null = cleared, text = set. A key an
    environment variable pins is refused - saving it would change nothing."""
    unknown = [k for k in patch if k not in DEFAULTS]
    if unknown:
        raise Invalid(f"Unknown setting: {', '.join(sorted(unknown))}.")
    pinned = [k for k in patch if k in _env_pins()]
    if pinned:
        raise Invalid(", ".join(f"{k} is set by {ENV_OVERRIDES[k]}" for k in pinned)
                      + " in the container's environment - change it there.")
    patch = dict(patch)
    url = patch.get("hubUrl")
    if isinstance(url, str) and (m := _PATH_KEY.search(url)):
        # The Hub's "Ollama apps" line pasted whole (http://HUB:11434/k/slqhub_.../):
        # the key goes where keys go, the address keeps only the host.
        patch["hubUrl"] = url[:m.start()]
        patch.setdefault("hubKey", m.group(1))
    saved = _saved()
    for key, value in patch.items():
        if key in ("searchApiKey", "hubKey") and value is None:
            saved.pop(key, None)
            continue
        saved[key] = _clean(key, value)
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    if "timezone" in patch:
        apply_timezone()
    return public()


def hub_base(url: str | None = None, settings: dict | None = None) -> str:
    """The Hub's Ollama-format address: its LAN address with port 11434 added
    when none is given."""
    from urllib.parse import urlparse
    url = (url if url is not None else (settings or load()).get("hubUrl") or "").strip().rstrip("/")
    if not url:
        return ""
    p = urlparse(url)
    if p.port is None and p.hostname:
        url = f"{p.scheme}://{p.hostname}:{HUB_OLLAMA_PORT}{p.path}"
    return url.rstrip("/")


def uses_hub(settings: dict | None = None) -> bool:
    return (settings or load()).get("aiServer") == "hub"


def role_model(role: str) -> str:
    """The model chosen for a role here. Categorise falls back to chat, so
    one model is enough to start; vision never falls back (a text model
    cannot see)."""
    s = load()
    model = (s.get(ROLES[role]) or "").strip()
    if not model and role == "categorise":
        model = (s.get("modelChat") or "").strip()
    return model


def apply_timezone() -> None:
    """Make the process's local time the configured zone (date.today() in
    the Økonomi ask, timestamps in exports)."""
    tz = load().get("timezone") or DEFAULTS["timezone"]
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return
    os.environ["TZ"] = tz
    if hasattr(time, "tzset"):
        time.tzset()
