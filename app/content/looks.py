"""Account looks: palette skins on the Simple Search shell.

Workshop is the default. The other four keep the same layout and swap
colour, type, and a little chrome. Structure changes are a later job.
"""

from __future__ import annotations

from typing import Optional

LOOKS = ("workshop", "broadsheet", "lab", "night", "catalog")
DEFAULT_LOOK = "workshop"

# Title and one-line blurb for the register / Account picker.
LOOK_CARDS = (
    ("workshop", "Workshop", "Warm paper and a clay accent. The current LitSieve look."),
    ("broadsheet", "Broadsheet", "Ink on newsprint. Serif type, square corners, a double rule."),
    ("lab", "Lab", "Cool light and a blue accent. Tight corners, like a product UI."),
    ("night", "Night", "Low light and a lamp glow. Amber on charcoal."),
    ("catalog", "Catalog", "Library card stock, a maroon stamp, ruled lines."),
)


def parse_look(raw: Optional[str]) -> Optional[str]:
    value = (raw or "").strip().lower()
    return value if value in LOOKS else None


def normalize_look(raw: Optional[str]) -> str:
    return parse_look(raw) or DEFAULT_LOOK
