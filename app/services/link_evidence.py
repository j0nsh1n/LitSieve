"""Per-source link evidence: adapters, merge reducer, and legacy merge detection."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

LINK_EVIDENCE_KEY = "link_evidence"
EVIDENCE_VERSION = 1
BASIS_OA_BEST = "oa_best"
BASIS_LOCATION_OPEN = "location_open"
BASIS_HAL_FILE = "hal_file"
BASIS_DOAJ_FULLTEXT = "doaj_fulltext"
BASIS_CROSSREF_ENTRY = "crossref_entry"
BASIS_LISTED_ONLY = "listed_only"
LICENCE_SCOPE_ENTRY = "entry"
LICENCE_SCOPE_RECORD = "record"
_LOCATION_KEYS = (
    "url",
    "oa_status",
    "licence",
    "licence_scope",
    "kind",
    "host",
    "basis",
    "details",
)
_RESERVED_PROVENANCE = frozenset({LINK_EVIDENCE_KEY, "conflicts"})


class UnreadableLinkEvidence(ValueError):
    """Stored evidence cannot be kept without erasing or guessing."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def evidence_url_key(url: str) -> Optional[str]:
    """Identity key for one listed URL. Scheme and trailing slash stay."""
    try:
        parsed = urlsplit(url)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
        if scheme not in {"http", "https"} or not host:
            return None
        port = parsed.port
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            port = None
        netloc = host if port is None else f"{host}:{port}"
        path = parsed.path or ""
        query = parsed.query
        fragment = parsed.fragment
        key = f"{scheme}://{netloc}{path}"
        if query:
            key = f"{key}?{query}"
        if fragment:
            key = f"{key}#{fragment}"
        return key
    except Exception:
        return None


def empty_evidence() -> Dict[str, Any]:
    return {"version": EVIDENCE_VERSION, "observations": []}


def parse_link_evidence(raw: Any) -> Optional[Dict[str, Any]]:
    """Trusted version-1 evidence, or None when missing or unusable on read."""
    payload = _unwrap_evidence(raw)
    if payload is None:
        return None
    if payload.get("version") != EVIDENCE_VERSION:
        return None
    observations = payload.get("observations")
    if not isinstance(observations, list):
        return None
    return payload


def _unwrap_evidence(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, Mapping):
        return None
    nested = raw.get(LINK_EVIDENCE_KEY) if LINK_EVIDENCE_KEY in raw else raw
    if nested is None or nested == "":
        return None
    if isinstance(nested, str):
        try:
            nested = json.loads(nested)
        except json.JSONDecodeError:
            return None
    return dict(nested) if isinstance(nested, Mapping) else None


