"""Spørg Alf - the family asks, the model answers from their own reviews
first (2.46.0, FamilyMap release 3).

One question at a time per person (Søren's choice): no history, a new
question replaces the old answer. The work is one job in the app's GPU
queue, so a question waits behind a render instead of running beside it.

The steps, each visible on the phone:

1. **Understand** - the FamilyMap chat model turns the question into a
   search: where (a town name, or "near me"), which categories, concrete
   words ("pizza"), a child's age, a radius.
2. **Search** - places around that point from the database, matched on
   category, on the words (name, OSM details such as cuisine=pizza, the
   family's review texts and fields, photo descriptions), and on age.
3. **Rank** - the rule Søren set: places the family reviewed AND that fit
   come first, best score first; then this person's wishlist; then the
   rest by distance. A place the family reviewed badly (under 50, or "vil
   ikke igen") is passed on as a warning, not a suggestion.
4. **Web** (only when fewer than MIN_MATCHES fit) - a web search; the model
   picks real places out of the results, and they are saved as places
   (source "web", position approximate: the town's).
5. **Answer** - the model writes a short Danish answer using ONLY the
   listed places, each marked [[id]] so the phone can link it.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time

from app.core import db, jobqueue, logs, ollama, settings, websearch

from . import familymap as fm, familymap_osm as osm

MIN_MATCHES = 3              # fewer fitting places than this -> ask the web
DEFAULT_RADIUS_KM = 15.0
NEAR_ME_RADIUS_KM = 10.0
MAX_RADIUS_KM = 80.0
GOOD_SCORE = 50              # a reviewed place below this is a warning
QUEUE_BASE = 2_000_000       # queue keys -(QUEUE_BASE + user id): one per person
MAX_QUESTION = 400

UNDERSTAND_PROMPT = """Du hjælper en familie med at finde steder. Læs spørgsmålet og svar KUN med JSON:
{"location": "bynavn som skrevet, eller null", "nearMe": true/false,
 "categories": [nøgler], "keywords": [ord], "age": tal eller null, "radiusKm": tal eller null}

Kategori-nøgler: %s.
- location: byen/området der nævnes ("Vojens", "Flensborg"). null hvis ingen.
- nearMe: true ved "her", "i nærheden", "tæt på mig", eller når intet sted nævnes.
- categories: de der passer; tom liste hvis alle kan passe. Noget at lave med børn: activity, playground, attraction, nature.
  Svømmehal, legeland, trampolinpark, biograf, klatring og skøjtebane er activity.
- keywords: KUN konkrete ting der skal matche stedet, små bogstaver, på dansk OG engelsk
  (fx "pizza", "sushi", "svømmehal", "swimming", "is", "ice cream"). Ikke generelle ord som "sted", "aktivitet", "god".
- age: barnets alder i år hvis nævnt.
- radiusKm: kun hvis spørgsmålet siger en afstand."""

WEB_PICK_PROMPT = """Nedenfor er søgeresultater. Find op til 5 RIGTIGE, konkrete steder (restauranter, legepladser,
museer osv.) i eller nær %s der passer til: %s.
Svar KUN med JSON: {"places": [{"name": "...", "category": "nøgle", "address": "... eller tom",
"website": "url eller tom", "why": "kort, hvad kilden siger"}]}
Kategori-nøgler: %s. Tag ikke oversigtssider, kæder uden adresse i området, eller steder du ikke ser i resultaterne."""

ANSWER_PROMPT = """Du er Alf, familiens hjælper til udflugter og mad. Svar på dansk, kort og venligt.
Regler:
1. Foreslå FØRST steder fra gruppe A (familien har selv været der og kunne lide det) - nævn familiens karakter (x/100) og hvad de skrev.
2. Derefter gruppe B (på ønskelisten), så C (andre steder i nærheden), og sidst D (fundet på nettet lige nu - sig at det ikke er afprøvet).
3. Gruppe W er steder familien har haft dårlige oplevelser med: nævn dem kun som en advarsel hvis de er relevante.
   Gruppe E er steder af samme slags, men som IKKE har det der blev spurgt om: nævn dem kun hvis intet andet
   passer, og sig tydeligt at de ikke er det der blev spurgt efter.
