# FamilyLog - handoff

Release notes per version for the next chat, newest first. Read the newest
"Start here" before changing anything.

---

## 0.3.9 - Start here

Dagbog → Familien is per person (`src/home/DagbogFamily.tsx`, `FamilyPage`):
route `#/dagbog/familien[/<userId>[/statistik]]` (an old `/familien/<date>`
link lands on the family). Backend: `dagbog.person_days` (newest first,
`before` + `limit`, `more`), `month_moods`, `stats` (per-week figures are the
mean of the days the field was filled in × 7; "links" = mood with vs without,
≥3 days each, |diff| ≥ 0.3); all go through `_may_see` - yourself, or family
looking at family (`Forbidden` → 403). Endpoints `/api/dagbog/person`,
`/person/month`, `/stats`. Privacy changed on Søren's word: a day's
`highlight`/`hasPhoto` go to the family when `shared` (column from migration
5, default 1; rows that had a text or photo were set to 0 since they were
written under "kun du kan se"). `shared` is only in the author's own DTO;
`GET /api/dagbog/photo?user=` serves a family member's shared photo.
Migration 5 also adds "Vitaminer" to a saved food list.

---

## 0.3.8 - Start here

Dagbog fields now: mood, mental, exercise (kind `slider`, minutes, step 30,
`format: "hours"`), foods, soda (`slider`), alcohol (`slider`, was `count`),
tags, sick (kind `sick`: `options` + `sickNote`), highlight. `SLIDERS` in
dagbog.py validates min/max/step. Dagbog migration 4 adds the columns
(exercise, soda, sick, sick_note), adds the new fields to hand-set members
and drops "Sodavand" from a saved food list. Frontend `SliderField` handles
every slider (min 1 = a scale, `x/10`; min 0 = an amount with unit;
`hoursText()` for motion). Søren wants statistics on the Dagbog later
("Mønstre" - e.g. mood on days with Sport vs without, vs Økonomi/Cyklus).

---

## 0.3.7 - Start here

Dagbog: `SliderField` in `src/home/Dagbog.tsx` renders scales with max > 5
(Mentalt overskud) as `<input type=range>`; null until touched (pointer-up
or key-up sets the shown value). `dagbog.family()` lists and returns only
`FAMILY_ROLES` = admin + family; `GET /api/dagbog/family` is 403 for a user
account (`is_family`), and the front page hides its Familien tab and menu
item.

---

## 0.3.6 - Start here

`parseAnswer` (familymap/phone/logic.ts) also takes `[id]` - only when the
id is a listed place, otherwise the text stays. `Chat.tsx` `linkNames()`
turns the place name right before a marker (case-insensitive, `**` or `"`
around it allowed) into the link text. Tiles: icon beside the name
(`.hm-tile` is a 2-column grid).

---

## 0.3.5 - Start here

Phone Økonomi (`src/home/Okonomi.tsx`) has tabs and a `PeriodBar`
(`periodRange()`: month/year/12m/all/custom → frm/to). New phone API in
`okonomi_routes.py`: `GET /api/okonomi/overview?frm&to&account` (baseline
only for a whole month), `GET /api/okonomi/trend?months&account`,
`GET /api/okonomi/merchants?q&category`, `/transactions` takes q, frm, to,
account, direction, order, offset; `PUT /api/okonomi/merchant` takes
`category` and/or `name`; `state` has `accounts`. `MerchantSheet` is the one
place a shop is moved/renamed. `.fm-sheet .fm-note` fixes light-on-light
notes inside cards.

---

## 0.3.4 - Start here

Categories: `car` is gone; new keys `car-loan`, `car-tax`, `car-maintenance`,
`fuel`, `gas-station`, `children` (40 in all). `ledger.CATEGORY_GROUPS` is
the picker's sections and order (every key exactly once - tested);
`summary()["categories"]` and `/api/okonomi/data` send `group`, and both
pickers render `<optgroup>`s via `sections/ledger/CategoryOptions.tsx`.
Tankstationer is per purchase, in SQL: `_cat_sql()` maps a `fuel` merchant's
row under `FUEL_MIN_ORE` (300 kr) to `gas-station`; the overview groups by
position (`GROUP BY 1`) because grouping by the alias `category` picked the
column `m.category`. Top merchants and recurring stay merchant-level. Ledger
migration 4 re-runs the rules and sends every merchant still in `car` back
to uncategorised. The categorise prompt has hints for the new keys.

---

## 0.3.3 - Start here

Søren: "Økonomi should be user based - every user with access needs its own
data." Ledger migration 3 adds `ledger_access(user_id)` (family accounts
with Økonomi) and copies 0.3.0's `ledger_viewers` rows into it (now unused,
kept - migrations only add). `ledger.ledger_for(me)` returns `me["id"]` for
admin/user, and for family only when in `ledger_access`; there is no path
to another person's ledger any more. `/api/ledger/viewers` is gone;
`GET/PUT /api/ledger/access {userId, on}` (admin). Phone API additions in
`okonomi_routes.py`: `GET /api/okonomi/data`, `POST /api/okonomi/import`,
`DELETE /api/okonomi/imports/{id}`, `PUT /api/okonomi/merchant`,
`POST /api/okonomi/categorise` - all on the caller's own ledger.
Frontend: `DataSection` in `src/home/Okonomi.tsx`; `OkonomiPage` takes `me`
(the admin-app link only for non-family). Categories are still the code's
`CATEGORIES` (35); Søren is reviewing the list.

---

## 0.3.2 - Start here

