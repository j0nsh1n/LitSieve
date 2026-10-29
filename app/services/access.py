"""Read-time access labels from stored OA fields. No network check."""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any, Callable, Iterable, List, Mapping, NamedTuple, Optional, Tuple
from urllib.parse import urlsplit

from app.content.source_catalog import source_display_name
from app.services.citations import article_url
from app.services.link_evidence import (
    BASIS_CROSSREF_ENTRY,
    BASIS_DOAJ_FULLTEXT,
    BASIS_HAL_FILE,
    BASIS_LOCATION_OPEN,
    BASIS_OA_BEST,
    EVIDENCE_ABSENT,
    EVIDENCE_OK,
    LICENCE_SCOPE_ENTRY,
    evidence_status_from_article,
    evidence_url_key,
    inspect_link_evidence,
    is_never_merged,
    observation_ownership,
)
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


class LinkWitness(NamedTuple):
    source: str
    source_record_id: str
    observed_at: str
    url: str
    host: Optional[str]
    basis: str


class LinkDecision(NamedTuple):
    open_listed: bool
    reasons: Tuple[str, ...]
    witnesses: Tuple[LinkWitness, ...]


def access_state(article: Any, *, trust_legacy: bool = True) -> AccessInfo:
    """Listed-open copy from stored fields only. Never raises on odd data."""
    try:
        return _access_state(
            article if isinstance(article, Mapping) else {},
            trust_legacy=trust_legacy,
        )
    except Exception:
        return AccessInfo(NONE_LISTED, None, ())


def access_public_dict(info: AccessInfo) -> dict:
    """Card payload: omit url when there is no listed open copy."""
    out = {"state": info.state, "sources": list(info.sources)}
    if info.state == OPEN_LISTED and info.url:
        out["url"] = info.url
    return out


def _use_legacy_access(article: Mapping[str, Any], trust_legacy: bool) -> bool:
    return trust_legacy and is_never_merged(article)


def _access_state(
    article: Mapping[str, Any], *, trust_legacy: bool = True,
) -> AccessInfo:
    source = str(article.get("source") or "").strip()
    locations = _locations(article)
    sources = _source_names(source, locations)
    status, evidence = evidence_status_from_article(article)
    if status == EVIDENCE_OK and evidence is not None:
        url = _card_url_from_index(_index_link_decisions(evidence))
        if url:
            return AccessInfo(OPEN_LISTED, url, sources)
        return AccessInfo(NONE_LISTED, None, sources)
    if status != EVIDENCE_ABSENT:
        return AccessInfo(NONE_LISTED, None, sources)
    if _use_legacy_access(article, trust_legacy):
        url = _open_copy_url(article, source, locations)
        if url:
            return AccessInfo(OPEN_LISTED, url, sources)
        return AccessInfo(NONE_LISTED, None, sources)
    return AccessInfo(NONE_LISTED, None, sources)


def link_access(evidence: Any, url: Any) -> LinkDecision:
    """Whether one URL is an open listed copy, from stored observations only."""
    checked = _http_url(url)
    if not checked:
        return LinkDecision(False, ("invalid_url",), ())
    wanted = evidence_url_key(checked)
    if not wanted:
        return LinkDecision(False, ("invalid_url",), ())
    status, payload = inspect_link_evidence(evidence)
    if status != EVIDENCE_OK or payload is None:
        return LinkDecision(False, ("missing_evidence",), ())
    return _index_link_decisions(payload).get(
        wanted, LinkDecision(False, ("missing_evidence",), ()),
    )


def _index_link_decisions(evidence: Mapping[str, Any]) -> dict[str, LinkDecision]:
    grouped: dict[str, List[Tuple[Mapping[str, Any], Mapping[str, Any], str]]] = {}
    for observation in evidence.get("observations") or []:
        if not isinstance(observation, Mapping):
            continue
        locations = observation.get("locations")
        if not isinstance(locations, list):
            continue
        for loc in locations:
            if not isinstance(loc, Mapping):
                continue
            loc_url = _http_url(loc.get("url"))
            if not loc_url:
                continue
            key = evidence_url_key(loc_url)
            if not key:
                continue
            grouped.setdefault(key, []).append((observation, loc, loc_url))
    out: dict[str, LinkDecision] = {}
    for key, items in grouped.items():
        witnesses: List[LinkWitness] = []
        reasons: List[str] = []
        for observation, loc, loc_url in items:
            witness, reason = _witness_from_location(observation, loc, loc_url)
            if witness is not None:
                witnesses.append(witness)
            elif reason:
                reasons.append(reason)
        if witnesses:
            witnesses.sort(key=lambda item: (
                item.source, item.source_record_id, item.observed_at, item.url,
            ))
            out[key] = LinkDecision(True, (witnesses[0].basis,), tuple(witnesses))
            continue
        unique: List[str] = []
        seen = set()
        for reason in reasons:
            if reason in seen:
                continue
            seen.add(reason)
            unique.append(reason)
        if not unique:
            unique.append("missing_evidence")
        out[key] = LinkDecision(False, tuple(unique), ())
    return out


