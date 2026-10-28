"""
Base Fetcher Module
Abstract base class plus shared HTTP client with retries and polite delay.
"""

from __future__ import annotations

import html
import logging
import math
import os
import random
import re
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_DELAY = 0.3
MAX_RETRIES = 4
DEFAULT_SOURCE_BUDGET = 90.0

# Per-thread cancel token: concurrent fetches must not share one process-global.
_CANCEL_TOKEN = threading.local()


def set_cancel_check(fn: Optional[Callable[[], bool]]) -> None:
    """Bind or clear this thread's cancel predicate (None clears)."""
    _CANCEL_TOKEN.check = fn


def source_fetch_budget() -> float:
    """Wall-clock seconds for a whole source, including pagination and waits."""
    try:
        seconds = float(os.getenv("LITSIEVE_FETCH_SOURCE_TIMEOUT", str(DEFAULT_SOURCE_BUDGET)))
    except ValueError:
        return DEFAULT_SOURCE_BUDGET
    return seconds if math.isfinite(seconds) and seconds > 0 else DEFAULT_SOURCE_BUDGET


def set_fetch_deadline(deadline: Optional[float]) -> None:
    _CANCEL_TOKEN.deadline = deadline


def check_fetch_deadline(deadline: Optional[float] = None) -> float:
    if _cancel_requested():
        raise FetchCancelled()
    if deadline is None:
        deadline = getattr(_CANCEL_TOKEN, "deadline", None)
    if deadline is None:
        return float("inf")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise FetchError("Source fetch timed out", kind="timeout")
    return remaining


def _cancel_requested() -> bool:
    fn = getattr(_CANCEL_TOKEN, "check", None)
    try:
        return bool(fn and fn())
    except Exception:
        return False


class FetchError(Exception):
    """Typed fetch failure for per-source student-facing reports."""

    def __init__(self, message: str, kind: str = "error", articles: Optional[List[Dict]] = None):
        super().__init__(message)
        self.kind = kind  # rate_limited | network | http | bad_query | no_results | error | cancelled | timeout | unavailable
        self.articles = articles or []


class FetchCancelled(FetchError):
    """Job cancel interrupted the HTTP retry ladder (message must stay exact)."""

    def __init__(self, message: str = "Cancelled"):
        super().__init__(message, kind="cancelled")


def reraise_fetch_error(exc: BaseException, articles: Optional[List[Dict]] = None) -> None:
    """Let typed HTTP failures reach the coordinator with the pages already fetched."""
    if isinstance(exc, FetchError):
        if articles and not exc.articles:
            exc.articles = articles
        raise exc


def json_of(resp) -> Any:
    """Parse a response body, or raise a typed error for a page that is not data.

    Bot walls answer 2xx with HTML (DBLP sent 202 "Making sure you're not a
    bot!"), which would otherwise surface as "Expecting value".
    """
    try:
        return resp.json()
    except ValueError as e:
        raise FetchError(
            "The source sent a web page instead of search results. "
            "It may be refusing automated requests right now; try again later.",
            kind="network",
        ) from e


# Tag-shaped only: "p < 0.01 and q > 2" in an abstract is text, not markup.
_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^<>]*)?/?>")
_SPACE = re.compile(r"\s+")


def clean_text(text: Any) -> str:
    """Plain text from an API string: tags dropped, entities decoded, spaces collapsed."""
    if not text:
        return ""
    plain = str(text)
    # Some APIs escape twice (DOAJ sends "&amp;lt;"), and Europe PMC escapes its tags.
    for _ in range(2):
        plain = html.unescape(plain)
    return _SPACE.sub(" ", _TAG.sub(" ", plain)).strip()


def user_agent(email: Optional[str] = None) -> str:
    """Identify LitSieve to APIs; add the student's contact only when they gave one."""
    email = (email or "").strip()
    return f"LitSieve (educational; {email})" if email else "LitSieve (educational)"


def classify_error(exc: BaseException) -> str:
    """Map an exception to a stable error class for UI reports."""
    if isinstance(exc, FetchError):
        return exc.kind
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
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
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "connection" in text or "network" in text:
        return "network"
    return "error"


