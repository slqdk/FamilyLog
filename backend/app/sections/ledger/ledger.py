"""Økonomi: a ledger of bank and card transactions (2.63.0).

The person drops a bank export (CSV or XLSX) now and then; the rows go into
SQLite and every number the app shows or answers with is computed here, in
SQL - never by the model. A model in a chat once read the first 200 rows of
a long export, counted a handful of payments to one shop and called it the
whole file; the real count was several times higher. Adding up rows is the
database's job.

What happens to a row:

* **parse** - Danish and English number and date styles, `;` `,` or tab,
  with or without a header (`parse_table`).
* **merge** - a re-upload overlaps the last one. A row is identified by
  (account, date, text, amount, occurrence): the occurrence is the n-th
  identical row that day, because two identical coffees on one day are two
  coffees (Søren's export has six such pairs) and a plain set would drop one.
* **classify** - kind (card, MobilePay, Betalingsservice, ATM, transfer,
  interest, fee, salary, card bill), the merchant pulled out of the text
  (`kontaktløs Dankort ABC Lavpris, Byen Nota C100200` -> ABC Lavpris), a
  foreign amount when there is one.
* **categorise** - by merchant: a built-in rule (Netto -> groceries), the
  model's suggestion for a merchant no rule knows (ledger_ask), or the
  person's own choice, which nothing overwrites.

Transfers between the person's own accounts (Opsparing, Budgetkonto, "Til
1234 ...") are category `transfers` and count as neither spending nor income
- otherwise they top every list. Amounts are stored in øre (integers), so a
sum is exact.
"""
from __future__ import annotations

import csv
import io
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from app.core import db

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200_000


class Invalid(ValueError):
    """Something the person can fix - shown as it is."""


# ---- categories ---------------------------------------------------------------
# key -> (English label, Danish label). The model gets both, so a question in
# either language finds the key.
#
# Some internal keys keep an old name for a new label, so existing rows are
# not disturbed: `home` is labelled "House improvement", `clothing` "Clothes",
# `leisure` "Sports & entertainment", `loans` "Quick loans". The keys that
# genuinely split (eating-out -> fast-food/restaurant, housing ->
# utilities/rent/mortgage) are migrated by migration 050. (2.63.2)
CATEGORIES: dict[str, tuple[str, str]] = {
    "groceries": ("Groceries", "Dagligvarer"),
    "fast-food": ("Fast food", "Fast food"),
    "restaurant": ("Restaurant", "Restaurant"),
    # 0.3.4 (Søren): "Bil & brændstof" split in four, plus the fuel
    # station's shop; and children.
    "car-loan": ("Car loan", "Billån"),
    "car-tax": ("Car taxes & fees", "Bilafgifter"),
    "car-maintenance": ("Car maintenance", "Bilvedligeholdelse"),
    "fuel": ("Fuel & charging", "Brændstof"),
    "gas-station": ("Fuel station shop", "Tankstationer"),
    "children": ("Children", "Børn"),
    "transport": ("Transport & parking", "Transport & parkering"),
    "clothing": ("Clothes", "Tøj"),
    "germany-shopping": ("Germany shopping", "Tysklandshandel"),
    "china-shopping": ("China shopping", "Kinahandel"),
    "electronics": ("Electronics & IT", "Elektronik & IT"),
    "shopping": ("Other shopping", "Andre indkøb"),
    "home": ("House improvement", "Boligforbedring"),
    "rent": ("House rent", "Husleje"),
    "mortgage": ("House mortgage", "Boliglån"),
    "utilities": ("Living utilities", "Forbrug (el, vand, varme)"),
    "streaming": ("Streaming", "Streaming"),
    "tv": ("TV", "TV"),
    "ai": ("AI subscriptions", "AI-abonnementer"),
    "subscriptions": ("Subscriptions & software", "Abonnementer & software"),
    "phone": ("Phone", "Telefon"),
    "insurance": ("Insurance", "Forsikring"),
    "union": ("Fagforening", "Fagforening"),
    "health": ("Health & pharmacy", "Sundhed & apotek"),
    "dental": ("Dental", "Tandlæge"),
    "physio": ("Physio", "Fysioterapeut"),
    "personal-care": ("Personal maintenance", "Personlig pleje"),
    "leisure": ("Sports & entertainment", "Sport & underholdning"),
    "travel": ("Travel & holidays", "Rejser & ferie"),
    "cash": ("Cash", "Kontanter"),
    "people": ("Paid to people", "Betalt til personer"),
    "card-bill": ("Credit card bill", "Kreditkortregning"),
    "fees": ("Fees & interest", "Gebyrer & renter"),
    "loans": ("Quick loans", "Kviklån"),
    "income": ("Income", "Indtægter"),
    "transfers": ("Own transfers", "Egne overførsler"),
    "other": ("Other", "Andet"),
}
# The order and sections of the category picker (0.3.4: house first, then
# the car, ...). Every key in exactly one section.
CATEGORY_GROUPS: list[tuple[str, list[str]]] = [
    ("Hus & bolig", ["rent", "mortgage", "utilities", "home"]),
    ("Bil & transport", ["car-loan", "car-tax", "car-maintenance", "fuel", "gas-station", "transport"]),
    ("Mad", ["groceries", "fast-food", "restaurant"]),
    ("Børn", ["children"]),
    ("Indkøb", ["clothing", "electronics", "germany-shopping", "china-shopping", "shopping"]),
    ("Faste udgifter & abonnementer", ["insurance", "phone", "streaming", "tv", "ai", "subscriptions", "union"]),
    ("Sundhed & pleje", ["health", "dental", "physio", "personal-care"]),
    ("Fritid & rejser", ["leisure", "travel"]),
    ("Penge", ["income", "transfers", "people", "cash", "card-bill", "fees", "loans"]),
    ("Andet", ["other"]),
]
# A purchase at a fuel station (a merchant in "fuel") below this is the
# station's shop - coffee, a hotdog - and counts as "gas-station" (0.3.4,
# Søren: by amount). Decided per purchase, in the SQL (_cat_sql).
FUEL_MIN_ORE = 300_00


def category_group(key: str) -> str:
    for title, keys in CATEGORY_GROUPS:
        if key in keys:
            return title
    return "Andet"


# Keys retired in 2.63.2, mapped to their best successor for any row still
# holding them (migration 050, and _spend_sql's safety).
RETIRED_CATEGORIES = {"eating-out": "restaurant", "housing": "utilities"}
# Neither spending nor income: money moving between the person's accounts.
NOT_COUNTED = {"transfers"}
UNCATEGORISED = ""            # a merchant the rules and the model have not placed yet


def category_label(key: str) -> str:
    return CATEGORIES.get(key, ("Not categorised", ""))[0] if key else "Not categorised"


def category_da(key: str) -> str:
    """The Danish name, for the family's phone page (0.3.0)."""
    return CATEGORIES.get(key, ("", "Ikke kategoriseret"))[1] if key else "Ikke kategoriseret"


# ---- who has an Økonomi (0.3.3) ------------------------------------------------------------------
# Søren: "Økonomi should be user based - every user with access needs its own
# data." Every admin and user account has its own ledger; a family account
# has one when the administrator turns Økonomi on for it. Nobody reads
# anyone else's ledger - the queries all take the signed-in person's id.
# (0.3.0's read access to another account's ledger is gone; its table,
# ledger_viewers, stays unused - migrations only add.)

def access_list() -> list[int]:
    """Family accounts with Økonomi turned on."""
    with db.connect() as con:
        return [r[0] for r in con.execute("SELECT user_id FROM ledger_access ORDER BY user_id")]


def set_access(user_id: int, on: bool) -> None:
    with db.connect() as con:
        u = con.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if u is None:
            raise Invalid("No such account.")
        if u["role"] != "family":
            raise Invalid("Admin and user accounts always have their own Økonomi.")
        if on:
            con.execute("INSERT OR IGNORE INTO ledger_access (user_id) VALUES (?)", (user_id,))
        else:
            con.execute("DELETE FROM ledger_access WHERE user_id=?", (user_id,))


def ledger_for(me: dict) -> int | None:
    """The signed-in person's own ledger, or None when they have no Økonomi."""
    if me["role"] in ("admin", "user"):
        return me["id"]
    with db.connect() as con:
        r = con.execute("SELECT 1 FROM ledger_access WHERE user_id=?", (me["id"],)).fetchone()
    return me["id"] if r else None


