"""Read-time access labels from stored OA fields. No network check."""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any, Iterable, List, Mapping, NamedTuple, Optional, Tuple
from urllib.parse import urlsplit

from app.content.source_catalog import source_display_name

OPEN_LISTED = "open_listed"
NONE_LISTED = "none_listed"

# OpenAlex oa_status values that mean a copy was listed as open.
_OPEN_OA_STATUS = frozenset({"gold", "green", "hybrid", "bronze", "diamond", "open"})
_CLOSED_OA_STATUS = frozenset({"closed", "embargo", "restricted"})
_CC_HOSTS = frozenset({"creativecommons.org", "www.creativecommons.org"})
_CC_LICENCE_PATH = re.compile(
    r"^/(?:licenses/(?:by-nc-sa|by-nc-nd|by-nc|by-nd|by-sa|by)"
    r"/(?:1\.0|2\.0|2\.1|2\.5|3\.0|4\.0)"
    r"|publicdomain/(?:zero|mark)/1\.0)"
    r"(?:/.*)?$",
    re.IGNORECASE,
)
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class AccessInfo(NamedTuple):
    state: str
    url: Optional[str]
    sources: Tuple[str, ...]


def access_state(article: Any) -> AccessInfo:
    """Listed-open copy from stored fields only. Never raises on odd data."""
    try:
        return _access_state(article if isinstance(article, Mapping) else {})
    except Exception:
        return AccessInfo(NONE_LISTED, None, ())


def access_public_dict(info: AccessInfo) -> dict:
    """Card payload: omit url when there is no listed open copy."""
    out = {"state": info.state, "sources": list(info.sources)}
    if info.state == OPEN_LISTED and info.url:
        out["url"] = info.url
    return out


def _access_state(article: Mapping[str, Any]) -> AccessInfo:
    source = str(article.get("source") or "").strip()
    locations = _locations(article)
    sources = _source_names(source, locations)
    url = _open_copy_url(article, source, locations)
    if url:
        return AccessInfo(OPEN_LISTED, url, sources)
    return AccessInfo(NONE_LISTED, None, sources)


def _open_copy_url(
    article: Mapping[str, Any], source: str, locations: List[Mapping[str, Any]],
) -> Optional[str]:
    source_id = source.lower()
    licensed_crossref = None
    doaj_url = None
    other_urls: List[str] = []
    for loc in locations:
        url = _http_url(loc.get("url"))
        if not url:
            continue
        via = str(loc.get("via") or "").strip().lower()
        if _is_crossref_link(via, source_id):
            if _has_cc_licence(loc.get("license") or loc.get("licence")):
                licensed_crossref = licensed_crossref or url
            continue
        if via == "doaj" or source_id == "doaj":
            doaj_url = doaj_url or url
            continue
        other_urls.append(url)

    if doaj_url:
        return doaj_url
    if not _status_is_open(article.get("oa_status")):
        return licensed_crossref
    best = _http_url(article.get("best_oa_url"))
    if best:
        return best
    for url in other_urls:
        return url
    return licensed_crossref


def _status_is_open(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text or text in _CLOSED_OA_STATUS:
        return False
    return text in _OPEN_OA_STATUS


def _is_crossref_link(via: str, source_id: str) -> bool:
    if via == "crossref":
        return True
    return source_id == "crossref" and not via


def _has_cc_licence(value: Any) -> bool:
    url = _http_url(value)
    if not url:
        return False
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
    except Exception:
        return False
    if host not in _CC_HOSTS:
        return False
    return bool(_CC_LICENCE_PATH.match(parsed.path or ""))


def _http_url(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    if not text or _has_illegal_url_chars(text):
        return None
    lowered = text.lower()
    if not (lowered.startswith("https://") or lowered.startswith("http://")):
        return None
    try:
        parsed = urlsplit(text)
        if parsed.scheme.lower() not in {"http", "https"}:
            return None
        if not parsed.netloc:
            return None
        host = parsed.hostname
        port = parsed.port
    except Exception:
        return None
    if not host or not _valid_hostname(host):
        return None
    if port is not None and not (1 <= port <= 65535):
        return None
    return text


def _has_illegal_url_chars(text: str) -> bool:
    return any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in text)


def _valid_hostname(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if len(host) > 253:
        return False
    if host.endswith("."):
        host = host[:-1]
        if not host:
            return False
    return all(_HOST_LABEL.fullmatch(label) for label in host.split("."))


def _locations(article: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    extra = article.get("_extra")
    raw = None
    if isinstance(extra, Mapping):
        raw = extra.get("locations")
    elif isinstance(extra, str):
        parsed = _parse_json(extra)
        if isinstance(parsed, Mapping):
            raw = parsed.get("locations")
    if raw is None:
        raw = article.get("locations")
    return _as_location_list(raw)


def _as_location_list(raw: Any) -> List[Mapping[str, Any]]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        raw = _parse_json(raw)
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _source_names(source: str, locations: Iterable[Mapping[str, Any]]) -> Tuple[str, ...]:
    ids: List[str] = []
    seen = set()

    def add(raw: Any) -> None:
        text = str(raw or "").strip().lower()
        if not text or text in seen:
            return
        seen.add(text)
        ids.append(text)

    add(source)
    for loc in locations:
        add(loc.get("via"))
    return tuple(source_display_name(item) for item in ids)
