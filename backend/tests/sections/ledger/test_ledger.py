"""Økonomi (2.63.0): bank exports in, exact numbers out.

The case behind it (2026-10-08): a chat model was handed the first 200 rows
of a long bank export and answered with a handful of payments to one shop -
"no other entries in the file" - when there were several times as many.
Here the rows go into SQLite and every number is counted by the app; the
model only reads the question and writes up the result.

No real bank data in here: the export is synthetic, in the same format.
"""
from __future__ import annotations

import importlib.util
import io
import random
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]


# ---- a synthetic export in his bank's format ----------------------------------------

def _kr(ore: int) -> str:
    s = f"{abs(ore) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if ore < 0 else "") + s


def _line(d: date, text: str, ore: int) -> str:
    return f"{d.strftime('%d-%m-%Y')};{text};{_kr(ore)};DKK"


def big_export(n_filler: int = 4000, seed: int = 7) -> tuple[bytes, dict]:
    """~4,000 rows over 2023-2026, newest first like the bank writes it, with
    31 Davidsens direct debits spread over the whole period - most of them
    far below row 200."""
    rnd = random.Random(seed)
    start = date(2023, 1, 2)
    rows: list[tuple[date, str, int]] = []
    shops = ["kontaktløs Dankort Netto Skagen Nota C{n}", "Q8 SERVICE - 8253, VOJENS Notanr {n}",
             "kontaktløs Dankort ABC Lavpris, Byen Nota C{n}", "Visa/Dankort MCDKOLDING, KOLDING, Nota nr. {n}",
             "kontaktløs Dankort Jem & Fix Vojens Nota Z{n}", "Dankort-køb proshop.dk Nota {n}"]
    for i in range(n_filler):
        d = start + timedelta(days=rnd.randrange(0, 1375))
        rows.append((d, rnd.choice(shops).format(n=rnd.randrange(10000, 99999)),
                     -rnd.randrange(2000, 90000)))
    davidsens = []
    for k in range(31):
        d = start + timedelta(days=12 + k * 44)
        ore = -(100_000 + k * 37_731)
        davidsens.append(ore)
        rows.append((d, "Betalingsservice DAVIDSENS TØMMERHANDEL A/S Aftalenr. 001234567", ore))
    for m in range(45):                       # own transfers and salary, monthly
        d = date(2023 + (m // 12), m % 12 + 1, 28)
        rows.append((d, "Budgetkonto", -1_200_000))
        rows.append((d, "OVERFØRSEL", 2_500_000))
    rows.append((date(2026, 7, 17), "Til 1234 0009876543", -9_000_000))
    rows.sort(key=lambda r: r[0], reverse=True)
    body = "\r\n".join(_line(*r) for r in rows) + "\r\n"
    return ("﻿" + body).encode("utf-8"), {"davidsensCount": 31,
                                               "davidsensOre": -sum(davidsens),
                                               "rows": len(rows)}


@pytest.fixture
def mock(monkeypatch):
    """The ledger's model calls, answered by tools/mock_ollama.py's logic."""
    spec = importlib.util.spec_from_file_location("mock_ollama_mod", REPO / "tools" / "mock_ollama.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from app.sections.ledger import ledger_ask
    calls: list[dict] = []

    async def stream_chat(model, messages, **kw):
        calls.append({"model": model, "messages": messages, "kw": kw})
        _think, answer = mod._answer_for(model, messages, kw.get("response_format"))
        for i in range(0, len(answer), 25):
            yield answer[i:i + 25]
    monkeypatch.setattr(ledger_ask.ollama, "stream_chat", stream_chat)
    ledger_ask.reset()
    yield calls
    ledger_ask.reset()


def _wait(client, path, until=("done", "failed", "stopped", "none"), timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        v = client.get(path).json()
        if v["state"] in until:
            return v
        time.sleep(0.05)
    raise AssertionError(f"{path} still {v['state']}")


def _upload(client, data: bytes, name="eksport.csv", account="Lønkonto"):
    r = client.post(f"/api/ledger/import?account={account}",
                    files={"file": (name, io.BytesIO(data), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


# ---- parsing ----------------------------------------------------------------------------

def test_his_banks_format_parses_bom_crlf_and_danish_numbers():
    from app.sections.ledger import ledger
    data = ("﻿08-10-2026;Betalingsservice DAVIDSENS TØMMERHANDEL A/S Aftalenr. 001234567;-1.542,88;DKK\r\n"
            "07-10-2026;Dankort-køb Simply.com Nota 6681496;-119,00;DKK\r\n"
            "30-09-2026;OVERFØRSEL;25.000,00;DKK\r\n").encode("utf-8")
    p = ledger.parse_file("eksport.csv", data)
    assert [r["amount"] for r in p["rows"]] == [-154288, -11900, 2500000]
    assert p["rows"][0]["date"] == "2026-10-08"
    assert p["rows"][0]["text"].startswith("Betalingsservice DAVIDSENS")
    assert p["skipped"] == 0


def test_a_header_picks_the_amount_not_the_balance():
    from app.sections.ledger import ledger
    data = ('"Dato";"Tekst";"Beløb";"Saldo";"Status"\n'
            '"02.10.2026";"Netto Vojens";"-245,50";"10.254,50";"Udført"\n'
            '"01.10.2026";"Løn";"25.000,00";"10.500,00";"Udført"\n').encode("cp1252")
    p = ledger.parse_file("danske.csv", data)
    assert p["columns"]["amount"] == "Beløb"
    assert [(r["date"], r["amount"]) for r in p["rows"]] == [("2026-10-02", -24550),
                                                            ("2026-10-01", 2500000)]


def test_english_numbers_and_iso_dates():
    from app.sections.ledger import ledger
    data = b"Date,Description,Amount,Currency\n2026-09-01,AMAZON,\"-1,542.88\",DKK\n2026-09-02,Refund,12.50,DKK\n"
    p = ledger.parse_file("x.csv", data)
    assert [r["amount"] for r in p["rows"]] == [-154288, 1250]


def test_an_xlsx_export_with_real_dates_and_numbers():
    from datetime import datetime
    from openpyxl import Workbook
    from app.sections.ledger import ledger
    wb = Workbook()
    ws = wb.active
    ws.append(["Dato", "Tekst", "Beløb", "Valuta"])
    ws.append([datetime(2026, 10, 8), "kontaktløs Dankort ABC Lavpris, Byen Nota C100200", -57.92, "DKK"])
    ws.append([datetime(2026, 10, 7), "Pengeautomat 8079 Trans.nr.      1030", -2000, "DKK"])
    buf = io.BytesIO()
    wb.save(buf)
    p = ledger.parse_file("eksport.xlsx", buf.getvalue())
    assert [(r["date"], r["amount"]) for r in p["rows"]] == [("2026-10-08", -5792),
                                                            ("2026-10-07", -200000)]


def test_not_a_bank_export_says_so():
    from app.sections.ledger import ledger
    with pytest.raises(ledger.Invalid, match="No date column"):
        ledger.parse_file("notes.csv", b"hello;world\nfoo;bar\n")
    with pytest.raises(ledger.Invalid):
        ledger.parse_file("picture.png", b"\x89PNG")


# ---- what a row is ----------------------------------------------------------------------

@pytest.mark.parametrize("text,amount,kind,merchant,category", [
    ("kontaktløs Dankort ABC Lavpris, Byen Nota C100200", -5792, "card", "ABC Lavpris", "groceries"),
    ("Betalingsservice DAVIDSENS TØMMERHANDEL A/S Aftalenr. 001234567", -154288, "betalingsservice",
     "Davidsens Tømmerhandel", "home"),
    ("Visa/Dankort MCDKOLDING, KOLDING, Nota nr. 45938", -8900, "card", "McDonald's", "fast-food"),
    ("Visa/Dankort MCD VEJLE DTC, VEJLE, Nota nr. 01389", -8900, "card", "McDonald's", "fast-food"),
    ("Q8 SERVICE - 8253, VOJENS Notanr 95659", -4400, "card", "Q8", "fuel"),
    ("Visa/Dankort PAYPAL *STEAM GAMES, 35314369001, Nota nr. 19425", -20919, "card", "Steam", "leisure"),
    ("Pengeautomat 8079 Trans.nr.      1030", -200000, "atm", "Cash withdrawal", "cash"),
    ("MobilePay: MobilePay Mette Hansen", -15000, "mobilepay", "Mette Hansen", "people"),
    ("Opsparing", -250000, "transfer", "Opsparing", "transfers"),
    ("Til 1234 0009876543", -9000000, "transfer", "Til 1234 0009876543", "transfers"),
    ("Rente af overtræk", -1234, "interest", "Rente af overtræk", "fees"),
    ("Forbrug på MasterCard 0009988776", -2225640, "card-bill", "Forbrug på MasterCard", "card-bill"),
    ("Visa/Dankort GOOGLE*YOUTUBEPREMIUM, INTERNET, Nota nr. 00052", -29900, "card",
     "YouTube Premium", "streaming"),
])
def test_rows_get_a_kind_a_merchant_and_a_rule(text, amount, kind, merchant, category):
    from app.sections.ledger import ledger
    c = ledger.classify(text, amount)
    assert (c["kind"], c["merchant"], (c["rule"] or ("", None))[1]) == (kind, merchant, category)


def test_a_foreign_purchase_keeps_its_own_amount():
    from app.sections.ledger import ledger
    c = ledger.classify("Visa/Dankort EUR 63,50 Kurs 755,14 Nota nr. 48138 Boskos Damacija, Harrislee", -47952)
    assert (c["foreignCurrency"], c["foreignAmount"]) == ("EUR", 63.5)
    assert c["merchant"] == "Boskos Damacija"


def test_an_unknown_shop_has_no_rule_and_salary_and_savings_stay_apart():
    from app.sections.ledger import ledger
    assert ledger.classify("kontaktløs Dankort Hylkedal Vest ApS Nota 895597", -5000)["rule"] is None
    salary = ledger.classify("OVERFØRSEL", 2500000)
    savings = ledger.classify("Overførsel", 1000000)
    assert ledger.merchant_key(salary["merchant"], salary["kind"]) != \
        ledger.merchant_key(savings["merchant"], savings["kind"])
    # Shops do group case-blind.
    assert ledger.merchant_key("NETTO", "card") == ledger.merchant_key("Netto", "card")


# ---- merging ------------------------------------------------------------------------------

def test_a_re_upload_adds_nothing_and_an_overlap_adds_only_the_new_rows(fresh_db):
    from app.sections.ledger import ledger
    a = [{"date": "2026-10-01", "text": "Netto", "amount": -1000, "currency": "DKK"},
         {"date": "2026-10-02", "text": "Q8", "amount": -500, "currency": "DKK"}]
    b = a + [{"date": "2026-10-03", "text": "Rema", "amount": -700, "currency": "DKK"}]
    assert ledger.import_rows(1, "Lønkonto", "a.csv", a)["added"] == 2
    again = ledger.import_rows(1, "Lønkonto", "a.csv", a)
    assert (again["added"], again["alreadyThere"]) == (0, 2)
    assert ledger.import_rows(1, "Lønkonto", "b.csv", b)["added"] == 1
    assert ledger.summary(1)["count"] == 3


def test_two_identical_purchases_on_one_day_both_stay(fresh_db):
    """Two coffees are two coffees. His export has six such pairs; a plain
    'skip if seen' would have thrown one of each away."""
    from app.sections.ledger import ledger
    coffee = {"date": "2026-10-05", "text": "Q8 SERVICE - 8253, VOJENS Notanr 1", "amount": -2500,
              "currency": "DKK"}
    # The morning export saw one; the evening export sees both.
    assert ledger.import_rows(1, "L", "am.csv", [coffee])["added"] == 1
    assert ledger.import_rows(1, "L", "pm.csv", [coffee, dict(coffee)])["added"] == 1
    assert ledger.transactions(1)["total"] == 2
    # Another account is another ledger line.
    assert ledger.import_rows(1, "MasterCard", "mc.csv", [coffee])["added"] == 1


# ---- counting ------------------------------------------------------------------------------

@pytest.fixture
def big(fresh_db):
    from app.sections.ledger import ledger
    data, facts = big_export()
    p = ledger.parse_file("eksport.csv", data)
    ledger.import_rows(1, "Lønkonto", "eksport.csv", p["rows"])
    return facts


def test_every_davidsens_payment_is_counted_not_just_the_first_200_rows(big):
    from app.sections.ledger import ledger
    spec = ledger.clean_spec({"merchants": ["davidsens"], "measure": "sum"})
    res = ledger.run_spec(1, spec)
    assert res["count"] == big["davidsensCount"] == 31
    assert round(res["total"] * 100) == big["davidsensOre"]          # exact, to the øre
    # And only Betalingsservice ones, when asked that way.
    res2 = ledger.run_spec(1, ledger.clean_spec({"merchants": ["davidsens"],
                                                 "kinds": ["betalingsservice"]}))
    assert res2["count"] == 31


def test_own_transfers_are_left_out_unless_asked_for(big):
    from app.sections.ledger import ledger
    top = ledger.run_spec(1, ledger.clean_spec({"measure": "list", "order": "largest", "top": 3}))
    assert all(r["category"] != "transfers" for r in top["rows"])
    assert top["rows"][0]["merchant"] == "Davidsens Tømmerhandel"
    assert top["excludedTransfers"]["count"] == 46                      # 45 Budgetkonto + Til 1234
    with_tr = ledger.run_spec(1, ledger.clean_spec({"measure": "list", "top": 1,
                                                    "includeTransfers": True}))
    assert with_tr["rows"][0]["text"] == "Til 1234 0009876543"
    assert with_tr["excludedTransfers"] is None


def test_groups_periods_and_a_miss(big):
    from app.sections.ledger import ledger
    per_month = ledger.run_spec(1, ledger.clean_spec({"merchants": ["davidsens"], "group": "month",
                                                      "from": "2025-01-01", "to": "2025-12-31"}))
    assert per_month["groups"] and all(g["group"].startswith("2025-") for g in per_month["groups"])
    assert sum(g["count"] for g in per_month["groups"]) == per_month["count"]
    miss = ledger.run_spec(1, ledger.clean_spec({"merchants": ["davidson"]}))
    assert miss["count"] == 0 and "Davidsens Tømmerhandel" in miss["notes"][0]


def test_the_models_search_is_cleaned_before_it_is_used():
    from app.sections.ledger import ledger
    s = ledger.clean_spec({"merchants": "netto", "categories": ["groceries", "DROP TABLE"],
                           "kinds": ["card", "bitcoin"], "from": "2025-12-31", "to": "2025-01-01",
                           "group": "hour", "measure": "median", "top": 5000, "direction": "sideways"})
    assert s["merchants"] == ["netto"] and s["categories"] == ["groceries"] and s["kinds"] == ["card"]
    assert (s["from"], s["to"]) == ("2025-01-01", "2025-12-31")
    assert (s["group"], s["measure"], s["top"], s["direction"]) == ("none", "sum", 100, "out")
    assert ledger.clean_spec({"categories": ["income"]})["direction"] == "in"


def test_overview_months_categories_and_recurring(big):
    from app.sections.ledger import ledger
    ov = ledger.overview(1)
    assert ov["count"] == big["rows"]
    assert ov["transfersOut"] == pytest.approx(45 * 12000 + 90000)
    assert ov["months"][0]["month"] == "2023-01"
    cats = {c["key"]: c for c in ov["categories"]}
    assert cats["home"]["spent"] > 0 and "transfers" not in cats
    names = [m["name"] for m in ov["topMerchants"]]
    assert "Davidsens Tømmerhandel" in names
    # Spending is the sum of the categories, øre for øre.
    assert round(sum(c["spent"] for c in ov["categories"]), 2) == round(ov["spent"], 2)


def test_recurring_finds_a_monthly_direct_debit(fresh_db):
    from app.sections.ledger import ledger
    rows = [{"date": f"2026-{m:02d}-08", "text": "Betalingsservice TELMORE A/S Aftalenr. 1",
             "amount": -9900, "currency": "DKK"} for m in range(3, 11)]
    rows += [{"date": f"2026-{m:02d}-10", "text": "kontaktløs Dankort Netto Nota C1",
              "amount": -30000, "currency": "DKK"} for m in range(3, 11)]
    ledger.import_rows(1, "L", "x.csv", rows)
    rec = ledger.recurring(1)
    assert [r["name"] for r in rec] == ["Telmore"]          # groceries come back too, but are not bills
    assert rec[0]["typical"] == 99.0 and rec[0]["yearly"] == 1188.0


def test_the_persons_category_is_never_overwritten_by_the_model(fresh_db):
    from app.sections.ledger import ledger
    ledger.import_rows(1, "L", "x.csv", [{"date": "2026-10-01", "text": "kontaktløs Dankort Hylkedal Vest Nota 1",
                                          "amount": -5000, "currency": "DKK"}])
    key = ledger.uncategorised(1)[0]["key"]
    assert ledger.set_category(1, key, "leisure", source="user")
    assert not ledger.set_category(1, key, "groceries", source="model")
    assert ledger.merchants(1)[0]["category"] == "leisure"
    with pytest.raises(ledger.Invalid):
        ledger.set_category(1, key, "nonsense")


# ---- the API --------------------------------------------------------------------------------

def test_import_overview_transactions_and_merchants_over_http(client, mock):
    data, facts = big_export(n_filler=400)
    out = _upload(client, data)
    assert out["added"] == facts["rows"] and out["account"] == "Lønkonto"
    assert _upload(client, data)["added"] == 0
    s = client.get("/api/ledger/summary").json()
    assert s["count"] == facts["rows"] and s["imports"][0]["filename"] == "eksport.csv"
    ov = client.get("/api/ledger/overview?frm=2025-01-01&to=2025-12-31").json()
    assert ov["firstDate"] >= "2025-01-01" and ov["lastDate"] <= "2025-12-31"
    tx = client.get("/api/ledger/transactions?q=davidsens&order=largest&limit=5").json()
    assert tx["total"] == 31 and len(tx["rows"]) == 5
    assert tx["rows"][0]["amount"] <= tx["rows"][-1]["amount"]
    m = client.get("/api/ledger/merchants?q=Budgetkonto").json()[0]
    r = client.put("/api/ledger/merchants", json={"key": m["key"], "category": "utilities"})
    assert r.status_code == 200
    assert client.get("/api/ledger/overview").json()["transfersOut"] == pytest.approx(90000)
    assert client.put("/api/ledger/merchants", json={"key": m["key"], "category": "x"}).status_code == 400
    assert client.delete(f"/api/ledger/imports/{out['importId']}").json()["removed"] == facts["rows"]
    assert client.delete("/api/ledger").json() == {"cleared": True}
    assert client.get("/api/ledger/summary").json()["count"] == 0


def test_one_persons_ledger_is_invisible_to_another(client, mock):
    from fastapi.testclient import TestClient
    from app.core import auth
    from app.main import app
    _upload(client, big_export(n_filler=50)[0])
    auth.create_user("sanne", "pw-sanne-12345", "user")
    uc = TestClient(app)
    assert uc.post("/api/auth/login", json={"username": "sanne", "password": "pw-sanne-12345"}).status_code == 200
    assert uc.get("/api/ledger/summary").json()["count"] == 0
    assert uc.get("/api/ledger/transactions?q=davidsens").json()["total"] == 0
    assert uc.get("/api/ledger/ask").json() == {"state": "none"}


def test_a_family_account_cannot_reach_it(client):
    from fastapi.testclient import TestClient
    from app.core import auth
    from app.main import app
    auth.create_user("barn", "pw-barn-1234567", "family")
    fc = TestClient(app)
    assert fc.post("/api/auth/login", json={"username": "barn", "password": "pw-barn-1234567"}).status_code == 200
    assert fc.get("/api/ledger/summary").status_code == 403


# ---- asking ----------------------------------------------------------------------------------

def test_an_ask_answers_with_the_apps_exact_numbers(client, mock):
    client.put("/api/ledger/settings", json={"model": "qwen3.6:27b"})
    _upload(client, big_export()[0])
    _wait(client, "/api/ledger/categorise")
    r = client.post("/api/ledger/ask", json={"question": "How much did I spend at Davidsens?"})
    assert r.status_code == 200, r.text
    v = _wait(client, "/api/ledger/ask")
    assert v["state"] == "done", v
    assert v["result"]["count"] == 31
    total = v["result"]["total"]
    from app.sections.ledger import ledger
    assert ledger.kr(total) in v["text"]                     # the model was handed the exact total
    assert "31 transactions" in v["text"]
    assert v["counted"].startswith("money out, matching \"davidsens\"")
    labels = [s["label"] for s in v["steps"]["steps"]]
    assert labels[:3] == ["Understand the question", "Count in the ledger (SQL)", "Answer"]
    # The model's search went out as JSON, without thinking; nothing it
    # returned was run as SQL.
    understand = [c for c in mock if c["kw"].get("response_format") == "json"]
    assert understand and all(c["kw"].get("think") is False for c in understand)


def test_a_follow_up_keeps_the_previous_search(client, mock):
    client.put("/api/ledger/settings", json={"model": "qwen3.6:27b"})
    _upload(client, big_export()[0])
    _wait(client, "/api/ledger/categorise")
    client.post("/api/ledger/ask", json={"question": "How much at Davidsens?"})
    first = _wait(client, "/api/ledger/ask")
    client.post("/api/ledger/ask", json={"question": "and in 2025, per month?"})
    v = _wait(client, "/api/ledger/ask")
    assert v["previous"] == "How much at Davidsens?"
    assert v["spec"]["merchants"] == ["davidsens"]
    assert (v["spec"]["from"], v["spec"]["group"]) == ("2025-01-01", "month")
    assert 0 < v["result"]["count"] < first["result"]["count"]
    md = client.get("/api/ledger/ask/export")
    assert md.status_code == 200 and md.text.startswith("# and in 2025, per month?")
    assert "## Result (computed by the app)" in md.text and "*Steps:" in md.text


def test_asking_needs_data_and_a_model_and_one_question_at_a_time(client, mock, monkeypatch):
    assert client.post("/api/ledger/ask", json={"question": "hi"}).status_code == 400   # no data
    client.put("/api/ledger/settings", json={"model": "qwen3.6:27b"})
    _upload(client, big_export(n_filler=20)[0])
    import asyncio
    from app.sections.ledger import ledger_ask

    async def slow(model, messages, **kw):
        await asyncio.sleep(30)
        yield "{}"
    monkeypatch.setattr(ledger_ask.ollama, "stream_chat", slow)
    ledger_ask.stop_categorise(1)
    assert client.post("/api/ledger/ask", json={"question": "how much at netto"}).status_code == 200
    assert client.post("/api/ledger/ask", json={"question": "again"}).status_code == 409
    v = client.post("/api/ledger/ask/stop").json()
    v = _wait(client, "/api/ledger/ask")
    assert v["state"] == "stopped"


def test_unknown_merchants_are_categorised_in_batches_after_import(client, mock):
    from app.sections.ledger import ledger, ledger_ask
    client.put("/api/ledger/settings", json={"model": "qwen3.6:27b"})
    # Names that match no built-in rule, so all 58 go to the model.
    rows = [f"0{1 + i % 9}-09-2026;kontaktløs Dankort Zxq Shop {i} Nota C{i};-10,00;DKK"
            for i in range(57)]
    rows += ["03-10-2026;kontaktløs Dankort Bogus Place Nota 1;-5,00;DKK"]
    out = _upload(client, ("\n".join(rows) + "\n").encode())
    assert out["newUncategorised"] == 58 and out["categorise"]["state"] in ("queued", "working")
    v = _wait(client, "/api/ledger/categorise")
    assert v["state"] == "done" and v["batches"] == 2           # 58 merchants, 40 per batch
    assert v["placed"] == 57 and v["left"] == 1                 # the invented key is refused
    cats = {m["name"]: m["category"] for m in ledger.merchants(1)}
    assert cats["Zxq Shop 0"] == "other"
    assert cats["Bogus Place"] == ""                            # nonsense-key ignored
    assert all(c["kw"].get("response_format") == "json" for c in mock)
    assert ledger_ask.cat_view(1)["left"] == 1


# ---- 2.63.1: what counts as spending, the month view, top N ---------------------------------

def test_money_in_that_is_not_a_refund_does_not_lower_spending(fresh_db):
    """2.63.0 netted every plus in a counted category against spending:
    'Advis' and money from people, categorised Other, made Other -174.199 kr
    and -144%, and a month with a big plus lost its bar."""
    from app.sections.ledger import ledger
    rows = [
        {"date": "2026-09-01", "text": "Dankort-køb IKEA Nota C1", "amount": -100_00, "currency": "DKK"},
        {"date": "2026-09-05", "text": "kontaktløs Dankort IKEA 123 Return Nota Z1", "amount": 30_00, "currency": "DKK"},
        {"date": "2026-09-06", "text": "Fra Hans Hansen", "amount": 500_00, "currency": "DKK"},
        {"date": "2026-09-07", "text": "Advis 100000000000001", "amount": 900_00, "currency": "DKK"},
        {"date": "2026-09-08", "text": "MobilePay: MobilePay Mette Hansen", "amount": 200_00, "currency": "DKK"},
        {"date": "2026-09-09", "text": "kontaktløs Dankort Netto Nota C2", "amount": -50_00, "currency": "DKK"},
    ]
    ledger.import_rows(1, "L", "x.csv", rows)
    for m in ledger.uncategorised(1):
        ledger.set_category(1, m["key"], "other")
    ov = ledger.overview(1)
    assert ov["spent"] == 120.0                         # 100 - 30 refund + 50
    assert ov["otherIn"] == 1600.0
    assert all(c["spent"] >= 0 for c in ov["categories"])
    assert {c["key"]: c["spent"] for c in ov["categories"]} == {"home": 70.0, "groceries": 50.0}
    assert [m["spent"] for m in ov["months"]] == [120.0]
    # The ask counts the same way: IKEA net of its return.
    ikea = ledger.run_spec(1, ledger.clean_spec({"merchants": ["ikea"]}))
    assert (ikea["count"], ikea["total"], ikea["largest"]) == (2, 70.0, 100.0)
    assert ikea["rows"][0]["amount"] == -100.0          # the purchase first, the return last
    everything = ledger.run_spec(1, ledger.clean_spec({}))
    assert everything["total"] == 120.0


def test_the_month_view_has_days_and_an_average_month_to_compare_with(fresh_db):
    from app.sections.ledger import ledger
    rows = []
    for m in range(1, 10):                              # Jan-Sep 2026, Netto 1.000 kr each month
        rows.append({"date": f"2026-{m:02d}-10", "text": "kontaktløs Dankort Netto Nota C1",
                     "amount": -1000_00, "currency": "DKK"})
    rows.append({"date": "2026-09-20", "text": "Dankort-køb proshop.dk Nota 9", "amount": -2500_00,
                 "currency": "DKK"})
    ledger.import_rows(1, "L", "x.csv", rows)
    ov = ledger.overview(1, "2026-09-01", "2026-09-30", baseline=12)
    assert len(ov["days"]) == 30 and ov["days"][9] == {"date": "2026-09-10", "spent": 1000.0}
    assert round(sum(d["spent"] for d in ov["days"]), 2) == ov["spent"] == 3500.0
    b = ov["baseline"]
    assert (b["from"], b["to"], b["months"]) == ("2026-01", "2026-08", 8)   # the data starts in January
    assert b["perMonth"] == 1000.0 and b["categories"] == {"groceries": 1000.0}
    # A long period has no days; no baseline unless asked.
    year = ledger.overview(1, "2026-01-01", "2026-12-31")
    assert year["days"] is None and year["baseline"] is None


def test_top_merchants_returns_as_many_as_asked(fresh_db):
    from app.sections.ledger import ledger
    rows = [{"date": "2026-09-01", "text": f"kontaktløs Dankort Shop Number {i} Nota C{i}",
             "amount": -(i + 1) * 100, "currency": "DKK"} for i in range(80)]
    ledger.import_rows(1, "L", "x.csv", rows)
    assert len(ledger.overview(1)["topMerchants"]) == 50
    assert len(ledger.overview(1, top=100)["topMerchants"]) == 80
    assert ledger.overview(1, top=10)["topMerchants"][0]["name"] == "Shop Number 79"


def test_overview_endpoint_takes_top_and_baseline(client, mock):
    _upload(client, big_export(n_filler=300)[0])
    ov = client.get("/api/ledger/overview?frm=2026-03-01&to=2026-03-31&top=5&baseline=12").json()
    assert len(ov["topMerchants"]) <= 5 and len(ov["days"]) == 31
    assert ov["baseline"]["months"] == 12


# ---- 2.63.2: the finer category set ----------------------------------------------------------

def test_the_new_categories_split_the_old_ones(fresh_db):
    from app.sections.ledger import ledger
    cases = {
        "Visa/Dankort MCDKOLDING, KOLDING, Nota nr. 1": "fast-food",
        "kontaktløs Dankort Restaurant Hinkelstein Nota C1": "restaurant",
        "kontaktløs Dankort Fleggaard Harislee Nota C1": "germany-shopping",
        "Visa/Dankort PAYPAL *ALIEXPRESS, 1, Nota nr. 1": "china-shopping",
        "Dankort-køb Netflix Nota 1": "streaming",
        "Visa/Dankort TV2 DK* ID 1, ODENSE C Nota nr. 1": "tv",
        "Dankort-køb ANTHROPIC, ANTHROPIC.COM Nota 1": "ai",
        "kontaktløs Dankort Tandlægeselskabet Nota Z1": "dental",
        "kontaktløs Dankort Fysioterapien Nota C1": "physio",
        "kontaktløs Dankort Klip & Krøl Frisør Nota C1": "personal-care",
        "Betalingsservice 3F FAGFORENING Aftalenr. 1": "union",
        "Betalingsservice Realkredit Danmark Aftalenr. 1": "mortgage",
        "Betalingsservice husleje Boligforening Aftalenr. 1": "rent",
        "Betalingsservice Norlys Energi Aftalenr. 1": "utilities",
    }
    for text, cat in cases.items():
        rule = ledger.classify(text, -10000)["rule"]
        assert rule is not None and rule[1] == cat, (text, rule)
    # Every category key the rules point at is a real category.
    for _pat, _name, cat in ledger.RULES:
        assert cat in ledger.CATEGORIES, cat


def test_migration_moves_existing_merchants_to_the_finer_categories(fresh_db):
    """A ledger filled before 2.63.2 (McDonald's under eating-out, a dentist
    under health) is re-sorted by migration 050 - but a category the person
    set by hand is left alone."""
    from app.core import db
    from app.sections.ledger import ledger
    with db.connect() as con:
        con.execute("INSERT INTO ledger_merchants (user_id, merchant_key, name, category, source,"
                    " sample, updated_at) VALUES"
                    " (1,'mcd','McDon''s','eating-out','model','Visa/Dankort MCDKOLDING Nota 1','x'),"
                    " (1,'rent','Some Café','eating-out','model','kontaktløs Dankort Café Nota 1','x'),"
                    " (1,'dent','Tandlægen','health','model','Tandlægen Nota 1','x'),"
                    " (1,'rk','Totalkredit','housing','model','Betalingsservice Totalkredit Nota 1','x'),"
                    " (1,'mine','My Thing','eating-out','user','Visa/Dankort MCD Nota 1','x')")
    with db.connect() as con:
        moved = ledger.reapply_rules(con)
    with db.connect() as con:
        got = {r["merchant_key"]: (r["category"], r["source"]) for r in
               con.execute("SELECT merchant_key, category, source FROM ledger_merchants")}
    assert got["mcd"] == ("fast-food", "rule")
    assert got["rent"] == ("restaurant", "rule")          # café matched the restaurant rule
    assert got["dent"] == ("dental", "rule")
    assert got["rk"] == ("mortgage", "rule")
    assert got["mine"] == ("eating-out", "user")          # user choice untouched
    assert moved >= 4


# ---- 0.3.4: the car split, the fuel station's shop, children ----------------------------

def test_every_category_has_one_place_in_the_picker():
    from app.sections.ledger import ledger
    keys = [k for _, ks in ledger.CATEGORY_GROUPS for k in ks]
    assert sorted(keys) == sorted(ledger.CATEGORIES) and len(keys) == len(set(keys)) == 40
    assert ledger.CATEGORY_GROUPS[0][0] == "Hus & bolig" and ledger.CATEGORY_GROUPS[1][0] == "Bil & transport"
    assert "car" not in ledger.CATEGORIES


@pytest.mark.parametrize("text, category", [
    ("Betalingsservice MOTORSTYRELSEN Vægtafgift", "car-tax"),
    ("Visa/Dankort THANSEN VOJENS Nota 1", "car-maintenance"),
    ("kontaktløs Dankort Clever Ladestander Nota 2", "fuel"),
    ("Betalingsservice VOJENS KOMMUNE PLADSANVISNING", "children"),
    ("kontaktløs Dankort BabySam Kolding Nota 3", "children"),
])
def test_the_new_rules(text, category):
    from app.sections.ledger import ledger
    c = ledger.classify(text, -50000)
    rule = ledger.rule_for(c["merchant"], text)
    assert rule is not None and rule[1] == category, (c, rule)


def test_a_small_purchase_at_a_fuel_station_is_the_station_shop(fresh_db):
    from app.sections.ledger import ledger
    rows = [{"date": "2026-09-01", "text": "Q8 SERVICE - 8253, VOJENS Notanr 1", "amount": -55000, "currency": "DKK"},
            {"date": "2026-09-02", "text": "Q8 SERVICE - 8253, VOJENS Notanr 2", "amount": -4500, "currency": "DKK"}]
    ledger.import_rows(1, "Løn", "a.csv", rows)
    o = ledger.overview(1, "2026-09-01", "2026-09-30")
    cats = {c["key"]: c["spent"] for c in o["categories"]}
    assert cats == {"fuel": 550.0, "gas-station": 45.0}
    t = ledger.transactions(1, category="gas-station")
    assert t["total"] == 1 and t["rows"][0]["category"] == "gas-station"
    assert ledger.transactions(1, category="fuel")["rows"][0]["amount"] == -550.0


def test_migration_4_moves_the_old_car_category(fresh_db):
    from app.core import db
    from app.sections.ledger import _m004_car_split
    with db.connect() as con:
        for key, name, sample, src in (("q8", "Q8", "Q8 SERVICE VOJENS", "rule"),
                                       ("bilmand", "Bilmanden", "BILMANDEN APS", "model"),
                                       ("lars", "Lars' garage", "LARS GARAGE", "user")):
            con.execute("INSERT INTO ledger_merchants (user_id, merchant_key, name, category, source, sample,"
                        " updated_at) VALUES (1, ?, ?, 'car', ?, ?, 'x')", (key, name, src, sample))
        _m004_car_split(con)
        got = {r[0]: (r[1], r[2]) for r in con.execute(
            "SELECT merchant_key, category, source FROM ledger_merchants")}
    assert got["q8"] == ("fuel", "rule")
    assert got["bilmand"] == ("", "none") and got["lars"] == ("", "none")       # back to "Mangler kategori"
