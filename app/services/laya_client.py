"""Optional client for the local Laya sidecar (tools/laya_worker.py).

Laya is a small typed-decision model: given a text and a fixed set of options it
picks one, with a probability. LitSieve uses it as a switch at points where the
code already owns every branch (study-type tags, topic areas) and never for
ranking. Everything here fails closed: when LITSIEVE_LAYA_URL is unset, the
worker is down or slow, or the answer is malformed, calls return None and the
caller keeps today's behaviour.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# connect, read (seconds). Search waits on this, so keep it short.
TIMEOUT = (0.25, 1.2)
# After a failure, skip Laya for this long instead of paying the timeout on every search.
COOLDOWN_SECONDS = 30.0

_state_lock = threading.Lock()
_down_until = 0.0


def base_url() -> str:
    return (os.environ.get("LITSIEVE_LAYA_URL") or "").strip().rstrip("/")


def enabled() -> bool:
    return bool(base_url())


def _mark_down(reason: str) -> None:
    global _down_until
    with _state_lock:
        _down_until = time.monotonic() + COOLDOWN_SECONDS
    logger.warning("Laya unavailable (%s); falling back for %.0fs", reason, COOLDOWN_SECONDS)


def _cooling_down() -> bool:
    with _state_lock:
        return time.monotonic() < _down_until


def choice(instructions: str, options: Dict[str, str], states: List[str]) -> Optional[List[dict]]:
    """Ask Laya to pick one option per state. Returns [{choice, p, probabilities}] or None."""
    url = base_url()
    if not url or not states or len(options) < 2 or _cooling_down():
        return None
    payload = {"instructions": instructions, "options": options, "states": list(states), "state_key": "text"}
    try:
        resp = requests.post(f"{url}/v1/choice", json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        _mark_down(type(exc).__name__)
        return None
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or len(results) != len(states):
        _mark_down("malformed response")
        return None
    clean = []
    for r in results:
        pick = r.get("choice") if isinstance(r, dict) else None
        p = r.get("p") if isinstance(r, dict) else None
        if pick not in options or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            _mark_down("malformed answer")
            return None
        raw = r.get("probabilities")
        probs = raw if isinstance(raw, dict) else {}
        clean.append({"choice": pick, "p": float(p),
                      "probabilities": {k: float(v) for k, v in probs.items() if k in options and isinstance(v, (int, float))}})
    return clean


def _reset_for_tests() -> None:
    global _down_until
    with _state_lock:
        _down_until = 0.0
