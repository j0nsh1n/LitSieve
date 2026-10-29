"""Read-time access labels from stored OA fields. No network check."""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any, Callable, Iterable, List, Mapping, NamedTuple, Optional, Tuple
from urllib.parse import urlsplit

from app.content.source_catalog import source_display_name
from app.services.citations import article_url
from app.services.work_types import normalize_doi

OPEN_LISTED = "open_listed"
NONE_LISTED = "none_listed"
COPY_LIMIT = 5
_URL_CONFLICT_FIELDS = frozenset({"best_oa_url"})
_UNKNOWN_HOSTS = frozenset({"", "unknown repository"})

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


class CopyInfo(NamedTuple):
    where: str
    url: str
    open_listed: bool


class CopySet(NamedTuple):
    copies: List[CopyInfo]
    has_open_copy: bool


class _UrlRecord(NamedTuple):
    url: str
    source: str
    oa_status: Any
    licence: Any
    crossref_location: bool


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
    licensed_crossref = None
    doaj_url = None
    best = None
    other = None
    seen: set[str] = set()

    def consider(url: str, loc: Mapping[str, Any]) -> None:
        nonlocal licensed_crossref, doaj_url, best, other
        key = _url_key(url)
        if not key or key in seen:
            return
        seen.add(key)
        if not _url_is_open(article, url, loc):
            return
        via = str(loc.get("via") or "").strip().lower()
        source_id = str(source or "").strip().lower()
        if _is_crossref_link(via, source_id):
            licensed_crossref = licensed_crossref or url
            return
        if via == "doaj" or source_id == "doaj":
            doaj_url = doaj_url or url
            return
        retained_best = _http_url(article.get("best_oa_url"))
        if retained_best and _url_key(retained_best) == key:
            best = best or url
            return
        other = other or url

    for loc in locations:
        url = _http_url(loc.get("url"))
        if url:
            consider(url, loc)
    best_url = _http_url(article.get("best_oa_url"))
    if best_url:
        filler = str(_provenance_mapping(article).get("best_oa_url") or "").strip()
        consider(best_url, {
            "url": best_url,
            "host": article.get("host_name"),
            "via": filler,
        })
    for loc in _urls_from_provenance(article):
        url = _http_url(loc.get("url"))
        if url:
            consider(url, loc)
    return doaj_url or best or other or licensed_crossref


def _url_is_open(
    article: Mapping[str, Any], url: Any, loc: Any = None,
) -> bool:
    """Open copy for this URL from records owned by the same source as the URL."""
    checked = _http_url(url)
    if not checked:
        return False
    this_key = _url_key(checked)
    if not this_key:
        return False
    records = list(_url_records(article))
    if isinstance(loc, Mapping):
        extra = _record_from_location(article, loc)
        if extra is not None:
            records.append(extra)
    return any(
        _url_key(record.url) == this_key and _record_says_open(record)
        for record in records
    )


def _url_records(article: Mapping[str, Any]) -> List[_UrlRecord]:
    """(url, source, oa_status of that source, licence) from the row, locations, provenance."""
    out: List[_UrlRecord] = []
    for loc in _locations(article):
        record = _record_from_location(article, loc)
        if record is not None:
            out.append(record)
    best = _http_url(article.get("best_oa_url"))
    if best:
        owner = _field_owner(article, "best_oa_url")
        out.append(_UrlRecord(
            best,
            owner,
            _oa_status_for_source(article, owner),
            None,
            False,
        ))
    for loc in _urls_from_provenance(article):
        record = _record_from_location(article, loc)
        if record is not None:
            out.append(record)
    return out


def _record_from_location(
    article: Mapping[str, Any], loc: Mapping[str, Any],
) -> Optional[_UrlRecord]:
    url = _http_url(loc.get("url"))
    if not url:
        return None
    via = str(loc.get("via") or "").strip().lower()
    article_source = str(article.get("source") or "").strip().lower()
    crossref_location = _is_crossref_location(via, loc, article_source)
    source = via or ("crossref" if crossref_location else "")
    return _UrlRecord(
        url,
        source,
        _oa_status_for_source(article, source) if source else None,
        loc.get("license") or loc.get("licence"),
        crossref_location,
    )


def _record_says_open(record: _UrlRecord) -> bool:
    if record.source == "doaj":
        return True
    if record.crossref_location:
        return _has_cc_licence(record.licence)
    return _status_is_open(record.oa_status)


def _is_crossref_location(
    via: str, loc: Mapping[str, Any], article_source: str,
) -> bool:
    if via == "crossref":
        return True
    if via:
        return False
    if article_source != "crossref":
        return False
    return bool(loc.get("kind") or loc.get("license") or loc.get("licence"))


