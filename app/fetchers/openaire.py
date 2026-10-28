"""
OpenAIRE Explore publications fetcher.

Free REST API: https://api.openaire.eu/search/publications
No key for basic classroom use. Aggregates European open-access deposits.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.fetchers.base import (
    BaseFetcher,
    FetchError,
    HttpClient,
    clean_text,
    json_of,
    reraise_fetch_error,
    user_agent,
)
from app.services.work_types import (
    as_list,
    attach_work_fields,
    join_provider_types,
    normalize_doi,
    pick_canonical_work_type,
)


def _node_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node.strip()
    if isinstance(node, dict):
        if "$" in node:
            return str(node["$"]).strip()
        if "text" in node:
            return str(node["text"]).strip()
        return ""
    if isinstance(node, list):
        for item in node:
            t = _node_text(item)
            if t:
                return t
        return ""
    return str(node).strip()


def _node_list_text(node: Any) -> List[str]:
    if node is None:
        return []
    if isinstance(node, list):
        out = []
        for item in node:
            t = _node_text(item)
            if t:
                out.append(t)
        return out
    t = _node_text(node)
    return [t] if t else []


def _instance_claims(meta: Dict) -> Tuple[List[str], List[str], List[str]]:
    """Normalize object-or-list shapes at instance, instancetype and hostedby."""
    children_raw = meta.get("children")
    children = children_raw if isinstance(children_raw, dict) else {}
    types: List[str] = []
    hosts: List[str] = []
    urls: List[str] = []
    for inst in as_list(children.get("instance")):
        if not isinstance(inst, dict):
            continue
        for node in as_list(inst.get("instancetype")):
            name = ""
            if isinstance(node, dict):
                name = str(node.get("@classname") or node.get("$") or "").strip()
            else:
                name = str(node).strip()
            if name and name not in types:
                types.append(name)
        for node in as_list(inst.get("hostedby")):
            name = ""
            if isinstance(node, dict):
                name = str(node.get("@name") or "").strip()
            else:
                name = str(node).strip()
            if name and name.lower() != "unknown repository" and name not in hosts:
                hosts.append(name)
        for node in as_list(inst.get("webresource")):
            href = _node_text(node.get("url") if isinstance(node, dict) else node)
            if href and href not in urls:
                urls.append(href)
    return types, hosts, urls


def _access_classname(meta: Dict) -> str:
    node = meta.get("bestaccessright")
    if isinstance(node, dict):
        return str(node.get("@classname") or "").strip()
    return str(node or "").strip()


class OpenAIREFetcher(BaseFetcher):
    SOURCE_NAME = "openaire"
    BASE_URL = "https://api.openaire.eu/search/publications"

    def __init__(self, email: Optional[str] = None):
        self.http = HttpClient(
            delay=0.45,
            timeout=45,
            user_agent=user_agent(email),
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles: List[Dict] = []
        page = 1
        # OpenAIRE pages can be heavy; keep page size modest.
        # The size stays constant: pages are numbered, so a smaller later page
        # would start inside records the earlier pages already returned.
        size = 25

        while len(articles) < max_results:
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={
                        "keywords": query,
                        "size": size,
                        "page": page,
                        "format": "json",
                    },
                )
                data = json_of(r)
            except FetchError as e:
                reraise_fetch_error(e, articles)
            except Exception as e:
                raise FetchError(
                    f"OpenAIRE request failed: {e}", kind="network", articles=articles
                ) from e

            results = (
                ((data.get("response") or {}).get("results") or {}).get("result")
            )
            if not results:
                break
            if isinstance(results, dict):
                results = [results]
            for res in results:
                art = self._parse(res)
                if art:
                    articles.append(art)
            if len(results) < size:
                break
            page += 1
            # Hard stop to avoid runaway pagination on huge totals
            if page > 40:
                break

        if not articles:
            raise FetchError("No OpenAIRE publications matched your query.", kind="no_results")
        return articles[:max_results]

    def _parse(self, res: Dict) -> Optional[Dict]:
        try:
            meta = (
                ((res.get("metadata") or {}).get("oaf:entity") or {}).get("oaf:result")
                or {}
            )
            if not meta:
                return None
            title = clean_text(_node_text(meta.get("title")))
            abstract = clean_text(_node_text(meta.get("description")))
            if not title or not abstract:
                return None

            authors = []
            for a in _node_list_text(meta.get("creator")):
                if a:
                    authors.append(a)
            # creator list may need special handling
            raw_creators = meta.get("creator")
            if isinstance(raw_creators, list):
                authors = []
                for c in raw_creators:
                    name = _node_text(c)
                    if name:
                        authors.append(name)
            elif isinstance(raw_creators, dict):
                name = _node_text(raw_creators)
                authors = [name] if name else []

            date = _node_text(meta.get("dateofacceptance") or meta.get("relevantdate"))
            year = date[:4] if date else ""
            journal = _node_text(meta.get("journal"))

            # Prefer a DOI, else the first pid (a PMID is a JSON number, so it is
            # stringified), else the OpenAIRE object id.
            pid = meta.get("pid")
            pids = pid if isinstance(pid, list) else [pid]
            aid = ""
            doi = None
            for p in pids:
                if isinstance(p, dict) and str(p.get("@classid", "")).lower() == "doi":
                    aid = _node_text(p)
                    doi = normalize_doi(aid)
                    if aid:
                        break
            if not aid:
                for p in pids:
                    aid = _node_text(p)
                    if aid:
                        break
            if not aid:
                aid = _node_text(
                    ((res.get("header") or {}).get("dri:objIdentifier"))
                )
            if not aid:
                return None

            inst_types, hosts, _urls = _instance_claims(meta)
            raw_types = inst_types or [_node_text((meta.get("resulttype") or {}).get("@classname"))]
            access = _access_classname(meta).lower()
            oa_status = None if access in ("", "unspecified", "unknown") else access
            extra = {
                "pid": meta.get("pid"),
                "resulttype": meta.get("resulttype"),
                "instancetype": inst_types,
                "hostedby": hosts,
                "bestaccessright": meta.get("bestaccessright"),
                "journal": meta.get("journal"),
                "dateofacceptance": meta.get("dateofacceptance"),
            }
            article = {
                "article_id": aid,
                "source": "openaire",
                "title": title,
                "abstract": abstract,
                "year": year,
                "authors": authors,
                "journal": journal,
            }
            return attach_work_fields(
                article,
                "openaire",
                extra,
                work_type=pick_canonical_work_type("openaire", raw_types),
                provider_type=join_provider_types("openaire", raw_types),
                doi=doi,
                container_title=journal or None,
                host_name=hosts[0] if hosts else None,
                oa_status=oa_status,
            )
        except Exception:
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a["article_id"] for a in self.search_and_fetch(query, max_results)]