# ---- merchant rules -------------------------------------------------------------
# (pattern on the cleaned merchant OR the raw text, canonical name, category).
# The canonical name groups a chain's shops: "MCDKOLDING", "MCD VEJLE DTC" and
# "MCDONALDS RODEKRO" are all McDonald's. First match wins.
_RULES_SRC: list[tuple[str, str, str]] = [
    # Danish supermarkets (German border shops are "germany-shopping" below).
    (r"\bnetto\b", "Netto", "groceries"),
    (r"\brema\s?1000\b", "Rema 1000", "groceries"),
    (r"\bf(?:ø|oe)tex\b", "Føtex", "groceries"),
    (r"\bbilka\b", "Bilka", "groceries"),
    (r"\blidl\b", "Lidl", "groceries"),
    (r"\baldi\b", "Aldi", "groceries"),
    (r"\bkvickly\b", "Kvickly", "groceries"),
    (r"\bsuper\s?brugsen\b", "SuperBrugsen", "groceries"),
    (r"\bdagli'?\s?brugsen\b", "Dagli'Brugsen", "groceries"),
    (r"\bcoop\s?365\b", "Coop 365", "groceries"),
    (r"\bcoop\b", "Coop", "groceries"),
    (r"\bfakta\b", "Fakta", "groceries"),
    (r"\bmeny\b", "Meny", "groceries"),
    (r"\bspar\b", "Spar", "groceries"),
    (r"\bl(?:ø|oe)vbjerg\b", "Løvbjerg", "groceries"),
    (r"\babc lavpris\b", "ABC Lavpris", "groceries"),
    (r"\bfisketorvet\b|\bfiskehandel\b", "Fiskehandel", "groceries"),
    (r"\bslagter\b", "Slagter", "groceries"),
    (r"\bbager\b|\bbageri\b|\bbakery\b|\blagkagehuset\b", "Bager", "groceries"),
    (r"\bnemlig\b", "Nemlig.com", "groceries"),
    # Germany shopping - the border shops and German retail/supermarkets.
    (r"\bfleggaard\b", "Fleggaard", "germany-shopping"),
    (r"\bcalle\b", "Calle", "germany-shopping"),
    (r"\bedeka\b", "Edeka", "germany-shopping"),
    (r"\brewe\b", "Rewe", "germany-shopping"),
    (r"\bfamila\b", "Famila", "germany-shopping"),
    (r"\bcitti\b", "Citti", "germany-shopping"),
    (r"\bnah\s?&\s?frisch\b", "Nah & Frisch", "germany-shopping"),
    (r"\bkaufland\b|\bmarktkauf\b|\bnetto marken\b", "", "germany-shopping"),
    (r"\botto duborg\b|\bscandinavian park\b|\bpoetzsch\b|\bpattburg\b|\bpholz\b|\bmaruhn\b", "", "germany-shopping"),
    (r"\bsky-?markt\b|\bfackelmann\b|\bdänisches bettenlager\b|\bdaenisches bettenlager\b", "", "germany-shopping"),
    # Fast food & takeaway.
    (r"\bmc\s?d(?:onald'?s)?\b|^mcd", "McDonald's", "fast-food"),
    (r"\bburger king\b", "Burger King", "fast-food"),
    (r"\bsunset\s?boulevard\b", "Sunset Boulevard", "fast-food"),
    (r"\bmax burgers?\b", "Max Burgers", "fast-food"),
    (r"\bkfc\b", "KFC", "fast-food"),
    (r"\bsubway\b", "Subway", "fast-food"),
    (r"\bwolt\b", "Wolt", "fast-food"),
    (r"\bjust\s?eat\b", "Just Eat", "fast-food"),
    (r"\bshawarma\b|\bkebab\b|\bd(?:ö|oe)ner\b|\bgrill\b|\bp(?:ø|oe)lse|\bhotdog\b|\bimbiss\b", "", "fast-food"),
    (r"\bpizza|\bpizzeria\b", "", "fast-food"),
    (r"\bsushi\b|\bwok\b|\bnoodle", "", "fast-food"),
    # Sit-down restaurants, cafés, bars, inns.
    (r"\brestaurant|\bristorante\b|\btrattoria\b|\bosteria\b|\btaverna\b", "", "restaurant"),
    (r"\bkro\b|\bbistro\b|\bbrasserie\b|\bdiner\b|\bsteakhouse\b|\bbr(?:ø|oe)dsdorff\b", "", "restaurant"),
    (r"\bcaf[eé]\b|\bkaffe\b|\bstarbucks\b|\bespresso house\b|\bbaresso\b|\bjoe & the juice\b", "", "restaurant"),
    (r"\bbodega\b|\bv(?:æ|ae)rtshus\b|\bbryghus\b|\bbrewpub\b|\bpub\b|\bbar\b", "", "restaurant"),
    (r"\bhotte\b|\boesterkroen\b|\b(?:ø|oe)sterkroen\b|\bbanehuset\b", "", "restaurant"),
    (r"\bis\b.{0,10}\bved\b|\bishuset\b|\bgelato\b|\bisbar\b", "", "restaurant"),
    # Car & fuel.
    # Fuel stations and charging -> fuel; a small purchase there counts as the
    # station's shop ("gas-station", by amount - see FUEL_MIN_ORE). (0.3.4)
    (r"\bq8\b", "Q8", "fuel"),
    (r"^ok\b|\bok plus\b|\bok benzin\b", "OK", "fuel"),
    (r"\bcircle\s?k\b", "Circle K", "fuel"),
    (r"\bshell\b", "Shell", "fuel"),
    (r"\buno-?x\b", "Uno-X", "fuel"),
    (r"\bingo\b", "Ingo", "fuel"),
    (r"\bf24\b", "F24", "fuel"),
    (r"\bgo'?on\b", "Go'on", "fuel"),
    (r"\boil!?\s?tank\b|\boil!\b", "OIL! tank & go", "fuel"),
    (r"\besso\b", "Esso", "fuel"),
    (r"\baral\b", "Aral", "fuel"),
    (r"\bstar tankstelle\b|\btankstelle\b|\bjet tank", "", "fuel"),
    (r"\bclever\b|\bspirii\b|\bmonta\b|\bionity\b|\btesla supercharg", "", "fuel"),
    # Keeping the car going -> car-maintenance; the state's car taxes -> car-tax;
    # paying off the car -> car-loan.
    (r"\bthansen\b|\bt\.\s?hansen\b", "Thansen", "car-maintenance"),
    (r"\bbilvask|\bvaskehal|\bwashtec\b", "", "car-maintenance"),
    (r"\bauto(?:værksted|vaerksted)?\b|\bdæk\b|\bdaek\b|\bbilsyn\b|\bmekaniker\b", "", "car-maintenance"),
    (r"\bmotorstyrelsen\b|\bv(?:æ|ae)gtafgift|\bejerafgift|\bgr(?:ø|oe)n afgift|\bbilafgift", "", "car-tax"),
    (r"\bbill(?:å|aa)n\b|\bbilfinans|\bautol(?:å|aa)n\b|\bbilleasing|\bprivatleasing", "", "car-loan"),
    (r"\btrailerudlejn", "", "transport"),
    # Children: childcare, after-school, toys and children's shops.
    (r"\bpladsanvisning|\bdagpleje|\bb(?:ø|oe)rnehave|\bvuggestue|\bsfo\b|\bfritidsklub|\bfritidshjem",
     "", "children"),
    (r"\bbabysam\b|\bbr[- ]leget(?:ø|oe)j|\blegek(?:æ|ae)den\b|\bname it\b|\bbilka toys\b", "", "children"),
    # Transport & parking.
    (r"\beasypark\b", "EasyPark", "transport"),
    (r"\bparkman\b", "ParkMan", "transport"),
    (r"\bcontipark\b", "Contipark", "transport"),
    (r"\bapcoa\b|\bparkering\b|\bparking\b|\bparkhaus\b|\bonepark\b", "", "transport"),
    (r"\bbrobizz\b", "BroBizz", "transport"),
    (r"\bstoreb(?:æ|ae)lt\b|\bsund\s?&\s?b(?:æ|ae)lt\b|\b(?:ø|oe)resundsbro", "", "transport"),
    (r"\bdsb\b", "DSB", "transport"),
    (r"\brejsekort\b", "Rejsekort", "transport"),
    (r"\bflixbus\b", "FlixBus", "transport"),
    (r"\btaxi\b|\buber\b|\bdantaxi\b", "", "transport"),
    (r"\bscandlines\b|\bmolslinjen\b|\bfærge\b|\bfaerge\b", "", "transport"),
    (r"\brastst\.?\b|\braststätte\b|\bautohof\b", "", "transport"),
    # House improvement: building materials, tools, garden, furniture.
    (r"\bdavidsens\b|\bdavidsen\.as\b|^davidsen\s+-\s", "Davidsens Tømmerhandel", "home"),
    (r"\bjem\s?&\s?fix\b", "Jem & Fix", "home"),
    (r"\bbauhaus\b", "Bauhaus", "home"),
    (r"\bsilvan\b", "Silvan", "home"),
    (r"\bharald nyborg\b", "Harald Nyborg", "home"),
    (r"\bstark\b", "Stark", "home"),
    (r"\bxl-?byg\b", "XL-Byg", "home"),
    (r"\bbygma\b", "Bygma", "home"),
    (r"\bikea\b", "IKEA", "home"),
    (r"\bjysk\b", "JYSK", "home"),
    (r"\bilva\b", "ILVA", "home"),
    (r"\bs(?:ø|oe)strene grene\b", "Søstrene Grene", "home"),
    (r"\bflying tiger\b", "Flying Tiger", "home"),
    (r"\bisenkr(?:æ|ae)mmer|\bvvs\b|\bel-?grossist|\bmaling\b|\bfl(?:ü|ue)gger\b|\bjohn bull\b|\bdepotrum\b", "", "home"),
    (r"\bbilligblomst|\bblomster|\bplantorama\b|\bplantecenter\b", "", "home"),
    (r"\bt(?:ø|oe)mmerhandel\b|\btr(?:æ|ae)last\b|\bbyggecenter\b|\bbyggemarked\b", "", "home"),
    (r"\bk(?:ø|oe)kken\b|\bhth\b|\bkvik\b", "", "home"),
    # House rent.
    (r"\bhusleje\b|\bdepositum\b|\bboligforening\b|\bandelsbolig\b|\bejendomskontor\b|\bejendomsservice\b", "", "rent"),
    # House mortgage.
    (r"\brealkredit\b|\btotalkredit\b|\bnykredit\b|\bbrf\s?kredit\b|\bnordea kredit\b|\bboliglån\b|\bprioritet", "", "mortgage"),
    # Living utilities: power, water, heating, waste.
    (r"\bnorlys\b(?!\s?(?:fiber|bredb|tv))", "Norlys", "utilities"),
    (r"\bandel energi\b|\bandel\b", "Andel Energi", "utilities"),
    (r"\b(?:ø|oe)rsted\b", "Ørsted", "utilities"),
    (r"\bewii\b", "Ewii", "utilities"),
    (r"\bvandv(?:æ|ae)rk\b|\bforsyning\b|\bfjernvarme\b|\bvarmev(?:æ|ae)rk\b|\bstr(?:ø|oe)mregning\b|\belregning\b|\bnrgi\b|\benergi fyn\b", "", "utilities"),
    (r"\bforbrugsopg|\brenovation\b|\baffald\b", "", "utilities"),
    # Electronics & IT.
    (r"\bproshop\b", "Proshop", "electronics"),
    (r"\bpower\b", "Power", "electronics"),
    (r"\belgiganten\b", "Elgiganten", "electronics"),
    (r"\bkomplett\b", "Komplett", "electronics"),
    (r"\bcomputersalg\b", "Computersalg", "electronics"),
    (r"\bav-?cables\b", "AV-Cables", "electronics"),
    (r"\blavprisel\b", "Lavprisel", "electronics"),
    (r"\bcomputercity\b", "ComputerCity", "electronics"),
    (r"\bfona\b", "Fona", "electronics"),
    (r"\bmedia\s?markt\b", "MediaMarkt", "electronics"),
    (r"\bsaturn\b", "Saturn", "electronics"),
    (r"\bapple store\b", "Apple Store", "electronics"),
    (r"\bstepperonline\b|\bstepper online\b", "StepperOnline", "electronics"),
    (r"\breichelt\b|\bconrad\b|\bmouser\b|\bdigi-?key\b|\bfarnell\b|\belfa\b|\bkjell\b", "", "electronics"),
    (r"\bbambu\b|\bprusa\b|\b3djake\b|\brefurb\.eu\b|\bgreenline\b", "", "electronics"),
    # AI subscriptions.
    (r"\banthropic\b|\bclaude\.ai\b", "Anthropic (Claude)", "ai"),
    (r"\bopenai\b|\bchatgpt\b", "OpenAI", "ai"),
    (r"\bmidjourney\b", "Midjourney", "ai"),
    (r"\bperplexity\b", "Perplexity", "ai"),
    (r"\bcursor\b|\bgithub copilot\b|\bcopilot\b", "", "ai"),
    (r"\belevenlabs\b|\brunway\b|\bgoogle gemini\b|\bx\.ai\b|\bgrok\b|\bmistral\b|\breplicate\b", "", "ai"),
    # Streaming (film, TV-on-demand, music).
    (r"\bnetflix\b", "Netflix", "streaming"),
    (r"\byoutube\s?premium\b|\byoutubepremium\b", "YouTube Premium", "streaming"),
    (r"\bspotify\b", "Spotify", "streaming"),
    (r"\bdisney\b", "Disney+", "streaming"),
    (r"\bhbo\b|\bmax\.com\b", "HBO Max", "streaming"),
    (r"\bviaplay\b", "Viaplay", "streaming"),
    (r"\bskyshowtime\b|\bprime video\b|\bparamount\b|\bapple tv\b|\bblockbuster\b", "", "streaming"),
    (r"\bmofibo\b|\bstorytel\b|\bnextory\b|\baudible\b|\bpodimo\b|\btidal\b|\bdeezer\b", "", "streaming"),
    # TV (broadcast / cable / distribution).
    (r"\btv\s?2\b|\btv2 \b", "TV 2", "tv"),
    (r"\byousee\b", "YouSee", "tv"),
    (r"\bstofa\b", "Stofa", "tv"),
    (r"\bboxer\b|\ballente\b|\bviasat\b|\bcanal digital\b|\bantenneforening\b|\bdr licens\b|\bmedielicens\b", "", "tv"),
    # Other subscriptions & software (hosting, cloud, app stores).
    (r"\bsimply\.com\b", "Simply.com", "subscriptions"),
    (r"\bgoogle\s?\*?\s?(?:google )?storage\b|\bgoogle one\b", "Google One", "subscriptions"),
    (r"\bgithub\b", "GitHub", "subscriptions"),
    (r"\bmicrosoft\b|\bxbox\b|\boffice 365\b", "Microsoft", "subscriptions"),
    (r"\bapple\.com\b|\bitunes\b|\bapp store\b", "Apple.com", "subscriptions"),
    (r"\bdropbox\b|\bproton\b|\bnordvpn\b|\bcloudflare\b|\bnamecheap\b|\bgandi\b|\bone\.com\b|\bhetzner\b|\bdigitalocean\b", "", "subscriptions"),
    (r"\bgoogle\b", "", "subscriptions"),
    # Phone & mobile.
    (r"\btelmore\b", "Telmore", "phone"),
    (r"\bcbb\b", "CBB Mobil", "phone"),
    (r"\btelenor\b", "Telenor", "phone"),
    (r"\btelia\b", "Telia", "phone"),
    (r"\bnorlys\s?(?:fiber|bredb(?:å|aa)nd)\b|\bfibia\b|\bwaoo\b|\bfastspeed\b|\bhiper\b", "", "phone"),
    (r"\boister\b|\blebara\b|\blycamobile\b|\bduka\b|\bgreentel\b|\bmobilix\b", "", "phone"),
    (r"\btdc\b|\bnuuday\b", "TDC", "phone"),
    # Insurance.
    (r"\btryg\b|\balm\.? brand\b|\btopdanmark\b|\bcodan\b|\bgf forsikring\b|\bif skadeforsikring\b|\blb forsikring\b|\bforsikring\b", "", "insurance"),
    # Fagforening (trade union) and unemployment fund.
    (r"\bfagforening\b|\ba-?kasse\b|\b3f\b|\bdansk metal\b|\bmetal\b.{0,6}\bforbund\b|\bhk\b|\bfoa\b|\bkrifa\b|\base\b|\bfagligt\b|\bprosa\b|\bida\b|\bing(?:e|i)ni(?:ø|oe)rforening|\bteknisk landsforbund\b|\blederne\b|\bdj(?:ø|oe)f\b|\bserviceforbund\b", "", "union"),
    # Health & pharmacy (dental and physio split off below).
    (r"\btandl(?:æ|ae)ge|\btandklinik\b|\btandpleje\b|\bdentist\b", "", "dental"),
    (r"\bfysioterap|\bfysio\b|\bkiropraktor\b|\bzoneterap|\bosteopat\b|\bphysio\b", "", "physio"),
    (r"\bapotek|\bapoteket\b|\bsygehus\b|\bhospital\b|\boptiker\b|\bsynoptik\b|\bprofil optik\b|\bl(?:æ|ae)ge\b|\bl(?:æ|ae)gehus\b|\bspeciall(?:æ|ae)ge\b", "", "health"),
    # Personal maintenance: hair, beauty, grooming, drugstore.
    (r"\bfris(?:ø|oe)r\b|\bbarber\b|\bsalon\b|\bkl(?:ø|oe)verblad\b", "", "personal-care"),
    (r"\bmatas\b|\bparfum|\bkosmetolog\b|\bsk(?:ø|oe)nhed\b|\bnegle\b|\bnail\b|\bwellness\b|\bsolcenter\b|\btatov|\bspa\b", "", "personal-care"),
    (r"\bdm drogerie\b|\bdrogerie\b|\brossmann\b|\bnormal a/s\b|\bnormal\b.{0,10}\b(?:vojens|hadersl|dk\d)", "Normal", "personal-care"),
    # Clothes & shoes.
    (r"\bh\s?&\s?m\b|\bzalando\b|\bboozt\b|\bdeichmann\b|\bskoringen\b|\bvero moda\b|\bjack\s?&\s?jones\b|\bbestseller\b|\bonly\b|\bmagasin\b|\bzizzi\b|\bvila\b", "", "clothing"),
    (r"\bt(?:ø|oe)j\s?eksperten\b|\bcb mode\b|\bsmagen\b|\bkik\b|\bc&a\b|\bprimark\b|\bnew yorker\b", "", "clothing"),
    (r"\bsport\s?24\b|\bintersport\b|\bsportmaster\b|\bunisport\b|\bstadium\b.{0,8}\bsport\b", "", "clothing"),
    # China shopping.
    (r"\baliexpress\b|\balipay\b|\balibaba\b", "AliExpress", "china-shopping"),
    (r"\btemu\b", "Temu", "china-shopping"),
    (r"\bshein\b", "Shein", "china-shopping"),
    (r"\bwish\b|\bbanggood\b|\bdhgate\b|\bgearbest\b|\bcdon\b.{0,0}", "", "china-shopping"),
    # Sports & entertainment: games, cinema, events, clubs, gym, betting.
    (r"\bdazn\b", "DAZN", "leisure"),
    (r"\bf1\.com\b|\bf1 tv\b|\beurosport\b", "F1 TV", "leisure"),
    (r"\bsteam(?:games|powered)?\b|\bsteamgames\.com\b", "Steam", "leisure"),
    (r"\bplaystation\b|\bpsn\b|\bsony interactive\b", "PlayStation", "leisure"),
    (r"\bnintendo\b", "Nintendo", "leisure"),
    (r"\bepic games\b", "Epic Games", "leisure"),
    (r"\bdigital license retailer\b|\bkinguin\b|\bg2a\b|\binstant gaming\b|\bproductkeys\b", "", "leisure"),
    (r"\bairsoft", "", "leisure"),
    (r"\bdanske spil\b|\bbet365\b|\bunibet\b|\blotto\b|\btipico\b|\bnordicbet\b", "", "leisure"),
    (r"\byourticket\b|\bticketmaster\b|\bbilletlugen\b|\bticketbutler\b|\bbillet|\bticket", "", "leisure"),
    (r"\bishock|\bishockey\b|\bfodbold\b|\bh(?:å|aa)ndbold\b|\bstadion\b|\bstadium\b|\barena\b|\bfloorball\b|\bidr(?:æ|ae)t", "", "leisure"),
    (r"\bbiograf|\bkino\b|\bnordisk film\b|\blegoland\b|\btivoli\b|\bzoo\b|\bmuseum\b|\bsv(?:ø|oe)mmehal", "", "leisure"),
    (r"\bfitness|\bsats\b|\bfitness world\b|\bpuregym\b|\bloop fitness\b|\btr(?:æ|ae)ningscenter\b", "", "leisure"),
    (r"\bboghandel\b|\bbog\s?&\s?id[eé]\b|\bsaxo\b|\bfaraos\b|\bgenbrug", "", "leisure"),
    (r"\bcykel|\bcykler\b|\bbike\b", "", "leisure"),
    (r"\bbr leget(?:ø|oe)j\b|\bleg(?:e|)k(?:æ|ae)den\b|\blego\b|\btoys", "", "leisure"),
    # Travel & holidays.
    (r"hotel|\bmarriott\b|\bhilton\b|\bscandic\b|\bradisson\b|\bbest western\b|\bcomwell\b|\bzleep\b|\bcabinn\b|\bmotel\b|\bbooking\.com\b|\bairbnb\b|\bhostel\b|\bcamping\b|\bferiepark\b|\bferiehus\b|\bnovasol\b|\bdancenter\b", "", "travel"),
    (r"\bryanair\b|\bsas\b|\bnorwegian\b|\beasyjet\b|\blufthansa\b|\bairport\b|\blufthavn\b|\bduty free\b|\bmomondo\b|\baelia\b", "", "travel"),
    # Other shopping (general retail, parcels, kiosks).
    (r"\bamazon\b|\bamz\b", "Amazon", "shopping"),
    (r"\bebay\b", "eBay", "shopping"),
    (r"\bbiltema\b", "Biltema", "shopping"),
    (r"\b7-?eleven\b", "7-Eleven", "shopping"),
    (r"\bdba\b|\bgul\s?&\s?gratis\b", "", "shopping"),
    (r"\btobak\b|\bkiosk\b|\bnarvesen\b", "", "shopping"),
    (r"\bpostnord\b|\bgls\b|\bdao\b|\bups\b|\bdhl\b", "", "shopping"),
    # Cash abroad: round EUR amounts at a bank are ATM withdrawals.
    (r"\bdeutsche bank\b|\bsparkasse\b|^spk\b|\bvolksbank\b|\bcommerzbank\b|\bpostbank\b|\braiffeisen", "", "cash"),
    # Quick loans / consumer credit paid by Betalingsservice.
    (r"\bsantander\b|\bekspres bank\b|\bexpress bank\b|\bresurs bank\b|\bikano\b|\bnordea finans\b|\bbank norwegian\b|\bviabill\b|\banyday\b|\bferratum\b|\bvivus\b|\bbasisbank\b|\bkomplett bank\b|\bl(?:å|aa)n\s?&\s?spar\b|\bkvikl(?:å|aa)n\b", "", "loans"),
    # Card payments that are really MobilePay person-to-person.
    (r"^mobilepay$", "", "people"),
]
RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(p, re.I), name, cat) for p, name, cat in _RULES_SRC]


