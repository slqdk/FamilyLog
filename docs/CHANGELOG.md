# Changelog

Newest first. **ACTION REQUIRED** marks steps to do by hand.

## 0.3.13 - 2026-10-19

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`.

- Alf's tables show as tables on the front page (they came out as `|` and
  `:---`), and bold and lists as such - every answer that is not about
  places (Økonomi, the family, anything else) is Markdown now. A wide table
  scrolls sideways inside the answer; amounts do not wrap.

## 0.3.12 - 2026-10-19

Alf answers about money.

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`.

- **Økonomi through Alf**: "Hvor meget har jeg brugt på dagligvarer i år?",
  "Hvad betaler jeg via Betalingsservice?", "og i 2024?". The same three steps
  as the question box in Økonomi - the model turns the question into a
  search, the app counts exactly, the model answers from the count only -
  on the asker's **own** Økonomi, never anyone else's. Asked about someone
  else's, Alf says each person's Økonomi is their own; without Økonomi, or
  with no transactions yet, he says what to do.
- Under the answer: what was counted (in Danish), how many transactions,
  and a link to Økonomi.

## 0.3.11 - 2026-10-19

Alf knows the family's Dagbog and Cyklus; every day's text and photo shared.

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`. Then give each
account the **name** the family uses (Settings → Accounts, e.g. "Sanne" for
her account) so Alf knows who is meant. Tell the family that the text and
photos of the days written before 0.3.9 are now shared too.

- **Alf answers about the family**: "Hvordan har mor haft det i denne uge?",
  "Hvornår får Sanne menstruation?", "Hvor meget har jeg motioneret?". He
  answers from exactly what the person asking can see in the app: the
  family's days (a family account and the administrator; a user account only
  its own), a cycle only when she shares it with the asker and only what she
  shares - never her cycle note. The answer says it came from the Dagbog and
  Cyklus. Nothing from Økonomi.
- **A name per account** (Settings → Accounts) - what the family calls the
  person. Alf matches it, the first name or the username.
- **The old days are shared**: the text and photos of days written before
  0.3.9 are now seen by the family too. A day its author has saved as
  private since 0.3.9 stays private.

## 0.3.10 - 2026-10-19

Dagbog statistics, corrected.

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`.

- **Dage skrevet** counts from the person's first day when they began after
  the period's start: two days written of two is 100%, not 7% of 30.
