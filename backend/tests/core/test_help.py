"""Help is kept current by tests, not discipline (from SLQ 2.42.0): every
data-help id in the frontend resolves in docs/HELP.md, every entry is
anchored in the frontend, and every entry says since when it exists."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FRONTEND = REPO / "frontend" / "src"
# data-help="id", helpId: 'id' (section registry), help="id" (settings groups)
_ANCHOR = re.compile(r"""(?:data-help="|helpId:\s*'|\shelp=")([A-Za-z0-9_.-]+)["']""")


def _anchors() -> set[str]:
    ids: set[str] = set()
    for path in FRONTEND.rglob("*.tsx"):
        ids.update(_ANCHOR.findall(path.read_text(encoding="utf-8")))
    for path in FRONTEND.rglob("*.ts"):
        ids.update(_ANCHOR.findall(path.read_text(encoding="utf-8")))
    return ids


def test_the_frontend_has_anchors():
    ids = _anchors()
    assert {"ledger.ask", "familymap.settings", "settings.models", "nav.ledger"} <= ids


def test_every_anchor_has_an_entry():
    from app.core import help as help_reg
    entries = help_reg.load()
    missing = sorted(_anchors() - set(entries))
    assert not missing, f"data-help ids without a docs/HELP.md entry: {missing}"


def test_every_entry_is_anchored_and_dated():
    from app.core import help as help_reg
    entries = help_reg.load()
    unanchored = sorted(set(entries) - _anchors())
    assert not unanchored, f"HELP.md entries no control points at: {unanchored}"
    undated = sorted(i for i, e in entries.items() if not e["since"])
    assert not undated, f"entries without since: {undated}"
    assert all(e["title"] and e["where"] and e["body"] for e in entries.values())


def test_help_is_served_with_the_version(client):
    from app.meta import APP_VERSION
    r = client.get("/api/help").json()
    assert r["version"] == APP_VERSION and r["name"] == "FamilyLog"
    assert any(e["id"] == "settings.ollamaTest" for e in r["entries"])


def test_a_duplicate_id_is_an_error():
    import pytest
    from app.core import help as help_reg
    with pytest.raises(ValueError):
        help_reg.parse("## a\ntitle: x\n\nbody\n\n## a\ntitle: y\n\nbody\n")
