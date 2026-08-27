"""Read-only support-view gate: block mutations and /admin, log visits."""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse

from app import core
from app.storage import helpdesk

logger = logging.getLogger(__name__)

# Read-only POSTs needed to reproduce a student's Search issue.
_ALLOWED_POST = frozenset({
    "/api/support-view/exit",
    "/api/search",
    "/api/search/seed",
    "/api/search/starred",
    "/api/coverage",
    "/api/screening/quick-preview",
})
_SKIP_PREFIXES = ("/static/", "/favicon", "/health")


def _path(request) -> str:
    return request.url.path or "/"


class SupportViewMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = _path(request)
        if path.startswith(_SKIP_PREFIXES) or path == "/favicon.ico":
            return await call_next(request)

        user = None
        try:
            user = core.current_user(request)
        except Exception:
            logger.exception("support-view current_user failed")

        view = (user or {}).get("support_view") if user else None
        if not view:
            return await call_next(request)

        method = (request.method or "GET").upper()
        if path == "/support-view/exit":
            return await call_next(request)

        try:
            helpdesk.log_support_visit(core.user_db, view["id"], method, path)
        except Exception:
            logger.exception("support-view visit log failed")

        if path == "/admin" or path.startswith("/api/admin") or path == "/ops" or path.startswith("/api/ops"):
            if path.startswith("/api/"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Student view is read-only. Exit to use Admin.", "support_view": True},
                )
            return RedirectResponse(url="/search", status_code=302)

        if method in ("POST", "PUT", "PATCH", "DELETE") and path not in _ALLOWED_POST:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "This student view is read-only. Exit student view to change anything.",
                    "support_view": True,
                },
            )
        return await call_next(request)