- **Motion, alkohol and sodavand** are shown as a total ("9 t i alt på 2
  dage") until there are 7 days with them filled in; only then as a week's
  average. Two days, one of them 8 hours, were shown as 31,5 t a week.
- A field never filled in in the period shows "–", not 0.

## 0.3.9 - 2026-10-18

Dagbog → Familien, person by person.

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`. Then tell the
family: **the day's text and photo are now seen by the family** (the family
accounts and the administrator). Days already written with a text or a
photo were written under "kun du kan se", so they **stay private** until
their author opens the day, ticks *Familien kan se teksten og billedet* and
saves. A user account's days are still its own.

- **Familien** opens on a card per person: the last 7 days as smileys, the
  week's mood and the newest text. Tap a person for their page.
- **A person's days**: every day, newest first, as a card - mood, mentalt
  overskud, motion, sodavand, alkohol, sickness, activities, food, the text
  and the photo. **Hent ældre dage** goes back as far as there are days; the
  month calendar (smileys coloured by mood) jumps straight to a day.
- **Statistik per person** for 30 days, 3 months, 12 months or everything:
  days written and the longest run, mood and overskud on average, motion,
  alkohol and sodavand a week, sick days, mood per month and per weekday,
  what they do and eat most - and **what goes with the mood** (activities,
  food, motion of an hour or more, alcohol, sodavand, sickness: the mood on
  days with against days without, when there are 3 or more of each).
- **The text and photo are shared with the family**, day by day: a box under
  the text says so and can be unticked to keep a day to yourself.
- **Vitaminer** is on the food list (added to a list you saved too).

## 0.3.8 - 2026-10-17

More in the Dagbog.

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`. The new fields
are on for everyone; turn them off per person under Dagbog → Settings in
the admin app (alcohol for the children, say).

- **Motion**: a slider in half hours, 0-8 hours.
- **Sodavand**: a slider, 0-10 glas. "Sodavand" leaves the food list (days
  that had it keep it).
- **Alkohol** is a slider now too, 0-20 genstande (it was + / −).
- **Sygdom og skader**: tap what it was (forkølet, feber, hoste, ondt i
  halsen, mavepine, hovedpine, migræne, allergi, skadet, ondt i ryggen,
  andet) and a short note. The family sees it in the week - unlike the
  day's highlight, which stays private.
- The family week shows motion, sodavand and sickness for a day.
- Fixed: Cyklus could for a moment show the last chosen day's
  explanation under the new one's heading.

## 0.3.7 - 2026-10-17

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`.

- **Mentalt overskud is a slider** (1-10). Untouched it says "Træk for at
  vælge"; a tap or a drag sets it, **Nulstil** clears it.
- **Familien shows only the family**: the family accounts and the
  administrator (who is family - the family sees the administrator's days).
  A *user* account is not family: it keeps its own Dagbog but has no
  Familien tab, and its days are not in the family's week.

## 0.3.6 - 2026-10-17

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`.

- **Smaller tiles** on the front page: the icon beside the name, about half
  the height.
- **Alf's places are links**: the place's name in an answer is the link to
  it in Alf's Atlas (with a small 📍 after it). Answers where the model
  wrote `[7088]` instead of `[[7088]]` are linked too - they showed as bare
  numbers before.

## 0.3.5 - 2026-10-17

More of Økonomi on the phone.

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`.

- **Tabs**: Overblik, Posteringer, Butikker, Udvikling.
- **Any period and account** on Overblik and Posteringer: a month or a year
  to step through, the last 12 months, everything, or your own dates; one
  account or all. A longer period shows its average month.
- **Posteringer**: search all transactions, filter by category and in/out,
  sort by date or size, 50 at a time.
- **Change any category**: tap a transaction, a shop, a top receiver or a
  fixed cost to move the shop to another category or rename it - every
  purchase there follows, and your choice is never overwritten.
- **Butikker**: every shop and payee, the most money first, searchable and
  filtered by category, with who placed it (you, Alf or a rule).
- **Udvikling**: the months side by side (6, 12, 24 or all) - all spending
  with income marked, or one category - and the average month.
- Fixed: the step text under "Spørg Alf om økonomien" ("Forstår
  spørgsmålet…") was light text on a light card.

## 0.3.4 - 2026-10-17

Søren's first pass over the Økonomi categories.

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`. Afterwards, look
at **Mangler kategori** (front page → Økonomi → Dine data, or the admin
app): shops that were in "Bil & brændstof" and that no rule knows - placed
by the model or by hand - are back there to be placed in the new
categories (or press "Lad Alf placere dem").

- **"Bil & brændstof" is split** into **Billån**, **Bilafgifter**,
  **Bilvedligeholdelse** and **Brændstof** (fuel and charging). The rules
  follow: fuel stations and chargers → Brændstof; Thansen, garages, tyres,
  car wash → Bilvedligeholdelse; Motorstyrelsen, weight/ownership tax →
  Bilafgifter; car loans and leasing → Billån.
- **Tankstationer** (new): a purchase at a fuel station under 300 kr is
  the station's shop (coffee, hotdogs) and counts as Tankstationer;
  300 kr and more is Brændstof. Decided per purchase.
- **Børn** (new): childcare (pladsanvisning, dagpleje, børnehave,
  vuggestue, SFO, fritidsklub), toys and children's shops.
- **The category picker is in sections**: Hus & bolig, Bil & transport,
  Mad, Børn, Indkøb, Faste udgifter & abonnementer, Sundhed & pleje,
  Fritid & rejser, Penge, Andet - on the phone and in the admin app.
- 40 categories now (was 35).

## 0.3.3 - 2026-10-17

Økonomi per person.

**ACTION REQUIRED**:
1. `cd /opt/familylog && bash update.sh`.
2. A family account that could read someone's Økonomi (0.3.0) now has its
   **own, empty** Økonomi instead - they read in their own bank export on
   the front page (Økonomi → Dine data). Settings → Accounts shows
   **Økonomi: own data** for them; set **no** where that is not wanted.

- **Every person with Økonomi has their own data.** Admin and user accounts
  always; family accounts when you turn it on. Nobody reads anyone else's.
- **Dine data on the phone page**: read in a bank export (CSV or Excel)
  with an account name, see and delete imports, place the shops no rule
  knows (a list with a category picker), or let the model place them.
  New Økonomi starts with "Kom i gang".
- Settings → Accounts: *Økonomi: own data / no* for family accounts
  (replaces "reads <name>'s").

## 0.3.2 - 2026-10-17

Alf's Atlas comes over from SLQ Companion after all.

**ACTION REQUIRED**:
1. `cd /opt/familylog && bash update.sh`.
2. Make the family's accounts in FamilyLog with the same usernames as in SLQ.
3. Follow docs/CONTAINER.md section 6: copy SLQ's database and photos to
   the FamilyLog LXC, run `python -m app.import_atlas` as a dry run, then
   with `--apply`.

- **`python -m app.import_atlas`** brings over everything in the old Atlas:
  places with every edit, the family's reviews and photos, wishlists and
  Spørg Alf's town names. People are matched by username; reviews by
  someone without an account yet come in as "(slettet bruger)" and are
  given back on a later run. A dry run is the default; `--apply` backs up
  FamilyLog's database first. Re-running never doubles anything; an OSM
  place FamilyLog already has is merged.

## 0.3.1 - 2026-10-17

Cyklus, after the first look next to Flo.

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`.

- **The week strip swipes** - six weeks back, eight ahead - and **tapping a
  day explains it**: what it is ("Menstruation ventes", "Frugtbar dag",
  "PMS-dag", ...), the chance of pregnancy, the symptoms to expect, when
  the next period comes, and **the mood and behaviour to expect** (energy,
  mood, overskud, social, patience - typical for the phase, moved by her
  own logs and Dagbog). Today leads with what is next, like "Frugtbare
  dage om 4 dage".
- **A full calendar**: Måned (months to scroll, with "I dag") and År (the
  whole year at a glance). A coming period shows its likely days and the
  days it may come early or late (wider when her cycles vary more). Tap a
  day for its explanation; **Rediger menstruationsdatoer** marks or
  unmarks the days she bled, one tap per day.
- **Those she shares with see the prediction and the mood forecast too**:
  today's on the card, and any day ahead by swiping and tapping - by the
  same rules as before (fertile days and the chance only if she shares
  them; never her note or Dagbog scores).
- Fixed: the admin app's Økonomi question could stop updating when the
  page's first reply came back after the question was sent.

## 0.3.0 - 2026-10-17

Økonomi for the family, on the phone, and Cyklus.

**ACTION REQUIRED**:
1. `cd /opt/familylog && bash update.sh` (migrations: a gender per account,
   Økonomi read access, the Cyklus tables).
2. Settings → Accounts: set **gender** on each account (female gets
   Cyklus), and for a family account that should see Økonomi pick
   **Økonomi: reads <name>'s**.

- **Økonomi on the front page** (green, for the phone): one month at a
  time - spent, against a normal month (the six before), a bar per day,
  categories with their transactions, the biggest receivers, fixed costs -
  and Alf to ask. Read only. The tile now opens this page; import and
  categories are still in the admin app (linked at the bottom).
- **Family access to Økonomi, per person**: the administrator picks which
  family account reads which Økonomi. A family account still cannot reach
  the admin app's Økonomi API at all; its Alf answers live in its own slot
  and are dropped when the access changes or the owner clears the ledger.
- **Gender per account** (not set / female / male).
- **Cyklus** for accounts set to female, in its own soft pink look: a week
  strip, "Menstruationsdag 1" / "Menstruation om 9 dage", one tap for "it
  started / ended today" (or another day), a day log (bleeding, symptoms,
  mood, a private note), insights (phase, next period, fertile days, what
  she usually feels in this phase and her Dagbog mood then), a month
  calendar with predictions, and her cycle history (average cycle and
  period, regular or not, edit and delete).
- **She decides who sees it** (Cyklus → Deling): per account; status only
  by default, the fertile days and her day's symptoms/mood/patterns only if
  she ticks them. Nobody else sees anything - the administrator included -
  and the note is never shared. Unshared fertile days read as the phase
  around them, so no label gives them away.
- The admin app's palette is the front page's sage and olive now.
- Four tiles on the front page sit two by two on a phone.

## 0.2.2 - 2026-10-17

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`.

- **Mentalt overskud** is rated 1-10 (two rows of five buttons); Humør keeps
  its five smileys. Days already saved on the old 1-5 scale are doubled
  (3 becomes 6) so old and new days compare. The family week shows it as
  dots and "7/10".
- **Børnepasning** (childcare) is a new activity. It is also added to an
  activity list the administrator has already saved.

## 0.2.1 - 2026-10-17

The Dagbog after the first look.

**ACTION REQUIRED**: `cd /opt/familylog && bash update.sh`.

- **Søvn** and **Energi** are gone from the Dagbog.
- **Mad** is now what you ate, ticked from a list: Hjemmelavet, Fastfood,
  Takeaway, Restaurant, Kage, Chips, Slik, Is, Sodavand, Frugt og grønt,
  Morgenmad, Madpakke. The administrator edits the list (Dagbog → Settings →
  Food).
- **Aktiviteter** has a longer default list: Skole/arbejde, Sport, Computer,
  Gaming, Fjernsyn, Mobil, Vedligehold af hus og have, Rengøring, Madlavning,
  Indkøb, Venner, Familie, Udenfor, Læsning, Hobby, Fri, Syg. (A list already
  saved under Dagbog → Settings is kept as it is.)
- The family week shows the food and activities of a day.
- The **Gem dagen** bar no longer shows the form through it.

Days saved in 0.2.0 keep their mood, mental readiness, alcohol, activities
and text; their old sleep, energy and 1-5 food values stay in the database
but are no longer shown.

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