def rule_for(merchant: str, text: str) -> tuple[str, str] | None:
    """(canonical name or '', category) of the first rule that matches."""
    for pat, name, cat in RULES:
        if pat.search(merchant) or pat.search(text):
            return name, cat
    return None


# ---- what a row is ----------------------------------------------------------------

_FOREIGN = re.compile(r"\b([A-Z]{3})\s+(-?\d[\d.]*,\d{1,2})\s+Kurs\s+\d[\d.]*,\d+", re.I)
_PREFIXES = [
    r"kontaktl(?:ø|oe)s\s+dankort\s+", r"kontaktl(?:ø|oe)s\s+", r"dankort-k(?:ø|oe)b\s+",
    r"visa/dankort\s+", r"visa\s+", r"mastercard\s+", r"dankort\s+",
    r"mobilepay\s+k(?:ø|oe)b\s+mobilepay\s+", r"mobilepay:\s*mobilepay\s+", r"mobilepay:\s*",
    r"mobilepay\s+", r"betalingsservice\s+", r"kortk(?:ø|oe)b\s+", r"k(?:ø|oe)b\s+",
]
_PREFIX_RE = re.compile(r"^(?:" + "|".join(_PREFIXES) + r")", re.I)
_NOTA = re.compile(r",?\s*\bnota(?:\s*nr\.?|nr\.?)?\s*[\w-]+\s*", re.I)
_TAIL_NOISE = [
    re.compile(r"\s+aftalenr\.?\s*\d+.*$", re.I),
    re.compile(r"\s+trans\.?\s*nr\.?.*$", re.I),
    re.compile(r"\s+id\s+\d{5,}.*$", re.I),
    re.compile(r"\*[A-Z0-9]{6,}$"),
    re.compile(r"\s+-\s+\d+$"),
    re.compile(r"(?<=[A-Za-z])\d{8,}$"),
    re.compile(r"(?:\s+\d{3,})+$"),
    re.compile(r"[\s*,.-]+$"),
]
_COMPANY = re.compile(r"\s+(?:a/s|aps|i/s|ivs|k/s|gmbh|ag|ltd|inc|srl|ab|as|oy|bv)\.?$", re.I)

