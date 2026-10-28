"""
HAL (Hyper Articles en Ligne) — French national open archive.

Free Solr API: https://api.archives-ouvertes.fr/search/
No key required. Multidisciplinary open-access / institutional deposit.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.fetchers.base import (
    BaseFetcher,
    FetchError,
    HttpClient,
    json_of,
    reraise_fetch_error,
    user_agent,
)
from app.fetchers.querytext import solr_safe
from app.services.work_types import (
    attach_work_fields,
    build_location,
    canonical_work_type,
    join_provider_types,
    normalize_doi,
)


class HALFetcher(BaseFetcher):
    SOURCE_NAME = "hal"
    BASE_URL = "https://api.archives-ouvertes.fr/search/"

    def __init__(self, email: Optional[str] = None):
        self.http = HttpClient(
            delay=0.35,
            user_agent=user_agent(email),
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles: List[Dict] = []
        start = 0
        page_size = min(100, max_results)
        q = self.remember_sent_query(solr_safe(query))
        if not q:
            raise FetchError("HAL needs search words.", kind="bad_query")

        while len(articles) < max_results:
            rows = min(page_size, max_results - len(articles))
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={
                        "q": q,
                        "wt": "json",
                        "rows": rows,
                        "start": start,
                        "fl": (
                            "halId_s,title_s,abstract_s,authFullName_s,"
                            "producedDateY_i,journalTitle_s,doiId_s,"
                            "docType_s,submitType_s,fileMain_s"
                        ),
                    },
                )
                docs = (json_of(r).get("response") or {}).get("docs") or []
            except FetchError as e:
                reraise_fetch_error(e, articles)
            except Exception as e:
                raise FetchError(f"HAL request failed: {e}", kind="network") from e

            if not docs:
                break
            for doc in docs:
                art = self._parse(doc)
                if art:
                    articles.append(art)
            if len(docs) < rows:
                break
            start += len(docs)

        if not articles:
            raise FetchError("No HAL records matched your query.", kind="no_results")
        return articles[:max_results]

    @staticmethod
    def _first(val: Any) -> str:
        if val is None:
            return ""
        if isinstance(val, list):
            return str(val[0]).strip() if val else ""
        return str(val).strip()

    def _parse(self, doc: Dict) -> Optional[Dict]:
        try:
            title = self._first(doc.get("title_s"))
            abstract = self._first(doc.get("abstract_s"))
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()
            if not title or not abstract:
                return None
            authors = doc.get("authFullName_s") or []
            if isinstance(authors, str):
                authors = [authors]
            authors = [str(a).strip() for a in authors if str(a).strip()]
            year = doc.get("producedDateY_i")
            year = str(year) if year else ""
            journal = self._first(doc.get("journalTitle_s"))
            aid = self._first(doc.get("doiId_s")) or self._first(doc.get("halId_s"))
            if not aid:
                return None
            raw_type = self._first(doc.get("docType_s"))
            submit = self._first(doc.get("submitType_s")).lower()
            file_main = self._first(doc.get("fileMain_s"))
            is_file = submit == "file" and bool(file_main)
            loc = build_location(
                url=file_main if is_file else None,
                kind="file",
                host="HAL",
                via="hal",
            )
            article = {
                "article_id": aid,
                "source": "hal",
                "title": title,
                "abstract": abstract,
                "year": year,
                "authors": authors,
                "journal": journal,
            }
            return attach_work_fields(
                article,
                "hal",
                doc,
                work_type=canonical_work_type("hal", raw_type),
                provider_type=join_provider_types("hal", raw_type),
                doi=normalize_doi(self._first(doc.get("doiId_s"))),
                container_title=journal or None,
                host_name="HAL",
                oa_status="green" if is_file else None,
                best_oa_url=file_main if is_file else None,
                locations=[loc] if loc else None,
            )
        except Exception:
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a["article_id"] for a in self.search_and_fetch(query, max_results)]
