# FamilyLog - handoff

Release notes per version for the next chat, newest first. Read the newest
"Start here" before changing anything.

---

## 0.2.0 - Start here

**What changed.** A mobile front page for the whole family at **/**, in
Alf's Atlas's look: Alf to talk to, tiles for Alf's Atlas, the Dagbog and
(admin/user only) Økonomi. A new **Dagbog** section. The admin app moved
from `/` to **/app/** (hash navigation: `/app/#ledger`, `#familymap`,
`#dagbog`, `#settings`). Family accounts now land on the front page.

**Three Vite pages** (`frontend/vite.config.ts`):
`/` = `index.html` → `src/home/` (HomeApp, Chat, Dagbog, logic, home.css on
top of the Atlas's `fm.css`); `/app/` = `app/index.html` → `src/main.tsx` (the
shell); `/fm/` = Alf's Atlas. First run (no accounts) sends `/` to `/app/`.

**Alf (`backend/app/sections/chat/`)** - `/api/chat/{state,send,stop,new}`.
One conversation per person in `chat_messages` (`archived` = after "Ny
samtale"). A message is one queue job: a JSON **route** call (places or
not, plus the message rewritten to stand alone using the last 8 turns);
places → `familymap_ask.gather()` (Spørg Alf's search, split out of
`run()` unchanged) and `ANSWER_PROMPT` with the last 4 turns; otherwise
`GENERAL_PROMPT` with the history. Model: `settings.role_model("chat")`
(FamilyMap's own chat override does not apply here). Answers keep `[[id]]`;
the page links them to `/fm/#/sted/<id>`.

**Dagbog (`backend/app/sections/dagbog/`)** - one row per person per day in
`dagbog_entries`: mood, sleep, energy, mental, food (1-5), alcohol (units),
tags (from the admin's list), highlight + one photo. **Privacy rule (Søren):
the family sees everything except the highlight text and photo**, which only
the author ever gets - enforced in `_entry_dto(own=...)` and in the photo
endpoints, which only read the signed-in person's own rows (the admin
included). Fields per person in `dagbog_members` (admin: Dagbog → Settings);
a field that is off is not stored. Photos under `/data/dagbog/photos/<uid>/`,
EXIF stripped (FamilyMap's `_process`). `Section.on_user_deleted` (new)
removes them when an account is deleted.

**Family access** is now `/api/fm/`, `/api/chat/`, `/api/dagbog/` (from the
sections' `family_prefixes`); `/api/dagbog/admin/...` checks admin itself.

**Found and fixed:** in this FastAPI (0.14x) included routers are not in
`app.routes`, so 0.1.0's "every route refuses family" test only saw the
shell's routes. It now reads all paths from the OpenAPI schema.

**Verify**: pytest 239+, vitest 34, tsc, vite build, browser check 40 checks
(first run → /app/, Settings, Økonomi, FamilyMap, the family's phone: Atlas,
front page chat general + places, Dagbog with photo, family week as admin
without the private text, the Økonomi tile).

**Open / next**: the Dagbog has no history or trends view beyond the week;
Alf's general answers have no web search; a desktop layout for the front
page is the phone layout centred.

---

## 0.1.0

**What it is.** A standalone, self-hosted household app (FastAPI + React +
SQLite) split out of SLQ Companion 2.67.2. Two sections, Økonomi and
FamilyMap, ported with their logic and tests unchanged; more sections come
later and plug in the same way. Name: **FamilyLog** (`backend/app/meta.py`,
the one place), technical id `familylog`, host `familylog.slq.dk`, host port
8081 in its own Proxmox LXC `30.11.0.108` (Docker; SLQ stays on `30.11.0.66`).
Repo: github.com/slqdk/FamilyLog (private).

**Layout**

```
backend/app/
  main.py          shell API: auth, users, settings, help, diagnostics; mounts every section
  meta.py          APP_DISPLAY_NAME, APP_ID, APP_VERSION (from /VERSION)
  core/            db, auth, settings, migrations, jobqueue (+broker), ollama, comfy,
                   telemetry (Steps), websearch, logs, help, sections (the Section type)
  sections/
    __init__.py    SECTIONS = [ledger, familymap, chat, dagbog]   <- the backend registry
    chat/          Alf on the front page (0.2.0)
    dagbog/        the Dagbog (0.2.0)
    ledger/        __init__ (SECTION + migrations), ledger.py, ledger_ask.py, ledger_routes.py
    familymap/     __init__ (SECTION + migrations), familymap*.py (six modules)
backend/tests/     core/, sections/ledger/, sections/familymap/, sections/test_end_to_end.py
frontend/
  index.html, app/index.html, fm/index.html   three Vite pages: / front page, /app/ admin, /fm/ Atlas
  src/home/                          the front page: HomeApp, Chat, Dagbog (0.2.0)
  src/App.tsx                        the admin shell at /app/ (nav from the registry, settings, help, account)
  src/core/                          api, types, LoginScreen, SettingsPage, HelpPanel, StepTree, Markdown
  src/sections/registry.ts           SECTIONS = [ledgerSection, familyMapSection, dagbogSection]
  src/sections/dagbog/               the Dagbog's settings in the admin app (0.2.0)
  src/sections/ledger/               index.ts, LedgerView(+test), api.ts, ledger.css
  src/sections/familymap/            index.ts, FamilyMapAdmin, api.ts, familymap.css, phone/ (the /fm/ page)
tools/  container.py (update.sh), mock_ollama.py, browser_check/{run.py,check_all.py}
deploy/container/  docker-compose.yml, docker-compose.override.example.yml
docs/   CHANGELOG, HANDOFF, HELP (served as /api/help), CONTAINER
```

**Adding a section** (e.g. `meals`):
1. `backend/app/sections/meals/` with `__init__.py` exporting
   `SECTION = Section(id="meals", title=…, router=…, migrations=[(1, "…", fn)], …)`;
   add it to `backend/app/sections/__init__.py`. Its migrations are numbered
   from 1 and recorded as `("meals", n)`; never renumber.
2. `frontend/src/sections/meals/index.ts` exporting a `SectionDef`
   (id, title, helpId `nav.meals`, tabs, render); add it to `registry.ts`.
3. Help entries in `docs/HELP.md` for every `data-help` id (`meals.*`,
   `nav.meals`) - `tests/core/test_help.py` fails otherwise.
4. Model work goes through `jobqueue.submit(key, kind, gen, factory)` and
   `ollama.stream_chat`; pick the model with `settings.role_model(role)`.
   A family account reaches only prefixes listed in `family_prefixes`.

**How SLQ's dependencies were replaced**
- `db.py` → `core/db.py`: `data_dir()` (env `APP_DATA_DIR`), `connect()`, WAL.
- `auth.py` → `core/auth.py`: same scrypt format, sessions, lockout,
  `family_allows` (prefixes from the registry). Dropped: sync tokens,
  project ownership, profiles, "trust this machine".
- `ollama.py` → `core/settings.py` (settings.json + `APP_*` env pins, roles)
  and `core/ollama.py` (`tags`, `list_models`, `stream_chat`; no warm-up,
  pulls or tools).
- `jobqueue.py` → `core/jobqueue.py`: same queue, plus a **broker** each job
  passes through. `LocalBroker.acquire()` frees ComfyUI VRAM when
  `comfyFreeFirst` is on (a "Free GPU (ComfyUI)" step in Steps). An SLQ
  broker goes in `_BROKERS` and `settings.BROKERS` when SLQ's GPU-job API
  exists. Stop during the broker still runs the job's own cleanup (tested).
- `imagegen.free_vram` → `core/comfy.py` (free_vram, system_stats, ping).
  The sections no longer call it themselves.
- `telemetry.py` → `core/telemetry.py`, `persist()` only finishes the
  recorder (no chat turns here).
- `websearch.py`, `logs.py`, `help.py` → `core/`, essentially as they were.

**Model roles.** Settings → Ollama has chat, vision, categorise
(categorise falls back to chat; vision never falls back). Section
overrides stay: Økonomi's per-person `ledger_settings.model` (overrides
both its roles) and FamilyMap's `chatModel` / `visionModel` (empty = role).
`ledger.get_settings()` now returns `model`, `categoriseModel`, `override`,
`chatRole`; `fm.chat_model()` / `fm.vision_model()` resolve FamilyMap's.

**Decisions taken (Søren, 2026-10-17)**: no migration tool - nothing is
carried over from SLQ, he moves data and accounts by hand; name FamilyLog;
host familylog.slq.dk. Own LXC `30.11.0.108` (Søren). Defaults chosen without asking: port 8081; SLQ's account limit (3, family not counted) kept.

**Verify before every release** (all were green for 0.1.0):

    cd backend && pip install -r requirements-dev.txt && python -m pytest -q     # 225 tests
    cd frontend && npm ci && npx vitest run && npx tsc --noEmit && npx vite build   # 26 tests
    python3 tools/browser_check/run.py      # real browser, real backend, mock Ollama (27 checks)

**Not verified in 0.1.0**: the Docker image was never built (Docker Hub is
blocked in the build sandbox), so the Dockerfile, compose files and
`update.sh` have not run against Docker; `tools/container.py`'s pure
functions are unit-tested only. No real Ollama, ComfyUI, Nominatim,
Overpass or web search was reached - all model and map calls in tests are
the mock or replaced functions. NPM and the `/fm/` redirect are documented,
not tried.

**Next**: first deploy on 30.11.0.108 and check `update.sh` end to end
(a second `update.sh --force` exercises backup + restart); then the
`/fm/` move; then the next section when Søren specifies it.