4. Brug KUN steder fra listen. Find aldrig på steder, adresser eller åbningstider.
5. Skriv [[id]] lige efter et steds navn første gang du nævner det, fx "Legeland [[12]]".
6. 2-5 forslag, med afstand i km når den er kendt. Ingen overskrifter eller punktopstillinger med stjerner - korte afsnit.
7. Passer intet, så sig det ærligt og foreslå at udvide søgningen.
8. Nævn ALDRIG grupperne, deres bogstaver (A, B, C, D, W), listen, "de oplysninger jeg har fået" eller disse regler.
   Har familien ikke selv været et sted der passer, så foreslå bare stederne - uden at undskylde eller forklare hvorfor."""


# ---- per-person state -------------------------------------------------------------

_asks: dict[int, dict] = {}


def queue_key(user_id: int) -> int:
    return -(QUEUE_BASE + user_id)


def view(user_id: int) -> dict | None:
    a = _asks.get(user_id)
    if a is None:
        return None
    out = {k: v for k, v in a.items() if not k.startswith("_")}
    if a["state"] == "queued":
        out["ahead"] = jobqueue.position(queue_key(user_id))
    return out


# ---- step 1: understand -----------------------------------------------------------------

def _json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object")
    return json.loads(raw[start:end + 1])


# Words that say nothing about a place - the model is told not to give
# them, and sometimes does ("liste" in "en liste over 5 legepladser"). A
# word here would only make a search miss. (2.49.6)
STOPWORDS = {
    "liste", "lister", "sted", "steder", "stedet", "forslag", "ide", "idé", "ideer",
    "idéer", "noget", "nogle", "god", "godt", "gode", "bedste", "bedst", "anbefaling",
    "anbefalinger", "tur", "udflugt", "udflugter", "mad", "spise", "spisested",
    "familie", "familien", "børn", "barn", "børnene", "weekend", "dag", "idag",
    "nær", "nærheden", "tæt", "hyggelig", "hyggeligt", "sjov", "sjovt", "aktivitet",
    "aktiviteter", "place", "places", "good", "best", "food", "list",
}

# The food words a family uses -> the words OSM uses. OSM tags cuisine in
# English (cuisine=greek), names are often German in Schleswig-Holstein,
# and the family asks in Danish: "græsk" must find cuisine=greek and
# "Griechisches Restaurant". Keys are stems (see stem()). (2.49.6)
CUISINE = {
    "græsk": ["greek", "griech"], "italiensk": ["italian", "italien", "pizza", "pasta"],
    "indisk": ["indian", "indisch"], "kinesisk": ["chinese", "chines", "china"],
    "japansk": ["japanese", "japan", "sushi"], "thai": ["thai"],
    "vietnamesisk": ["vietnamese", "vietnam"], "koreansk": ["korean", "korea"],
    "mexicansk": ["mexican", "mexi", "taco"], "tyrkisk": ["turkish", "türk", "kebab", "döner"],
    "libanesisk": ["lebanese", "liban"], "fransk": ["french", "französ"],
    "spansk": ["spanish", "spani", "tapas"], "amerikansk": ["american", "burger", "diner"],
    "dansk": ["danish", "dänisch", "smørrebrød"], "tysk": ["german", "deutsch"],
    "asiatisk": ["asian", "asia", "wok", "sushi", "thai", "chinese"],
    "is": ["ice_cream", "eis", "gelato"], "pizza": ["pizza"], "burger": ["burger"],
    "sushi": ["sushi"], "kebab": ["kebab", "döner"], "fisk": ["fish", "seafood", "fisch"],
    "skaldyr": ["seafood", "fisch"], "bøf": ["steak"], "steak": ["steak"],
    "vegetar": ["vegetarian"], "vegansk": ["vegan"], "vegan": ["vegan"],
    "kaffe": ["coffee"], "kage": ["cake", "kuchen", "bakery"], "bager": ["bakery", "bäcker"],
    "morgenmad": ["breakfast", "brunch", "frühstück"], "brunch": ["brunch"],
}


def expand(words: list[str]) -> list[str]:
    """Each word as a stem, plus what OSM and German names say for it."""
    out: list[str] = []
    for w in words:
        s = stem(w)
        hit = next((v for k, v in CUISINE.items()
                    if s == k or (len(k) >= 4 and s.startswith(k))
                    or (len(s) >= 4 and k.startswith(s))), [])
        for x in [s, *hit]:
            if x not in out:
                out.append(x)
    return out


def clean_intent(d: dict) -> dict:
    """The model's reading of the question, made safe to search with."""
    cats = [c for c in (d.get("categories") or []) if c in fm.CATEGORIES]
    words = []
    for w in d.get("keywords") or []:
        w = " ".join(str(w).casefold().split())
        if w in STOPWORDS or stem(w) in STOPWORDS:
            continue
        if 2 <= len(w) <= 40 and w not in words:
            words.append(w)
    age = d.get("age")
    try:
        age = int(age) if age not in (None, "") else None
    except (TypeError, ValueError):
        age = None
    if age is not None and not 0 <= age <= 99:
        age = None
    radius = d.get("radiusKm")
    try:
        radius = float(radius) if radius not in (None, "") else None
    except (TypeError, ValueError):
        radius = None
    if radius is not None:
        radius = max(1.0, min(radius, MAX_RADIUS_KM))
    loc = d.get("location")
    loc = str(loc).strip()[:80] if loc and str(loc).strip().lower() != "null" else None
    return {"location": loc, "nearMe": bool(d.get("nearMe")), "categories": cats,
            "keywords": words[:8], "age": age, "radiusKm": radius}


