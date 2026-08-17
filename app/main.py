"""
FastAPI Application — LitSieve v5.0.3
Multi-user web interface for literature search and analysis.

This module only wires the app together: configuration, static files, the
startup warm-up, and the route modules in app/routes/. Shared runtime state
lives in app.core; endpoints live in app/routes/<area>.py.
"""

import logging
import os
import threading
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

from app import core  # noqa: E402
from app.logging_setup import configure_logging  # noqa: E402
from app.routes import (  # noqa: E402
    admin,
    ai,
    auth,
    corpus,
    exports,
    libraries,
    pages,
    search,
    shares,
    start_over,
)
from app.security import SecurityHeadersMiddleware  # noqa: E402

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup/shutdown hook (replaces the deprecated on_event decorator)."""
    # UMAP's first fit pays ~8s of numba JIT; absorb it at boot in a daemon
    # thread so the first Generate Clusters click stays ~1s (bench_scale.py).
    from app.services.clustering import warm_density_reducer
    threading.Thread(target=warm_density_reducer, daemon=True, name="umap-warmup").start()
    yield
    # Nothing to tear down: SQLite handles close via the pipeline cache and the
    # warm-up thread is a daemon.


app = FastAPI(
    title="LitSieve",
    version="5.0.3",
    lifespan=lifespan,
)
app.state.limiter = core.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SecurityHeadersMiddleware)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Route modules, in workflow order (pages first so "/" resolves predictably).
for _module in (pages, auth, admin, libraries, shares, corpus, start_over, search, exports, ai):
    app.include_router(_module.router)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
