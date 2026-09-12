"""
Base Fetcher Module
Abstract base class plus shared HTTP client with retries and polite delay.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_DELAY = 0.3
MAX_RETRIES = 4

# Per-thread cancel token: concurrent fetches must not share one process-global.
_CANCEL_TOKEN = threading.local()


def set_cancel_check(fn: Optional[Callable[[], bool]]) -> None:
    """Bind or clear this thread's cancel predicate (None clears)."""
    _CANCEL_TOKEN.check = fn


def _cancel_requested() -> bool:
    fn = getattr(_CANCEL_TOKEN, "check", None)
    try:
        return bool(fn and fn())
    except Exception:
        return False


class FetchError(Exception):
    """Typed fetch failure for per-source student-facing reports."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind  # rate_limited | network | http | no_results | error | cancelled


class FetchCancelled(FetchError):
    """Job cancel interrupted the HTTP retry ladder (message must stay exact)."""

    def __init__(self, message: str = "Cancelled"):
        super().__init__(message, kind="cancelled")


def classify_error(exc: BaseException) -> str:
    """Map an exception to a stable error class for UI reports."""
    if isinstance(exc, FetchError):
        return exc.kind
    if isinstance(exc, requests.exceptions.Timeout):
        return "network"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "network"
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = getattr(exc, "response", None)
        code = getattr(resp, "status_code", None)
        if code == 429:
            return "rate_limited"
        if code is not None and 500 <= int(code) < 600:
            return "network"
        return "http"
    text = str(exc).lower()
    if "429" in text or "rate limit" in text or "too many" in text:
        return "rate_limited"
    if "timeout" in text or "connection" in text or "network" in text:
        return "network"
    return "error"


class HttpClient:
    """Session wrapper: timeout, exponential backoff on 429/5xx, polite delay."""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        delay: float = DEFAULT_DELAY,
        max_retries: int = MAX_RETRIES,
        user_agent: str = "LiteratureResearchAide/3.7 (educational; polite bot)",
        headers: Optional[Dict[str, str]] = None,
    ):
        self.timeout = timeout
        self.delay = delay
        self.max_retries = max_retries
        self.session = requests.Session()
        base_headers = {"User-Agent": user_agent}
        if headers:
            base_headers.update(headers)
        self.session.headers.update(base_headers)
        self._last_request_at = 0.0

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    def polite_delay(self) -> None:
        """Sleep so successive calls respect self.delay (shared across threads per client)."""
        if self.delay <= 0:
            return
        now = time.monotonic()
        wait = self.delay - (now - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        data=None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        """HTTP request with retries on 429/5xx; raises FetchError on hard failure.

        A job cancel aborts further retries and backoff immediately (FetchCancelled).
        An in-flight socket wait still runs out (≤ DEFAULT_TIMEOUT, typically 30s).
        """
        timeout = self.timeout if timeout is None else timeout
        last_exc: Optional[BaseException] = None

        for attempt in range(self.max_retries + 1):
            if _cancel_requested():
                raise FetchCancelled()
            self.polite_delay()
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    data=data,
                    headers=headers,
                    timeout=timeout,
                )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_exc = e
                if attempt >= self.max_retries:
                    raise FetchError(f"Network error: {e}", kind="network") from e
                self._backoff_sleep(attempt, retry_after=None)
                continue
            except requests.exceptions.RequestException as e:
                raise FetchError(f"Request failed: {e}", kind="network") from e

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last_exc = FetchError(
                    f"HTTP {resp.status_code} from {url}",
                    kind="rate_limited" if resp.status_code == 429 else "network",
                )
                if attempt >= self.max_retries:
                    raise last_exc
                retry_after = resp.headers.get("Retry-After")
                self._backoff_sleep(attempt, retry_after=retry_after)
                continue

            if resp.status_code >= 400:
                raise FetchError(
                    f"HTTP {resp.status_code}: {(resp.text or '')[:200]}",
                    kind="http",
                )

            return resp

        if last_exc:
            raise last_exc
        raise FetchError("Request failed after retries", kind="network")

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request("POST", url, **kwargs)

    @staticmethod
    def _backoff_sleep(attempt: int, retry_after: Optional[str]) -> None:
        if retry_after:
            try:
                seconds = float(retry_after)
                if seconds >= 0:
                    HttpClient._sleep_interruptible(min(seconds, 60.0))
                    return
            except (TypeError, ValueError):
                pass
        # Exponential backoff with jitter: ~0.5, 1, 2, 4 …
        base = min(30.0, 0.5 * (2 ** attempt))
        HttpClient._sleep_interruptible(base + random.uniform(0, 0.25))

    @staticmethod
    def _sleep_interruptible(seconds: float) -> None:
        """Sleep in ≤0.2s slices so a job cancel can abort long Retry-After waits."""
        remaining = max(0.0, float(seconds))
        if remaining == 0.0:
            time.sleep(0)
            if _cancel_requested():
                raise FetchCancelled()
            return
        while remaining > 0:
            if _cancel_requested():
                raise FetchCancelled()
            slice_s = min(0.2, remaining)
            time.sleep(slice_s)
            remaining -= slice_s
        if _cancel_requested():
            raise FetchCancelled()


def polite_sleep(seconds: float = DEFAULT_DELAY) -> None:
    """Module-level delay for fetchers that do not own an HttpClient (e.g. Entrez)."""
    if seconds > 0:
        time.sleep(seconds)


class BaseFetcher(ABC):
    """Abstract base for article fetchers from different sources.

    Two implementation patterns:
    - Two-step (e.g. PubMed, arXiv): implement search() + fetch_details();
      the default search_and_fetch() chains them.
    - One-shot (most APIs, where one request returns full records): override
      search_and_fetch() directly. fetch_details() is then never called and
      must NOT be stubbed out — the base default raises if something does
      call it, which beats silently returning no articles.

    The pipeline only ever calls search_and_fetch().
    """

    SOURCE_NAME: str = ""

    @abstractmethod
    def search(self, query: str, max_results: int = 1000) -> List[str]:
        """Search for articles and return list of source-specific IDs"""
        pass

    def fetch_details(self, ids: List[str], batch_size: int = 200) -> List[Dict]:
        """
        Fetch article details for given IDs (two-step fetchers only).

        Returns:
            List of article dicts with keys:
            article_id, source, title, abstract, year, authors, journal
        """
        raise NotImplementedError(
            f"{type(self).__name__} is a one-shot fetcher: use search_and_fetch()."
        )

    def search_and_fetch(self, query: str, max_results: int = 1000) -> List[Dict]:
        """Complete workflow: search then fetch details"""
        ids = self.search(query, max_results)
        if not ids:
            return []
        return self.fetch_details(ids)