_OWN_TRANSFER = re.compile(
    r"^(?:opsparing|budgetkonto|til opsparing|fra opsparing|til budgetkonto|fra budgetkonto|"
    r"overf(?:ø|oe)rsel|overf(?:ø|oe)rt|overf\.|til\s+\d|fra\s+\d|til\s+konto|fra\s+konto|"
    r"lønkonto|l(?:ø|oe)nkonto|egen konto|til afbetalingskonto|overtr(?:æ|ae)k budgetkonto|"
    r"kontooverf|intern overf)", re.I)
_SALARY = re.compile(r"^(?:l(?:ø|oe)n|løn\b|overskydende skat|skat retur|overf\.\s*skattestyr|"
                     r"feriepenge|pension|udbetaling|b(?:ø|oe)rnepenge|b(?:ø|oe)rne-? og ungeydelse|"
                     r"su\b|dagpenge|kompensation)", re.I)
_INTEREST = re.compile(r"^(?:rente|renter)\b", re.I)
_FEE = re.compile(r"^(?:gebyr|kortgebyr|årsgebyr|depotleje|kontogebyr)", re.I)
_ATM = re.compile(r"^(?:pengeautomat|h(?:æ|ae)veautomat|atm\b|kontanten\b|kontant)", re.I)
_CARD_BILL = re.compile(r"^(?:forbrug p(?:å|aa) mastercard|forbrug p(?:å|aa) kreditkort|"
                        r"mastercard afregning|betaling af kreditkort|kreditkort)", re.I)
_LOAN = re.compile(r"\b(?:l(?:å|aa)n|afdrag|ydelse|santander|express bank|resurs|ikano|"
                   r"nordea finans|bank norwegian)\b", re.I)


def _nice_case(s: str) -> str:
    """'JEM & FIX VOJENS' -> 'Jem & Fix Vojens'; mixed case is left alone;
    web addresses go lower case."""
    letters = [c for c in s if c.isalpha()]
    if not letters or not all(c.isupper() for c in letters):
        return s
    out = []
    for w in s.split(" "):
        if "." in w and re.search(r"\.[a-z]{2,4}$", w, re.I):
            out.append(w.lower())
        elif len(w) <= 3 and w.isalpha() and w not in ("THE", "AND", "OG", "DEN", "DET"):
            out.append(w)               # DSB, CBB, Q8, AV - acronyms stay
        else:
            out.append(w[:1] + w[1:].lower())
    return " ".join(out)


def classify(text: str, amount_ore: int) -> dict:
    """kind, merchant and (foreign) amount for one bank text.

    The merchant is what the person would call the shop; for a transfer it
    is the bank text itself (case kept, so the monthly "OVERFØRSEL" salary
    and the occasional "Overførsel" from savings stay apart and can be
    categorised apart)."""
    raw = " ".join((text or "").split())
    out = {"kind": "other", "merchant": raw or "(no text)", "foreignAmount": None,
           "foreignCurrency": None, "rule": None}
    m = _FOREIGN.search(raw)
    t = raw
    if m:
        cur = m.group(1).upper()
        if cur != "DKK":
            out["foreignCurrency"] = cur
            out["foreignAmount"] = _num(m.group(2), comma_decimal=True)
        t = (raw[:m.start()] + " " + raw[m.end():]).strip()

    low = t.lower()
    if _CARD_BILL.search(low):
        out.update(kind="card-bill", merchant=re.sub(r"\s+\d{6,}$", "", t), rule=("", "card-bill"))
        return out
    if _ATM.search(low):
        out.update(kind="atm", merchant="Cash withdrawal", rule=("", "cash"))
        return out
    if _INTEREST.search(low):
        out.update(kind="interest", merchant=t, rule=("", "fees"))
        return out
    if _FEE.search(low):
        out.update(kind="fee", merchant=t, rule=("", "fees"))
        return out
    if _OWN_TRANSFER.search(low):
        out.update(kind="transfer", merchant=t, rule=("", "transfers"))
        return out
    if _SALARY.search(low) and amount_ore > 0:
        out.update(kind="salary", merchant=t, rule=("", "income"))
        return out

    if re.match(r"^mobilepay", low):
        out["kind"] = "mobilepay"
        person = not re.match(r"^mobilepay\s+k(?:ø|oe)b", low)
    elif re.match(r"^betalingsservice", low):
        out["kind"] = "betalingsservice"
        person = False
    elif re.search(r"dankort|visa|mastercard|\bnota\b|notanr|nota nr|kortk(?:ø|oe)b|paypal", low):
        out["kind"] = "card"
        person = False
    else:
        person = False

    name = _PREFIX_RE.sub("", t)
    name = _NOTA.sub(" ", name).strip()
    # "<shop>, <town or id>" - the shop is the first part.
    first = name.split(",")[0].strip() or name
    first = re.sub(r"^(?:paypal|zettle_?|sumup|iz|pay|sq|sp|uzr|bs)\s*\*\s*", "", first, flags=re.I)
    first = re.sub(r"\s*\*\s*[A-Za-z0-9]{6,}$", "", first)
    for pat in _TAIL_NOISE:
        first = pat.sub("", first).strip()
    first = _COMPANY.sub("", first).strip() or first
    merchant = _nice_case(" ".join(first.split())) or raw
    out["merchant"] = merchant[:80]

    rule = rule_for(merchant, raw)
    if rule:
        out["rule"] = rule
        if rule[0]:
            out["merchant"] = rule[0]
    elif out["kind"] == "mobilepay" and person:
        out["rule"] = ("", "people")
    elif out["kind"] == "other" and _LOAN.search(low):
        out["rule"] = ("", "loans")
    elif out["kind"] == "other" and amount_ore > 0:
        # Money in with no shop behind it - a person paying back, a refund
        # from somewhere unknown. The model is asked about the rest.
        out["rule"] = None
    return out


_SHOP_KINDS = {"card", "mobilepay", "betalingsservice", "atm"}


def merchant_key(name: str, kind: str = "card") -> str:
    """Shops group case-blind ("NETTO" = "Netto"). Bank texts keep their
    case: Søren's monthly salary arrives as "OVERFØRSEL" and money from his
    savings as "Overførsel" - one key would make them one category."""
    norm = " ".join(name.split())
    return norm.casefold() if kind in _SHOP_KINDS else norm


# ---- parsing ------------------------------------------------------------------------

_DATE_FORMATS = ["%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%y",
                 "%d.%m.%y", "%d/%m/%y", "%Y%m%d"]


def _date(v) -> str | None:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v or "").strip()
    if not s:
        return None
    s = s.split(" ")[0].split("T")[0]
    for f in _DATE_FORMATS:
        try:
            d = datetime.strptime(s, f).date()
        except ValueError:
            continue
        if 1990 <= d.year <= 2100:
            return d.isoformat()
    return None


_NUM_CHARS = re.compile(r"^[+-]?[\d.,\s ]+$")