async def _ask_json(model: str, system: str, user: str) -> dict:
    raw = ""
    async for piece in ollama.stream_chat(model, [{"role": "system", "content": system},
                                                  {"role": "user", "content": user}],
                                          response_format="json"):
        raw += piece
    return _json(raw)


# ---- step 2+3: search and rank ----------------------------------------------------------------

_AGE_NUM = r"(\d{1,2})"


def parse_age_range(text: str) -> tuple[int | None, int | None] | None:
    """The family's own "Passer til alder" as (from, to), either end open.
    "3-10 år", "3 til 10", "fra 5 år", "5+", "over 5", "under 6",
    "op til 12", "0-3". A lone number or anything else says too little to
    exclude a place with, and gives None. (2.49.3)"""
    t = " ".join(str(text or "").casefold().replace("–", "-").replace("—", "-").split())
    if not t:
        return None
    m = re.search(_AGE_NUM + r"\s*(?:-|til)\s*" + _AGE_NUM, t)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (min(lo, hi), max(lo, hi))
    m = re.search(r"(?:fra|over|min\.?|mindst)\s*" + _AGE_NUM, t) or re.search(_AGE_NUM + r"\s*\+", t)
    if m:
        n = int(m.group(1))
        return (n + 1 if t.lstrip().startswith("over") or " over " in f" {t} " else n, None)
    m = re.search(r"(?:under|op til|højst|max\.?|maks\.?)\s*" + _AGE_NUM, t)
    if m:
        n = int(m.group(1))
        return (None, n - 1 if "under" in t else n)
    return None


def _family_age_verdict(reviews: list, age: int) -> bool | None:
    """What the family's reviews say about this age: True when any review's
    range includes it, False when every range given excludes it, None when
    no review gives a range. The family's word beats OSM's. (2.49.3)"""
    ranges = []
    for r in reviews:
        try:
            fields = json.loads(r["fields"] or "{}")
        except (TypeError, ValueError):
            continue
        rng = parse_age_range(fields.get("ageRange", ""))
        if rng:
            ranges.append(rng)
    if not ranges:
        return None
    return any((lo is None or age >= lo) and (hi is None or age <= hi) for lo, hi in ranges)


def _age_fits(extra: dict, age: int | None) -> bool:
    if age is None:
        return True
    def num(v):
        m = re.match(r"\s*(\d+)", str(v or ""))
        return int(m.group(1)) if m else None
    lo, hi = num(extra.get("min_age")), num(extra.get("max_age"))
    return (lo is None or age >= lo) and (hi is None or age <= hi)


