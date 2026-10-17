"""Cyklus (0.3.0): the calendar arithmetic, the log, and - above all - that
nobody sees her cycle unless she shares it, and then only what she ticked."""
from __future__ import annotations

from datetime import date, timedelta

from app.sections.cyklus import predict
from app.sections.cyklus.predict import Period

D = date(2026, 10, 17)


def _d(n: int) -> date:
    return D + timedelta(days=n)


# ---- arithmetic -------------------------------------------------------------------------------------

def test_averages_come_from_her_log_then_her_setting_then_28():
    assert predict.averages([])["cycle"] == 28 and predict.averages([])["period"] == 5
    assert predict.averages([], cycle_setting=31, period_setting=4)["cycle"] == 31
    ps = [Period(_d(-90), _d(-86)), Period(_d(-60), _d(-56)), Period(_d(-30), _d(-26))]
    a = predict.averages(ps, cycle_setting=26)
    assert (a["cycle"], a["period"], a["cyclesMeasured"]) == (30, 5, 2)    # measured beats setting
    # A gap of 120 days is a missing log, not a cycle.
    gap = [Period(_d(-200)), Period(_d(-80)), Period(_d(-52)), Period(_d(-24))]
    assert predict.lengths(gap) == [28, 28]


def test_phases_of_a_28_day_cycle():
    ph = [predict.phase_of(cd, 28, 5) for cd in range(1, 31)]
    assert ph[:5] == ["menstruation"] * 5
    assert predict.ovulation_day(28, 5) == 15 and ph[14] == "ovulation"
    assert ph[9:14] == ["fertile"] * 5 and ph[15] == "fertile"
    assert ph[16] == "luteal" and ph[23] == "pms" and ph[27] == "pms"
    assert ph[28] == "pms"                                  # late counts as PMS


def test_status_today_next_period_and_fertile_window():
    ps = [Period(_d(-47), _d(-43)), Period(_d(-19), _d(-15))]     # 28-day cycle, day 20 today
    st = predict.status(ps, D)
    assert st["cycleDay"] == 20 and st["phase"] == "luteal" and not st["inPeriod"]
    assert st["nextStart"] == _d(9).isoformat() and st["daysUntilNext"] == 9
    # This cycle's window is behind her: the next one is shown.
    assert st["ovulation"] == (_d(9) + timedelta(days=14)).isoformat()
    # In the period: period day 2 of an un-ended period.
    st = predict.status([Period(_d(-29), _d(-25)), Period(_d(-1))], D)
    assert st["inPeriod"] and st["periodDay"] == 2 and st["phase"] == "menstruation"
    assert st["lastOpen"] is True


def test_a_late_period_and_a_long_one():
    st = predict.status([Period(_d(-58), _d(-54)), Period(_d(-30), _d(-26))], D)
    assert st["late"] == 2 and st["nextStart"] == _d(1).isoformat() and st["phase"] == "pms"
    # Flow logged on day 7 keeps an un-ended period going past her usual 5.
    ps = [Period(_d(-34), _d(-30)), Period(_d(-6))]
    assert not predict.status(ps, D)["inPeriod"]
    assert predict.status(ps, D, flow_days={D})["inPeriod"]


def test_calendar_marks_logged_and_predicted_days():
    ps = [Period(_d(-47), _d(-43)), Period(_d(-19), _d(-15))]
    k = predict.day_kinds(ps, _d(-20), _d(40), D)
    assert k[_d(-19)] == "period" and k[_d(-15)] == "period" and k[_d(-14)] == ""
    assert k[_d(9)] == "predicted" and k[_d(13)] == "predicted"
    # 0.3.1: around a coming period, the days it may run early or late (two
    # either side until three cycles are measured).
    assert [k[_d(i)] for i in (6, 7, 8, 14, 15, 16)] == ["pms", "possible", "possible", "possible", "possible", ""]
    assert k[_d(9 + 14)] == "ovulation" and k[_d(9 + 9)] == "fertile"
    assert k[_d(5)] == "pms"
    # A period that started yesterday: the coming days of it are expected...
    k = predict.day_kinds([Period(_d(-29), _d(-25)), Period(_d(-1))], _d(-1), _d(5), D)
    assert [k[_d(i)] for i in range(-1, 5)] == ["period", "period", "predicted", "predicted", "predicted", ""]
    # ...but not once she has ended it.
    k = predict.day_kinds([Period(_d(-29), _d(-25)), Period(_d(-1), D)], D, _d(3), D)
    assert k[_d(1)] == ""