def _num(v, comma_decimal: bool | None = None) -> float | None:
    """A number in Danish ("-1.542,88") or English ("-1,542.88") style.
    `comma_decimal` is the file's style when it is known; without it a lone
    separator followed by 1-2 digits is the decimal one."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v or "").strip().replace("−", "-").replace(" ", "").replace("\xa0", "")
    s = re.sub(r"(?i)(dkk|kr\.?|eur|€|\$)$", "", s).strip()
    neg = False
    if s.endswith("-"):
        neg, s = True, s[:-1]
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if not s or not _NUM_CHARS.match(s):
        return None
    s = s.replace(" ", "")
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
    elif "," in s:
        dec = "," if comma_decimal is not False else "."
        if comma_decimal is None and not re.search(r",\d{1,2}$", s):
            dec = "."            # "1,542" in an English file
    elif "." in s:
        dec = "." if comma_decimal is not True else ","
        if comma_decimal is None and re.search(r"\.\d{3}$", s) and s.count(".") >= 1 \
                and not re.search(r"\.\d{1,2}$", s):
            dec = ","            # "1.542" - Danish thousands
    else:
        dec = "."
    thousands = "." if dec == "," else ","
    s = s.replace(thousands, "").replace(dec, ".")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and not data[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", errors="replace")


def _table_from_csv(data: bytes) -> list[list]:
    text = _decode(data)
    sample = text[:20_000]
    counts = {d: sample.count(d) for d in (";", "\t", ",")}
    # A Danish export with decimal commas has more commas than semicolons -
    # but every line has the same number of semicolons. Prefer ; and tab.
    lines = [ln for ln in sample.splitlines() if ln.strip()][:50]
    delim = ","
    for d in (";", "\t"):
        per = [ln.count(d) for ln in lines]
        if per and min(per) >= 1 and len(set(per)) <= 2:
            delim = d
            break
    else:
        if counts[","] == 0:
            delim = ";"
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim)]


def _table_from_xlsx(data: bytes) -> list[list]:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        best: list[list] = []
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            rows = [r for r in rows if any(c not in (None, "") for c in r)]
            if len(rows) > len(best):
                best = rows
        return best
    finally:
        wb.close()


_HEAD_DATE = re.compile(r"^(dato|date|bogf(?:ø|oe)ringsdato|bogført|posteringsdato|"
                        r"rentedato|valuteringsdato|transaktionsdato|buchungstag|booking date)$", re.I)
_HEAD_TEXT = re.compile(r"^(tekst|text|beskrivelse|description|posteringstekst|"
                        r"navn|name|modtager|merchant|verwendungszweck|details)$", re.I)
_HEAD_AMOUNT = re.compile(r"^(bel(?:ø|oe)b|amount|beløb i dkk|bel(?:ø|oe)b \(dkk\)|betrag|sum)$", re.I)
_HEAD_CUR = re.compile(r"^(valuta|currency|währung)$", re.I)


def parse_table(rows: list[list]) -> dict:
    """{'rows': [{date, text, amount, currency}], 'skipped': n, 'columns': {...}}.

    Finds the date, text, amount and currency columns by header names when
    there is a header, otherwise by what the values look like."""
    rows = [list(r) for r in rows if r and any(str(c or "").strip() for c in r)]
    if not rows:
        raise Invalid("The file is empty.")
    width = max(len(r) for r in rows)
    rows = [r + [None] * (width - len(r)) for r in rows]
    header = None
    first = [str(c or "").strip().strip('"') for c in rows[0]]
    if not any(_date(c) for c in rows[0]):
        header = first
        body = rows[1:]
    else:
        body = rows
    col: dict[str, int | None] = {"date": None, "text": None, "amount": None, "currency": None}
    if header:
        for i, h in enumerate(header):
            for key, pat in (("date", _HEAD_DATE), ("text", _HEAD_TEXT),
                             ("amount", _HEAD_AMOUNT), ("currency", _HEAD_CUR)):
                if col[key] is None and pat.match(h):
                    col[key] = i
    sample = body[:300]

    def share(i: int, test) -> float:
        vals = [r[i] for r in sample if str(r[i] or "").strip()]
        return sum(1 for v in vals if test(v)) / max(1, len(sample))

    if col["date"] is None:
        col["date"] = next((i for i in range(width) if share(i, _date) > 0.8), None)
    if col["date"] is None:
        raise Invalid("No date column found - is this a bank export? "
                      "Expected rows like 08-10-2026;Text;-1.542,88;DKK.")
    if col["currency"] is None:
        col["currency"] = next((i for i in range(width) if i != col["date"] and share(
            i, lambda v: bool(re.fullmatch(r"[A-Z]{3}", str(v).strip()))) > 0.8), None)
    numeric = [i for i in range(width) if i not in (col["date"], col["currency"])
               and share(i, lambda v: _num(v) is not None) > 0.8]
    if col["amount"] is None:
        if not numeric:
            raise Invalid("No amount column found.")
        # The amount, not the balance: amounts change sign, a balance rarely
        # does; with a header the name decided already.
        def sign_changes(i: int) -> int:
            vals = [_num(r[i]) for r in sample]
            return sum(1 for v in vals if v is not None and v < 0)
        col["amount"] = max(numeric, key=lambda i: (sign_changes(i) > 0, -i))
    if col["text"] is None:
        cands = [i for i in range(width) if i not in (col["date"], col["amount"], col["currency"])
                 and i not in numeric]
        if not cands:
            raise Invalid("No text column found.")
        col["text"] = max(cands, key=lambda i: sum(len(str(r[i] or "")) for r in sample))

    raw_amounts = [str(r[col["amount"]] or "") for r in body
                   if not isinstance(r[col["amount"]], (int, float))]
    comma = None
    if raw_amounts:
        c_dec = sum(1 for s in raw_amounts if re.search(r",\d{2}$", s.strip()))
        p_dec = sum(1 for s in raw_amounts if re.search(r"\.\d{2}$", s.strip()))
        comma = c_dec >= p_dec if (c_dec or p_dec) else None

    out, skipped = [], 0
    for r in body[:MAX_ROWS]:
        d = _date(r[col["date"]])
        a = _num(r[col["amount"]], comma)
        t = " ".join(str(r[col["text"]] or "").split())
        if d is None or a is None:
            skipped += 1
            continue
        cur = str(r[col["currency"]] or "DKK").strip().upper() if col["currency"] is not None else "DKK"
        out.append({"date": d, "text": t, "amount": int(round(a * 100)), "currency": cur[:3] or "DKK"})
    if not out:
        raise Invalid("No transactions could be read from the file.")
    return {"rows": out, "skipped": skipped,
            "columns": {k: (header[v] if header and v is not None else v) for k, v in col.items()}}


def parse_file(filename: str, data: bytes) -> dict:
    if len(data) > MAX_FILE_BYTES:
        raise Invalid("The file is larger than 20 MB.")
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        try:
            table = _table_from_xlsx(data)
        except Exception as exc:
            raise Invalid(f"Could not open the workbook: {type(exc).__name__}") from exc
    elif name.endswith((".csv", ".txt", ".tsv")) or not name:
        table = _table_from_csv(data)
    else:
        raise Invalid("Upload the bank's CSV or XLSX export.")
    return parse_table(table)


# ---- storing --------------------------------------------------------------------------

def _now() -> str:
    return db.utcnow()


def import_rows(user_id: int, account: str, filename: str, rows: list[dict]) -> dict:
    """Merge parsed rows into the ledger. Returns what happened, including
    the merchants no rule knows (the caller may ask the model about them)."""
    account = " ".join((account or "").split())[:60] or "Bank"
    occ: Counter = Counter()
    prepared = []
    for r in sorted(rows, key=lambda x: x["date"]):
        k = (r["date"], r["text"], r["amount"])
        occ[k] += 1
        c = classify(r["text"], r["amount"])
        prepared.append((r, occ[k], c))
    added = known = 0
    first = min((r["date"] for r in rows), default=None)
    last = max((r["date"] for r in rows), default=None)
    with db.connect() as con:
        cur = con.execute(
            "INSERT INTO ledger_imports (user_id, account, filename, imported_at, rows_in_file,"
            " rows_added, first_date, last_date) VALUES (?,?,?,?,?,0,?,?)",
            (user_id, account, (filename or "")[:200], _now(), len(rows), first, last))
        imp = cur.lastrowid
        merchants: dict[str, tuple[str, tuple | None, str]] = {}
        for r, n, c in prepared:
            res = con.execute(
                "INSERT OR IGNORE INTO ledger_tx (user_id, account, date, text, amount, currency,"
                " occurrence, kind, merchant, merchant_key, foreign_amount, foreign_currency, import_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, account, r["date"], r["text"], r["amount"], r["currency"], n,
                 c["kind"], c["merchant"], merchant_key(c["merchant"], c["kind"]),
                 c["foreignAmount"], c["foreignCurrency"], imp))
            if res.rowcount:
                added += 1
                key = merchant_key(c["merchant"], c["kind"])
                if key not in merchants or (merchants[key][1] is None and c["rule"]):
                    merchants[key] = (c["merchant"], c["rule"], r["text"])
            else:
                known += 1
        new_uncat = 0
        for key, (name, rule, sample) in merchants.items():
            row = con.execute("SELECT category FROM ledger_merchants WHERE user_id=? AND merchant_key=?",
                              (user_id, key)).fetchone()
            if row is not None:
                continue
            cat = rule[1] if rule else UNCATEGORISED
            con.execute("INSERT INTO ledger_merchants (user_id, merchant_key, name, category, source,"
                        " sample, updated_at) VALUES (?,?,?,?,?,?,?)",
                        (user_id, key, name, cat, "rule" if rule else "none", sample[:200], _now()))
            if not rule:
                new_uncat += 1
        con.execute("UPDATE ledger_imports SET rows_added=?, rows_known=? WHERE id=?",
                    (added, known, imp))
    return {"importId": imp, "account": account, "rowsInFile": len(rows), "added": added,
            "alreadyThere": known, "firstDate": first, "lastDate": last,
            "newUncategorised": new_uncat, "uncategorised": count_uncategorised(user_id)}


def count_uncategorised(user_id: int) -> int:
    with db.connect() as con:
        return con.execute("SELECT COUNT(*) FROM ledger_merchants WHERE user_id=? AND category=''",
                           (user_id,)).fetchone()[0]


def uncategorised(user_id: int, limit: int = 1000) -> list[dict]:
    """Merchants still to be placed, the most used first, with a sample text
    and how much went through them (the model gets both)."""
    with db.connect() as con:
        rows = con.execute(
            "SELECT m.merchant_key, m.name, m.sample, COUNT(t.id) n, SUM(t.amount) total"
            " FROM ledger_merchants m LEFT JOIN ledger_tx t"
            "   ON t.user_id = m.user_id AND t.merchant_key = m.merchant_key"
            " WHERE m.user_id=? AND m.category='' GROUP BY m.merchant_key"
            " ORDER BY n DESC, m.name LIMIT ?", (user_id, limit)).fetchall()
    return [{"key": r["merchant_key"], "name": r["name"], "sample": r["sample"],
             "count": r["n"], "total": (r["total"] or 0) / 100} for r in rows]


def set_category(user_id: int, key: str, category: str, source: str = "user") -> bool:
    """Place a merchant. The person's choice ('user') is never overwritten
    by the model; the model only fills what is still empty."""
    if category not in CATEGORIES:
        raise Invalid(f"Unknown category: {category}")
    with db.connect() as con:
        if source == "user":
            res = con.execute("UPDATE ledger_merchants SET category=?, source='user', updated_at=?"
                              " WHERE user_id=? AND merchant_key=?", (category, _now(), user_id, key))
        else:
            res = con.execute("UPDATE ledger_merchants SET category=?, source=?, updated_at=?"
                              " WHERE user_id=? AND merchant_key=? AND category=''",
                              (category, source, _now(), user_id, key))
        return res.rowcount > 0


def rename_merchant(user_id: int, key: str, name: str) -> bool:
    name = " ".join((name or "").split())[:80]
    if not name:
        raise Invalid("A merchant needs a name.")
    with db.connect() as con:
        res = con.execute("UPDATE ledger_merchants SET name=?, updated_at=? WHERE user_id=?"
                          " AND merchant_key=?", (name, _now(), user_id, key))
        con.execute("UPDATE ledger_tx SET merchant=? WHERE user_id=? AND merchant_key=?",
                    (name, user_id, key))
        return res.rowcount > 0


def reapply_rules(con) -> int:
    """Re-run the merchant rules over every merchant the person has NOT placed
    by hand, and move any still in a retired category to its successor. Used
    by migration 050 when the category set changes so existing data follows
    the finer categories (McDonald's -> fast-food, Netflix -> streaming, a
    dentist -> dental). A merchant with source 'user' is never touched.
    Returns how many rows changed."""
    rows = con.execute("SELECT user_id, merchant_key, name, category, source, sample"
                       " FROM ledger_merchants").fetchall()
    changed = 0
    for r in rows:
        if r["source"] == "user":
            continue
        rule = rule_for(r["name"] or "", r["sample"] or "")
        if rule is not None:
            new_cat, new_src = rule[1], "rule"
        elif r["category"] in RETIRED_CATEGORIES:
            new_cat, new_src = RETIRED_CATEGORIES[r["category"]], "migrated"
        else:
            continue
        if new_cat != r["category"] or new_src != r["source"]:
            con.execute("UPDATE ledger_merchants SET category=?, source=?, updated_at=?"
                        " WHERE user_id=? AND merchant_key=?",
                        (new_cat, new_src, _now(), r["user_id"], r["merchant_key"]))
            changed += 1
    return changed


# ---- reading --------------------------------------------------------------------------

_JOIN = (" FROM ledger_tx t LEFT JOIN ledger_merchants m"
         " ON m.user_id = t.user_id AND m.merchant_key = t.merchant_key")


def _cat_sql() -> str:
    """A row's category: its merchant's - except a small purchase at a fuel
    station, which is the station's shop (0.3.4)."""
    return (f"(CASE WHEN m.category = 'fuel' AND t.amount < 0 AND t.amount > -{FUEL_MIN_ORE}"
            " THEN 'gas-station' ELSE COALESCE(m.category, '') END)")