def _witness_from_location(
    observation: Mapping[str, Any], loc: Mapping[str, Any], url: str,
) -> Tuple[Optional[LinkWitness], Optional[str]]:
    owner = observation_ownership(observation)
    if owner is None:
        return None, "missing_evidence"
    source, record_id, observed_at = owner
    basis = str(loc.get("basis") or "").strip()
    kind = str(loc.get("kind") or "").strip().lower()
    if basis == BASIS_CROSSREF_ENTRY:
        if str(loc.get("licence_scope") or "") != LICENCE_SCOPE_ENTRY:
            return None, "missing_entry_licence"
        if not _has_cc_licence(loc.get("licence") or loc.get("license")):
            return None, "missing_entry_licence"
    elif basis == BASIS_HAL_FILE:
        if kind != "file":
            return None, "hal_not_file"
        if not _status_is_open(loc.get("oa_status")):
            return None, "closed_status"
    elif basis == BASIS_DOAJ_FULLTEXT:
        pass
    elif basis in {BASIS_OA_BEST, BASIS_LOCATION_OPEN}:
        if not _status_is_open(loc.get("oa_status")):
            return None, "closed_status"
    else:
        return None, "missing_evidence"
    return LinkWitness(
        source=source,
        source_record_id=record_id,
        observed_at=observed_at,
        url=url,
        host=_text_or_none(loc.get("host")),
        basis=basis,
    ), None


def _card_url_from_index(index: Mapping[str, LinkDecision]) -> Optional[str]:
    ranked: List[Tuple[int, str, str]] = []
    seen = set()
    for decision in index.values():
        if not decision.open_listed or not decision.witnesses:
            continue
        witness = decision.witnesses[0]
        source = witness.source
        if source == "doaj":
            priority = 0
        elif source == "crossref":
            priority = 2
        else:
            priority = 1
        marker = (priority, source, witness.url)
        if marker in seen:
            continue
        seen.add(marker)
        ranked.append(marker)
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][2]


def _text_or_none(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


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


def other_copies(
    article: Any, same_work_rows: Any = None, *, trust_legacy: bool = True,
) -> List[CopyInfo]:
    """Other listed copies of the same work. Never raises on odd data."""
    return other_copies_result(
        article, same_work_rows, trust_legacy=trust_legacy,
    ).copies


def other_copies_result(
    article: Any, same_work_rows: Any = None, *, trust_legacy: bool = True,
) -> CopySet:
    """Display copies plus whether any open same-work URL exists."""
    try:
        rows = same_work_rows if isinstance(same_work_rows, list) else []
        body = article if isinstance(article, Mapping) else {}
        copies, has_open = _other_copies(body, rows, trust_legacy=trust_legacy)
        return CopySet(copies, has_open)
    except Exception:
        return CopySet([], False)


def copy_public_dict(info: CopyInfo) -> dict:
    return {"where": info.where, "url": info.url, "open_listed": info.open_listed}


def other_copies_payload(
    articles: Mapping[Tuple[str, str], Any],
    same_work_rows: Iterable[Any] = (),
    *,
    trust_legacy: bool = True,
) -> List[dict]:
    """Public payload for starred none-listed cards. Empty when nothing to show."""
    try:
        return _other_copies_payload(
            articles, same_work_rows, trust_legacy=trust_legacy,
        )
    except Exception:
        return []


def _other_copies_payload(
    articles: Mapping[Tuple[str, str], Any],
    same_work_rows: Iterable[Any],
    *,
    trust_legacy: bool = True,
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
        if access_state(raw, trust_legacy=trust_legacy).state != NONE_LISTED:
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
        found = other_copies_result(raw, peers, trust_legacy=trust_legacy)
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
    article: Mapping[str, Any],
    same_work_rows: List[Any],
    *,
    trust_legacy: bool = True,
) -> Tuple[List[CopyInfo], bool]:
    main = _main_link_key(article)
    selected: dict[str, CopyInfo] = {}
    has_open = False

    def take(
        row: Mapping[str, Any],
        loc: Mapping[str, Any],
        status: str,
        index: Mapping[str, LinkDecision],
    ) -> None:
        nonlocal has_open
        copy = _copy_from_location(
            row, loc, status, index, trust_legacy=trust_legacy,
        )
        if copy is None:
            return
        if copy.open_listed:
            has_open = True
        key = evidence_url_key(copy.url)
        if not key or key == main:
            return
        existing = selected.get(key)
        if existing is None:
            if len(selected) >= COPY_LIMIT:
                return
            selected[key] = copy
            return
        if copy.open_listed and not existing.open_listed:
            selected[key] = copy

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
    take: Callable[
        [Mapping[str, Any], Mapping[str, Any], str, Mapping[str, LinkDecision]],
        None,
    ],
) -> None:
    status, evidence = evidence_status_from_article(row)
    index: Mapping[str, LinkDecision] = (
        _index_link_decisions(evidence) if status == EVIDENCE_OK and evidence is not None else {}
    )
    seen: set[str] = set()

    def emit(loc: Mapping[str, Any]) -> None:
        url = _http_url(loc.get("url"))
        key = evidence_url_key(url) if url else None
        if not key or key in seen:
            return
        seen.add(key)
        take(row, loc, status, index)

    if status == EVIDENCE_OK and evidence is not None:
        for observation in evidence.get("observations") or []:
            if not isinstance(observation, Mapping):
                continue
            if observation_ownership(observation) is None:
                continue
            locations = observation.get("locations")
            if not isinstance(locations, list):
                continue
            for loc in locations:
                if not isinstance(loc, Mapping):
                    continue
                emit({
                    "url": loc.get("url"),
                    "host": loc.get("host"),
                    "via": observation.get("source"),
                    "kind": loc.get("kind"),
                    "licence": loc.get("licence"),
                    "license": loc.get("licence") or loc.get("license"),
                    "source": observation.get("source"),
                })
    for loc in _locations(row):
        emit(loc)
    best = _http_url(row.get("best_oa_url"))
    if best:
        emit({
            "url": best,
            "host": row.get("host_name"),
            "via": row.get("source"),
        })
    for loc in _urls_from_provenance(row):
        emit(loc)