# ---- the API ------------------------------------------------------------------------------------

def _login(client, name, pw, role="family", gender=""):
    from fastapi.testclient import TestClient
    from app.main import app
    r = client.post("/api/users", json={"username": name, "password": pw, "role": role,
                                        "gender": gender})
    assert r.status_code == 200, r.text
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": name, "password": pw}).status_code == 200
    return c, r.json()["id"]


def test_only_accounts_set_to_female_log(client):
    s = client.get("/api/cyklus/state").json()
    assert s["enabled"] is False and s["shared"] == [] and "own" not in s
    assert client.post("/api/cyklus/period/start", json={"day": D.isoformat()}).status_code == 403
    mor, _ = _login(client, "mor", "familie-kode-1", gender="female")
    s = mor.get("/api/cyklus/state").json()
    assert s["enabled"] and s["own"]["status"]["empty"] is True
    assert "Kramper" in s["options"]["symptoms"] and "ikke prævention" in s["options"]["disclaimer"]


def test_logging_a_period_and_a_day(client):
    mor, _ = _login(client, "mor", "familie-kode-1", gender="female")
    today = date.today()
    start = (today - timedelta(days=30)).isoformat()
    r = mor.post("/api/cyklus/period/start", json={"day": start})
    assert r.status_code == 200, r.text
    assert mor.post("/api/cyklus/period/start", json={"day": start}).status_code == 400
    assert mor.post("/api/cyklus/period/end",
                    json={"day": (today - timedelta(days=26)).isoformat()}).status_code == 200
    r = mor.post("/api/cyklus/period/start", json={"day": (today - timedelta(days=2)).isoformat()})
    own = r.json()
    assert own["status"]["inPeriod"] and own["status"]["periodDay"] == 3
    assert [p["cycleLength"] for p in own["periods"]] == [None, 28]
    assert mor.post("/api/cyklus/period/start",
                    json={"day": (today + timedelta(days=1)).isoformat()}).status_code == 400
    r = mor.put("/api/cyklus/day", json={"day": today.isoformat(), "flow": "kraftig",
                                         "symptoms": ["kramper", "Træt"], "moods": ["Følsom"],
                                         "note": "Kun min"})
    assert r.status_code == 200, r.text
    assert r.json()["today"]["symptoms"] == ["Kramper", "Træt"]
    assert mor.put("/api/cyklus/day", json={"day": today.isoformat(), "flow": "voldsom"}).status_code == 400
    assert mor.put("/api/cyklus/day", json={"day": today.isoformat(), "symptoms": ["Rumsyge"]}).status_code == 400
    cal = mor.get(f"/api/cyklus/calendar?frm={(today - timedelta(days=31)).isoformat()}"
                  f"&to={(today + timedelta(days=40)).isoformat()}").json()["days"]
    kinds = {d["day"]: d for d in cal}
    assert kinds[today.isoformat()]["kind"] == "period" and kinds[today.isoformat()]["logged"]
    assert any(d["kind"] == "predicted" for d in cal)
    pid = own["periods"][0]["id"]
    assert mor.delete(f"/api/cyklus/period/{pid}").status_code == 200
    assert mor.delete(f"/api/cyklus/period/{pid}").status_code == 404