def stem(word: str) -> str:
    """Danish plural and definite endings off, so "legepladser" finds
    "Legeplads" and "svømmehallerne" finds "svømmehal". Only for words long
    enough that the rest still means something. (2.49.2)"""
    w = word.casefold().strip()
    for end in ("erne", "ene", "ers", "er", "en", "et", "e", "s"):
        if w.endswith(end) and len(w) - len(end) >= 4:
            w = w[: -len(end)]
            break
    if len(w) >= 5 and w[-1] == w[-2]:
        w = w[:-1]                          # hall -> hal, after "haller" -> "hall"
    return w


def drop_category_words(intent: dict) -> dict:
    """A keyword that only names a chosen category ("legepladser" with
    category playground) adds nothing but a way to miss: the category
    already says it. Such words are dropped. (2.49.2)"""
    names = []
    for c in intent["categories"]:
        names += [c.casefold(), *fm.CATEGORIES[c]["label"].casefold().replace("/", " ").split()]
    kept = [w for w in intent["keywords"]
            if not any(stem(w) in n or n in w.casefold() for n in names if len(n) >= 3)]
    return {**intent, "keywords": kept}


def search(center: tuple[float, float], radius_km: float, intent: dict,
           user_id: int, limit_others: int = 12) -> dict:
    """Candidates around `center`, in Søren's order. Returns the groups the
    answer prompt lists: good (A), wished (B), others (C), warnings (W)."""
    lat0, lng0 = center
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(0.2, math.cos(math.radians(lat0))))
    where = ["p.lat BETWEEN ? AND ?", "p.lng BETWEEN ? AND ?"]
    args: list = [lat0 - dlat, lat0 + dlat, lng0 - dlng, lng0 + dlng]
    if intent["categories"]:
        where.append(f"p.category IN ({','.join('?' * len(intent['categories']))})")
        args += intent["categories"]
    sql = fm._STATS_SQL + " WHERE " + " AND ".join(where)
    with db.connect() as con:
        rows = con.execute(_positional(sql), [user_id, *args]).fetchall()
        places = [fm._place_dto(r, fm._stats(r)) for r in rows]
        ids = [p["id"] for p in places if p["reviewCount"]]
        reviews: dict[int, list] = {}
        photos: dict[int, list] = {}
        if ids:
            marks = ",".join("?" * len(ids))
            for r in con.execute(
                    f"SELECT r.*, u.username AS author FROM fm_reviews r"
                    f" LEFT JOIN users u ON u.id = r.user_id WHERE r.place_id IN ({marks})"
                    f" ORDER BY r.visited_on DESC, r.id DESC", ids):
                reviews.setdefault(r["place_id"], []).append(r)
            for r in con.execute(
                    f"SELECT r.place_id, ph.description FROM fm_photos ph"
                    f" JOIN fm_reviews r ON r.id = ph.review_id"
                    f" WHERE r.place_id IN ({marks}) AND ph.description IS NOT NULL", ids):
                photos.setdefault(r["place_id"], []).append(r["description"])

    words = expand(intent["keywords"])
    fitting = []
    for p in places:
        p["distanceKm"] = round(fm.distance_km(lat0, lng0, p["lat"], p["lng"]), 1)
        if p["distanceKm"] > radius_km:
            continue
        revs = reviews.get(p["id"], [])
        if intent["age"] is not None:
            family = _family_age_verdict(revs, intent["age"])
            if family is False or (family is None
                                   and not _age_fits(p.get("extra") or {}, intent["age"])):
                continue
        p["_reviews"] = revs
        p["_photos"] = photos.get(p["id"], [])[:2]
        if words:
            blob = " ".join([
                p["name"], p["address"], fm.CATEGORIES[p["category"]]["label"],
                " ".join(f"{k} {v}" for k, v in (p.get("extra") or {}).items()),
                " ".join(r["text"] + " " + r["fields"] for r in revs),
                " ".join(p["_photos"])]).casefold()
            if not any(w in blob for w in words):
                continue
        fitting.append(p)

    def bad(p):
        revs = p["_reviews"]
        return (p["familyScore"] is not None and p["familyScore"] < GOOD_SCORE) or \
            any(r["again"] == 0 for r in revs)
    reviewed = [p for p in fitting if p["reviewCount"]]
    good = sorted([p for p in reviewed if not bad(p)],
                  key=lambda p: (-(p["familyScore"] or 0), p["distanceKm"]))
    warnings = sorted([p for p in reviewed if bad(p)], key=lambda p: p["distanceKm"])[:3]
    rest = [p for p in fitting if not p["reviewCount"]]
    wished = sorted([p for p in rest if p["wished"]], key=lambda p: p["distanceKm"])[:5]
    others = sorted([p for p in rest if not p["wished"]], key=lambda p: p["distanceKm"])
    return {"good": good[:6], "wished": wished, "others": others[:limit_others],
            "warnings": warnings, "fitting": len(good) + len(wished) + len(others)}


