"""What a section is. Every section package exports one `SECTION`.

A section brings, in one place:

* id           - short, stable; prefix of its help ids and its migration list
* title        - shown in the navigation (the frontend has its own registry)
* router       - its FastAPI routes
* migrations   - its own numbered list [(version, name, fn(con))]; versions
                 are permanent and recorded as (section id, version), so a
                 new section never renumbers anything
* public_paths - API paths reachable without a session (e.g. a login
                 screen's brand name)
* family_prefixes - API prefixes a `family` account may call (only the
                 family page's API; everything else refuses family)
* reset        - optional: clears in-memory state (tests, "clear data")

Adding a section: a package under app/sections/, one line in
app/sections/__init__.py, a folder under frontend/src/sections/ plus one line
in its registry, and help entries in docs/HELP.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from fastapi import APIRouter


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    router: APIRouter
    migrations: list[tuple[int, str, Callable]] = field(default_factory=list)
    public_paths: tuple[str, ...] = ()
    family_prefixes: tuple[str, ...] = ()
    reset: Callable[[], None] | None = None