def test_nobody_sees_her_cycle_until_she_shares_and_then_only_what_she_ticked(client):
    mor, mor_id = _login(client, "mor", "familie-kode-1", gender="female")
    far, far_id = _login(client, "far", "pw-far-12345678", role="user", gender="male")
    barn, _ = _login(client, "barn", "familie-kode-2", gender="male")
    today = date.today()
    for back in (58, 30):
        mor.post("/api/cyklus/period/start", json={"day": (today - timedelta(days=back)).isoformat()})
    mor.put("/api/cyklus/day", json={"day": today.isoformat(), "symptoms": ["Hovedpine"],
                                     "moods": ["Irritabel"], "note": "Hemmelig note"})
    # Not shared: nobody sees anything - the administrator included.
    for viewer in (client, far, barn):
        assert viewer.get("/api/cyklus/state").json()["shared"] == []
        assert viewer.get("/api/cyklus/calendar?frm=2026-01-01&to=2026-01-02").status_code == 403
    # Shared with far, status only.
    r = mor.put("/api/cyklus/settings", json={"viewers": [far_id]})
    assert r.status_code == 200 and r.json()["settings"]["viewers"] == [far_id]
    card = far.get("/api/cyklus/state").json()["shared"][0]
    assert card["name"] == "mor" and card["cycleDay"] == 31 and card["phaseLabel"]
    assert "fertileFrom" not in card and "todayLog" not in card and "pattern" not in card
    assert all(w["kind"] not in ("fertile", "ovulation") for w in card["week"])
    assert barn.get("/api/cyklus/state").json()["shared"] == []
    assert client.get("/api/cyklus/state").json()["shared"] == []
    # With the fertile window and her day ticked - never her note.
    mor.put("/api/cyklus/settings", json={"shareFertile": True, "shareDetails": True})
    r = far.get("/api/cyklus/state")
    card = r.json()["shared"][0]
    assert "fertileFrom" in card and card["todayLog"]["symptoms"] == ["Hovedpine"]
    assert "Hemmelig" not in r.text
    # She is no longer set to female: she shares nothing.
    client.patch(f"/api/users/{mor_id}", json={"gender": ""})
    assert far.get("/api/cyklus/state").json()["shared"] == []
    assert mor.get("/api/cyklus/state").json()["enabled"] is False


def test_settings_are_checked(client):
    mor, _ = _login(client, "mor", "familie-kode-1", gender="female")
    assert mor.put("/api/cyklus/settings", json={"cycleLength": 12}).status_code == 400
    assert mor.put("/api/cyklus/settings", json={"periodLength": 11}).status_code == 400
    assert mor.put("/api/cyklus/settings", json={"viewers": [999]}).status_code == 400
    s = mor.put("/api/cyklus/settings", json={"cycleLength": 30, "periodLength": 4}).json()
    assert s["settings"]["cycleLength"] == 30
    names = [c["username"] for c in s["candidates"]]
    assert "admin" in names and "mor" not in names


def test_patterns_count_what_she_logs_per_phase(fresh_db):
    from app.core import auth
    from app.sections.cyklus import cyklus
    u = auth.create_user("mor", "familie-kode-1", "family")
    today = date.today()
    starts = [today - timedelta(days=d) for d in (84, 56, 28)]
    for s in starts:
        cyklus.start_period(u["id"], s.isoformat())
    for s in starts:                    # two PMS days before each period: irritable, headache
        for back in (1, 2):
            cyklus.save_day(u["id"], {"day": (s - timedelta(days=back)).isoformat(),
                                      "moods": ["Irritabel"], "symptoms": ["Hovedpine"]})
    p = cyklus.patterns(u["id"])
    assert p["pms"]["days"] == 4                                     # the first cycle has no start before it
    assert [t["name"] for t in p["pms"]["top"]] == ["Hovedpine", "Irritabel"]