def find(center: tuple[float, float], radius_km: float, intent: dict, user_id: int) -> dict:
    """The places that fit the question - by its words when it has any:
    first in the chosen categories, then in EVERY category (the model's
    category is a guess, a concrete word is not: "kastanjer" read as Natur
    missed the family's "Kastanjetræ" under Oplevelse, 2.49.4). Without
    words: the categories. What to do when too few fit - the web, then the
    rest of the category - is the caller's (run). (2.49.6)"""
    words, cats = intent["keywords"], intent["categories"]
    passes = [search(center, radius_km, intent, user_id)]
    if words and cats:
        passes.append(search(center, radius_km, {**intent, "categories": []}, user_id))
    return _merge(passes)


def fill(center: tuple[float, float], radius_km: float, intent: dict, user_id: int,
         have: set[int]) -> list[dict]:
    """The rest of the category, without the words - offered only as "if
    nothing else": a Greek restaurant was asked for, and the family's
    favourite steakhouse must not be suggested as one. (2.49.6)"""
    g = search(center, radius_km, {**intent, "keywords": []}, user_id)
    rest = [p for k in ("good", "wished", "others") for p in g[k] if p["id"] not in have]
    return rest[:6]


def _merge(passes: list[dict]) -> dict:
    """Union of several searches, first pass first, each place once."""
    seen: set[int] = set()
    merged: dict[str, list] = {"good": [], "wished": [], "others": [], "warnings": []}
    for g in passes:
        for key in merged:
            for p in g[key]:
                if p["id"] not in seen:
                    seen.add(p["id"])
                    merged[key].append(p)
    merged["good"].sort(key=lambda p: (-(p["familyScore"] or 0), p["distanceKm"]))
    ids = {p["id"] for k in ("good", "wished", "others") for p in merged[k]}
    return {"good": merged["good"][:6], "wished": merged["wished"][:5],
            "others": merged["others"][:12], "warnings": merged["warnings"][:3],
            "fitting": len(ids), "_ids": ids}


def _positional(sql: str) -> str:
    # _STATS_SQL names its one parameter :me; the WHERE here is positional.
    # sqlite cannot mix them, so :me becomes the first "?".
    return sql.replace(":me", "?")


# ---- step 4: the web ----------------------------------------------------------------------

