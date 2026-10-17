# Changelog

Newest first. **ACTION REQUIRED** marks steps to do by hand.

## 0.2.0 - 2026-10-17

A front page for the family, Alf to talk to, and the Dagbog.

**ACTION REQUIRED**

1. `cd /opt/familylog && bash update.sh` (backup, build, check, rollback on failure).
2. The admin app is now at **https://familylog.slq.dk/app/**; the address
   without a path is the new front page. Update bookmarks.
3. Optional: Dagbog → Settings in the admin app - the activity list, and
   which fields each person records (e.g. no alcohol for a child).

**Front page (/)** - for everyone, phone first, in Alf's Atlas's look:
- **Alf**: ask anything. Questions about places (playgrounds, food out,
  trips...) use Spørg Alf's search over the family's own reviews and link the
  places into the Atlas; everything else gets a general answer. One
  conversation per person, kept until "Ny samtale".
- Tiles: **Alf's Atlas**, **Dagbog** ("Hvordan var i dag?" until today is
  filled in), and **Økonomi** for the administrator and user accounts only.
- Family accounts land here when they sign in; the admin app sends them here.

**Dagbog** - rate the day: mood (smileys), sleep, energy, mental readiness,
food (1-5), alcohol (units), activities, and the day's highlight (text and a
photo). **Familien** shows everyone's week. The family sees ratings and
activities; the highlight text and photo are only ever shown to their author.
The administrator sets the activities and each person's fields.

**Admin app** moved to **/app/**; `/app/#ledger`, `#familymap`, `#dagbog` and
`#settings` open those pages directly and survive a reload. The Atlas's menu
has "Til forsiden".

## 0.1.0 - 2026-10-17

The first release: a standalone household app, split out of SLQ Companion
2.67.2, with Økonomi and FamilyMap.

**ACTION REQUIRED (first install)**

1. Create the GitHub repo (`familylog`), push this tree, and add a read-only
   deploy key for the server (docs/CONTAINER.md §1).
2. On the LXC `30.11.0.108` (Docker installed): clone to `/opt/familylog`, copy
   `deploy/container/docker-compose.override.example.yml` to
   `docker-compose.override.yml` and edit it, then
   `bash update.sh compose up -d --build`.
3. In NPM: proxy host `familylog.slq.dk` → `30.11.0.108:8081` with SSL and
   `client_max_body_size 100m;` (docs/CONTAINER.md §2).
4. Open the site, create the administrator, then Settings → Ollama:
   **Test**, pick the chat and vision models, **Save**.
5. Make the family accounts (FamilyMap → Family accounts) and, when ready,
   add the `/fm/` redirect on `companion.slq.dk` (docs/CONTAINER.md §3).
   Nothing is imported from SLQ - accounts and data start empty.

**The app**

- Accounts: administrator (first run), users (max 3 accounts with the
  admin), and family accounts that reach only the family page's API.
  scrypt passwords in SLQ's format; sessions as in SLQ (30/10 days, two
  devices each).
- Settings (admin): Ollama address with **Test** (lists the models), the
  model per role (chat, vision, categorise), keep-alive and context cap;
  ComfyUI address and "free VRAM first"; web search (DuckDuckGo, SearXNG,
  Brave); Nominatim and Overpass; time zone; accounts; diagnostics.
  `APP_*` environment variables pin values and show them locked.
- One model queue for every model job, with a broker seam for SLQ's future
  GPU-job API; the optional ComfyUI free runs at the start of each job and
  shows in Steps.
- Sections are packages with their own routes, migrations (recorded per
  section), frontend folder and help ids; the navigation comes from the
  registry. The display name lives in `backend/app/meta.py` only.
- Help: Alt+click any control, or **?** - `docs/HELP.md`, kept in step with
  the UI by tests.

**Økonomi** (from SLQ 2.63.2, logic unchanged): import, rules, the model
categorising unknown merchants, Overview, Transactions, Merchants, Ask
with every number from SQL. Changed: the model defaults to Settings' roles
(chat for questions, categorise for merchants); a person's own choice
still overrides both.

**FamilyMap** (from SLQ 2.49.x, logic unchanged): the Danish family page at
`/fm/`, the admin view, photos, OSM import, Nominatim, photo descriptions,
the wishlist and Spørg Alf. Changed: its chat and vision models default to
Settings' roles (FamilyMap's own choice overrides); the Overpass address
defaults to Settings → Maps.

**Deployment**: Dockerfile (Python 3.13 slim, uid 1000, `/data`), compose
with an override file (host port 8081), `update.sh` with backup, health
check and automatic rollback (SLQ's `slq_container.py`).
