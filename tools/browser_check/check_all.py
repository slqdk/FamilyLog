"""Browser check for FamilyLog v0.1 - run with tools/browser_check/run.py.

Through the real UI, against the real backend and the mock Ollama:
first-run setup, Settings (Ollama Test lists the models, roles saved and
kept after a reload), Økonomi (import, categorise by role, Overview,
Transactions, an Ask with Steps and "Counted by the app"), FamilyMap admin
(tabs, a family account, the role shown as default), the family page at
/fm/ (login, list, Spørg Alf with the phone's position), the family lockout,
Alt+click help, and the phone width. Every expectation is checked; a page
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
    expect(page.get_by_role("heading", name="FamilyLog")).to_be_visible()
    check("first run shows setup", page.get_by_role("button", name="Create administrator").is_visible())
    page.fill("input[name=username]", "admin")
    page.fill("input[name=password]", "test-password-1")
    page.fill("input[name=confirm]", "test-password-1")
    page.get_by_role("button", name="Create administrator").click()
    page.wait_for_selector(".topbar")
    check("signed in, app name in the top bar", page.locator(".brand").inner_text() == "FamilyLog")
    check("both sections in the navigation",
          page.locator(".nav-btn").all_inner_texts() == ["Økonomi", "FamilyMap"])

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
    page.get_by_role("button", name="Settings").click()
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
    wait_until(page, lambda: page.locator(".led-counted").count() > 0
               and page.locator(".led-ask-row .primary-btn").count() > 0)
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
    fp.goto(BASE + "/")
    fp.wait_for_url("**/fm/", timeout=10000)
    check("the app sends a family account to /fm/", fp.url.endswith("/fm/"))

    # ---- the app at phone width ----------------------------------------------------------
    ph = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True).new_page()
    watch(ph, "phone app")
    ph.request.post(BASE + "/api/auth/login", data={"username": "admin", "password": "test-password-1"})
    ph.goto(BASE + "/")
    ph.wait_for_selector(".led-tile, .led-empty, .led-ask-box", timeout=15000)
    for label, open_ in (("Økonomi", lambda: ph.locator(".subnav-btn", has_text="Overview").click()),
                         ("Settings", lambda: ph.get_by_role("button", name="Settings").click())):
        open_()
        ph.wait_for_timeout(1000)
        sw = ph.evaluate("document.documentElement.scrollWidth")
        check(f"{label} fits a phone", sw <= 390, f"scrollWidth {sw}")
        ph.screenshot(path=f"{OUT}/07-phone-{label.lower()}.png", full_page=True)

    browser.close()

print(f"\n{len(passed)} passed, {len(problems)} problem(s)")
for pr in problems:
    print("  PROBLEM:", pr)
sys.exit(1 if problems else 0)
