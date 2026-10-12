"""Appearance settings: each look is a preset, and a student can change any
setting on top of it. Only the settings that differ from the look's preset
are stored; choosing a look again clears them.

SETTINGS is the single allowlist. theme-init.js mirrors it (and PRESETS) so
the page paints the right layout before CSS loads; tests keep them equal.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional

from app.content.looks import normalize_look

# setting -> (label, ((value, option label), ...))
SETTINGS: Dict[str, tuple] = {
    "layout": ("Results layout", (
        ("cards", "Cards"),
        ("list", "Ruled list"),
        ("register", "Register"),
        ("table", "Table"),
        ("columns", "Columns"),
        ("index", "Index cards"),
        ("reading", "Reading column"),
    )),
    "text": ("Text size", (
        ("small", "Small"),
        ("standard", "Standard"),
        ("large", "Large"),
        ("larger", "Larger"),
    )),
    "measure": ("Reading width", (
        ("narrow", "Narrow"),
        ("standard", "Standard"),
        ("wide", "Wide"),
    )),
    "titles": ("Titles", (
        ("sans", "Sans"),
        ("serif", "Serif"),
        ("book", "Book"),
    )),
    "reading": ("Abstracts", (
        ("sans", "Sans"),
        ("serif", "Serif"),
        ("book", "Book"),
    )),
    "accent": ("Accent", (
        ("look", "The look's own"),
        ("green", "Green"),
        ("blue", "Blue"),
        ("clay", "Clay"),
        ("teal", "Teal"),
        ("ochre", "Ochre"),
        ("maroon", "Maroon"),
    )),
    "density": ("Spacing", (
        ("compact", "Compact"),
        ("standard", "Standard"),
        ("roomy", "Roomy"),
    )),
    "corners": ("Corners", (
        ("square", "Square"),
        ("small", "Small"),
        ("medium", "Medium"),
        ("round", "Round"),
    )),
    "edges": ("Edges", (
        ("hairline", "Hairline"),
        ("bordered", "Bordered"),
        ("offset", "Offset"),
    )),
}

_BASE = {"text": "standard", "measure": "standard", "accent": "look", "density": "standard"}

PRESETS: Dict[str, Dict[str, str]] = {
    "workshop": {**_BASE, "layout": "cards", "titles": "serif", "reading": "sans",
                 "corners": "round", "edges": "bordered"},
    "broadsheet": {**_BASE, "layout": "columns", "titles": "serif", "reading": "serif",
                   "corners": "square", "edges": "hairline"},
    "lab": {**_BASE, "layout": "table", "titles": "sans", "reading": "sans",
            "density": "compact", "corners": "small", "edges": "hairline"},
    "night": {**_BASE, "layout": "list", "titles": "book", "reading": "book",
              "density": "roomy", "corners": "medium", "edges": "hairline"},
    "catalog": {**_BASE, "layout": "index", "titles": "serif", "reading": "serif",
                "corners": "small", "edges": "offset"},
    "observatory": {**_BASE, "layout": "register", "titles": "sans", "reading": "sans",
                    "density": "roomy", "corners": "medium", "edges": "hairline"},
    "reading": {**_BASE, "layout": "reading", "titles": "book", "reading": "book",
                "measure": "wide", "corners": "medium", "edges": "hairline"},
}

def _allowed(setting: str) -> tuple:
    return tuple(value for value, _ in SETTINGS[setting][1])


def parse_overrides(raw: Any, look: Optional[str]) -> Dict[str, str]:
    """Allowlisted settings that differ from the look's preset. Unknown keys
    and values are dropped, so a stale cookie or column can never break paint."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return {}
    if not isinstance(raw, Mapping):
        return {}
    preset = PRESETS[normalize_look(look)]
    out: Dict[str, str] = {}
    for setting in SETTINGS:
        value = raw.get(setting)
        if isinstance(value, str) and value in _allowed(setting) and value != preset[setting]:
            out[setting] = value
    return out


def effective(look: Optional[str], overrides: Mapping[str, str]) -> Dict[str, str]:
    return {**PRESETS[normalize_look(look)], **parse_overrides(overrides, look)}


def cookie_value(overrides: Mapping[str, str]) -> str:
    """`layout.table~density.compact`: cookie-safe without quoting."""
    return "~".join(f"{k}.{v}" for k, v in overrides.items())
