"""
Errors whose message is written for the student.

A route may show a caught error's message only when the app wrote that
message for a student. ``UserError`` marks such messages at the raise site and
``sentence_for`` resolves a caught exception back to one of them, so no text
from a library or system exception reaches the client.
"""

from __future__ import annotations

FALLBACK = "That did not work. Try again."

_SENTENCES: dict[str, str] = {}


def sentence(text: str) -> str:
    """Record ``text`` as a sentence a student may be shown, and return it."""
    _SENTENCES[text] = text
    return text


class UserError(ValueError):
    """A ValueError whose message is a sentence written for the student."""

    def __init__(self, text: str):
        super().__init__(sentence(text))


def sentence_for(exc: BaseException, fallback: str = FALLBACK) -> str:
    """The sentence a response may show for ``exc``.

    Returns the sentence the app recorded for it, or ``fallback`` when the
    message was not written for a student (a library or system error).
    """
    return _SENTENCES.get(str(exc), fallback)