async def web_places(model: str, intent: dict, where: dict, question: str,
                     user_id: int) -> list[dict]:
    """Search the web, let the model pick real places, save them. Returns
    the saved places (new or already known by name in that town)."""
    kind = [fm.CATEGORIES[c]["label"].split(" /")[0].lower() for c in intent["categories"][:1]]
    words = intent["keywords"][:3] or []
    # "græsk restaurant Flensburg" - the word, the kind of place, the town.
    query = " ".join([*words, *kind, where["name"]]).strip()
    try:
        results = await websearch.search(query, settings.load(), limit=6)
    except Exception as exc:
        logs.record_exception(exc, "Spørg Alf web search")
        return []
    if not results:
        return []
    listing = "\n".join(f"- {r.get('title', '')} | {r.get('url', '')} | {r.get('snippet', '')}"
                        for r in results)
    keys = ", ".join(fm.CATEGORIES)
    try:
        picked = await _ask_json(model, WEB_PICK_PROMPT % (where["name"], question, keys), listing)
    except Exception as exc:
        logs.record_exception(exc, "Spørg Alf picking places from the web")
        return []
    saved = []
    for item in (picked.get("places") or [])[:5]:
        name = " ".join(str(item.get("name") or "").split())[:fm.MAX_SHORT]
        cat = item.get("category")
        if not name or cat not in fm.CATEGORIES:
            continue
        with db.connect() as con:
            known = con.execute(
                "SELECT id FROM fm_places WHERE name = ? COLLATE NOCASE"
                " AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
                (name, where["lat"] - .2, where["lat"] + .2,
                 where["lng"] - .3, where["lng"] + .3)).fetchone()
        if known:
            pid = known["id"]
        else:
            website = str(item.get("website") or "")
            place = fm.create_place({
                "name": name, "category": cat,
                "address": str(item.get("address") or where["name"])[:fm.MAX_SHORT],
                "lat": where["lat"], "lng": where["lng"],
                "website": website if website.startswith(("http://", "https://")) else "",
                "notes": f"Fundet på nettet af Spørg Alf: {str(item.get('why') or '')[:300]}",
                "source": "web"}, user_id)
            pid = place["id"]
            with db.connect() as con:
                con.execute("UPDATE fm_places SET extra = ? WHERE id = ?",
                            (json.dumps({"position": "omtrentlig (byens midte)"},
                                        ensure_ascii=False), pid))
        p = fm.get_place(pid, me=user_id)
        p["distanceKm"] = None
        p["_reviews"], p["_photos"] = [], []
        saved.append(p)
    return saved


# ---- step 5: answer ---------------------------------------------------------------------------

def _describe(p: dict) -> str:
    cat = fm.CATEGORIES[p["category"]]
    bits = [f"[{p['id']}] {p['name']} ({cat['label']})"]
    if p.get("distanceKm") is not None:
        bits.append(f"{p['distanceKm']} km")
    if p["address"]:
        bits.append(p["address"])
    if p["familyScore"] is not None:
        bits.append(f"familiens karakter {p['familyScore']}/100 ({p['reviewCount']} anmeldelser)")
    extra = {k: v for k, v in (p.get("extra") or {}).items()
             if k in ("cuisine", "opening_hours", "min_age", "max_age", "fee",
                      "outdoor_seating", "wheelchair", "description", "position")}
    if extra:
        bits.append("detaljer: " + "; ".join(f"{k}={v}" for k, v in extra.items()))
    if p.get("notes"):
        bits.append(p["notes"][:200])
    lines = [", ".join(bits)]
    labels = {f["key"]: f for f in cat["fields"]}
    for r in p.get("_reviews", [])[:3]:
        fields = json.loads(r["fields"] or "{}")
        fl = "; ".join(f"{labels[k]['label']}: {('ja' if v else 'nej') if isinstance(v, bool) else v}"
                       for k, v in fields.items() if k in labels)
        again = "" if r["again"] is None else (" Vil gerne igen." if r["again"] else " Vil IKKE igen.")
        lines.append(f"   {r['author'] or 'Familien'} ({r['visited_on'] or 'ukendt dato'}): "
                     f"{r['overall']}/100. {r['text'][:300]} {fl}{again}".rstrip())
    for d in p.get("_photos", []):
        lines.append(f"   Billede: {d[:200]}")
    return "\n".join(lines)


def answer_context(groups: dict, web: list[dict]) -> str:
    parts = []
    for key, title in (("good", "A - familien har været der og kunne lide det"),
                       ("wished", "B - på ønskelisten"),
                       ("others", "C - andre steder i nærheden"),
                       ("web", "D - fundet på nettet lige nu, ikke afprøvet"),
                       ("rest", "E - samme slags sted, men UDEN det der blev spurgt om"),
                       ("warnings", "W - dårlige oplevelser (kun som advarsel)")):
        items = web if key == "web" else groups.get(key, [])
        if items:
            parts.append(f"Gruppe {title}:\n" + "\n".join(_describe(p) for p in items))
    return "\n\n".join(parts) or "(ingen steder fundet)"