def _copy_from_location(
    row: Mapping[str, Any],
    loc: Mapping[str, Any],
    status: str,
    index: Mapping[str, LinkDecision],
    *,
    trust_legacy: bool = True,
) -> Optional[CopyInfo]:
    url = _http_url(loc.get("url"))
    key = evidence_url_key(url) if url else None
    if not url or not key:
        return None
    open_listed = False
    where = None
    via = str(loc.get("via") or loc.get("source") or "").strip().lower()
    source_id = str(row.get("source") or "").strip().lower()
    kind = str(loc.get("kind") or "").strip().lower()
    licensed = _has_cc_licence(loc.get("license") or loc.get("licence"))
    if status == EVIDENCE_OK:
        decision = index.get(key)
        if decision is not None:
            open_listed = decision.open_listed
            if decision.witnesses:
                where = _witness_where(decision.witnesses[0], loc, row)
                url = decision.witnesses[0].url
        if (
            not open_listed
            and kind == "text-mining"
            and _is_crossref_link(via, source_id)
            and not licensed
        ):
            return None
    elif status == EVIDENCE_ABSENT and _use_legacy_access(row, trust_legacy):
        if _is_crossref_link(via, source_id) and not licensed:
            return None
        open_listed = _legacy_copy_is_open(row, loc, url)
    else:
        if _is_crossref_link(via, source_id) and not licensed:
            return None
        open_listed = False
    return CopyInfo(where or _copy_where(loc, row), url, open_listed)


def _legacy_copy_is_open(
    row: Mapping[str, Any], loc: Mapping[str, Any], url: str,
) -> bool:
    best = _http_url(row.get("best_oa_url"))
    best_key = evidence_url_key(best) if best else None
    this_key = evidence_url_key(url)
    synthetic = {
        "source": loc.get("via") or row.get("source"),
        "oa_status": row.get("oa_status"),
        "best_oa_url": best if best_key and best_key == this_key else None,
        "locations": [loc],
    }
    return access_state(synthetic).state == OPEN_LISTED


def _witness_where(
    witness: LinkWitness, loc: Mapping[str, Any], row: Mapping[str, Any],
) -> str:
    host = str(witness.host or "").strip()
    if host and host.casefold() not in _UNKNOWN_HOSTS:
        return host
    if witness.source:
        name = source_display_name(witness.source)
        if name:
            return name
    loc_url = _http_url(loc.get("url"))
    loc_key = evidence_url_key(loc_url) if loc_url else None
    witness_key = evidence_url_key(witness.url)
    if loc_key and witness_key and loc_key == witness_key:
        return _copy_where(loc, row)
    return "publisher page"


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
    return evidence_url_key(checked)


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