def summary(user_id: int) -> dict:
    with db.connect() as con:
        r = con.execute("SELECT COUNT(*) n, MIN(date) a, MAX(date) b FROM ledger_tx WHERE user_id=?",
                        (user_id,)).fetchone()
        accounts = [dict(x) for x in con.execute(
            "SELECT account, COUNT(*) n, MIN(date) first, MAX(date) last FROM ledger_tx"
            " WHERE user_id=? GROUP BY account ORDER BY account", (user_id,))]
        imports = [dict(x) for x in con.execute(
            "SELECT id, account, filename, imported_at importedAt, rows_in_file rowsInFile,"
            " rows_added added, rows_known alreadyThere, first_date firstDate, last_date lastDate"
            " FROM ledger_imports WHERE user_id=? ORDER BY id DESC LIMIT 30", (user_id,))]
        merchants = con.execute("SELECT COUNT(*) FROM ledger_merchants WHERE user_id=?",
                                (user_id,)).fetchone()[0]
    return {"count": r["n"], "firstDate": r["a"], "lastDate": r["b"], "accounts": accounts,
            "imports": imports, "merchants": merchants,
            "uncategorised": count_uncategorised(user_id),
            "categories": [{"key": k, "label": CATEGORIES[k][0], "da": CATEGORIES[k][1],
                            "counted": k not in NOT_COUNTED, "group": g}
                           for g, keys in CATEGORY_GROUPS for k in keys]}


def _period_where(frm: str | None, to: str | None, account: str | None,
                  params: list) -> str:
    sql = ""
    if frm:
        sql += " AND t.date >= ?"
        params.append(frm)
    if to:
        sql += " AND t.date <= ?"
        params.append(to)
    if account:
        sql += " AND t.account = ?"
        params.append(account)
    return sql


def _refund_sql(cat: str) -> str:
    """Money in that undoes a purchase: a card or Betalingsservice row with a
    plus (an IKEA return, a reversed direct debit), or a MobilePay refund
    from a shop. Money in from people, winnings, "Advis" and the like is
    not a refund - netting it against spending made "Other" -174.199 kr
    and -144% (2.63.1)."""
    return (f"(t.amount > 0 AND (t.kind IN ('card','betalingsservice')"
            f" OR (t.kind = 'mobilepay' AND {cat} <> 'people')))")


def _spend_sql(cat: str) -> str:
    """Øre this row adds to spending: money out, minus refunds; nothing for
    own transfers, income, or other money in. Category keys are the code's
    constants, so they are written into the SQL."""
    skip = ",".join(f"'{k}'" for k in sorted(NOT_COUNTED | {"income"}))
    return (f"(CASE WHEN {cat} IN ({skip}) THEN 0 WHEN t.amount < 0 THEN -t.amount"
            f" WHEN {_refund_sql(cat)} THEN -t.amount ELSE 0 END)")