def _field_owner(article: Mapping[str, Any], field: str) -> str:
    filled = str(_provenance_mapping(article).get(field) or "").strip().lower()
    if filled:
        return filled
    return str(article.get("source") or "").strip().lower()


def _oa_status_for_source(article: Mapping[str, Any], source_id: str) -> Any:
    wanted = str(source_id or "").strip().lower()
    if not wanted:
        return None
    conflict = _conflict_value_for_source(
        _provenance_conflicts(article), "oa_status", wanted,
    )
    if conflict is not None:
        return conflict
    filled = str(_provenance_mapping(article).get("oa_status") or "").strip().lower()
    if filled == wanted:
        return article.get("oa_status")
    article_source = str(article.get("source") or "").strip().lower()
    if wanted == article_source and not filled:
        return article.get("oa_status")
    return None


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


def other_copies(article: Any, same_work_rows: Any = None) -> List[CopyInfo]:
    """Other listed copies of the same work. Never raises on odd data."""
    return other_copies_result(article, same_work_rows).copies


def other_copies_result(article: Any, same_work_rows: Any = None) -> CopySet:
    """Display copies plus whether any open same-work URL exists."""
    try:
        rows = same_work_rows if isinstance(same_work_rows, list) else []
        body = article if isinstance(article, Mapping) else {}
        copies, has_open = _other_copies(body, rows)
        return CopySet(copies, has_open)
    except Exception:
        return CopySet([], False)


def copy_public_dict(info: CopyInfo) -> dict:
    return {"where": info.where, "url": info.url, "open_listed": info.open_listed}


def other_copies_payload(
    articles: Mapping[Tuple[str, str], Any],
    same_work_rows: Iterable[Any] = (),
) -> List[dict]:
    """Public payload for starred none-listed cards. Empty when nothing to show."""
    try:
        return _other_copies_payload(articles, same_work_rows)
    except Exception:
        return []


def _other_copies_payload(
    articles: Mapping[Tuple[str, str], Any],
    same_work_rows: Iterable[Any],
) -> List[dict]:
    peers_by_doi: dict[str, List[Mapping[str, Any]]] = {}
    for raw in same_work_rows:
        if not isinstance(raw, Mapping):
            continue
        doi = _work_doi(raw.get("doi"))
        if not doi:
            continue
        peers_by_doi.setdefault(doi, []).append(raw)

    out: List[dict] = []
    for key, raw in articles.items():
        if not isinstance(raw, Mapping):
            continue
        if access_state(raw).state != NONE_LISTED:
            continue
        article_id, source = key
        doi = _work_doi(raw.get("doi"))
        peers = []
        if doi:
            for peer in peers_by_doi.get(doi, []):
                peer_key = (
                    str(peer.get("article_id") or ""),
                    str(peer.get("source") or ""),
                )
                if peer_key != (article_id, source):
                    peers.append(peer)
        found = other_copies_result(raw, peers)
        if not found.copies and not found.has_open_copy:
            continue
        out.append({
            "article_id": article_id,
            "source": source,
            "copies": [copy_public_dict(item) for item in found.copies],
            "has_open_copy": found.has_open_copy,
        })
    return out


def _other_copies(
    article: Mapping[str, Any], same_work_rows: List[Any],
) -> Tuple[List[CopyInfo], bool]:
    main = _main_link_key(article)
    selected: dict[str, CopyInfo] = {}
    has_open = False

    def take(row: Mapping[str, Any], loc: Mapping[str, Any]) -> None:
        nonlocal has_open
        copy = _copy_from_location(row, loc)
        if copy is None:
            return
        if copy.open_listed:
            has_open = True
        key = _url_key(copy.url)
        if not key or key == main:
            return
        existing = selected.get(key)
        if existing is None:
            if len(selected) >= COPY_LIMIT:
                return
            selected[key] = copy
            return
        if copy.open_listed and not existing.open_listed:
            selected[key] = existing._replace(open_listed=True)

    _collect_row_copies(article, take)
    article_key = (
        str(article.get("article_id") or ""),
        str(article.get("source") or ""),
    )
    for raw in same_work_rows:
        if not isinstance(raw, Mapping):
            continue
        peer_key = (str(raw.get("article_id") or ""), str(raw.get("source") or ""))
        if peer_key == article_key and peer_key != ("", ""):
            continue
        _collect_row_copies(raw, take)
    return list(selected.values()), has_open


