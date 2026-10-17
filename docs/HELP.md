# FamilyLog — Help

One section per control. The backend (`app/core/help.py`) serves this file as
`GET /api/help`; the UI opens a section when you **Alt + click** the control,
or from the **?** in the top bar.

Format: `## <id>`, then `title:` / `where:` / `since:` / `changed:` lines, a
blank line, then the body in Markdown. Ids are dotted and must match the
`data-help` anchor in the UI; `backend/tests/core/test_help.py` fails when they
drift. When you change a control, update its section and add `changed:`.
The Økonomi and FamilyMap entries come from SLQ Companion 2.67.2.

## app.help
title: Help
where: Top bar
since: 0.1.0

This drawer, in the admin app at **/app/**. **Alt + click** any control - a button, a field, a card, a
section header - and its entry opens here. The **?** in the top bar opens
the index; the search box filters by title, location and text. **Esc**
closes it. The version in the header is the release this help describes.

## app.sections
title: Sections
where: Top bar
since: 0.1.0

The app's sections. Each has its own pages, shown as tabs under the top
bar; the app remembers the section and page you were on in this browser.
FamilyMap is shown to the administrator only.

## app.home
title: Front page
where: Top bar
since: 0.2.0
changed: 0.3.5

Opens the front page at **/** - what everyone in the family sees on the
phone: Alf to talk to, and tiles for Alf's Atlas, the Dagbog, Økonomi and
Cyklus. Family accounts land there when they sign in and can reach nothing
in this admin app. On a phone, "Add to home screen" makes it an app icon.

**Økonomi** on the front page is each person's own (0.3.3): one month at a
time (what went out, per category against a normal month, the biggest
receivers, fixed costs), Alf to ask, and **Dine data** - read in a bank
export (CSV or Excel), delete an import, place the shops no rule knows, or
let the model place them. Since 0.3.5 it has tabs: **Overblik** (any period - a month or
year to step through, the last 12 months, everything, or your own dates - and
one account or all), **Posteringer** (search, category, in/out, order; tap
one to move or rename its shop), **Butikker** (every shop, to move to another
category or rename) and **Udvikling** (the months side by side, all spending
or one category). Administrator and user accounts always have it; a
family account when the administrator turns it on (Settings → Accounts).
Nobody sees anyone else's Økonomi - the administrator included.

**Cyklus** is for accounts set to female (Settings → Accounts): a period
log with symptoms, mood and a note, the cycle day and phase, the next
period, the fertile window, PMS days, and her own patterns per phase. It is
a calendar estimate, not contraception. She chooses under **Deling** who
sees her status (phase, cycle day, next period) and whether they also see
the fertile days and her day's symptoms and mood.

Since 0.3.1 the week strip swipes over the weeks before and after; tapping
a day explains it - what it is, the chance of pregnancy, the symptoms to
expect, and the mood and behaviour to expect (energy, mood, overskud,
social, patience; "typisk" for the phase, or from her own logs and
Dagbog). The calendar has a month and a year view, likely and possible
period days, and **Rediger menstruationsdatoer** - tap the days she bled.
Those she shares with can swipe her days too and see each day's
prediction and mood forecast, by the same sharing rules (no Dagbog
scores, no note, fertile days and chance only if she shares them). Nobody else sees
anything - the administrator included - and her note is never shared.
(An administrator who resets her password could sign in as her; that is
the one limit no app can close.)

## app.settings
title: Settings
where: Top bar (administrator)
since: 0.1.0

The app-wide settings: the Ollama connection and the model per role, the
GPU, web search, maps, the time zone, the accounts and diagnostics. Only the
administrator sees them. Changes are kept in the form until **Save**;
**Undo** drops them. The **Test** buttons act at once on the address typed
in the form, saved or not.

## app.account
title: Your account
where: Top bar, your name
since: 0.1.0

Who is signed in. **Change password** sets a new one (10+ characters);
**Sign out** ends this browser's session. A login lasts 30 days for the
administrator and family accounts, 10 days for user accounts, and each
person can be signed in on two devices at once - a third sign-in ends the
least recently used one.

## settings.ollama
title: Ollama
where: Settings
since: 0.1.0

