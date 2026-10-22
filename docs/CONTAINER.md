# FamilyLog in a container

FamilyLog runs in Docker in its own Proxmox LXC, **`30.11.0.108`** (Debian 12,
unprivileged, `nesting=1,keyctl=1`, 2 cores, 2 GB RAM + 512 MB swap, 24 GB
disk), on host port **8081**. SLQ stays on `30.11.0.66`. Ollama and ComfyUI
stay on the GPU VM (`30.11.0.104`) and are reached over HTTP. Nginx Proxy Manager serves it as **familylog.slq.dk**.
The update flow (`update.sh`) is SLQ's, ported unchanged.

## 1. Clone, your settings, first start

In the LXC, once:

    apt update && apt install -y curl git python3
    curl -fsSL https://get.docker.com | sh

The repo is private, so the host signs in to GitHub with a read-only
**deploy key**:

    ssh-keygen -t ed25519 -f ~/.ssh/familylog_deploy
    # add ~/.ssh/familylog_deploy.pub under the repo's Settings → Deploy keys (no write access)
    GIT_SSH_COMMAND="ssh -i ~/.ssh/familylog_deploy" \
      git clone git@github.com:slqdk/FamilyLog.git /opt/familylog
    git -C /opt/familylog config core.sshCommand "ssh -i ~/.ssh/familylog_deploy"

**Do not edit files in the clone** - updates are fast-forwards and refuse a
changed clone. Your own settings go in an override file that git ignores:

    cd /opt/familylog
    cp deploy/container/docker-compose.override.example.yml \
       deploy/container/docker-compose.override.yml
    nano deploy/container/docker-compose.override.yml   # GPU VM URLs, volume, port

A host folder instead of the named volume (easier to back up) must belong
to uid 1000: `mkdir -p /srv/familylog/data && chown -R 1000:1000 /srv/familylog/data`.

First start (builds the image; the first build takes a few minutes):

    bash update.sh compose up -d --build

