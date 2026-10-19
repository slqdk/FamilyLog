"""Alf on the family's Dagbog and Cyklus (0.3.11): he answers from exactly
what the person asking can see in the app - the family's shared days, a
cycle only when she shares it and only what she ticked, never her note."""
from __future__ import annotations

from datetime import date, timedelta

from test_chat import _setup, _wait

TODAY = date.today()


def _login(client, name, pw, role="family", gender=""):
    from fastapi.testclient import TestClient
    from app.main import app
    r = client.post("/api/users", json={"username": name, "password": pw, "role": role, "gender": gender})
    assert r.status_code == 200, r.text
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": name, "password": pw}).status_code == 200
    return c, r.json()["id"]


def _user(uid):
    from app.core import auth
    return auth.get_user(uid)


def _family(client):
    mor, mor_id = _login(client, "mor", "familie-kode-1", gender="female")
    far, far_id = _login(client, "far", "familie-kode-2", gender="male")
    barn, barn_id = _login(client, "barn", "familie-kode-3")
    sanne, sanne_id = _login(client, "sanne", "pw-sanne-12345", role="user")
    mor.put("/api/dagbog/entry", json={"day": TODAY.isoformat(), "mood": 4, "exercise": 60,
                                       "highlight": "Delt tekst"})
    mor.put("/api/dagbog/entry", json={"day": (TODAY - timedelta(days=1)).isoformat(), "mood": 2,
                                       "highlight": "Privat tekst", "shared": False})
    for back in (58, 30):
        mor.post("/api/cyklus/period/start", json={"day": (TODAY - timedelta(days=back)).isoformat()})
    mor.put("/api/cyklus/day", json={"day": TODAY.isoformat(), "symptoms": ["Hovedpine"], "note": "Hemmelig note"})
    return {"mor": (mor, mor_id), "far": (far, far_id), "barn": (barn, barn_id), "sanne": (sanne, sanne_id)}


def test_alf_sees_what_the_asker_sees(client):
    from app.sections.chat import family
    f = _family(client)
    mor_id, far_id, barn_id, sanne_id = (f[k][1] for k in ("mor", "far", "barn", "sanne"))
    # far, family: mor's shared day, not her private one; no cycle until she shares it.
    ctx = family.gather(_user(far_id), "mor")
    assert ctx["people"] == ["mor"] and "Delt tekst" in ctx["context"] and "humør 4/5" in ctx["context"]
    assert "Privat tekst" not in ctx["context"] and "Cyklus" not in ctx["context"]
    assert "Hemmelig" not in ctx["context"]
    # She shares the status with far: the phase, never the fertile days or her note.
    f["mor"][0].put("/api/cyklus/settings", json={"viewers": [far_id]})
    ctx = family.gather(_user(far_id), "mor")["context"]
    assert "Cyklus (delt med dig): cyklusdag 31" in ctx and "deler ikke de frugtbare dage" in ctx
    assert "Frugtbare dage" not in ctx and "Hovedpine" not in ctx and "Hemmelig" not in ctx
    f["mor"][0].put("/api/cyklus/settings", json={"shareFertile": True, "shareDetails": True})
    ctx = family.gather(_user(far_id), "mor")["context"]
    assert "Frugtbare dage" in ctx and "Hovedpine" in ctx and "Hemmelig" not in ctx
    # barn is family but not shared with: her days, not her cycle.
    ctx = family.gather(_user(barn_id), "mor")["context"]
    assert "Delt tekst" in ctx and "Cyklus" not in ctx
    # A user account is not family: nothing of mor.
    ctx = family.gather(_user(sanne_id), "mor")
    assert ctx["missing"] == "mor" and ctx["people"] == [] and "Delt tekst" not in ctx["context"]
    # mor about herself: everything of hers, her own cycle - still not her note.
    ctx = family.gather(_user(mor_id), "mig")
    assert ctx["people"] == ["mor"] and "Privat tekst" in ctx["context"] and "Cyklus i dag" in ctx["context"]
    assert "Hemmelig" not in ctx["context"]


def test_alf_knows_people_by_their_name(client):
    """The administrator gives an account the name the family uses."""
    from app.sections.chat import family
    f = _family(client)
    mor_id, far_id = f["mor"][1], f["far"][1]
    r = client.patch(f"/api/users/{mor_id}", json={"name": "  Mette   Hansen "})
    assert r.status_code == 200 and r.json()["name"] == "Mette Hansen"
    assert client.patch(f"/api/users/{mor_id}", json={"name": "x" * 41}).status_code == 400
    assert f["far"][0].patch(f"/api/users/{mor_id}", json={"name": "Mor"}).status_code == 403
    for asked in ("Mette", "mette hansen", "Hansen", "mo"):
        assert family.gather(_user(far_id), asked)["people"] == ["Mette Hansen"], asked
    assert family.gather(_user(far_id), "mig")["people"] == ["far"]
    everyone = family.gather(_user(far_id), None)
    assert everyone["people"] == ["far", "admin", "barn", "Mette Hansen"]   # the asker first
    assert "Mette Hansen (konto mor)" in everyone["context"]


def test_alf_answers_about_the_family_in_the_chat(client, mock_ollama):
    from fastapi.testclient import TestClient
    from app.main import app
    _setup(client, mock_ollama)
    f = _family(client)
    client.patch(f"/api/users/{f['mor'][1]}", json={"name": "Mette"})
    with TestClient(app) as far:
        far.post("/api/auth/login", json={"username": "far", "password": "familie-kode-2"})
        far.post("/api/chat/send", json={"message": "Hvordan har Mette det?"})
        v = _wait(far)
    assert v["job"]["state"] == "done" and v["job"]["route"] == "family", v["job"]
    answer = v["messages"][-1]
    assert answer["meta"] == {"route": "family", "searched": "Mette"}
    assert "Mette (konto mor)" in answer["content"] and "Delt tekst" in answer["content"]
    assert "Privat tekst" not in answer["content"]


def test_migration_6_shares_the_old_days(fresh_db):
    """0.3.11 (Søren): the days written before 0.3.9 show their text too - a
    day its author has saved since keeps the choice made then."""
    from app.core import auth, db
    from app.sections.dagbog import _m006_share_old_days, dagbog
    u = auth.create_user("mor", "familie-kode-1", "family")
    with db.connect() as con:
        con.execute("UPDATE schema_migrations SET applied_at = '2026-10-18T20:00:00+00:00'"
                    " WHERE section = 'dagbog' AND version = 5")
        for d, at in (("2026-10-01", "2026-10-01T10:00:00+00:00"), ("2026-10-02", "2026-10-19T06:00:00+00:00")):
            con.execute("INSERT INTO dagbog_entries (user_id, day, tags, highlight, shared, created_at, updated_at)"
                        " VALUES (?, ?, '[]', 'tekst', 0, ?, ?)", (u["id"], d, at, at))
        _m006_share_old_days(con)
    assert dagbog.get_entry(u["id"], "2026-10-01")["shared"] is True
    assert dagbog.get_entry(u["id"], "2026-10-02")["shared"] is False     # made private since
