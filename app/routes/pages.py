"""HTML pages, health check, and small read-only lookups (public + app shell)."""

import logging
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse

from app.content.feature_guides import get_guide, list_guides, neighbors
from app.core import (
    current_user,
    templates,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health():
    # Opportunistic cleanup: drop guest demos past their 30-minute window even
    # when no one is starting a new /guest session (watchdog hits /health).
    try:
        from app import core as _core
        _core.purge_expired_guests()
    except Exception:
        logger.exception("purge_expired_guests from /health failed")
    return {"status": "healthy", "version": "5.1.0"}


# Browsers and crawlers request these at the site root, where the /static mount
# cannot serve them. Both were logging 404s on real traffic.

@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.ico", media_type="image/x-icon")


@router.get("/robots.txt", include_in_schema=False)
async def robots():
    """Public pages are indexable; app and auth endpoints are not.

    The app pages already require a login, so this mostly stops crawlers from
    burning requests on redirects — and keeps password-reset and share-join
    URLs out of search results.
    """
    body = (
        "User-agent: *\n"
        "Allow: /$\n"
        "Allow: /learn/\n"
        "Disallow: /api/\n"
        "Disallow: /login\n"
        "Disallow: /register\n"
        "Disallow: /reset-password\n"
        "Disallow: /verify-email\n"
        "Disallow: /join\n"
        "Disallow: /data-management\n"
        "Disallow: /clusters\n"
        "Disallow: /statistics\n"
        "Disallow: /search\n"
        "Disallow: /account\n"
        "Disallow: /admin\n"
        "Disallow: /ops\n"
    )
    return PlainTextResponse(body, media_type="text/plain")


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
    """Public source catalog: names, student tips, topics, high-school packs.

    Single source of truth is source_catalog.py so Data Management, coverage,
    and duplicate priority stay aligned.
    """
    from app import core
    from app.content.source_catalog import public_catalog
    from app.storage import helpdesk
    catalog = public_catalog()
    extras = helpdesk.public_site_content(core.user_db)
    catalog["preset_notes"] = extras.get("topic_presets") or []
    catalog["help_text"] = extras.get("help_text") or ""
    return catalog


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


def _cookie_wants_simple(request: Request) -> bool:
    """Simple/Advanced is a client preference; we persist ui_mode so pages can redirect."""
    mode = (request.cookies.get("ui_mode") or "").strip().lower()
    if mode == "simple":
        return True
    if mode == "advanced":
        return False
    return (request.cookies.get("ui_mode_seed") or "").strip().lower() == "simple"


@router.get("/data-management")
async def data_management_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    # Simple home is /search (empty collect vs papers). ?collect=1 opens the
    # collect state on Search (Start over). Advanced still renders this page.
    if _cookie_wants_simple(request):
        collect = (request.query_params.get("collect") or "").strip() == "1"
        dest = "/search?collect=1" if collect else "/search"
        return RedirectResponse(url=dest, status_code=302)
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
    """Copy a library by code (auth required). Clone only — not live access."""
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