def test_unshared_fertile_days_read_as_the_phase_around_them(client):
    """Review finding (0.3.0): a "mid" label on exactly the fertile days gave
    the window away. Without fertile sharing, a viewer sees follicular
    before ovulation and luteal after it - and no fertile marks."""
    mor, _ = _login(client, "mor", "familie-kode-1", gender="female")
    far, far_id = _login(client, "far", "pw-far-12345678", role="user", gender="male")
    today = date.today()
    for back in (40, 12):                      # 28-day cycles: today is cycle day 13, fertile
        mor.post("/api/cyklus/period/start", json={"day": (today - timedelta(days=back)).isoformat()})
    assert mor.get("/api/cyklus/state").json()["own"]["status"]["phase"] == "fertile"
    mor.put("/api/cyklus/settings", json={"viewers": [far_id]})
    card = far.get("/api/cyklus/state").json()["shared"][0]
    assert card["phase"] == "follicular" and "Frugt" not in card["phaseLabel"]
    assert all(w["kind"] not in ("fertile", "ovulation") for w in card["week"])
    mor.put("/api/cyklus/settings", json={"shareFertile": True})
    assert far.get("/api/cyklus/state").json()["shared"][0]["phase"] == "fertile"
    # Taking him off the list again: nothing.
    mor.put("/api/cyklus/settings", json={"viewers": []})
    assert far.get("/api/cyklus/state").json()["shared"] == []


def test_a_viewer_reaches_none_of_her_own_endpoints(client):
    mor, _ = _login(client, "mor", "familie-kode-1", gender="female")
    far, far_id = _login(client, "far", "pw-far-12345678", role="user", gender="male")
    datter, _ = _login(client, "datter", "familie-kode-3", gender="female")
    today = date.today().isoformat()
    pid = mor.post("/api/cyklus/period/start", json={"day": today}).json()["periods"][0]["id"]
    mor.put("/api/cyklus/day", json={"day": today, "note": "Hemmelig"})
    mor.put("/api/cyklus/settings", json={"viewers": [far_id], "shareDetails": True})
    # A man shared with: only the shared card, no other endpoint.
    for method, path in (("get", f"/api/cyklus/day?day={today}"), ("get", "/api/cyklus/settings"),
                         ("delete", f"/api/cyklus/period/{pid}")):
        assert getattr(far, method)(path).status_code == 403, path
    # Another woman: her own endpoints act on her own rows only.
    assert datter.delete(f"/api/cyklus/period/{pid}").status_code == 404
    assert datter.put(f"/api/cyklus/period/{pid}", json={"start": today}).status_code == 404
    assert datter.get(f"/api/cyklus/day?day={today}").json()["day"]["note"] == ""
    assert mor.get("/api/cyklus/state").json()["own"]["periods"][0]["id"] == pid
    # Her Dagbog scores are not part of what "details" shares.
    card = far.get("/api/cyklus/state").json()["shared"][0]
    assert "Hemmelig" not in str(card) and (card.get("pattern") is None or "mood" not in card["pattern"])


def test_sharing_input_is_strict(client):
    mor, _ = _login(client, "mor", "familie-kode-1", gender="female")
    assert mor.put("/api/cyklus/settings", json={"shareFertile": "false"}).status_code == 400
    assert mor.put("/api/cyklus/settings", json={"shareDetails": 1}).status_code == 400
    assert mor.put("/api/cyklus/settings", json={"viewers": [True]}).status_code == 400
    assert mor.put("/api/cyklus/day", json={"day": date.today().isoformat(), "flow": ["let"]}).status_code == 400
    assert mor.get("/api/cyklus/calendar?frm=9999-12-01&to=9999-12-31").status_code == 400
    assert mor.get("/api/cyklus/settings").json()["settings"]["shareFertile"] is False


def test_an_old_log_gives_no_forecast():
    st = predict.status([Period(_d(-200), _d(-196)), Period(_d(-172), _d(-168))], D)
    assert st["stale"] is True and "phase" not in st and "late" not in st
    assert set(predict.day_kinds([Period(_d(-172))], D, _d(30), D).values()) == {""}