class HttpClient:
    """Session wrapper: timeout, exponential backoff on 429/5xx, polite delay."""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        delay: float = DEFAULT_DELAY,
        max_retries: int = MAX_RETRIES,
        user_agent: str = "LitSieve (educational)",
        headers: Optional[Dict[str, str]] = None,
        budget_seconds: Optional[float] = None,
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
        self.budget_seconds = source_fetch_budget() if budget_seconds is None else budget_seconds
        self._deadline: Optional[float] = None

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    def polite_delay(self, deadline: Optional[float] = None) -> None:
        """Sleep so successive calls respect self.delay (shared across threads per client)."""
        if self.delay <= 0:
            return
        now = time.monotonic()
        wait = self.delay - (now - self._last_request_at)
        if wait > 0:
            self._sleep_interruptible(wait, deadline=deadline)
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
        Requests and waits use the remaining whole-source budget.
        """
        timeout = self.timeout if timeout is None else timeout
        last_exc: Optional[BaseException] = None
        deadline = getattr(_CANCEL_TOKEN, "deadline", None)
        if deadline is None:
            if self._deadline is None:
                self._deadline = time.monotonic() + self.budget_seconds
            deadline = self._deadline

        for attempt in range(self.max_retries + 1):
            check_fetch_deadline(deadline)
            self.polite_delay(deadline)
            remaining = check_fetch_deadline(deadline)
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    data=data,
                    headers=headers,
                    timeout=min(timeout, remaining),
                )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_exc = e
                check_fetch_deadline(deadline)
                if attempt >= self.max_retries:
                    kind = "timeout" if isinstance(e, requests.exceptions.Timeout) else "network"
                    raise FetchError(f"Network error: {e}", kind=kind) from e
                self._backoff_sleep(attempt, retry_after=None, deadline=deadline)
                continue
            except requests.exceptions.RequestException as e:
                raise FetchError(f"Request failed: {e}", kind="network") from e

            check_fetch_deadline(deadline)
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last_exc = FetchError(
                    f"HTTP {resp.status_code} from {url}",
                    kind="rate_limited" if resp.status_code == 429 else "network",
                )
                if attempt >= self.max_retries:
                    raise last_exc
                retry_after = resp.headers.get("Retry-After")
                self._backoff_sleep(
                    attempt, retry_after=retry_after, deadline=deadline, kind=last_exc.kind
                )
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
    def _backoff_sleep(
        attempt: int,
        retry_after: Optional[str],
        deadline: Optional[float] = None,
        kind: str = "rate_limited",
    ) -> None:
        if retry_after:
            try:
                seconds = float(retry_after)
            except (TypeError, ValueError):
                seconds = -1.0
            if seconds >= 0:
                wait = min(seconds, 60.0)
                if wait > check_fetch_deadline(deadline):
                    raise FetchError(
                        f"The source asked us to wait {int(seconds)} seconds, longer than the time left.",
                        kind=kind,
                    )
                HttpClient._sleep_interruptible(wait, deadline=deadline)
                return
        # Exponential backoff with jitter: ~0.5, 1, 2, 4 …
        base = min(30.0, 0.5 * (2 ** attempt))
        HttpClient._sleep_interruptible(base + random.uniform(0, 0.25), deadline=deadline)

    @staticmethod
    def _sleep_interruptible(seconds: float, deadline: Optional[float] = None) -> None:
        """Sleep in ≤0.2s slices so a job cancel can abort long Retry-After waits."""
        remaining = max(0.0, float(seconds))
        if remaining == 0.0:
            time.sleep(0)
            check_fetch_deadline(deadline)
            return
        while remaining > 0:
            budget = check_fetch_deadline(deadline)
            slice_s = min(0.2, remaining, budget)
            time.sleep(slice_s)
            remaining -= slice_s
        check_fetch_deadline(deadline)


def polite_sleep(seconds: float = DEFAULT_DELAY) -> None:
    """Module-level delay for fetchers that do not own an HttpClient (e.g. Entrez)."""
    HttpClient._sleep_interruptible(seconds)


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
    sent_query: Optional[str] = None

    def remember_sent_query(self, query: str) -> str:
        """Record the query actually sent after sanitizing; defaults to input."""
        self.sent_query = query
        return query

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
        self.remember_sent_query(query)
        ids = self.search(query, max_results)
        if not ids:
            return []
        return self.fetch_details(ids)