Søren reversed "no migration": `app/sections/familymap/atlas_import.py`
(entry `python -m app.import_atlas`, wrapper `app/import_atlas.py`) imports
SLQ's Atlas from a copy of SLQ's app.db (read through a private temp copy,
so WAL files in a read-only folder are fine) plus its familymap/photos
folder. FamilyMap migration 5 adds `fm_import_map(kind, src_id, dst_id,
src_user)` - places/reviews/photos already imported are recognised on a
re-run. Places: mapped → update when SLQ is newer (or SLQ locked and ours
not); unmapped OSM/Google with the same (source, source_id) → merged; else
new. Reviews: inserted once; user by username, NULL ("slettet bruger") when
no account, filled in on a later run. Photos: files copied under their own
names (renamed on a clash, never overwritten); missing files are counted
and left out. Wishlists INSERT OR IGNORE (waiting when no account);
fm_localities INSERT OR IGNORE by osm_id; fm_settings not copied. Dry run =
the same transaction rolled back. Tests: tests/sections/familymap/test_atlas_import.py
(synthetic data only). Docs: CONTAINER.md section 6.

---

## 0.3.1 - Start here

`predict.day_map` replaces the bare kinds: per day `kind` (now also
`possible` - `uncertainty()` days either side of a coming period, from the
spread of her cycles, growing one day per cycle ahead), `cycleDay`, `phase`,
`chance` (lav/middel/høj around ovulation). `day_kinds` wraps it.
`predict.toggle_day` rebuilds her periods from the bled days with one day
flipped (calendar edit mode, `POST /api/cyklus/period/toggle`).
`cyklus.forecast_for(phase, pattern, use_diary)` = the mood/behaviour
forecast (`PROFILES` per phase, nudged by her top logged items; Dagbog
mood/overskud only for her own view). `GET /api/cyklus/dayinfo` explains one
of her days. Viewers: `GET /api/cyklus/shared/calendar|day?owner=` through
`_share_settings` (must be shared + female), a window of 21 days back to 120
ahead, fertile kinds/phase hidden and no `chance` without `share_fertile`,
no log/note/Dagbog. Frontend: `ScrollStrip` (weeks as snap columns, scrolls
to the selected day's week, keeps it on resize), `SharedDays`,
`ForecastCard`, `CyklusCalendar` (Måned/År, `DaySheet`, edit mode).
Also fixed a race in LedgerView's Ask (first askState overwrote a new ask).

---

## 0.3.0 - Start here

**Gender**: core migration 2 adds `users.gender` ('' | female | male);
`user_dto` carries it, so `request.state.user["gender"]` is live per request.
`PATCH /api/users/{uid}` (admin) sets it; `POST /api/users` takes it too.

**Økonomi read access**: ledger migration 2 `ledger_viewers(user_id PK,
owner_id)` - family account → one admin/user ledger. `ledger.ledger_for(me)`
decides whose ledger the phone page reads. The phone API is
`ledger/okonomi_routes.py` under `/api/okonomi/` (the ledger section's
`family_prefixes`); `/api/ledger/*` stays closed to family. `ledger_ask.submit`
takes `ledger_uid`: the ask slot is the asker's, the search the owner's
(`a["_ledger"]`). `okonomi_routes._ask` drops an answer whose ledger is not
the one the person may read now; `PUT /api/ledger/viewers` and clearing the
ledger forget viewers' asks too (review finding).

**Cyklus** (`sections/cyklus/`): `predict.py` is pure calendar arithmetic
(tested on its own): averages of the last six plausible cycles (15-60 days)
else her setting else 28; ovulation 14 days before the next start; fertile
= ovulation -5..+1; PMS = last 5 days; an un-ended period counts to her
usual length or the last flow day logged (max 10); 75+ days without a
start = `stale`, no forecast. `cyklus.py` holds the DB, validation, Danish
texts (`PHASES`) and `shared_with(viewer)` - the only path to another
person's cycle; it returns status always, fertile only with
`share_fertile`, today's log and symptom patterns only with
`share_details`, never the note or her Dagbog averages. Unshared fertile
days map to follicular/luteal. All own endpoints need gender female.
Frontend: `src/home/Cyklus.tsx` (`.cy-*` classes in home.css, own pink
tokens on `.cy-page`), `src/home/Okonomi.tsx` (`.ok-*`). Routes
`#/okonomi[/YYYY-MM]`, `#/cyklus`, `#/cyklus/dag/<day>`,
`#/cyklus/kalender[/<month>]`, `#/cyklus/deling`.

An independent review (privacy) found the "mid" label leak, stale Alf
answers after an access change, Dagbog averages in the shared pattern,
loose bool/list parsing and the "150 days late" case; all fixed with
regression tests. Known limit: the admin can reset a password and sign in
as her (said in HELP).

---

## 0.2.2 - Start here

`mental` is now 1-10: `SCALES` entries carry `max` (mood 5, mental 10),
`save_entry` validates against it, and the front page renders `f.max`
buttons (`.hm-scale-long` = two rows of five). The family-week detail has
the max hard-coded in `SCALE_KEYS` (`['mental', 'Mentalt overskud', 10]`)
because it does not load the config - change both if a scale changes.
Dagbog migration 3 doubles stored `mental` values <= 5 and appends
"Børnepasning" to an admin-saved `tags` list; `DEFAULT_TAGS` has it too.

---

## 0.2.1

Dagbog changes from Søren's first look (read 0.2.0 below for the rest):
fields are now `mood`, `mental` (1-5), `foods` (list, like `tags`), `alcohol`,
`tags`, `highlight`. Sleep/energy/food-scale were removed from `FIELDS`;
their columns stay (additive migrations) and are not written or sent.
Dagbog migration 2 adds `foods` and gives `foods` to members who had `food`.
Both lists come from `choice_list("tags"|"foods")` (admin-saved or
`DEFAULT_TAGS`/`DEFAULT_FOODS`). The front page treats `tags` and `foods`
the same way (chips). The save bar is solid now.

---

## 0.2.0

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
