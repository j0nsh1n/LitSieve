"""
FastAPI Application — Literature Research Aide v4.2.0
Multi-user web interface for literature search and analysis.

This module only wires the app together: configuration, static files, the
startup warm-up, and the route modules in app/routes/. Shared runtime state
lives in app.core; endpoints live in app/routes/<area>.py.
"""

import logging
import os
import threading

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

from app import core  # noqa: E402
from app.routes import (  # noqa: E402
    ai,
    auth,
    corpus,
    exports,
    libraries,
    pages,
    search,
    shares,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Literature Research Aide", version="4.2.0")
app.state.limiter = core.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Route modules, in workflow order (pages first so "/" resolves predictably).
for _module in (pages, auth, libraries, shares, corpus, search, exports, ai):
    app.include_router(_module.router)


@app.on_event("startup")
async def _warm_umap_kernels():
    # UMAP's first fit pays ~8s of numba JIT; absorb it at boot in a daemon
    # thread so the first Generate Clusters click stays ~1s (bench_scale.py).
    from app.services.clustering import warm_density_reducer
    threading.Thread(target=warm_density_reducer, daemon=True, name="umap-warmup").start()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
