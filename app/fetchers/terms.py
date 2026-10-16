"""Split a student's topic into terms and operators for APIs that OR bare words."""

from __future__ import annotations

import re
from typing import List

OPERATORS = ("AND", "OR", "NOT")
_TOKEN = re.compile(r'"[^"]+"|[^\s()"]+')


def boolean_terms(query: str) -> List[str]:
    """Terms and AND/OR/NOT in order, with AND between words written side by side.

    "heart disease" -> ["heart", "AND", "disease"]; a quoted phrase stays one
    term; operators must be upper case, as in PubMed and Europe PMC.
    """
    out: List[str] = []
    for token in _TOKEN.findall(query or ""):
        if token in OPERATORS:
            if out and out[-1] not in OPERATORS:
                out.append(token)
            elif token == "NOT" and out and out[-1] == "AND":
                out.append(token)
            continue
        if out and out[-1] not in OPERATORS:
            out.append("AND")
        out.append(token)
    while out and out[-1] in OPERATORS:
        out.pop()
    return out