def test_day_map_has_the_cycle_day_phase_and_chance():
    ps = [Period(_d(-47), _d(-43)), Period(_d(-19), _d(-15))]
    m = predict.day_map(ps, _d(-19), _d(40), D)
    assert m[_d(-19)] == {"kind": "period", "cycleDay": 1, "phase": "menstruation", "chance": "lav"}
    assert m[D]["cycleDay"] == 20 and m[D]["phase"] == "luteal" and m[D]["chance"] == "lav"
    ov = _d(9 + 14)                                         # next cycle's ovulation, cycle day 15
    assert m[ov]["kind"] == "ovulation" and m[ov]["chance"] == "høj"
    assert m[ov - timedelta(days=4)]["chance"] == "middel" and m[ov + timedelta(days=2)]["chance"] == "lav"
    # Cycles that vary more widen the possible days.
    wide = [Period(_d(-120)), Period(_d(-96)), Period(_d(-62)), Period(_d(-36)), Period(_d(-6), _d(-2))]
    assert predict.uncertainty(predict.averages(wide)) == 4


def test_toggling_days_edits_her_periods():
    ps = [Period(_d(-30), _d(-26)), Period(_d(-2))]           # one ended, one going (3 days so far)
    out = predict.toggle_day(ps, _d(-25), D, 5)                # one more day on the first
    assert out[0] == Period(_d(-30), _d(-25)) and out[1] == Period(_d(-2), None)
    out = predict.toggle_day(ps, _d(-28), D, 5)                # a day out of the middle splits it
    assert out[:2] == [Period(_d(-30), _d(-29)), Period(_d(-27), _d(-26))]
    out = predict.toggle_day(ps, _d(-10), D, 5)                # a lone day is a period of its own
    assert Period(_d(-10), _d(-10)) in out
    out = predict.toggle_day([Period(D)], D, D, 5)             # the only day off: no period left
    assert out == []


def test_a_day_explained_with_its_forecast(client):
    mor, _ = _login(client, "mor", "familie-kode-1", gender="female")
    today = date.today()
    for back in (40, 12):                                  # 28-day cycles; today cycle day 13
        mor.post("/api/cyklus/period/start", json={"day": (today - timedelta(days=back)).isoformat()})
    i = mor.get(f"/api/cyklus/dayinfo?day={today.isoformat()}").json()
    assert i["cycleDay"] == 13 and i["title"] == "Frugtbar dag" and i["chanceLabel"] == "Høj"
    assert i["nextPeriodIn"] == 16 and i["log"] is not None
    labels = [x["label"] for x in i["forecast"]["items"]]
    assert labels == ["Energi", "Humør", "Social lyst", "Tålmodighed"]
    later = (today + timedelta(days=13)).isoformat()            # cycle day 26: PMS
    j = mor.get(f"/api/cyklus/dayinfo?day={later}").json()
    assert j["title"] in ("PMS-dag", "Menstruationen kan komme") and j["log"] is None
    assert "Irritabel" in j["forecast"]["expect"] and j["forecast"]["expectSource"] == "typisk"
    # Before anything is logged there is nothing to say.
    assert mor.get(f"/api/cyklus/dayinfo?day={(today - timedelta(days=90)).isoformat()}").json()["title"] == "Ingen forudsigelse"


def test_tapping_days_in_the_calendar_edits_periods(client):
    mor, _ = _login(client, "mor", "familie-kode-1", gender="female")
    today = date.today()
    for back in range(30, 25, -1):
        r = mor.post("/api/cyklus/period/toggle", json={"day": (today - timedelta(days=back)).isoformat()})
        assert r.status_code == 200, r.text
    ps = r.json()["periods"]
    assert len(ps) == 1 and ps[0]["start"] == (today - timedelta(days=30)).isoformat() and ps[0]["periodDays"] == 5
    mor.post("/api/cyklus/period/toggle", json={"day": (today - timedelta(days=28)).isoformat()})
    assert len(mor.get("/api/cyklus/state").json()["own"]["periods"]) == 2
    assert mor.post("/api/cyklus/period/toggle",
                    json={"day": (today + timedelta(days=1)).isoformat()}).status_code == 400