Then open the address and create the administrator (the first account).
The front page is `/` (the family's phone page); the admin app is `/app/`.
`bash update.sh compose …` is `docker compose` with the right files - use it
for anything compose: `bash update.sh compose logs -f`, `… ps`, `… restart`.

Everything that is yours lives in `/data`: `app.db`, `settings.json`,
`familymap/photos/` and `logs/`. The image holds only code (Python, the app
and the built frontend) - rebuild it freely.

Environment (compose file / override):

| Variable | Meaning |
|---|---|
| `APP_DATA_DIR` | the data folder (`/data`) |
| `APP_AI_SERVER`, `APP_HUB_URL`, `APP_HUB_KEY` | SLQ Hub (0.4.0): `hub`, its LAN address, the app key; when set they win over Settings → AI server and show locked. Put the key only in the git-ignored override file |
| `APP_OLLAMA_URL`, `APP_COMFY_URL` | the old GPU VM; when set they win over Settings, and the Settings page shows them locked |
| `APP_SEARXNG_URL`, `APP_NOMINATIM_URL`, `APP_OVERPASS_URL`, `APP_TIMEZONE` | the same, for those settings |
| `TZ` | `Europe/Copenhagen` for the container itself |
| `APP_BACKUP_DIR` | (on the host, for update.sh) where backups go; default `/opt/familylog-backups` |

Leaving the `APP_*` URLs out is fine: then they are set on the Settings
page and kept in `/data/settings.json`.

## 2. Nginx Proxy Manager

New proxy host **familylog.slq.dk** → `http://30.11.0.108:8081`, with a Let's
Encrypt certificate and **Force SSL**. Websockets are not used. Under
Advanced, raise the upload limit for bank exports and photos and give Spørg
Alf and the OSM import time:

    client_max_body_size 100m;
    proxy_read_timeout 600s;

The app reads `X-Forwarded-Proto`, so its session cookie is `Secure` behind
the proxy.

## 3. The family page: from companion.slq.dk/fm/ to familylog.slq.dk/fm/

The family phones open `companion.slq.dk/fm/` today. Once FamilyLog is
running and you have made the family accounts there (FamilyMap → Family
accounts, or Settings → Accounts):

1. On the **companion.slq.dk** proxy host in NPM, Advanced, add:

       location ^~ /fm/ {
           return 301 https://familylog.slq.dk$request_uri;
       }
       location ^~ /api/fm/ {
           default_type application/json;
           return 410 '{"detail": "Familiesiden er flyttet til familylog.slq.dk - genindlæs siden."}';
       }

   The first sends the page (and home-screen icons) to the new address. The
   second makes a page that is still open on a phone show a clear message
   instead of writing into SLQ's FamilyMap after the move.
2. Each phone signs in once at the new address (a login is per address).
   A home-screen icon follows the redirect; re-adding it from the new
   address avoids the hop.
3. When you have confirmed FamilyLog works, FamilyMap and Økonomi can be
   removed from SLQ, and later the redirect.

## 4. Updates, backups and rolling back

Push to GitHub, then on the Docker host:

    cd /opt/familylog && bash update.sh

It shows the new commits and version and asks. Then:

1. It builds the new image **while the old one keeps serving**. A failed
   build puts the code back; the app was never stopped.
2. It stops the app and backs up the whole `/data` volume to
   `/opt/familylog-backups/<time>_<version>.tar.gz` (stopped, so the
   database is not copied mid-write).
3. It starts the new version and waits until it answers
   `/api/auth/status` inside the container.
4. **If it does not answer within 5 minutes, or crash-loops**, it shows the
   log and puts everything back by itself: the old code, the old image, and
   `/data` from step 2. That version is skipped until something newer is
   pushed (`--force` tries it anyway).

The three newest backups are kept (`--keep 5` keeps more).

    bash update.sh status            # version, container, does it answer, backups
    bash update.sh backups           # the backups, newest first
    bash update.sh rollback          # back to the newest backup: code, image AND data
    bash update.sh rollback <name>   # or a named one
    bash update.sh --yes             # update without asking

`rollback` saves the current state as `…-before-rollback` first, so nothing
is lost for good. Unattended, every night at 04:40, only when there is
something new:

    40 4 * * * cd /opt/familylog && bash update.sh --yes >> /var/log/familylog-update.log 2>&1

Still back up `/data` off the host too (Proxmox Backup Server, or a copy of
`/opt/familylog-backups` to the NAS): the update backups live on the same disk.

## 5. The GPU

Every model job of this app waits in one in-process queue and runs alone.
With a ComfyUI address set and **Free ComfyUI VRAM first** on (Settings →
GPU), each job first asks ComfyUI to drop its models. SLQ has its own queue,
so an SLQ answer and a FamilyLog job can still meet on the card; the queue
module (`backend/app/core/jobqueue.py`) has a broker seam for SLQ's GPU-job
API when it exists.

## 6. Bringing Alf's Atlas over from SLQ Companion (0.3.2)

Everything in the old Atlas comes over: places (yours, OSM's and every
edit), the family's reviews and photos, wishlists, and the town names Spørg
Alf uses. People are matched by **username**, so make the family's accounts
in FamilyLog first with the same usernames as in SLQ. Anyone without an
account yet is listed; their reviews come in as "(slettet bruger)" and are
given back to them when you run the import again after making the account.
Running it again is always safe - nothing is doubled.

**1. On the SLQ host** - a consistent copy of SLQ's database, and its photos:

    docker exec slq-companion python3 -c "import sqlite3; s=sqlite3.connect('/data/app.db'); d=sqlite3.connect('/tmp/atlas.db'); s.backup(d); d.execute('PRAGMA journal_mode=DELETE'); d.close()"
    mkdir -p ~/atlas
    docker cp slq-companion:/tmp/atlas.db ~/atlas/atlas.db
    docker cp slq-companion:/data/familymap/photos ~/atlas/photos
    docker exec slq-companion rm /tmp/atlas.db
    scp -r ~/atlas root@30.11.0.108:/root/

(If SLQ runs in the same LXC as FamilyLog, skip the `scp`.)

**2. On the FamilyLog LXC (30.11.0.108)** - into the container, then a dry
run that shows exactly what will happen and changes nothing:

    docker cp /root/atlas familylog:/tmp/atlas
    docker exec familylog python -m app.import_atlas /tmp/atlas/atlas.db --photos /tmp/atlas/photos

It prints the places (new / merged with FamilyLog's own OSM places /
updated), reviews, photos (and any missing from the folder), wishlists,
towns, who was matched and who has no account yet.

**3. Import:**

    docker exec familylog python -m app.import_atlas /tmp/atlas/atlas.db --photos /tmp/atlas/photos --apply

It first saves FamilyLog's database to `/data/backups/app-<time>-before-atlas-import.db`
inside the container. To undo: `bash update.sh rollback` (the update
backups), or copy that file back over `/data/app.db` with the container
stopped.

**4. Clean up** when you are happy: `docker exec -u 0 familylog rm -rf /tmp/atlas`
and `rm -rf /root/atlas` (and `~/atlas` on the SLQ host). The copies hold the
family's reviews and photos.

A place that changes in SLQ after the import is updated by a later run,
unless it was changed in FamilyLog after that. SLQ's Atlas settings (name,
models) are not copied - FamilyLog has its own under FamilyMap → Settings.