def _month_add(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    k = y * 12 + (m - 1) + n
    return f"{k // 12:04d}-{k % 12 + 1:02d}"


def overview(user_id: int, frm: str | None = None, to: str | None = None,
             account: str | None = None, top: int = 50, baseline: int = 0) -> dict:
    """The Overview page: totals, money out per month (and per day for a
    period of up to two months), per category, top merchants, recurring
    payments, own transfers. `baseline` > 0: each category's average month
    over that many whole months before `frm`, to compare a month against."""
    params: list = [user_id]
    where = " WHERE t.user_id=?" + _period_where(frm, to, account, params)
    cat = _cat_sql()
    spend = _spend_sql(cat)
    refund = _refund_sql(cat)
    with db.connect() as con:
        tot = con.execute(
            f"SELECT COUNT(*) n, MIN(t.date) a, MAX(t.date) b, SUM({spend}) spent,"
            f" SUM(CASE WHEN {cat}='income' THEN t.amount ELSE 0 END) income,"
            f" SUM(CASE WHEN {cat} NOT IN ('transfers','income') AND t.amount>0 AND NOT {refund}"
            f"     THEN t.amount ELSE 0 END) other_in,"
            f" SUM(CASE WHEN {cat}='transfers' AND t.amount<0 THEN -t.amount ELSE 0 END) tr_out,"
            f" SUM(CASE WHEN {cat}='transfers' AND t.amount>0 THEN t.amount ELSE 0 END) tr_in"
            + _JOIN + where, params).fetchone()
        months = con.execute(
            f"SELECT substr(t.date,1,7) month, {cat} category, SUM({spend}) spent"
            + _JOIN + where + f" AND {spend} <> 0 GROUP BY 1, 2 ORDER BY month",
            params).fetchall()
        income_m = con.execute(
            f"SELECT substr(t.date,1,7) month, SUM(t.amount) income" + _JOIN + where
            + f" AND {cat}='income' GROUP BY month", params).fetchall()
        cats = con.execute(
            f"SELECT {cat} category, SUM({spend}) spent, COUNT(*) n" + _JOIN + where
            + f" AND {spend} <> 0 GROUP BY 1 ORDER BY spent DESC", params).fetchall()
        top_rows = con.execute(
            f"SELECT t.merchant_key k, COALESCE(m.name, t.merchant) name, COALESCE(m.category, '') category,"
            f" SUM({spend}) spent, SUM(CASE WHEN t.amount<0 THEN 1 ELSE 0 END) n, MAX(t.date) last"
            + _JOIN + where + f" AND {spend} <> 0 GROUP BY t.merchant_key"
            " HAVING spent > 0 ORDER BY spent DESC LIMIT ?",
            params + [max(1, min(int(top or 50), 1000))]).fetchall()
        days: list[dict] | None = None
        try:
            d0, d1 = date.fromisoformat(frm or ""), date.fromisoformat(to or "")
        except ValueError:
            d0 = d1 = None
        if d0 and d1:
            if 0 <= (d1 - d0).days <= 62:
                per = {r["date"]: r["spent"] for r in con.execute(
                    f"SELECT t.date, SUM({spend}) spent" + _JOIN + where + " GROUP BY t.date",
                    params)}
                days = [{"date": (d0 + timedelta(days=i)).isoformat(),
                         "spent": (per.get((d0 + timedelta(days=i)).isoformat()) or 0) / 100}
                        for i in range((d1 - d0).days + 1)]
        base = None
        if baseline and frm:
            first = con.execute("SELECT MIN(date) FROM ledger_tx WHERE user_id=?",
                                (user_id,)).fetchone()[0]
            b_to = _month_add(frm[:7], -1)
            b_from = _month_add(frm[:7], -int(baseline))
            if first and first[:7] > b_from:
                b_from = first[:7]
            if first and b_from <= b_to:
                n_b = (int(b_to[:4]) * 12 + int(b_to[5:7])) - (int(b_from[:4]) * 12 + int(b_from[5:7])) + 1
                bp: list = [user_id, f"{b_from}-01", f"{b_to}-31"]
                bw = " WHERE t.user_id=? AND t.date >= ? AND t.date <= ?"
                if account:
                    bw += " AND t.account = ?"
                    bp.append(account)
                brows = con.execute(f"SELECT {cat} category, SUM({spend}) spent" + _JOIN + bw
                                    + " GROUP BY 1", bp).fetchall()
                total_b = sum((r["spent"] or 0) for r in brows)
                base = {"from": b_from, "to": b_to, "months": n_b,
                        "perMonth": round(total_b / 100 / n_b, 2),
                        "categories": {r["category"]: round((r["spent"] or 0) / 100 / n_b, 2)
                                       for r in brows if r["spent"]}}
    month_map: dict[str, dict] = {}
    for r in months:
        m = month_map.setdefault(r["month"], {"spent": 0, "income": 0, "byCategory": {}})
        m["spent"] += r["spent"] or 0
        m["byCategory"][r["category"]] = (r["spent"] or 0) / 100
    for r in income_m:
        m = month_map.setdefault(r["month"], {"spent": 0, "income": 0, "byCategory": {}})
        m["income"] += r["income"] or 0
    month_list = [{"month": k, "spent": month_map[k]["spent"] / 100,
                   "income": month_map[k]["income"] / 100,
                   "byCategory": month_map[k]["byCategory"]} for k in sorted(month_map)]
    n_months = len(month_list) or 1
    return {
        "from": frm, "to": to, "account": account,
        "count": tot["n"], "firstDate": tot["a"], "lastDate": tot["b"],
        "spent": (tot["spent"] or 0) / 100,
        "income": (tot["income"] or 0) / 100,
        "otherIn": (tot["other_in"] or 0) / 100,
        "perMonth": round((tot["spent"] or 0) / 100 / n_months, 2),
        "transfersOut": (tot["tr_out"] or 0) / 100,
        "transfersIn": (tot["tr_in"] or 0) / 100,
        "months": month_list,
        "days": days,
        "baseline": base,
        "categories": [{"key": r["category"], "label": category_label(r["category"]),
                        "spent": (r["spent"] or 0) / 100, "count": r["n"]} for r in cats],
        "topMerchants": [{"key": r["k"], "name": r["name"], "category": r["category"],
                          "spent": (r["spent"] or 0) / 100, "count": r["n"], "last": r["last"]}
                         for r in top_rows],
        "recurring": recurring(user_id, account=account),
        "uncategorised": count_uncategorised(user_id),
    }


def recurring(user_id: int, account: str | None = None, months_back: int = 6) -> list[dict]:
    """Payments that come back month after month: a merchant paid in at
    least 4 of the last 6 months of data, by direct debit or in a
    bill-like category - groceries and fuel come back too, but are not
    what "recurring" means."""
    with db.connect() as con:
        last = con.execute("SELECT MAX(date) FROM ledger_tx WHERE user_id=?",
                           (user_id,)).fetchone()[0]
        if not last:
            return []
        d = date.fromisoformat(last)
        start = (d.replace(day=1) - timedelta(days=31 * (months_back - 1))).replace(day=1).isoformat()
        params: list = [user_id, start]
        acc = ""
        if account:
            acc = " AND t.account=?"
            params.append(account)
        rows = con.execute(
            "SELECT t.merchant_key k, COALESCE(m.name, t.merchant) name, COALESCE(m.category,'') cat,"
            " t.kind, t.date, -t.amount amount" + _JOIN +
            " WHERE t.user_id=? AND t.date>=? AND t.amount<0" + acc, params).fetchall()
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r["k"]].append(r)
    billish = {"subscriptions", "streaming", "tv", "ai", "phone", "insurance", "union",
               "utilities", "rent", "mortgage", "loans", "card-bill"}
    out = []
    for k, rs in by.items():
        months = {r["date"][:7] for r in rs}
        if len(months) < 4:
            continue
        cat = rs[0]["cat"]
        if not (any(r["kind"] == "betalingsservice" for r in rs) or cat in billish):
            continue
        per_month: dict[str, int] = defaultdict(int)
        for r in rs:
            per_month[r["date"][:7]] += r["amount"]
        typical = statistics.median(per_month.values())
        out.append({"key": k, "name": rs[0]["name"], "category": cat,
                    "months": len(months), "typical": round(typical / 100, 2),
                    "last": max(r["date"] for r in rs),
                    "yearly": round(typical / 100 * 12, 2)})
    out.sort(key=lambda x: -x["typical"])
    return out


def transactions(user_id: int, q: str = "", category: str | None = None,
                 merchant: str | None = None, frm: str | None = None, to: str | None = None,
                 account: str | None = None, direction: str = "", offset: int = 0,
                 limit: int = 100, order: str = "newest") -> dict:
    params: list = [user_id]
    where = " WHERE t.user_id=?" + _period_where(frm, to, account, params)
    if q.strip():
        for word in q.split()[:6]:
            where += " AND (t.text LIKE ? OR t.merchant LIKE ? OR m.name LIKE ?)"
            params += [f"%{word}%"] * 3
    if category is not None and category != "*":
        where += f" AND {_cat_sql()} = ?"
        params.append(category)
    if merchant:
        where += " AND t.merchant_key = ?"
        params.append(merchant)
    if direction == "out":
        where += " AND t.amount < 0"
    elif direction == "in":
        where += " AND t.amount > 0"
    orders = {"newest": "t.date DESC, t.id DESC", "oldest": "t.date, t.id",
              "largest": "t.amount ASC", "smallest": "ABS(t.amount) ASC",
              "income": "t.amount DESC"}
    with db.connect() as con:
        tot = con.execute("SELECT COUNT(*) n, SUM(t.amount) s" + _JOIN + where, params).fetchone()
        rows = con.execute(
            "SELECT t.id, t.account, t.date, t.text, t.amount, t.currency, t.kind,"
            f" t.merchant_key, COALESCE(m.name, t.merchant) merchant, {_cat_sql()} category,"
            " t.foreign_amount, t.foreign_currency" + _JOIN + where
            + f" ORDER BY {orders.get(order, orders['newest'])} LIMIT ? OFFSET ?",
            params + [max(1, min(limit, 500)), max(0, offset)]).fetchall()
    return {"total": tot["n"], "sum": (tot["s"] or 0) / 100,
            "rows": [_tx(r) for r in rows]}


def _tx(r) -> dict:
    return {"id": r["id"], "account": r["account"], "date": r["date"], "text": r["text"],
            "amount": r["amount"] / 100, "currency": r["currency"], "kind": r["kind"],
            "merchantKey": r["merchant_key"], "merchant": r["merchant"],
            "category": r["category"], "foreignAmount": r["foreign_amount"],
            "foreignCurrency": r["foreign_currency"]}


def merchants(user_id: int, q: str = "", category: str | None = None,
              limit: int = 300) -> list[dict]:
    params: list = [user_id]
    where = " WHERE m.user_id=?"
    if q.strip():
        where += " AND (m.name LIKE ? OR m.sample LIKE ?)"
        params += [f"%{q.strip()}%"] * 2
    if category is not None and category != "*":
        where += " AND m.category = ?"
        params.append(category)
    with db.connect() as con:
        rows = con.execute(
            "SELECT m.merchant_key k, m.name, m.category, m.source, m.sample,"
            " COUNT(t.id) n, SUM(t.amount) total, MAX(t.date) last"
            " FROM ledger_merchants m LEFT JOIN ledger_tx t"
            "   ON t.user_id=m.user_id AND t.merchant_key=m.merchant_key"
            + where + " GROUP BY m.merchant_key ORDER BY ABS(SUM(t.amount)) DESC LIMIT ?",
            params + [max(1, min(limit, 2000))]).fetchall()
    return [{"key": r["k"], "name": r["name"], "category": r["category"], "source": r["source"],
             "sample": r["sample"], "count": r["n"], "total": (r["total"] or 0) / 100,
             "last": r["last"]} for r in rows]


def delete_import(user_id: int, import_id: int) -> int:
    """Take one import's rows out again (merchants stay - their category is
    the person's work)."""
    with db.connect() as con:
        n = con.execute("DELETE FROM ledger_tx WHERE user_id=? AND import_id=?",
                        (user_id, import_id)).rowcount
        con.execute("DELETE FROM ledger_imports WHERE user_id=? AND id=?", (user_id, import_id))
    return n


def clear(user_id: int) -> None:
    with db.connect() as con:
        con.execute("DELETE FROM ledger_tx WHERE user_id=?", (user_id,))
        con.execute("DELETE FROM ledger_imports WHERE user_id=?", (user_id,))
        con.execute("DELETE FROM ledger_merchants WHERE user_id=?", (user_id,))


# ---- settings --------------------------------------------------------------------------

def get_settings(user_id: int) -> dict:
    """The person's model for Økonomi. `override` is what they chose here
    (empty = none); `model` (questions) and `categoriseModel` fall back to
    the roles in Settings when there is no override. (FamilyLog 0.1.0)"""
    from app.core import settings
    with db.connect() as con:
        r = con.execute("SELECT model FROM ledger_settings WHERE user_id=?", (user_id,)).fetchone()
    override = ((r["model"] if r else None) or "").strip()
    return {"model": override or settings.role_model("chat"),
            "categoriseModel": override or settings.role_model("categorise"),
            "override": override, "chatRole": settings.role_model("chat")}


def set_settings(user_id: int, model: str) -> dict:
    with db.connect() as con:
        con.execute("INSERT INTO ledger_settings (user_id, model, updated_at) VALUES (?,?,?)"
                    " ON CONFLICT(user_id) DO UPDATE SET model=excluded.model,"
                    " updated_at=excluded.updated_at", (user_id, (model or "")[:120], _now()))
    return get_settings(user_id)


# ---- the ask's query -----------------------------------------------------------------------
# The model turns a question into a QuerySpec (JSON); this runs it. The model
# never writes SQL: every field is checked, every value bound.

GROUPS = {"none", "month", "year", "merchant", "category", "weekday", "account", "kind"}
MEASURES = {"sum", "count", "average", "list", "max"}
ORDERS = {"largest", "smallest", "newest", "oldest"}
DIRECTIONS = {"out", "in", "both"}
KINDS = {"card", "mobilepay", "betalingsservice", "atm", "transfer", "interest", "fee",
         "salary", "card-bill", "other"}