def test_the_shared_forecast_does_not_give_the_fertile_days_away(client):
    mor, _ = _login(client, "mor", "familie-kode-1", gender="female")
    far, far_id = _login(client, "far", "pw-far-12345678", role="user", gender="male")
    today = date.today()
    for back in (40, 12):                                  # fertile today
        mor.post("/api/cyklus/period/start", json={"day": (today - timedelta(days=back)).isoformat()})
    mor.put("/api/cyklus/settings", json={"viewers": [far_id]})
    f = far.get("/api/cyklus/state").json()["shared"][0]["forecast"]
    assert {x["key"]: x["value"] for x in f["items"]} == {"energy": 4, "mood": 4, "social": 4, "patience": 4}
    assert all(x["key"] != "overskud" for x in f["items"])          # no Dagbog scores to viewers


def test_people_she_shares_with_see_the_days_ahead_as_she_shares_them(client):
    """0.3.1 (Søren): the prediction and mood forecast per day for the men
    she shares with - fertile days and chance only when she shares them."""
    mor, mor_id = _login(client, "mor", "familie-kode-1", gender="female")
    far, far_id = _login(client, "far", "pw-far-12345678", role="user", gender="male")
    barn, _ = _login(client, "barn", "familie-kode-2", gender="male")
    today = date.today()
    for back in (40, 12):                                  # fertile today, PMS in ~11 days
        mor.post("/api/cyklus/period/start", json={"day": (today - timedelta(days=back)).isoformat()})
    mor.put("/api/cyklus/day", json={"day": today.isoformat(), "note": "Hemmelig"})
    t = today.isoformat()
    assert far.get(f"/api/cyklus/shared/day?owner={mor_id}&day={t}").status_code == 403    # not shared yet
    mor.put("/api/cyklus/settings", json={"viewers": [far_id]})
    d = far.get(f"/api/cyklus/shared/day?owner={mor_id}&day={t}").json()
    assert d["phase"] == "follicular" and d["kind"] == "" and "chance" not in d and "Frugt" not in str(d)
    assert "Hemmelig" not in str(d) and "log" not in d
    assert [x["key"] for x in d["forecast"]["items"]] == ["energy", "mood", "social", "patience"]
    pms = far.get(f"/api/cyklus/shared/day?owner={mor_id}&day={(today + timedelta(days=12)).isoformat()}").json()
    assert pms["title"] == "PMS-dag" and "Irritabel" in pms["forecast"]["expect"]
    cal = far.get(f"/api/cyklus/shared/calendar?owner={mor_id}&frm={t}"
                  f"&to={(today + timedelta(days=60)).isoformat()}").json()["days"]
    kinds = {x["kind"] for x in cal}
    assert "predicted" in kinds and not kinds & {"fertile", "ovulation"}
    # With the fertile days shared they show, with the chance.
    mor.put("/api/cyklus/settings", json={"shareFertile": True})
    d = far.get(f"/api/cyklus/shared/day?owner={mor_id}&day={t}").json()
    assert d["title"] == "Frugtbar dag" and d["chanceLabel"] == "Høj"
    # Bounds, and nobody else.
    assert far.get(f"/api/cyklus/shared/day?owner={mor_id}&day={(today + timedelta(days=200)).isoformat()}").status_code == 400
    assert barn.get(f"/api/cyklus/shared/day?owner={mor_id}&day={t}").status_code == 403
    assert client.get(f"/api/cyklus/shared/calendar?owner={mor_id}&frm={t}&to={t}").status_code == 403