def _collect_row_copies(
    row: Mapping[str, Any],
    take: Callable[[Mapping[str, Any], Mapping[str, Any]], None],
) -> None:
    seen: set[str] = set()

    def once(loc: Mapping[str, Any]) -> None:
        url = _http_url(loc.get("url"))
        key = _url_key(url) if url else None
        if key:
            if key in seen:
                return
            seen.add(key)
        take(row, loc)

    for loc in _locations(row):
        once(loc)
    best = _http_url(row.get("best_oa_url"))
    if best:
        filler = str(_provenance_mapping(row).get("best_oa_url") or "").strip()
        once({
            "url": best,
            "host": row.get("host_name"),
            "via": filler or row.get("source"),
        })
    for loc in _urls_from_provenance(row):
        once(loc)


def _copy_from_location(
    row: Mapping[str, Any], loc: Mapping[str, Any],
) -> Optional[CopyInfo]:
    url = _http_url(loc.get("url"))
    if not url or not _url_key(url):
        return None
    via = str(loc.get("via") or "").strip().lower()
    source_id = str(row.get("source") or "").strip().lower()
    if _is_crossref_link(via, source_id):
        if not _has_cc_licence(loc.get("license") or loc.get("licence")):
            return None
    return CopyInfo(_copy_where(loc, row), url, _copy_is_open(row, loc, url))


def _copy_is_open(
    row: Mapping[str, Any], loc: Mapping[str, Any], url: str,
) -> bool:
    return _url_is_open(row, url, loc)


def _copy_where(loc: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    for raw in (loc.get("host"), row.get("host_name")):
        text = str(raw or "").strip()
        if text and text.casefold() not in _UNKNOWN_HOSTS:
            return text
    via = str(loc.get("via") or "").strip()
    if via:
        name = source_display_name(via.lower())
        if name:
            return name
    source = str(row.get("source") or "").strip()
    if source:
        name = source_display_name(source.lower())
        if name:
            return name
    return "publisher page"


def _work_doi(value: Any) -> Optional[str]:
    normalized = normalize_doi(value)
    if normalized:
        return normalized
    text = str(value or "").strip().lower()
    return text or None


def _main_link_key(article: Mapping[str, Any]) -> Optional[str]:
    try:
        url = article_url(dict(article))
    except Exception:
        return None
    checked = _http_url(url)
    if not checked:
        return None
    return _url_key(checked)


def _url_key(url: str) -> Optional[str]:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if not host:
            return None
        path = (parsed.path or "").rstrip("/")
        port = parsed.port
        if port in (80, 443):
            port = None
        netloc = host if port is None else f"{host}:{port}"
        query = parsed.query
        return f"{netloc}{path}?{query}" if query else f"{netloc}{path}"
    except Exception:
        return None


def _extra_mapping(article: Mapping[str, Any]) -> Mapping[str, Any]:
    extra = article.get("_extra")
    if isinstance(extra, Mapping):
        return extra
    if isinstance(extra, str):
        parsed = _parse_json(extra)
        if isinstance(parsed, Mapping):
            return parsed
    return {}


def _provenance_mapping(article: Mapping[str, Any]) -> Mapping[str, Any]:
    extra = _extra_mapping(article)
    raw = extra.get("provenance") if extra else None
    if raw is None:
        raw = article.get("provenance")
    if isinstance(raw, str):
        raw = _parse_json(raw)
    return raw if isinstance(raw, Mapping) else {}


def _provenance_conflicts(article: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = _provenance_mapping(article).get("conflicts")
    return raw if isinstance(raw, Mapping) else {}


def _conflict_entries(conflicts: Mapping[str, Any], field: str) -> List[Mapping[str, Any]]:
    payload = conflicts.get(field)
    if payload is None:
        return []
    entries = payload if isinstance(payload, list) else [payload]
    return [entry for entry in entries if isinstance(entry, Mapping)]


def _conflict_value_for_source(
    conflicts: Mapping[str, Any], field: str, source: str,
) -> Any:
    wanted = str(source or "").strip().lower()
    if not wanted:
        return None
    for entry in _conflict_entries(conflicts, field):
        if str(entry.get("source") or "").strip().lower() == wanted:
            return entry.get("value")
    return None


def _urls_from_provenance(article: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    conflicts = _provenance_conflicts(article)
    if not conflicts:
        return []
    out: List[Mapping[str, Any]] = []
    for field, payload in conflicts.items():
        if str(field or "") not in _URL_CONFLICT_FIELDS:
            continue
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            url = _http_url(entry.get("value"))
            if not url:
                continue
            loc: dict = {"url": url}
            via = str(entry.get("source") or "").strip()
            if via:
                loc["via"] = via
            out.append(loc)
    return out