def card(p: dict) -> dict:
    return {k: p.get(k) for k in ("id", "name", "category", "address", "familyScore",
                                  "reviewCount", "coverPhotoId", "distanceKm", "source",
                                  "wished", "latestText")}


# ---- the job -----------------------------------------------------------------------------------

async def gather(user_id: int, question: str, phone: tuple[float, float] | None,
                 radius_override: float | None, a: dict, model: str, step) -> dict | None:
    """Steps 1-4: understand, find where, search, the web. Fills the view
    `a` as it goes (intent, where, radiusKm, webAdded, relaxed, searched,
    places) and returns {"where", "radius", "context"} for the answer -
    or None when there is no place to search around (a["text"] then says
    so). Split out of run() in FamilyLog 0.2.0, so the front page's chat
    can ask the same search; the steps are unchanged."""
    keys = ", ".join(f"{k} ({c['label']})" for k, c in fm.CATEGORIES.items())
    intent = clean_intent(await _ask_json(model, UNDERSTAND_PROMPT % keys, question))
    a["intent"] = intent

    where = None
    if intent["location"]:
        where = osm.find_locality(intent["location"]) or _place_as_locality(intent["location"])
    if where is None and phone is not None:
        where = {"name": "din position", "lat": phone[0], "lng": phone[1], "kind": "phone"}
    if where is None:
        a["text"] = ("Jeg kunne ikke finde " + (f"\"{intent['location']}\"" if intent["location"]
                     else "et sted i spørgsmålet") +
                     ". Skriv en by (fx Vojens), eller slå \"Nær mig\" til, så jeg kan bruge din position.")
        return None
    a["where"] = where["name"]
    # The page's choice wins; then a distance said in the question; then
    # the defaults. (2.47.0)
    radius = radius_override or intent["radiusKm"] or (
        NEAR_ME_RADIUS_KM if where["kind"] == "phone" else DEFAULT_RADIUS_KM)
    a["radiusKm"] = radius

    step(f"Søger omkring {where['name']}…", "search")
    intent = drop_category_words(intent)
    a["intent"] = intent
    groups = await asyncio.to_thread(find, (where["lat"], where["lng"]), radius,
                                     intent, user_id)
    # Too few fit the words: the web first (2.49.6 - "græsk restaurant i
    # Flensborg" was answered with the whole category and never asked
    # the web). Near the phone, the web is asked about the nearest town.
    web: list[dict] = []
    if groups["fitting"] < MIN_MATCHES:
        town = where if where["kind"] != "phone" else (
            osm.nearest_locality(where["lat"], where["lng"]))
        if town:
            step("Finder for lidt - søger på nettet…", "web")
            known = {p["id"] for g in ("good", "wished", "others") for p in groups[g]}
            web = [p for p in await web_places(model, intent, town, question, user_id)
                   if p["id"] not in known]
            a["webAdded"] = len(web)
    # Still too few, and there is a category: the rest of it, as its own
    # group - "if nothing else".
    rest: list[dict] = []
    if groups["fitting"] + len(web) < MIN_MATCHES and intent["categories"] \
            and intent["keywords"]:
        have = {p["id"] for g in ("good", "wished", "others", "warnings") for p in groups[g]}
        rest = await asyncio.to_thread(fill, (where["lat"], where["lng"]), radius,
                                       intent, user_id, have | {p["id"] for p in web})
    a["relaxed"] = bool(rest)
    groups["rest"] = rest
    # What was actually searched for, in words, shown under the answer.
    what = [fm.CATEGORIES[c]["label"] for c in intent["categories"]] or ["alle slags steder"]
    used = intent["keywords"]
    a["searched"] = ", ".join(what) + (f" med \"{', '.join(used)}\"" if used else "") + \
        (" (ordene også i andre kategorier)" if used and intent["categories"] else "") + \
        (" - for få, så også resten af kategorien" if rest else "") + \
        (f", {intent['age']} år" if intent["age"] is not None else "")
    a["places"] = [card(p) for g in ("good", "wished", "others") for p in groups[g]] + \
        [card(p) for p in web] + [card(p) for p in rest] + \
        [card(p) for p in groups["warnings"]]
    return {"where": where, "radius": radius, "context": answer_context(groups, web)}


