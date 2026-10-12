"""Optional Laya switches exposed to the browser.

POST /api/topic-area: the student's typed topic -> the topic area(s) Laya thinks
it belongs to, so the collect step can suggest the chip that picks the
recommended databases. The student always decides; with Laya off this returns
{"available": false} and the page shows nothing.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.content.source_catalog import TOPIC_META
from app.core import csrf_failed, current_user, limiter, run_in_thread
from app.schemas import TopicAreaFeedback, TopicAreaRequest
from app.services import laya_client

router = APIRouter()
logger = logging.getLogger(__name__)

MIN_BEST = 0.5        # below this Laya is unsure; suggest nothing
SECOND_RATIO = 0.5    # include the runner-up when it has at least half the best's probability


def suggest_topic_areas(topic: str) -> dict:
    if not laya_client.enabled():
        return {"available": False, "reason": "disabled", "topics": []}
    options = {tid: meta["name"] for tid, meta in TOPIC_META.items()}
    answers = laya_client.choice("Which subject area is this student research topic in?", options, [topic])
    if not answers:
        return {"available": False, "reason": "unavailable", "topics": []}
    probs = {k: v for k, v in answers[0]["probabilities"].items() if k in TOPIC_META} or {answers[0]["choice"]: answers[0]["p"]}
    ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    best_id, best_p = ranked[0]
    if best_p < MIN_BEST:
        return {"available": True, "reason": "unsure", "topics": []}
    picks = [(best_id, best_p)]
    if len(ranked) > 1 and ranked[1][1] >= SECOND_RATIO * best_p:
        picks.append(ranked[1])
    return {"available": True, "reason": None,
            "topics": [{"id": tid, "name": TOPIC_META[tid]["name"], "p": round(p, 3)} for tid, p in picks]}


@router.post("/api/topic-area")
@limiter.limit("30/minute")
async def api_topic_area(req: TopicAreaRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    return await run_in_thread(suggest_topic_areas, req.topic.strip())


@router.post("/api/topic-area/feedback")
@limiter.limit("30/minute")
async def api_topic_area_feedback(req: TopicAreaFeedback, request: Request):
    """Log Laya's pick against the areas actually searched, to tune MIN_BEST.

    Only topic-area ids are recorded, never the topic text or the user.
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    suggested = sorted({t for t in req.suggested if t in TOPIC_META})
    final = sorted({t for t in req.final if t in TOPIC_META})
    if not suggested:
        return {"ok": False}
    logger.info("laya topic-area feedback suggested=%s final=%s kept=%s opened=%s",
                ",".join(suggested), ",".join(final), set(suggested) <= set(final), req.opened)
    return {"ok": True}