**Ollama address** is the GPU VM's Ollama (default
`http://30.11.0.104:11434`). If the container sets `APP_OLLAMA_URL`, the
field is locked and names the variable - change it in
`docker-compose.override.yml`. Under **More**: **Keep loaded** is how long
Ollama keeps a model after a call (empty = Ollama's own 5 minutes; the GPU
is shared, so short is kind), and **Context window, max** caps the context
asked for (the model's own length is used when it is smaller).

## settings.ollamaTest
title: Test the Ollama connection
where: Settings → Ollama
since: 0.1.0

Asks the address in the field (saved or not) for its models (`/api/tags`)
and lists them with size, parameters and quantisation. The model pickers
below then offer exactly those. When it fails it says why - not answering,
an HTTP status, or an address without http://.

## settings.models
title: Models per role
where: Settings → Ollama
since: 0.1.0

One model per job. **Chat / answers**: Økonomi questions and Spørg Alf.
**Vision**: FamilyMap photo descriptions - must be a vision model; without
one, photos wait (it never falls back to the chat model). **Categorise**:
placing unknown merchants in Økonomi; empty uses the chat model. A section
can override a role for itself (Økonomi per person, FamilyMap in its own
Settings). A model marked *(not on the server)* is saved but Ollama does
not have it - the job will fail and say so.

## settings.gpu
title: GPU
where: Settings
since: 0.1.0

Every model job in this app - a question, a categorise batch, a photo
description, Spørg Alf - waits in one queue and runs alone. **ComfyUI
address** is only used to ask ComfyUI to free its VRAM before a job when
**Free ComfyUI VRAM first** is on, so the Ollama model loads whole instead
of half on the CPU. It is best effort: an unreachable ComfyUI costs a few
seconds at most and never fails the job; the job's Steps show "Free GPU
(ComfyUI)" with the outcome. **Queue** is this app's own; a queue shared
with SLQ comes when SLQ's GPU-job API exists.

## settings.search
title: Web search
where: Settings
since: 0.1.0

Used by Spørg Alf when too few of the family's own places fit.
**DuckDuckGo** needs nothing; **SearXNG** your own instance's address;
**Brave** an API key (stored on the server, never shown again - **Remove**
deletes it on Save). Under **More**: how many results to ask for, how many
pages to read, and address ranges never to fetch. Private, loopback and
link-local addresses, and the Ollama and ComfyUI hosts, are always refused.

## settings.maps
title: Maps
where: Settings
since: 0.1.0

**Nominatim** turns a point tapped on the family page's map into an
address (`/reverse` is added to the address). **Overpass** is where
FamilyMap's OSM import asks; FamilyMap → Settings can override it. Both
default to the public OpenStreetMap servers.

## settings.general
title: General
where: Settings
since: 0.1.0

**Time zone** (IANA name, default Europe/Copenhagen) is the app's local
time: "this year" and "last month" in Økonomi questions, and the dates in
exports. The container's `APP_TIMEZONE` pins it.

## settings.accounts
title: Accounts
where: Settings
since: 0.1.0
changed: 0.3.3

Everyone who can sign in. **user** accounts use the app (each has their own
Økonomi); at most 3 accounts in all for administrator and users. **family**
accounts use the front page and Alf's Atlas only and do not count towards
the limit (FamilyMap → Family accounts lists them too).

**gender**: an account set to *female* gets Cyklus on the front page.
**Økonomi** (family accounts only): *own data* gives that person their own
Økonomi on the front page - their own bank exports, categories and Alf
answers, seen by nobody else. Turning it off hides it (the data stays for
when it is turned on again) and drops the answer Alf last gave them. **Password** sets a new
one and signs that person out; **Sign out** ends their sessions;
**Delete** removes the login - their FamilyMap reviews stay, shown as
"slettet bruger".

## settings.diagnostics
title: Diagnostics
where: Settings
since: 0.1.0

The version, what the model queue is doing, and the errors the app caught
since it started (newest first; click one for the traceback). The full log
is `/data/logs/familylog.log` in the container. **Clear errors** empties the
list here, not the log file.

## nav.ledger
title: Økonomi
where: Top bar
since: 0.1.0

Your own bank and card transactions: import the bank's CSV or Excel export
now and then, then see where the money went (**Overview**), ask questions
(**Ask**), browse and filter every row (**Transactions**), and fix how shops
are categorised (**Merchants**). Every number is counted by the app in its
database - the model only reads your question and writes up the result, so
a 4,000-row export is counted to the øre. Each account sees only its own
ledger. Its pages are the tabs under the top bar.

## ledger.header
title: Økonomi header
where: Økonomi, top
since: 0.1.0

How many transactions the ledger holds and the period they cover. On the
right: merchants no rule knows yet, and the model placing them.

## ledger.categorise
title: Categorise with the model
where: Økonomi header
since: 0.1.0

Built-in rules know the common shops (Netto, Q8, Jem & Fix, Proshop, ...).
Merchants they do not know are shown to the model in batches of 40 after an
import - it picks a category for each from a fixed list, and anything it
answers outside that list is ignored. Each batch is its own job in the
queue, so another job (a question, a photo) can get in between. **Stop** stops after the batch it is
on. The model only fills empty categories; your own choice always stands.

## ledger.overview
title: Overview
where: Økonomi → Overview
since: 0.1.0

What you spent and where, for the period chosen at the top: **Last 12
months**, **Month**, **Year**, **All** or **Custom** (remembered in this
browser). Tiles: money out, per month (in the Month view: your average
month before it), income and own transfers. The chart shows money out per
month - click a bar to open that month - or, in the Month view, per day
(click a day for its transactions). Then spending by category, recurring
payments and the top merchants; click any row for the transactions behind
it.

Money out is purchases minus refunds (a return at IKEA lowers IKEA). Other
money coming in - people paying you back, winnings, "Advis" - is shown as
"other money in" under Income and is not subtracted from spending. **Own
transfers** (Opsparing, Budgetkonto, "Til 1234 ...") count as neither.
**Income** is only what is in the Income category: if your salary arrives
as a transfer, set that merchant to Income on the Merchants page.

## ledger.period
title: Month and year
where: Økonomi → Overview, beside the period buttons
since: 0.1.0

‹ and › step one month (or year) back and forward; the list jumps straight
to any month with data. In the Month view, **By category** gains **Avg
month** - each category's average over up to 12 months before - and **vs
avg**, how much more (red) or less this month spent.

## ledger.top
title: Top merchants
where: Økonomi → Overview
since: 0.1.0

The merchants you spent most at in the period - top 25, 50 (the default),
100 or 250 - with how many times, the total, its share of all spending, the
average per payment and the last date. Every merchant is on the Merchants
page.

## ledger.recurring
title: Recurring payments
where: Økonomi → Overview
since: 0.1.0

Merchants paid in at least 4 of the last 6 months of data, by
Betalingsservice or in a bill-like category (subscriptions, phone,
insurance, rent and utilities, loans, card bills), with the typical monthly
amount (the median) and what that is per year. Groceries and fuel come back
every month too, but are not listed here.

## ledger.ask
title: Ask
where: Økonomi → Ask
since: 0.1.0

Ask in Danish or English: "how much at Netto?", "groceries per month in
2025", "my 5 most expensive purchases this year". Three steps, all in Steps:
the model turns the question into a search (shop names, category, period,
per month / shop / category, sum / count / list), the app counts it in the
database, and the model writes a short answer from that result only. The
matching rows are listed under the answer, so every number can be checked.
A follow-up ("and in 2024?", "per month?") keeps the previous search and
changes only what you name. Own transfers are left out unless you ask about
them. One question at a time; the latest is kept when you leave the page.

## ledger.model
title: Økonomi model
where: Økonomi → Ask, beside the question
since: 0.1.0

The Ollama model that reads questions and places unknown merchants. It runs
without thinking - its jobs are a small JSON search and a short write-up of
numbers it is given. **Settings: …** (the default) uses the models chosen
in Settings: the chat model for questions, the categorise model for
merchants. Choosing a model here uses it for both, for your account only.

## ledger.counted
title: Counted by the app
where: Økonomi → Ask, under the answer
since: 0.1.0

What the app actually counted, in words - money in or out, the shops or
categories matched, the period, and whether own transfers were left out -
with the count and total it found. If the answer and this line disagree,
this line is right.

## ledger.export
title: Download the question
where: Økonomi → Ask, beside the question
since: 0.1.0

The latest question as Markdown: the model, the search it made (as JSON),
the answer, the result the app computed (groups and rows) and the Steps
tree - for the same use as a chat export.

## ledger.transactions
title: Transactions
where: Økonomi → Transactions
since: 0.1.0

Every row, filtered by text, category, money in/out, period and account,
with the count and the sum of what is shown. The category on a row is its
merchant's: changing it moves every row of that merchant. Clicking a
number on the Overview opens this page with the matching filter.

## ledger.merchants
title: Merchants
where: Økonomi → Merchants
since: 0.1.0

Every shop or payee with its category, who set it (rule, model or you), how
often it was paid and the total. Click a name to rename it (rename two to
the same name and they are counted together in questions). Opens on **Not
categorised** while there are any.

## ledger.import
title: Import
where: Økonomi → Import
since: 0.1.0

Drop the bank's export (CSV with `;` or `,`, or Excel; Danish or English
number and date styles, with or without a header row). Rows already in the
ledger are recognised by account, date, text and amount - and two identical
purchases on one day stay two. Give each account its own name. If you
import a credit card's own statement as well, set the bank's monthly
"Forbrug på MasterCard" line to Own transfers, or the card's spending is
counted twice. **Remove** takes one import's rows out again; **Delete
everything** empties the ledger.

