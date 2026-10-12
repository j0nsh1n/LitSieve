"""Account looks: palette, type and results layout on the Search shell.

Workshop is the default. Every look keeps the same controls and paper
actions; each lays the result list out its own way (cards, register, table,
editorial columns, index cards, a ruled list or a reading column).
"""

from __future__ import annotations

from typing import Optional

LOOKS = ("workshop", "broadsheet", "lab", "night", "catalog", "observatory", "reading")
DEFAULT_LOOK = "workshop"

# Title and one-line blurb for the register / Account picker.
LOOK_CARDS = (
    ("workshop", "Workshop", "Warm paper and a clay accent. The current LitSieve look."),
    ("broadsheet", "Broadsheet", "Ink on newsprint. A lead paper and editorial columns under a double rule."),
    ("lab", "Lab", "Cool light and a blue accent. Results as a source and year table."),
    ("night", "Night", "Low light and a lamp glow. Amber on charcoal."),
    ("catalog", "Catalog", "Library card stock and a maroon stamp. Index cards with source tabs."),
    ("observatory", "Observatory", "Deep blue and a green signal. A year, title and source register."),
    ("reading", "Reading room", "Quiet blue on white. A book serif and a wide reading column."),
)


def parse_look(raw: Optional[str]) -> Optional[str]:
    value = (raw or "").strip().lower()
    return value if value in LOOKS else None


def normalize_look(raw: Optional[str]) -> str:
    return parse_look(raw) or DEFAULT_LOOK
