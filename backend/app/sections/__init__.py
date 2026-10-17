"""The section registry. The migrations, the routers and the family lockout
all come from this list - adding a section is one line here (and one in
frontend/src/sections/registry.ts when it has a page in the admin app)."""
from __future__ import annotations

from .chat import SECTION as _chat
from .cyklus import SECTION as _cyklus
from .dagbog import SECTION as _dagbog
from .familymap import SECTION as _familymap
from .ledger import SECTION as _ledger

# Order matters only for migrations: familymap before chat (chat reads it).
SECTIONS = [_ledger, _familymap, _chat, _dagbog, _cyklus]
