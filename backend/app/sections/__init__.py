"""The section registry. The navigation, the migrations, the routers and
the family lockout all come from this list - adding a section is one line
here (and one in frontend/src/sections/registry.ts)."""
from __future__ import annotations

from .familymap import SECTION as _familymap
from .ledger import SECTION as _ledger

SECTIONS = [_ledger, _familymap]