async def run(user_id: int, question: str, phone: tuple[float, float] | None,
              radius_override: float | None = None) -> None:
    a = _asks[user_id]
    model = fm.chat_model()

    def step(s: str, phase: str):
        # `phase` picks the animation on the phone (2.48.0); `step` is its text.
        a["state"], a["step"], a["phase"] = "working", s, phase

    try:
        # The queue freed ComfyUI's VRAM before this job started (setting
        # comfyFreeFirst) - SLQ called free_vram here itself.
        step("Forstår spørgsmålet…", "understand")
        found = await gather(user_id, question, phone, radius_override, a, model, step)
        if found is None:
            a["state"] = "done"
            return
        where, radius = found["where"], found["radius"]

        step("Skriver svaret…", "write")
        a["text"] = ""

        def thinking(_text: str) -> None:
            # A thinking model reasons before it writes - often the longest
            # wait of all, with nothing to show. Say so. (2.48.0)
            if not a["text"]:
                a["step"], a["phase"] = "Tænker over svaret…", "think"
        async for piece in ollama.stream_chat(model, [
                {"role": "system", "content": ANSWER_PROMPT},
                {"role": "user", "content":
                    f"Spørgsmål: {question}\nOmråde: {where['name']}, radius {radius:g} km.\n\n"
                    f"{found['context']}"}],
                on_thinking=thinking):
            if not a["text"]:
                a["step"], a["phase"] = "Skriver svaret…", "write"
            a["text"] += piece
        a["state"] = "done"
    except Exception as exc:
        logs.record_exception(exc, "Spørg Alf")
        a["state"] = "failed"
        a["error"] = f"Alf kunne ikke svare: {str(exc) or exc.__class__.__name__}"
    finally:
        a["finishedAt"] = time.time()


def _place_as_locality(name: str) -> dict | None:
    """A town that is a FamilyMap place (category city) but not yet in the
    gazetteer - e.g. before the first import of town names."""
    with db.connect() as con:
        r = con.execute("SELECT name, lat, lng FROM fm_places WHERE category = 'city'"
                        " AND name = ? COLLATE NOCASE AND lat IS NOT NULL", (name,)).fetchone()
    return {"name": r["name"], "lat": r["lat"], "lng": r["lng"], "kind": "city"} if r else None


def submit(user_id: int, question: str, phone: tuple[float, float] | None,
           radius_km: float | None = None) -> dict:
    """Queue a question. Must be called from a running event loop."""
    question = " ".join(str(question or "").split())
    if not question:
        raise fm.Invalid("Skriv et spørgsmål.")
    if len(question) > MAX_QUESTION:
        raise fm.Invalid(f"Spørgsmålet er for langt (højst {MAX_QUESTION} tegn).")
    if not fm.chat_model():
        raise fm.Invalid("Alf har ingen model endnu - bed administratoren vælge en chatmodel "
                         "under Settings (eller FamilyMap → Settings).")
    if radius_km is not None:
        radius_km = max(1.0, min(float(radius_km), MAX_RADIUS_KM))
    old = _asks.get(user_id)
    if old and old["state"] in ("queued", "working"):
        raise fm.Invalid("Alf tænker stadig over dit sidste spørgsmål.")
    a = {"question": question, "state": "queued", "step": "Venter på sin tur…", "phase": "queue",
         "text": "", "places": [], "error": None, "intent": None, "where": None,
         "radiusKm": None, "webAdded": 0, "startedAt": time.time(), "finishedAt": None}
    _asks[user_id] = a
    gen: dict = {"text": "", "thinking": "", "done": False, "error": None,
                 "model": fm.chat_model(), "usage": {}}

    def factory():
        async def go():
            try:
                await run(user_id, question, phone, radius_km)
            finally:
                gen["done"] = True
        return go()
    jobqueue.submit(queue_key(user_id), "familymap-ask", gen, factory)
    return view(user_id)
