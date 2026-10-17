"""Browser check for FamilyLog - run with tools/browser_check/run.py.

Through the real UI, against the real backend and the mock Ollama:
first-run setup, Settings (Ollama Test lists the models, roles saved and
kept after a reload), Økonomi (import, categorise by role, Overview,
Transactions, an Ask with Steps and "Counted by the app"), FamilyMap admin
(tabs, a family account, the role shown as default), the family page at
/fm/ (login, list, Spørg Alf with the phone's position), the family lockout,
Alt+click help, the phone width, and (0.2.0) the front page: Alf answering
a general question and a question about places, the shortcuts per role,
the Dagbog filled in on a phone and the family week without the private
text. Every expectation is checked; a page
error or console error fails the run. No real data: the export is synthetic.
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta

from playwright.sync_api import Page, expect, sync_playwright

BASE, MOCK, OUT = sys.argv[1:4]
problems: list[str] = []
passed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passed if ok else problems).append(name + (f" - {detail}" if detail and not ok else ""))
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""))


def watch(page: Page, label: str) -> None:
    page.on("pageerror", lambda e: problems.append(f"{label} pageerror: {e}"))

    def on_console(m):
        # A 4xx the page itself asked for and handles (e.g. 401 before
        # login) is logged by Chromium as a console error; those are fine.
        if m.type == "error" and "Failed to load resource" not in m.text:
            problems.append(f"{label} console: {m.text}")
    page.on("console", on_console)


def synthetic_export() -> bytes:
    rnd = random.Random(3)
    rows = []
    shops = ["kontaktløs Dankort Netto Skagen Nota C{n}", "Q8 SERVICE - 8253, VOJENS Notanr {n}",
             "kontaktløs Dankort Zxq Shop {n} Nota C1", "Dankort-køb proshop.dk Nota {n}"]
    start = date(2025, 1, 2)
    for _ in range(400):
        d = start + timedelta(days=rnd.randrange(0, 600))
        rows.append((d, rnd.choice(shops).format(n=rnd.randrange(1, 30)), -rnd.randrange(2000, 90000)))
    for k in range(18):
        d = date(2025 + (k // 12), k % 12 + 1, 8)
        rows.append((d, "Betalingsservice DAVIDSENS TØMMERHANDEL A/S Aftalenr. 001234567", -(150000 + k * 41000)))
        rows.append((date(d.year, d.month, 28), "Budgetkonto", -1200000))
    rows.sort(key=lambda r: r[0], reverse=True)

    def kr(o):
        s = f"{abs(o) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return ("-" if o < 0 else "") + s
    return ("﻿" + "\r\n".join(f"{d.strftime('%d-%m-%Y')};{t};{kr(a)};DKK" for d, t, a in rows)
            + "\r\n").encode()


def wait_until(page: Page, fn, timeout_ms: int = 20000, step: int = 250) -> bool:
    for _ in range(timeout_ms // step):
        if fn():
            return True
        page.wait_for_timeout(step)
    return False


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    watch(page, "app")

    # ---- first run: the setup screen makes the admin ----------------------------
    page.goto(BASE + "/")
    page.wait_for_url("**/app/", timeout=10000)          # the front page sends the first run here
    expect(page.get_by_role("heading", name="FamilyLog")).to_be_visible()
    check("first run shows setup", page.get_by_role("button", name="Create administrator").is_visible())
    page.fill("input[name=username]", "admin")
    page.fill("input[name=password]", "test-password-1")
    page.fill("input[name=confirm]", "test-password-1")
    page.get_by_role("button", name="Create administrator").click()
    page.wait_for_selector(".topbar")
    check("signed in, app name in the top bar", page.locator(".brand").inner_text() == "FamilyLog")
    check("the sections in the navigation",
          page.locator(".nav-btn").all_inner_texts() == ["Økonomi", "FamilyMap", "Dagbog"])

    # ---- Settings: Test lists the models, roles are saved ------------------------
    page.get_by_role("button", name="Settings").click()
    url = page.locator("[data-help='settings.ollama'] input").first
    expect(url).to_have_value("http://30.11.0.104:11434")
    url.fill(MOCK)
    page.get_by_role("button", name="Test Ollama").click()
    page.wait_for_selector("text=/Connected - 3 models/")
    check("Test lists the mock's models", page.locator(".settings-models tbody tr").count() == 3)
    selects = page.locator("[data-help='settings.models'] select")
    selects.nth(0).select_option("qwen3.6:27b")
    selects.nth(1).select_option("qwen3-vl:8b")
    page.get_by_role("button", name="Save (3)").click()
    page.wait_for_selector(".settings-head .fma-ok")
    page.screenshot(path=f"{OUT}/01-settings.png", full_page=True)
    page.reload()
    page.wait_for_selector(".topbar")
    check("a reload stays on Settings (#settings)", page.url.endswith("/app/#settings")
          and page.locator(".settings-page").count() == 1, page.url)
    expect(page.locator("[data-help='settings.ollama'] input").first).to_have_value(MOCK)
    check("roles kept after a reload",
          page.locator("[data-help='settings.models'] select").nth(0).input_value() == "qwen3.6:27b"
          and page.locator("[data-help='settings.models'] select").nth(1).input_value() == "qwen3-vl:8b")
    page.locator("[data-help='settings.ollama'] input").first.fill("http://127.0.0.1:9")
    page.get_by_role("button", name="Test Ollama").click()
    page.wait_for_selector("[data-help='settings.ollamaTest'] .fma-error")
    check("a failing Test says why",
          "not answering" in page.locator("[data-help='settings.ollamaTest'] .fma-error").inner_text())
    page.get_by_role("button", name="Undo").click()

    # ---- Økonomi ---------------------------------------------------------------------
    page.locator(".nav-btn", has_text="Økonomi").click()
    page.get_by_role("button", name="Import a bank export").click()
    page.locator(".led-drop input[type=file]").set_input_files(
        files=[{"name": "eksport.csv", "mimeType": "text/csv", "buffer": synthetic_export()}])
    page.wait_for_selector(".led-import .fma-ok", timeout=30000)
    check("import reports the new rows", " new, 0 already in the ledger" in page.locator(".led-import .fma-ok").inner_text(),
          page.locator(".led-import .fma-ok").inner_text()[:120])
    st = {}

    def categorised() -> bool:
        global st
        st = page.request.get(BASE + "/api/ledger/categorise").json()
        return st["state"] not in ("queued", "working")
    wait_until(page, categorised)
    check("unknown merchants categorised by the chat role", st.get("state") == "done"
          and st.get("model") == "qwen3.6:27b", str({k: st.get(k) for k in ("state", "model", "placed", "left")}))
    page.locator(".subnav-btn", has_text="Overview").click()
    page.wait_for_selector(".led-tile")
    check("overview tiles", page.locator(".led-tile").count() >= 3)
    page.screenshot(path=f"{OUT}/02-okonomi-overview.png", full_page=True)
    page.locator(".subnav-btn", has_text="Transactions").click()
    page.wait_for_timeout(800)
    check("transactions listed", page.locator(".led-sum").count() == 1)
    page.locator(".subnav-btn", has_text="Ask").click()
    check("model picker offers the Settings model",
          page.locator(".led-model select option").first.inner_text() == "Settings: qwen3.6:27b")
    page.locator(".led-ask-box textarea").fill("How much have I spent at Davidsens?")
    page.locator(".led-ask-row .primary-btn").click()
    # Behind the categorise batches in the one queue - give it time (it timed out now and then at 20 s).
    wait_until(page, lambda: page.locator(".led-counted").count() > 0
               and page.locator(".led-ask-row .primary-btn").count() > 0, timeout_ms=90000)
    counted = page.locator(".led-counted").inner_text() if page.locator(".led-counted").count() else ""
    check("answer counted by the app", "18 transactions" in counted, counted[:160])
    check("answer text from the mock", "From the ledger:" in page.locator(".led-md").inner_text())
    page.locator(".steps-head").first.click()
    labels = page.locator(".steps-row .steps-label").all_inner_texts()
    check("Steps show the three stages",
          any("Understand the question" in l for l in labels) and any("Count in the ledger" in l for l in labels),
          " / ".join(l.strip()[:30] for l in labels[:6]))
    page.screenshot(path=f"{OUT}/03-okonomi-ask.png", full_page=True)

    # ---- help: Alt+click opens the control's entry ---------------------------------------
    page.locator(".led-ask-box textarea").click(modifiers=["Alt"])
    page.wait_for_selector(".help-drawer .help-entry.open")
    check("Alt+click opens the help entry",
          page.locator(".help-entry.open .help-entry-title").inner_text() == "Ask")
    page.keyboard.press("Escape")
    check("Esc closes help", page.locator(".help-drawer").count() == 0)

    # ---- FamilyMap admin ---------------------------------------------------------------
    page.locator(".nav-btn", has_text="FamilyMap").click()
    page.wait_for_selector(".fma-head")
    for t in ("Places", "Reviews", "Family accounts", "Import from OSM", "Settings"):
        page.locator(".subnav-btn", has_text=t).click()
        page.wait_for_timeout(300)
    check("FamilyMap settings default to the vision role",
          page.locator(".fma-settings select").first.locator("option").first.inner_text() == "Settings: qwen3-vl:8b")
    page.locator(".subnav-btn", has_text="Family accounts").click()
    page.fill("input[placeholder=Username]", "mor")
    page.fill("input[placeholder='Password (10+ characters)']", "familie-kode-1")
    page.get_by_role("button", name="Add family member").click()
    page.wait_for_selector("text=mor can now sign in at /fm/.")
    wait_until(page, lambda: page.locator(".user-list .user-name", has_text="mor").count() == 1)   # the list reloads after
    check("family account added", page.locator(".user-list .user-name", has_text="mor").count() == 1)
    pid = page.request.post(BASE + "/api/fm/places", data={
        "name": "Søparkens Legeplads", "category": "playground", "lat": 55.246, "lng": 9.306}).json()["id"]
    page.screenshot(path=f"{OUT}/04-familymap-admin.png", full_page=True)

    # ---- the family page on a phone ----------------------------------------------------------
    phone = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True,
                                geolocation={"latitude": 55.246, "longitude": 9.306},
                                permissions=["geolocation"])
    fp = phone.new_page()
    watch(fp, "family page")
    fp.goto(BASE + "/fm/")
    fp.wait_for_selector(".fm-login")
    check("family page brand", "Alf" in fp.locator(".fm-login").inner_text())
    fp.locator(".fm-login input").nth(0).fill("mor")
    fp.locator(".fm-login input").nth(1).fill("familie-kode-1")
    fp.locator(".fm-login .fm-primary").click()
    fp.wait_for_selector(".fm-card", timeout=15000)
    check("family sees the place list", fp.locator(".fm-card-name", has_text="Søparkens Legeplads").count() == 1)
    fp.screenshot(path=f"{OUT}/05-fm-list.png", full_page=True)
    fp.locator(".fm-ask-btn").click()
    fp.locator(".fm-ask-box textarea").fill("En legeplads her")
    pos = fp.locator(".fm-ask-pos input[type=checkbox]")
    if not pos.is_checked():
        pos.check()
    fp.locator(".fm-ask-send").click()
    wait_until(fp, lambda: fp.locator(".fm-answer-p").count() > 0 or fp.locator(".fm-answer .fm-error").count() > 0)
    answer = " ".join(fp.locator(".fm-answer-p").all_inner_texts())
    check("Spørg Alf answers with the place", "Søparkens Legeplads" in answer, answer[:120])
    check("the answer links the place", fp.locator(".fm-answer-link").count() >= 1)
    fp.screenshot(path=f"{OUT}/06-fm-ask.png", full_page=True)
    sw = fp.evaluate("document.documentElement.scrollWidth")
    check("family page fits the phone", sw <= 390, f"scrollWidth {sw}")
    # The lockout: the family account reaches nothing but /api/fm/.
    check("family refused outside /api/fm/", fp.request.get(BASE + "/api/ledger/summary").status == 403
          and fp.request.get(BASE + "/api/settings").status == 403)
    fp.goto(BASE + "/app/")
    fp.wait_for_url(BASE + "/", timeout=10000)
    check("the admin app sends a family account to the front page", fp.url == BASE + "/")

    # ---- the front page on the family's phone (0.2.0) ---------------------------------------
    fp.wait_for_selector(".hm-tiles")
    tiles = fp.locator(".hm-tile-name").all_inner_texts()
    check("family tiles: Atlas and Dagbog, no Økonomi", tiles == ["Alf’s Atlas", "Dagbog"], str(tiles))
    fp.locator(".hm-composer textarea").fill("Hvad er en god aftensmad?")
    fp.get_by_role("button", name="Send").click()
    wait_until(fp, lambda: fp.locator(".hm-alf").count() > 0 and "Hej! Det er Alf" in fp.locator(".hm-alf").last.inner_text())
    check("Alf answers a general question", "Hej! Det er Alf" in fp.locator(".hm-alf").last.inner_text())
    pos = fp.locator(".hm-pos input")
    if not pos.is_checked():
        pos.check()
    fp.locator(".hm-composer textarea").fill("Find en legeplads her")
    fp.get_by_role("button", name="Send").click()
    wait_until(fp, lambda: fp.locator(".hm-alf .fm-answer-link").count() > 0)
    link = fp.locator(".hm-alf .fm-answer-link").first
    check("a question about places links the place in the Atlas",
          link.count() == 1 and link.get_attribute("href") == f"/fm/#/sted/{pid}")
    fp.screenshot(path=f"{OUT}/08-home-chat.png", full_page=True)
    sw = fp.evaluate("document.documentElement.scrollWidth")
    check("front page fits the phone", sw <= 390, f"scrollWidth {sw}")

    # Dagbog: fill in today.
    fp.locator(".hm-tile", has_text="Dagbog").click()
    fp.wait_for_selector(".hm-field")
    fp.get_by_label("Humør 4").click()
    check("no Søvn or Energi in the Dagbog (0.2.1)", fp.get_by_label("Søvn 3").count() == 0
          and fp.get_by_label("Energi 3").count() == 0)
    check("Mentalt overskud runs 1-10 (0.2.2)",
          fp.locator(".hm-field[aria-label='Mentalt overskud'] .hm-scale button").count() == 10)
    fp.get_by_label("Mentalt overskud 7").click()
    fp.locator(".hm-field[aria-label='Mad'] .hm-tags button", has_text="Hjemmelavet").click()
    fp.locator(".hm-field[aria-label='Mad'] .hm-tags button", has_text="Kage").click()
    fp.get_by_label("Flere").click()
    fp.locator(".hm-tags button", has_text="Sport").click()
    fp.locator(".hm-tags button", has_text="Børnepasning").click()
    fp.locator(".hm-text").fill("Hemmelig dagbogstekst")
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (90, 140, 200)).save(buf, "JPEG")
    fp.locator(".hm-photo-pick input[type=file]").set_input_files(
        files=[{"name": "dag.jpg", "mimeType": "image/jpeg", "buffer": buf.getvalue()}])
    fp.wait_for_selector(".hm-photo img", timeout=15000)
    if fp.locator(".hm-save").is_enabled():
        fp.locator(".hm-save").click()
    wait_until(fp, lambda: "Gemt" in fp.locator(".hm-save").inner_text())
    check("the day is saved", "Gemt" in fp.locator(".hm-save").inner_text(), fp.locator(".hm-save").inner_text())
    fp.screenshot(path=f"{OUT}/09-dagbog.png", full_page=True)
    sw = fp.evaluate("document.documentElement.scrollWidth")
    check("Dagbog fits the phone", sw <= 390, f"scrollWidth {sw}")
    fp.locator(".hm-tabs a", has_text="Familien").click()
    fp.wait_for_selector(".hm-week")
    fp.screenshot(path=f"{OUT}/10-dagbog-family.png", full_page=True)
    fp.goto(BASE + "/fm/")
    fp.locator(".fm-burger").click()
    check("the Atlas menu leads back to the front page",
          fp.locator(".fm-drawer a", has_text="Til forsiden").get_attribute("href") == "/")

    # ---- the app at phone width ----------------------------------------------------------
    ph = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True).new_page()
    watch(ph, "phone app")
    ph.request.post(BASE + "/api/auth/login", data={"username": "admin", "password": "test-password-1"})
    ph.goto(BASE + "/")
    ph.wait_for_selector(".hm-tiles")
    wait_until(ph, lambda: ph.locator(".hm-tile-name", has_text="Økonomi").count() == 1)
    tiles = ph.locator(".hm-tile-name").all_inner_texts()
    check("the admin's tiles include Økonomi", "Økonomi" in tiles, str(tiles))
    # The admin sees mor's day in the family week - and never her text.
    ph.goto(BASE + "/#/dagbog/familien")
    ph.wait_for_selector(".hm-week")
    row = ph.locator(".hm-week tbody tr", has_text="mor")
    check("the family week shows mor's mood", "🙂" in row.inner_text(), row.inner_text())
    row.locator(".hm-cell:not(.hm-empty)").first.click()
    detail = ph.locator(".hm-detail").inner_text()
    check("the day's detail has ratings, food and activities, not the text",
          "Sport" in detail and "Kage" in detail and "Børnepasning" in detail
          and "7/10" in detail and "Hemmelig" not in detail
          and "kun for mor" in detail, detail[:200])
    check("mor's text is nowhere on the admin's page", "Hemmelig" not in ph.content())
    ph.screenshot(path=f"{OUT}/11-admin-family-week.png", full_page=True)
    ph.locator(".fm-back").click()
    ph.wait_for_selector(".hm-tiles")
    # ---- Økonomi on the phone (0.3.0) -------------------------------------------------------
    ph.locator(".hm-tile", has_text="Økonomi").click()
    ph.wait_for_selector(".ok-hero", timeout=15000)
    check("the Økonomi tile opens the phone page", "#/okonomi" in ph.url and "kr" in ph.locator(".ok-hero-num").inner_text(),
          ph.url)
    check("the owner is pointed to import in the admin app", ph.locator(".ok-foot a", has_text="admin-appen").count() == 1)
    ph.locator(".ok-cat").first.click()
    ph.wait_for_selector(".ok-tx-row", timeout=10000)
    check("a category opens its transactions", ph.locator(".ok-tx-row").count() > 0)
    cats = ph.locator(".ok-cat-name").all_inner_texts()
    check("Q8 shows as Brændstof after the car split (0.3.4)", "Brændstof" in cats and "Bil & brændstof" not in cats, str(cats))
    sw = ph.evaluate("document.documentElement.scrollWidth")
    check("phone Økonomi fits the phone", sw <= 390, f"scrollWidth {sw}")
    ph.screenshot(path=f"{OUT}/12-okonomi-phone.png", full_page=True)
    # 0.3.5: a year, all transactions searched, a shop moved, the months side by side.
    ph.get_by_label("Periode", exact=True).select_option("year")
    wait_until(ph, lambda: ph.locator(".hm-dayname").inner_text().isdigit())
    check("a whole year on the phone", "pr. måned i snit" in ph.locator(".ok-hero").inner_text(),
          ph.locator(".ok-hero").inner_text()[:120])
    ph.get_by_role("button", name="Posteringer", exact=True).click()
    ph.get_by_label("Søg i posteringer").fill("netto")
    wait_until(ph, lambda: ph.locator(".ok-tx-full .ok-tx-row").count() > 0
               and all("Netto" in x for x in ph.locator(".ok-tx-full .ok-tx-text").all_inner_texts()[:5]))
    check("searching the transactions", ph.locator(".ok-tx-full .ok-tx-row").count() > 0
          and "posteringer" in ph.locator(".ok-tx-full").locator("xpath=..").inner_text())
    ph.screenshot(path=f"{OUT}/12b-okonomi-search.png", full_page=True)
    ph.locator(".ok-tx-full .ok-tx-row").first.click()
    ph.wait_for_selector(".ok-sheet")
    ph.get_by_label("Kategori for butikken").select_option("shopping")
    ph.get_by_role("button", name="Gem", exact=True).click()
    wait_until(ph, lambda: ph.locator(".ok-sheet").count() == 0)
    wait_until(ph, lambda: "Andre indkøb" in ph.locator(".ok-tx-full").inner_text())
    check("a shop moved to another category from a transaction", "Andre indkøb" in ph.locator(".ok-tx-full").inner_text())
    ph.get_by_role("button", name="Butikker", exact=True).click()
    wait_until(ph, lambda: ph.locator(".ok-list .ok-row").count() > 0)
    check("the shops list", "valgt af dig" in ph.locator(".ok-list").inner_text())
    ph.screenshot(path=f"{OUT}/12c-okonomi-shops.png", full_page=True)
    ph.get_by_role("button", name="Udvikling", exact=True).click()
    wait_until(ph, lambda: ph.locator(".ok-trend li").count() > 0)
    check("the months side by side", ph.locator(".ok-trend li").count() == 12, str(ph.locator(".ok-trend li").count()))
    sw = ph.evaluate("document.documentElement.scrollWidth")
    check("the Økonomi tabs fit the phone", sw <= 390, f"scrollWidth {sw}")
    ph.screenshot(path=f"{OUT}/12d-okonomi-trend.png", full_page=True)
    ph.get_by_role("button", name="Overblik", exact=True).click()
    ph.goto(BASE + "/app/#ledger")
    ph.wait_for_selector(".led-tile, .led-empty, .led-ask-box", timeout=15000)
    check("the admin app still has Økonomi", ph.locator(".nav-btn.active").inner_text() == "Økonomi")
    for label, open_ in (("Økonomi", lambda: ph.locator(".subnav-btn", has_text="Overview").click()),
                         ("Settings", lambda: ph.get_by_role("button", name="Settings").click())):
        open_()
        ph.wait_for_timeout(1000)
        sw = ph.evaluate("document.documentElement.scrollWidth")
        check(f"{label} fits a phone", sw <= 390, f"scrollWidth {sw}")
        ph.screenshot(path=f"{OUT}/07-phone-{label.lower()}.png", full_page=True)

    # ---- the administrator sets mor to female and gives her Økonomi (Settings → Accounts) ----
    page.goto(BASE + "/app/#settings")
    page.reload()
    row = page.locator("[data-help='settings.accounts'] .user-list li", has_text="mor")
    row.wait_for(timeout=15000)
    row.locator("select[aria-label='Gender of mor']").select_option("female")
    page.wait_for_selector("text=mor updated.")
    row.locator("select[aria-label='Økonomi for mor']").select_option(label="Økonomi: own data")
    page.wait_for_selector("text=mor now has their own Økonomi.")
    check("Accounts sets gender and Økonomi access",
          row.locator("select[aria-label='Gender of mor']").input_value() == "female")
    page.screenshot(path=f"{OUT}/13-accounts.png", full_page=True)

    # ---- mor: her own Økonomi (0.3.3), and her Cyklus ------------------------------------------
    admin_count = ph.request.get(BASE + "/api/okonomi/state").json()["count"]
    fp.goto(BASE + "/")
    fp.wait_for_selector(".hm-tile")
    wait_until(fp, lambda: fp.locator(".hm-tile-name", has_text="Cyklus").count() == 1)
    tiles = fp.locator(".hm-tile-name").all_inner_texts()
    check("mor's tiles now include Økonomi and Cyklus", tiles == ["Alf’s Atlas", "Dagbog", "Økonomi", "Cyklus"], str(tiles))
    fp.screenshot(path=f"{OUT}/14-home-four-tiles.png")
    fp.locator(".hm-tile", has_text="Økonomi").click()
    fp.wait_for_selector("text=Kom i gang", timeout=15000)
    check("mor starts with her own, empty Økonomi", "Davidsens" not in fp.content() and fp.locator(".ok-foot").count() == 0)
    fp.locator(".ok-import input[aria-label=Konto]").fill("Mors konto")
    fp.locator(".ok-pick input[type=file]").set_input_files(
        files=[{"name": "mor.csv", "mimeType": "text/csv", "buffer": synthetic_export()}])
    fp.wait_for_selector(".ok-hero", timeout=30000)
    check("mor reads in her own bank export on the phone", "kr" in fp.locator(".ok-hero-num").inner_text())
    fp.locator(".ok-data-head").click()
    fp.wait_for_selector(".ok-uncat select, .ok-imports", timeout=15000)
    if fp.locator(".ok-uncat select").count():
        groups = fp.locator(".ok-uncat select").first.evaluate("s => [...s.querySelectorAll('optgroup')].map(g => g.label)")
        check("the category picker is in sections, house first, then car", groups[:2] == ["Hus & bolig", "Bil & transport"], str(groups))
    check("the admin's Økonomi is untouched by hers",
          ph.request.get(BASE + "/api/okonomi/state").json()["count"] == admin_count)
    fp.locator(".ok-ask-row input").fill("Hvor meget hos Davidsens?")
    fp.get_by_role("button", name="Spørg").click()
    wait_until(fp, lambda: fp.locator(".ok-answer .md").count() > 0 and fp.locator(".ok-answer .ok-note").count() > 0)
    check("mor asks Alf about her own Økonomi", "From the ledger:" in fp.locator(".ok-answer").inner_text(),
          fp.locator(".ok-answer").inner_text()[:160])
    check("mor still cannot reach the owner's API", fp.request.get(BASE + "/api/ledger/summary").status == 403
          and fp.request.delete(BASE + "/api/ledger").status == 403)
    fp.screenshot(path=f"{OUT}/15-okonomi-mor.png", full_page=True)

    import datetime as _dt
    today = _dt.date.today()
    fp.goto(BASE + "/#/cyklus")
    fp.wait_for_selector(".cy-hero", timeout=15000)
    check("Cyklus starts empty", "Velkommen" in fp.locator(".cy-big").inner_text())
    # 0.3.1: the strip swipes over weeks; tap the day it started, then "startede denne dag".
    first = today - _dt.timedelta(days=today.weekday()) - _dt.timedelta(days=42)
    days_btn = fp.locator(".cy-strip-scroll .cy-strip-day")
    check("the week strip holds weeks before and after", days_btn.count() == 15 * 7, str(days_btn.count()))
    days_btn.nth((today - _dt.timedelta(days=30) - first).days).click()
    fp.get_by_role("button", name="Menstruationen startede denne dag").click()
    wait_until(fp, lambda: fp.locator(".cy-big").inner_text().startswith("Menstruationsdag"))
    fp.get_by_role("button", name="Tilbage til i dag").click()
    wait_until(fp, lambda: fp.locator(".cy-forecast h3", has_text="i dag").count() == 1
               and fp.locator(".cy-cards").count() == 1)
    check("today is explained with a mood and behaviour forecast",
          fp.locator(".cy-forecast .cy-bars li").count() >= 4 and "Chance for graviditet" in fp.locator(".cy-cards").inner_text())
    fp.get_by_role("button", name="Menstruationen startede i dag").click()
    wait_until(fp, lambda: fp.locator(".cy-big").inner_text() == "Menstruationsdag 1")
    check("a period started today: Menstruationsdag 1", fp.locator(".cy-big").inner_text() == "Menstruationsdag 1",
          fp.locator(".cy-big").inner_text())
    check("the week strip marks today as a period day", fp.locator(".cy-strip .cy-today.cy-period").count() == 1)
    check("her cycles: 30 days measured", "30" in fp.locator(".cy-avgs").inner_text())
    sw = fp.evaluate("document.documentElement.scrollWidth")
    check("Cyklus fits the phone", sw <= 390, f"scrollWidth {sw}")
    pos = fp.evaluate("(() => { const e = document.querySelector('.cy-strip-scroll'); return [e.scrollLeft, e.clientWidth]; })()")
    check("the strip opens on this week", pos[0] == 6 * pos[1], str(pos))
    fp.screenshot(path=f"{OUT}/16a-cyklus-viewport.png")
    fp.screenshot(path=f"{OUT}/16-cyklus.png", full_page=True)
    fp.locator(".cy-actions a", has_text="Log i dag").click()
    fp.wait_for_selector(".cy-chips button")
    fp.locator(".cy-chips button", has_text="Kraftig").click()
    fp.locator(".cy-chips button", has_text="Kramper").click()
    fp.locator(".cy-chips button", has_text="Følsom").click()
    fp.locator(".cy-text").fill("Hemmelig cyklusnote")
    fp.get_by_role("button", name="Gem dagen").click()
    wait_until(fp, lambda: "Gemt" in fp.locator(".cy-save").inner_text())
    check("her day is saved", "Gemt" in fp.locator(".cy-save").inner_text())
    fp.screenshot(path=f"{OUT}/17-cyklus-day.png", full_page=True)
    fp.goto(BASE + "/#/cyklus/kalender")
    fp.wait_for_selector(".cy-cal-grid .cy-period", timeout=10000)
    check("the calendar shows logged, predicted and possible periods",
          fp.locator(".cy-cal-grid .cy-period").count() >= 5 and fp.locator(".cy-cal-grid .cy-predicted").count() >= 1
          and fp.locator(".cy-cal-grid .cy-possible").count() >= 1)
    fp.screenshot(path=f"{OUT}/18-cyklus-calendar.png")
    later = today + _dt.timedelta(days=12)
    fp.locator(f".cy-month[data-month='{later.isoformat()[:7]}'] .cy-cal-day").nth(later.day - 1).click()
    fp.wait_for_selector(".cy-sheet .cy-sheet-title")
    check("a day in the calendar opens its explanation", "Cyklusdag" in fp.locator(".cy-sheet").inner_text(),
          fp.locator(".cy-sheet").inner_text()[:120])
    fp.screenshot(path=f"{OUT}/18b-cyklus-day-sheet.png")
    fp.get_by_role("button", name="Luk").click()
    n_before = fp.locator(".cy-cal-grid .cy-period").count()
    fp.get_by_role("button", name="Rediger menstruationsdatoer").click()
    d29 = today - _dt.timedelta(days=25)                      # one day longer than the 5 logged
    fp.locator(f".cy-month[data-month='{d29.isoformat()[:7]}'] .cy-cal-day").nth(d29.day - 1).click()
    wait_until(fp, lambda: fp.locator(".cy-cal-grid .cy-period").count() == n_before + 1)
    check("editing period dates adds a day with one tap", fp.locator(".cy-cal-grid .cy-period").count() == n_before + 1)
    fp.screenshot(path=f"{OUT}/18c-cyklus-edit.png")
    fp.get_by_role("button", name="Færdig").click()
    fp.get_by_role("tab", name="År").click()
    fp.wait_for_selector(".cy-year-grid")
    check("the year view shows twelve months", fp.locator(".cy-mini").count() == 12)
    sw = fp.evaluate("document.documentElement.scrollWidth")
    check("the calendar fits the phone", sw <= 390, f"scrollWidth {sw}")
    fp.screenshot(path=f"{OUT}/18d-cyklus-year.png", full_page=True)
    # Nobody sees anything before she shares - the admin included.
    check("before sharing the admin sees no cycle",
          ph.request.get(BASE + "/api/cyklus/state").json()["shared"] == [])
    fp.goto(BASE + "/#/cyklus/deling")
    fp.wait_for_selector(".cy-checks")
    fp.locator(".cy-checks label", has_text="admin").locator("input").check()
    fp.wait_for_selector("text=Gemt ✓")
    fp.screenshot(path=f"{OUT}/19-cyklus-share.png", full_page=True)

    ph.goto(BASE + "/")
    ph.wait_for_selector(".hm-tile")
    wait_until(ph, lambda: ph.locator(".hm-tile", has_text="Cyklus").count() == 1)
    check("the admin gets a Cyklus tile once mor shares", "mor: menstruation" in ph.locator(".hm-tile", has_text="Cyklus").inner_text())
    ph.locator(".hm-tile", has_text="Cyklus").click()
    ph.wait_for_selector(".cy-shared")
    shared = ph.locator(".cy-shared").inner_text()
    check("the shared card shows her status only", "Menstruationsdag 1" in shared and "Frugtbare" not in shared
          and "Kramper" not in shared, shared[:200])
    check("the shared card has today's mood and behaviour forecast", ph.locator(".cy-forecast .cy-bars li").count() == 4)
    # 0.3.1: he can swipe ahead and tap a day for its prediction and mood forecast.
    ph.locator(".cy-shared .cy-strip-day").nth(14 + today.weekday() + 5).click()
    ph.wait_for_selector(".cy-shared-day .cy-shared-line")
    wait_until(ph, lambda: "Cyklusdag" in ph.locator(".cy-shared-day").inner_text())
    check("a coming day explained to him, with its mood forecast",
          "Forudsigelse" in ph.locator(".cy-shared-day").inner_text()
          and ph.locator(".cy-shared .cy-forecast .cy-bars li").count() == 4
          and "chance" not in ph.locator(".cy-shared").inner_text(), ph.locator(".cy-shared-day").inner_text()[:120])
    ph.screenshot(path=f"{OUT}/20b-cyklus-shared-day.png", full_page=True)
    check("her note is nowhere on the admin's page", "Hemmelig cyklusnote" not in ph.content())
    check("the admin cannot log a cycle (not set to female)", ph.locator(".cy-hero").count() == 0)
    ph.screenshot(path=f"{OUT}/20-cyklus-shared.png", full_page=True)

    browser.close()

print(f"\n{len(passed)} passed, {len(problems)} problem(s)")
for pr in problems:
    print("  PROBLEM:", pr)
sys.exit(1 if problems else 0)