def evidence_from_article(article: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    extra = article.get("_extra")
    provenance = None
    if isinstance(extra, Mapping):
        provenance = extra.get("provenance")
    if provenance is None:
        provenance = article.get("provenance")
    if isinstance(provenance, str):
        try:
            provenance = json.loads(provenance)
        except json.JSONDecodeError:
            provenance = None
    if not isinstance(provenance, Mapping):
        return None
    return parse_link_evidence(provenance.get(LINK_EVIDENCE_KEY))


def is_never_merged(row: Any) -> bool:
    """True when provenance shows no value from a source other than the row."""
    if not isinstance(row, Mapping):
        return True
    own = str(row.get("source") or "").strip().lower()
    provenance = _provenance_of(row)
    if provenance is None:
        return True
    if not isinstance(provenance, Mapping):
        return False
    if not provenance:
        return True
    for key, value in provenance.items():
        if key in _RESERVED_PROVENANCE:
            continue
        if _source_text(value) and _source_text(value) != own:
            return False
    conflicts = provenance.get("conflicts")
    if not isinstance(conflicts, Mapping):
        return True
    for payload in conflicts.values():
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            other = _source_text(entry.get("source"))
            if other and other != own:
                return False
    return True


def observation_from_record(incoming: Mapping[str, Any]) -> Dict[str, Any]:
    """Build one trusted observation. Incoming JSON cannot supply this key."""
    source = str(incoming.get("source") or "").strip().lower()
    source_record_id = str(incoming.get("article_id") or incoming.get("source_record_id") or "")
    observed_at = str(incoming.get("observed_at") or "")
    locations = _incoming_locations(incoming)
    oa_status = _text(incoming.get("oa_status"))
    best_url = _text(incoming.get("best_oa_url"))
    built: List[Dict[str, Any]] = []
    seen_best = False
    for loc in locations:
        url = _text(loc.get("url") or loc.get("URL"))
        if not url:
            continue
        is_best = bool(best_url) and evidence_url_key(url) == evidence_url_key(best_url)
        if is_best:
            seen_best = True
        built.append(_location_evidence(source, loc, url, oa_status, is_best))
    if best_url and not seen_best:
        built.append(_location_evidence(
            source,
            {"url": best_url, "kind": None, "host": _text(incoming.get("host_name"))},
            best_url,
            oa_status,
            True,
        ))
    return _normalize_observation({
        "source": source,
        "source_record_id": source_record_id,
        "observed_at": observed_at,
        "locations": built,
    })


def merge_link_evidence(existing_evidence: Any, incoming_record: Mapping[str, Any]) -> Dict[str, Any]:
    """Pure set-union of complete observations. Does not mutate inputs."""
    incoming = observation_from_record(incoming_record)
    existing, unsupported = _load_existing_for_write(existing_evidence)
    observations = [_normalize_observation(item) for item in existing]
    observations.append(incoming)
    merged = _unique_sorted(observations, _normalize_observation)
    out: Dict[str, Any] = {
        "version": EVIDENCE_VERSION,
        "observations": merged,
    }
    if unsupported:
        out["unsupported"] = list(unsupported)
    return json.loads(canonical_json(out))


def serialize_link_evidence(evidence: Mapping[str, Any]) -> str:
    return canonical_json(evidence)


def _load_existing_for_write(existing_evidence: Any) -> Tuple[List[Any], List[Any]]:
    if existing_evidence is None or existing_evidence == "":
        return [], []
    raw = existing_evidence
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UnreadableLinkEvidence("unreadable link_evidence") from exc
    if not isinstance(raw, Mapping):
        raise UnreadableLinkEvidence("unreadable link_evidence")
    version = raw.get("version")
    observations = raw.get("observations")
    unsupported = list(raw.get("unsupported") or [])
    if version is None and observations is None and not unsupported:
        # Unversioned leftover blob: keep it, do not treat as observations.
        if raw:
            return [], [json.loads(canonical_json(dict(raw)))]
        return [], []
    if version != EVIDENCE_VERSION:
        return [], [json.loads(canonical_json(dict(raw)))]
    if not isinstance(observations, list):
        raise UnreadableLinkEvidence("unreadable link_evidence")
    kept = []
    for item in observations:
        if not isinstance(item, Mapping):
            raise UnreadableLinkEvidence("unreadable link_evidence")
        kept.append(dict(item))
    extra = [item for item in unsupported if item is not None]
    return kept, extra


def _normalize_observation(item: Mapping[str, Any]) -> Dict[str, Any]:
    locations = item.get("locations") or []
    if not isinstance(locations, list):
        locations = []
    normalized_locations = _unique_sorted(
        [_normalize_location(loc) for loc in locations if isinstance(loc, Mapping)],
        lambda loc: loc,
    )
    return {
        "source": str(item.get("source") or ""),
        "source_record_id": str(item.get("source_record_id") or ""),
        "observed_at": str(item.get("observed_at") or ""),
        "locations": normalized_locations,
    }


def _normalize_location(loc: Mapping[str, Any]) -> Dict[str, Any]:
    details = loc.get("details")
    if not isinstance(details, Mapping):
        details = {}
    out = {
        "url": _text(loc.get("url")) or "",
        "oa_status": _text(loc.get("oa_status")),
        "licence": _text(loc.get("licence") or loc.get("license")),
        "licence_scope": _text(loc.get("licence_scope")),
        "kind": _text(loc.get("kind")),
        "host": _text(loc.get("host")),
        "basis": _text(loc.get("basis")) or BASIS_LISTED_ONLY,
        "details": json.loads(canonical_json(dict(details))),
    }
    return {key: out[key] for key in _LOCATION_KEYS}


def _unique_sorted(items: Sequence[Mapping[str, Any]], normalize) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        normalized = normalize(item)
        marker = canonical_json(normalized)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(normalized)
    out.sort(key=canonical_json)
    return out


def _location_evidence(
    source: str,
    loc: Mapping[str, Any],
    url: str,
    record_status: Optional[str],
    is_best: bool,
) -> Dict[str, Any]:
    kind = _text(loc.get("kind"))
    host = _text(loc.get("host"))
    licence = _text(loc.get("licence") or loc.get("license"))
    version = _text(loc.get("version"))
    details: Dict[str, Any] = {}
    if version:
        details["version"] = version
    raw_license = _text(loc.get("license"))
    raw_licence = _text(loc.get("licence"))
    if raw_license and raw_licence and raw_license != raw_licence:
        details["license"] = raw_license
    basis, oa_status, licence_scope = _basis_for(
        source, kind, licence, record_status, is_best, loc,
    )
    return _normalize_location({
        "url": url,
        "oa_status": oa_status,
        "licence": licence if licence_scope == LICENCE_SCOPE_ENTRY else None,
        "licence_scope": licence_scope,
        "kind": kind,
        "host": host,
        "basis": basis,
        "details": details,
    })


def _basis_for(
    source: str,
    kind: Optional[str],
    licence: Optional[str],
    record_status: Optional[str],
    is_best: bool,
    loc: Mapping[str, Any],
) -> Tuple[str, Optional[str], Optional[str]]:
    own_status = _text(loc.get("oa_status"))
    if source == "crossref":
        if licence:
            return BASIS_CROSSREF_ENTRY, None, LICENCE_SCOPE_ENTRY
        return BASIS_LISTED_ONLY, None, None
    if source == "hal":
        if kind == "file" or is_best:
            return BASIS_HAL_FILE, own_status or record_status, None
        return BASIS_LISTED_ONLY, None, None
    if source == "doaj":
        if kind == "fulltext" or is_best:
            return BASIS_DOAJ_FULLTEXT, own_status or record_status, None
        return BASIS_LISTED_ONLY, None, None
    if is_best:
        return BASIS_OA_BEST, own_status or record_status, (
            LICENCE_SCOPE_ENTRY if licence else None
        )
    if own_status:
        return BASIS_LOCATION_OPEN, own_status, (
            LICENCE_SCOPE_ENTRY if licence else None
        )
    return BASIS_LISTED_ONLY, None, None


def _incoming_locations(incoming: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    extra = incoming.get("extra")
    raw = None
    if isinstance(extra, Mapping):
        raw = extra.get("locations")
    if raw is None:
        raw = incoming.get("locations")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _provenance_of(row: Mapping[str, Any]) -> Any:
    extra = row.get("_extra")
    raw = None
    if isinstance(extra, Mapping):
        raw = extra.get("provenance")
    if raw is None:
        raw = row.get("provenance")
    if raw is None:
        return None
    if isinstance(raw, str):
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _source_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    return text or None


def incoming_record_from_article(
    article: Mapping[str, Any],
    extra: Optional[Mapping[str, Any]],
    observed_at: str,
) -> Dict[str, Any]:
    """Fetch envelope for the reducer. Drops any claimed link_evidence."""
    payload_extra: Dict[str, Any] = dict(extra or {})
    provenance = payload_extra.get("provenance")
    if isinstance(provenance, Mapping):
        cleaned = {key: value for key, value in provenance.items() if key != LINK_EVIDENCE_KEY}
        payload_extra["provenance"] = cleaned
    return {
        "source": article.get("source"),
        "article_id": article.get("article_id"),
        "oa_status": article.get("oa_status"),
        "best_oa_url": article.get("best_oa_url"),
        "host_name": article.get("host_name"),
        "locations": payload_extra.get("locations") or [],
        "extra": payload_extra,
        "observed_at": observed_at,
    }
