"""HTML pages, health check, and small read-only lookups (public + app shell)."""

import logging
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.content.feature_guides import get_guide, list_guides, neighbors
from app.core import (
    current_user,
    templates,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy", "version": "4.2.0"}


@router.get("/api/ui-flags")
async def api_ui_flags():
    """Deployer toggles for classroom UI (env: HIDE_STUDY_TYPE_TAGS, HIDE_AI_BUTTONS).

    Public so the app shell can load flags before authenticated API calls.
    Extractive key points are never gated by these flags.
    """
    from app.content.ui_flags import get_ui_flags
    return get_ui_flags()


@router.get("/api/sources")
async def api_sources():
    """Public source catalog: names, student tips, topics, HS packs (Phase R4).

    Single source of truth is source_catalog.py so Data Management, coverage,
    and duplicate priority stay aligned.
    """
    from app.content.source_catalog import public_catalog
    return public_catalog()


@router.get("/")
async def root(request: Request):
    # The landing page is the default page for everyone. The CTA adapts: signed-in
    # users get an "Open App" button, logged-out visitors get login/register.
    user = current_user(request)
    return templates.TemplateResponse(request, "landing.html", context={"user": user})


@router.get("/learn/{slug}")
async def feature_guide_page(slug: str, request: Request):
    """Public detail pages for each landing feature card (no login required)."""
    guide = get_guide(slug)
    if not guide:
        return RedirectResponse(url="/", status_code=302)
    prev_g, next_g = neighbors(slug)
    user = current_user(request)
    return templates.TemplateResponse(
        request,
        "feature_guide.html",
        context={
            "guide": guide,
            "prev": prev_g,
            "next": next_g,
            "all_guides": list_guides(),
            "user": user,
        },
    )


@router.get("/search")
async def search_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "search.html", context={"active_page": "search", "user": user})


@router.get("/data-management")
async def data_management_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "data_management.html", context={"active_page": "data_management", "user": user})


@router.get("/statistics")
async def statistics_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "statistics.html", context={"active_page": "statistics", "user": user})


@router.get("/clusters")
async def clusters_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "clusters.html", context={"active_page": "clusters", "user": user})


@router.get("/account")
async def account_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "account.html", context={"active_page": "account", "user": user})


@router.get("/join")
async def join_page(request: Request):
    """Join a shared library by class code (auth required)."""
    code = (request.query_params.get("code") or "").strip()
    user = current_user(request)
    if not user:
        next_path = "/join" + (f"?code={quote(code)}" if code else "")
        return RedirectResponse(
            url=f"/login?next={quote(next_path, safe='')}",
            status_code=302,
        )
    return templates.TemplateResponse(
        request,
        "join.html",
        context={
            "active_page": "account",
            "user": user,
            "join_code": code,
        },
    )
