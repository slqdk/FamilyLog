"""The Help registry: one entry per control, served as GET /api/help and
opened by Alt+click on the control (or the ? in the top bar).

Source: `docs/HELP.md`, one section per `## <id>`. The lines right after
the heading up to the first blank line are fields (`title:`, `where:`,
`since:`, `changed:`); the rest is the body, in Markdown. Ids are dotted and
start with the section id (`ledger.ask`, `familymap.places`) or `app.` /
`settings.` for the shell.

Kept current by tests, not discipline: every `data-help` id in the frontend
must resolve here, every entry is anchored somewhere, and every entry
carries `since:` (tests/core/test_help.py). From SLQ's help.py, without
SLQ's generated option catalogue.
"""
from __future__ import annotations

import re
from pathlib import Path

HELP_PATH = Path(__file__).resolve().parents[3] / "docs" / "HELP.md"

_ID = re.compile(r"^## ([A-Za-z0-9_.-]+)\s*$")


def parse(text: str) -> dict[str, dict]:
    """`## id` sections -> {id: {title, where, since, changed, body}}.
    A duplicate id raises, so a test says so."""
    out: dict[str, dict] = {}
    cur: dict | None = None
    in_fields = False
    body: list[str] = []

    def flush() -> None:
        if cur is not None:
            cur["body"] = "\n".join(body).strip()
            out[cur["id"]] = cur

    for line in text.splitlines():
        m = _ID.match(line)
        if m:
            flush()
            if m.group(1) in out:
                raise ValueError(f"HELP.md: duplicate section {m.group(1)!r}")
            cur = {"id": m.group(1), "title": "", "where": "", "since": "", "changed": ""}
            body = []
            in_fields = True
            continue
        if cur is None:
            continue                      # preamble before the first section
        if in_fields:
            if not line.strip():
                in_fields = False
                continue
            fm = re.match(r"^(title|where|since|changed):\s*(.*)$", line)
            if fm:
                cur[fm.group(1)] = fm.group(2).strip()
                continue
            in_fields = False
        body.append(line)
    flush()
    return out


def load(path: Path = HELP_PATH) -> dict[str, dict]:
    try:
        return parse(path.read_text(encoding="utf-8-sig"))
    except OSError:
        return {}


def entries(path: Path = HELP_PATH) -> list[dict]:
    """Sorted for the panel's index: by `where`, then title."""
    return sorted(load(path).values(),
                  key=lambda e: (e["where"].lower(), e["title"].lower()))