## nav.familymap
title: FamilyMap
where: Top bar
since: 0.1.0

The admin side of FamilyMap: the family's own reviews of places they have
been - restaurants, hotels, towns, playgrounds, outings, nature. The family
writes on their own Danish page at **/fm/** (on the phone). The tabs under
the top bar are **Places**, **Reviews**, **Family accounts**, **Import from
OSM** and **Settings**. Admin only - user accounts do not see it (they can
still use the family page).

## familymap.header
title: FamilyMap overview
where: FamilyMap
since: 0.1.0

How many places there are, how many of them the family has reviewed, and
how many reviews and photos exist. **Open family page** opens /fm/ in a new
tab - what the family sees on their phones. Your admin login works there
too.

## familymap.places
title: Places
where: FamilyMap → Places
since: 0.1.0

Every place, reviewed ones first. Search by name or address, narrow by
category or by whether the family has reviewed it. **Family** is the average
of the family's overall scores (1-100). **Source** is where the place came
from: *family* (added on the phone or here), *osm* (the import) or *web*
(found by Spørg Alf; its position is the town's, approximate);
*(edited)* marks an imported place you corrected, which later imports leave
alone. **Web** stays empty - OpenStreetMap has no ratings. The list shows
at most 500 rows (the count above is the total) - search or filter to find
one. Names sort by their first letter - quotes and leading numbers are
skipped, names of only digits come last. **+ Place** adds one by hand;
click a row to edit it.

## familymap.placeEdit
title: Edit a place
where: FamilyMap → Places → a row
since: 0.1.0

Name, category, address, position (latitude/longitude - "Nær mig" on the
phone sorts by it), website and a note. Saving an imported (OSM) place marks
it edited, and imports stop changing it. The OSM details line shows the tags
kept for the day-ideas model (opening hours, cuisine, ages...). **Delete
place** removes it with all its reviews and their photo files - there is no
undo; a deleted OSM place comes back at the next import. Changing the
category of a reviewed place keeps the reviews' old fields stored but shows
only the new category's.

## familymap.reviews
title: Reviews
where: FamilyMap → Reviews
since: 0.1.0

The newest 200 reviews across all places: score, who wrote it, when and
with whom, the category fields, the text and the photos. Click a photo to
open it full size; **×** deletes one photo, **Delete** the whole review and
its photos. The small dot on a photo is its description: green described,
amber queued, red failed (hover for the reason), white waiting. The
descriptions are listed under the photos. The family can only change their
own reviews; you can change any.

## familymap.family
title: Family accounts
where: FamilyMap → Family accounts
since: 0.1.0

Logins for the family's page. A family account signs in at /fm/ and can do
nothing else in this app - every other endpoint refuses it - and it does
not count towards the app's three-account limit. A family login lasts 30
days before the phone asks again, like the admin's. **Password** sets a new
one (10+ characters) and signs their phone out; **Sign out** ends their
sessions; **Delete** removes the login, their reviews stay under "slettet
bruger".

## familymap.import
title: Import from OSM
where: FamilyMap → Import from OSM
since: 0.1.0

Fills FamilyMap with places from OpenStreetMap for Denmark,
Schleswig-Holstein and Hamburg - one query per category to the Overpass
server in Settings. Only named places are taken - except playgrounds
(since 2.49.1): OSM rarely names them, so unnamed public ones come in as
"Legeplads, <street>" when OSM knows the street, else "Legeplads ved
<town>"; the first time someone opens one of those, its street is looked up
once and the name becomes "Legeplads, <street>". Private playgrounds
(kindergartens, housing co-ops) stay out. The table shows which OSM tags feed each category and, per
run, how many were found, added, updated, unchanged, and skipped because you
edited them. **Import all again** is safe: it updates and adds, never
deletes. A category can take minutes; the import runs on without this page.
The public Overpass server is often busy (429, or a 504 timeout even for a
small query): the import then waits and tries again - after 30 s, then 90 s
("Overpass busy") - and only then marks that category failed. **Retry
failed** runs just the failed ones. OSM data is free to keep; the family
page credits OpenStreetMap wherever it is shown.

**Aktivitet** (since 2.49.0) takes swimming baths (a sports centre with
sport=swimming, or a pool that is not private), indoor play, trampoline
parks, ice rinks, cinemas and climbing centres - run **Import all again**
once to fetch them.

The last row, **Town names**, is not a category: every city, town, village,
district and hamlet name in the region (Danish and German names too, so
"Flensborg" finds Flensburg), used only by Spørg Alf to turn "omkring
Vojens" into a point - never shown as places. Since 2.46.0 the queries ask
Overpass for full positions; run **Import all again** once after updating,
so places that came without a position get one.

## familymap.settings
title: FamilyMap settings
where: FamilyMap → Settings
since: 0.1.0

**Name of the family page** is what the phone page calls itself - browser
title, login screen and header (default "Alf’s Atlas"; emptying it brings
the default back). FamilyMap stays the name of this admin section.

The models: empty (**Settings: …**) uses the model chosen for that role in
the app's Settings; a model chosen here is used by FamilyMap instead. The
vision model never falls back to the chat model. **Vision model** describes each visit photo automatically when it is uploaded, in
the app's model queue behind whatever is already waiting; the few Danish
sentences are for the day-ideas model, not shown to the family, and say
nothing about how the people look. **Describe waiting photos** queues the
ones without a description: uploaded before a model was chosen, failed, or
forgotten by a backend restart. **Chat model** answers **Spørg Alf** on the
family page: it reads the question (where, what, a child's age), the app
searches around that place, and the model answers from the family's own
reviews first, then their wishlist, then other places - and a place the
family rated under 50 or would not revisit only as a warning. When fewer
than three places fit, it searches the web (the app's search setting) and
saves the places it finds (source *web*, position approximate). Without a
chat model (here or in Settings) the family is told to ask you to choose one. **Overpass address** is where the OSM import asks; empty uses the address in
Settings → Maps.

## nav.dagbog
title: Dagbog
where: Top bar (administrator)
since: 0.2.0
changed: 0.2.2

The Dagbog's settings. Everyone rates their own day on the front page
(**Dagbog**): mood (5 smileys), mental readiness (1-10), what they ate (food categories),
alcohol, activities and the day's highlight (a text and a photo). The family
sees each other's ratings, food and activities as a week (**Familien**); the highlight
text and photo are only ever shown to the person who wrote them - not to the
administrator either, here or anywhere else.

## dagbog.members
title: Fields per person
where: Dagbog → Settings
since: 0.2.0

Which fields each person fills in - for example no alcohol field for a
child. A field that is off is neither asked on the phone nor stored, even
if a request sends it. Every person keeps at least one field. Accounts are
made in Settings → Accounts (family accounts too).

## dagbog.tags
title: Activities
where: Dagbog → Settings
since: 0.2.0
changed: 0.2.2

The list of activities everyone picks from in their Dagbog (school or work,
sport, computer, television, house and garden, childcare, friends, ...), one per line. Duplicates and empty lines are dropped;
at most 40, each up to 30 characters. Removing one keeps it on the days
that already have it.

## dagbog.foods
title: Food
where: Dagbog → Settings
since: 0.2.1

The food categories everyone ticks under **Mad** - homemade, fast food,
takeaway, cake, chips, sweets, fruit and vegetables and so on - one per
line, same rules as the activities. The family sees what each other ticked.