def clean_spec(d: dict, today: date | None = None) -> dict:
    """The model's reading of a question, made safe to query with."""
    def words(v, n=6) -> list[str]:
        if isinstance(v, str):
            v = [v]
        out = []
        for w in v or []:
            w = " ".join(str(w).split())[:60]
            if len(w) >= 2 and w.casefold() not in [o.casefold() for o in out]:
                out.append(w)
        return out[:n]

    spec = {
        "merchants": words(d.get("merchants") or d.get("merchant")),
        "words": words(d.get("words") or d.get("text")),
        "categories": [c for c in words(d.get("categories") or d.get("category"), 8)
                       if c in CATEGORIES],
        "kinds": [k for k in words(d.get("kinds") or d.get("kind"), 6) if k in KINDS],
        "from": _date(d.get("from")) if d.get("from") else None,
        "to": _date(d.get("to")) if d.get("to") else None,
        "direction": d.get("direction") if d.get("direction") in DIRECTIONS else "out",
        "group": d.get("group") if d.get("group") in GROUPS else "none",
        "measure": d.get("measure") if d.get("measure") in MEASURES else "sum",
        "order": d.get("order") if d.get("order") in ORDERS else "largest",
        "top": None,
        "includeTransfers": bool(d.get("includeTransfers")),
        "account": " ".join(str(d.get("account") or "").split())[:60] or None,
    }
    try:
        top = int(d.get("top")) if d.get("top") not in (None, "", 0) else None
    except (TypeError, ValueError):
        top = None
    spec["top"] = max(1, min(top, 100)) if top else None
    if spec["from"] and spec["to"] and spec["from"] > spec["to"]:
        spec["from"], spec["to"] = spec["to"], spec["from"]
    # Asking about a category or kind that is a transfer means transfers.
    if "transfers" in spec["categories"] or "transfer" in spec["kinds"]:
        spec["includeTransfers"] = True
    if "income" in spec["categories"] or "salary" in spec["kinds"]:
        spec["direction"] = "in" if spec["direction"] == "out" else spec["direction"]
    return spec


def run_spec(user_id: int, spec: dict) -> dict:
    """Totals, groups and the matching rows for a cleaned spec. Everything
    the answer may say is in here."""
    params: list = [user_id]
    where = " WHERE t.user_id=?" + _period_where(spec["from"], spec["to"], spec["account"], params)
    cat = _cat_sql()
    notes: list[str] = []
    matched_merchants: list[dict] = []
    if spec["merchants"]:
        parts = []
        for w in spec["merchants"]:
            parts.append("(t.merchant LIKE ? OR m.name LIKE ? OR t.text LIKE ?)")
            params += [f"%{w}%"] * 3
        where += " AND (" + " OR ".join(parts) + ")"
    for w in spec["words"]:
        where += " AND (t.text LIKE ? OR t.merchant LIKE ? OR m.name LIKE ?)"
        params += [f"%{w}%"] * 3
    if spec["categories"]:
        where += f" AND {cat} IN ({','.join('?' * len(spec['categories']))})"
        params += spec["categories"]
    if spec["kinds"]:
        where += f" AND t.kind IN ({','.join('?' * len(spec['kinds']))})"
        params += spec["kinds"]
    if spec["direction"] == "out":
        # Money out, net of refunds (a return at IKEA lowers what was spent
        # at IKEA); money in from people or winnings is not a refund.
        where += f" AND (t.amount < 0 OR {_refund_sql(cat)})"
    elif spec["direction"] == "in":
        where += " AND t.amount > 0"
    excluded_transfers = None
    # Money out is shown as a positive number of kroner spent.
    sign = -1 if spec["direction"] == "out" else 1
    if not spec["includeTransfers"]:
        with db.connect() as con:
            r = con.execute("SELECT COUNT(*) n, SUM(t.amount) s" + _JOIN + where
                            + f" AND {cat} = 'transfers'", params).fetchone()
        if r["n"]:
            excluded_transfers = {"count": r["n"], "sum": (r["s"] or 0) / 100 * sign}
        where += f" AND {cat} <> 'transfers'"
    with db.connect() as con:
        tot = con.execute(
            "SELECT COUNT(*) n, SUM(t.amount) s, MIN(t.date) a, MAX(t.date) b,"
            f" MAX({ {'out': '-t.amount', 'in': 't.amount'}.get(spec['direction'], 'ABS(t.amount)') }) mx"
            + _JOIN + where, params).fetchone()
        groups: list[dict] = []
        if spec["group"] != "none":
            gexpr = {"month": "substr(t.date,1,7)", "year": "substr(t.date,1,4)",
                     "merchant": "COALESCE(m.name, t.merchant)", "category": cat,
                     "weekday": "strftime('%w', t.date)", "account": "t.account",
                     "kind": "t.kind"}[spec["group"]]
            order = "g" if spec["group"] in ("month", "year", "weekday") else "total DESC"
            if spec["measure"] == "count" and spec["group"] not in ("month", "year", "weekday"):
                order = "n DESC"
            grows = con.execute(
                f"SELECT {gexpr} g, COUNT(*) n, SUM(t.amount) * {sign} total" + _JOIN + where
                + f" GROUP BY g ORDER BY {order} LIMIT ?",
                params + [spec["top"] or (60 if spec["group"] in ("month", "weekday") else 25)]
            ).fetchall()
            wd = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            for r in grows:
                g = r["g"]
                label = (category_label(g) if spec["group"] == "category"
                         else wd[int(g)] if spec["group"] == "weekday" and g is not None else g)
                groups.append({"group": label, "count": r["n"], "total": (r["total"] or 0) / 100,
                               "average": round((r["total"] or 0) / 100 / max(1, r["n"]), 2)})
        signed = {"out": "t.amount", "in": "-t.amount"}.get(spec["direction"], "-ABS(t.amount)")
        orders = {"largest": f"{signed} ASC", "smallest": "ABS(t.amount) ASC",
                  "newest": "t.date DESC, t.id DESC", "oldest": "t.date, t.id"}
        limit = spec["top"] if spec["measure"] in ("list", "max") and spec["top"] else (
            1 if spec["measure"] == "max" else 50)
        rows = con.execute(
            "SELECT t.id, t.account, t.date, t.text, t.amount, t.currency, t.kind, t.merchant_key,"
            f" COALESCE(m.name, t.merchant) merchant, {_cat_sql()} category,"
            " t.foreign_amount, t.foreign_currency" + _JOIN + where
            + f" ORDER BY {orders[spec['order']]} LIMIT ?", params + [limit]).fetchall()
        if spec["merchants"]:
            matched_merchants = [
                {"name": r["name"], "count": r["n"]} for r in con.execute(
                    "SELECT COALESCE(m.name, t.merchant) name, COUNT(*) n" + _JOIN + where
                    + " GROUP BY name ORDER BY n DESC LIMIT 12", params)]
    if tot["n"] == 0 and spec["merchants"]:
        sugg = similar_merchants(user_id, spec["merchants"])
        if sugg:
            notes.append("No transactions matched " + ", ".join(f'"{w}"' for w in spec["merchants"])
                         + ". Similar merchant names: " + ", ".join(sugg) + ".")
    total = (tot["s"] or 0) / 100 * sign
    return {
        "count": tot["n"], "total": round(total, 2),
        "average": round(total / tot["n"], 2) if tot["n"] else None,
        "firstDate": tot["a"], "lastDate": tot["b"],
        "largest": (tot["mx"] or 0) / 100,
        "groups": groups,
        "rows": [_tx(r) for r in rows],
        "rowsShown": len(rows),
        "matchedMerchants": matched_merchants,
        "excludedTransfers": excluded_transfers,
        "notes": notes,
    }


def similar_merchants(user_id: int, words: list[str], n: int = 6) -> list[str]:
    """Merchant names close to what was asked for ("davidson" ->
    Davidsens Tømmerhandel): word against word, so a long shop name does
    not drown the match."""
    import difflib
    with db.connect() as con:
        names = [r[0] for r in con.execute("SELECT name FROM ledger_merchants WHERE user_id=?",
                                           (user_id,))]
    scored: dict[str, float] = {}
    for w in words:
        w = w.casefold()
        for nm in names:
            best = 0.0
            for tok in re.split(r"[\s,./&*-]+", nm.casefold()):
                if not tok:
                    continue
                r = difflib.SequenceMatcher(None, w, tok).ratio()
                if len(w) >= 4 and (tok.startswith(w[:4]) or w in tok):
                    r = max(r, 0.8)
                best = max(best, r)
            if best >= 0.75:
                scored[nm] = max(scored.get(nm, 0.0), best)
    return [nm for nm, _ in sorted(scored.items(), key=lambda x: -x[1])][:n]


def describe_spec(spec: dict) -> str:
    """The spec in words, shown under the answer: what was actually counted."""
    bits = []
    what = {"out": "money out", "in": "money in", "both": "money in and out"}[spec["direction"]]
    bits.append(what)
    if spec["merchants"]:
        bits.append("matching " + " or ".join(f'"{m}"' for m in spec["merchants"]))
    if spec["words"]:
        bits.append("with " + " and ".join(f'"{w}"' for w in spec["words"]) + " in the text")
    if spec["categories"]:
        bits.append("in " + ", ".join(category_label(c) for c in spec["categories"]))
    if spec["kinds"]:
        bits.append("paid by " + ", ".join(spec["kinds"]))
    if spec["from"] or spec["to"]:
        bits.append(f"from {spec['from'] or 'the start'} to {spec['to'] or 'the end'}")
    else:
        bits.append("in all data")
    if spec["account"]:
        bits.append(f"account {spec['account']}")
    if spec["group"] != "none":
        bits.append(f"per {spec['group']}")
    if spec["measure"] in ("list", "max"):
        bits.append(f"{spec['order']} first" + (f", top {spec['top']}" if spec["top"] else ""))
    if not spec["includeTransfers"]:
        bits.append("own transfers left out")
    return ", ".join(bits)


def kr(x: float | None) -> str:
    """9410.5 -> '9.410,50 kr' - the Danish way, as the bank writes it."""
    if x is None:
        return "-"
    s = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if x < 0 else "") + s + " kr"
