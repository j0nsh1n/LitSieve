"""Other listed copies of a starred paper: other_copies rules."""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.services.access import (
    COPY_LIMIT,
    OPEN_LISTED,
    CopyInfo,
    access_state,
    other_copies,
    other_copies_result,
)
from app.services.pipeline import LiteratureSearchPipeline
from app.storage import dbconn
from app.storage.database import ArticleDatabase


def _article(**kwargs):
    article = {
        "article_id": kwargs.pop("article_id", "10.1234/closed"),
        "source": kwargs.pop("source", "pubmed"),
        "oa_status": kwargs.pop("oa_status", None),
        "best_oa_url": kwargs.pop("best_oa_url", None),
    }
    extra = kwargs.pop("extra", None)
    locations = kwargs.pop("locations", None)
    if extra is not None:
        article["_extra"] = extra
    if locations is not None:
        article["locations"] = locations
    article.update(kwargs)
    return article


def _urls(copies):
    return [item.url for item in copies]


def test_same_record_locations_skip_the_main_link():
    copies = other_copies(_article(
        article_id="10.1234/closed",
        source="crossref",
        locations=[
            {"url": "https://doi.org/10.1234/closed", "via": "crossref",
             "license": "https://creativecommons.org/licenses/by/4.0/"},
            {"url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/",
             "host": "PubMed Central", "via": "openalex"},
        ],
    ))
    assert _urls(copies) == ["https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/"]
    assert copies[0].where == "PubMed Central"


def test_same_doi_row_locations_and_best_oa_url_are_listed():
    card = _article(article_id="cr-1", source="crossref", doi="10.1234/same")
    peer = _article(
        article_id="W1",
        source="openalex",
        doi="10.1234/same",
        oa_status="gold",
        best_oa_url="https://zenodo.org/record/1/files/a.pdf",
        host_name="Zenodo",
        locations=[{
            "url": "https://zenodo.org/record/1/files/a.pdf",
            "host": "Zenodo",
            "via": "zenodo",
        }],
    )
    copies = other_copies(card, [peer])
    assert _urls(copies) == ["https://zenodo.org/record/1/files/a.pdf"]
    assert copies[0].where == "Zenodo"
    assert copies[0].open_listed is True


def test_set_aside_same_doi_row_still_counts():
    card = _article(article_id="keep", source="pubmed", doi="10.1234/dup")
    aside = _article(
        article_id="dup",
        source="europepmc",
        doi="10.1234/dup",
        locations=[{
            "url": "https://europepmc.org/articles/PMC9",
            "host": "Europe PMC",
            "via": "europepmc",
        }],
    )
    copies = other_copies(card, [aside])
    assert copies[0].url == "https://europepmc.org/articles/PMC9"
    assert copies[0].where == "Europe PMC"


def test_merged_best_oa_url_conflict_is_listed():
    copies = other_copies(_article(
        extra={
            "locations": [],
            "provenance": {
                "conflicts": {
                    "best_oa_url": {
                        "value": "https://example.org/merged.pdf",
                        "source": "doaj",
                    },
                    "journal": {"value": "Other Journal", "source": "crossref"},
                },
            },
        },
    ))
    assert _urls(copies) == ["https://example.org/merged.pdf"]
    assert copies[0].where == "DOAJ"


def test_dedupes_by_normalized_url():
    copies = other_copies(_article(
        article_id="x",
        source="pubmed",
        locations=[
            {"url": "https://PMC.EXAMPLE.ORG/a", "host": "PubMed Central"},
            {"url": "https://pmc.example.org/a", "host": "PMC"},
        ],
    ))
    assert len(copies) == 1
    assert copies[0].where == "PubMed Central"


def test_trailing_slash_and_scheme_are_distinct_copies():
    copies = other_copies(_article(
        locations=[
            {"url": "https://example.org", "host": "Example"},
            {"url": "https://example.org/", "host": "Example slash"},
            {"url": "http://example.org/doc", "host": "HTTP"},
            {"url": "https://example.org/doc", "host": "HTTPS"},
            {"url": "https://other.example/a", "host": "A"},
        ],
    ))
    urls = _urls(copies)
    assert "https://example.org" in urls
    assert "https://example.org/" in urls
    assert "http://example.org/doc" in urls
    assert "https://example.org/doc" in urls
    assert len(copies) == COPY_LIMIT
    assert "https://other.example/a" in urls


def test_invalid_urls_are_skipped():
    copies = other_copies(_article(
        locations=[
            {"url": "ftp://example.org/a.pdf", "host": "Files"},
            {"url": "javascript:alert(1)", "host": "XSS"},
            {"url": "/relative", "host": "Local"},
            {"url": "https://", "host": "Empty"},
            {"url": "https://example.org/ok.pdf", "host": "Zenodo"},
        ],
    ))
    assert _urls(copies) == ["https://example.org/ok.pdf"]


def test_crossref_without_licence_is_omitted():
    copies = other_copies(_article(
        source="crossref",
        locations=[{
            "url": "https://api.elsevier.com/content/article/doi/10",
            "kind": "text-mining",
            "via": "crossref",
        }],
    ))
    assert copies == []


def test_stored_crossref_record_keeps_non_text_mining_copy(tmp_path, monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(str(tmp_path / "copies-via.db"))
    try:
        db.insert_articles([{
            "article_id": "10.1234/closed",
            "source": "crossref",
            "title": "Closed paper",
            "abstract": "An abstract about copies.",
            "year": "2020",
            "authors": [],
            "doi": "10.1234/closed",
            "_extra": {"locations": [
                {
                    "url": "https://api.elsevier.com/content/article/doi/10",
                    "kind": "text-mining",
                    "via": "crossref",
                },
                {
                    "url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/",
                    "host": "PubMed Central",
                    "via": "openalex",
                },
            ]},
        }], dedupe=False)
        extra = db.conn.execute(
            "SELECT provenance FROM article_extra "
            "WHERE article_id=? AND source=?",
            ("10.1234/closed", "crossref"),
        ).fetchone()
        row = db.get_all_articles()[0]
        row["provenance"] = json.loads(extra[0])
        copies = other_copies(row)
        urls = _urls(copies)
        assert "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/" in urls
        assert "https://api.elsevier.com/content/article/doi/10" not in urls
        pmc = next(item for item in copies if "PMC1" in item.url)
        assert pmc.where == "PubMed Central"
        assert pmc.open_listed is False
    finally:
        db.close()


def test_crossref_with_cc_licence_is_listed_as_open():
    copies = other_copies(_article(
        article_id="10.3/cc",
        source="crossref",
        locations=[{
            "url": "https://example.org/cc.pdf",
            "via": "crossref",
            "license": "https://creativecommons.org/licenses/by/4.0/",
        }],
    ))
    assert copies == [CopyInfo("CrossRef", "https://example.org/cc.pdf", True)]


def test_closed_copy_has_no_open_label():
    copies = other_copies(_article(
        oa_status="closed",
        locations=[{"url": "https://publisher.example/article", "host": "publisher page"}],
    ))
    assert len(copies) == 1
    assert copies[0].open_listed is False
    assert copies[0].where == "publisher page"


def test_later_open_peer_labels_card_location():
    card = _article(
        article_id="123",
        source="pubmed",
        doi="10.1234/same",
        locations=[{
            "url": "https://zenodo.org/records/9/files/paper.pdf",
            "via": "openalex",
            "host": "Zenodo",
        }],
    )
    peer = _article(
        article_id="W9",
        source="openalex",
        doi="10.1234/same",
        oa_status="gold",
        best_oa_url="https://zenodo.org/records/9/files/paper.pdf",
    )
    copies = other_copies(card, [peer])
    assert copies == [
        CopyInfo("OpenAlex", "https://zenodo.org/records/9/files/paper.pdf", True),
    ]


def test_later_open_peer_labels_earlier_closed_peer():
    card = _article(article_id="123", source="pubmed", doi="10.1234/same")
    closed = _article(
        article_id="cr-1",
        source="crossref",
        doi="10.1234/same",
        locations=[{
            "url": "https://zenodo.org/records/9/files/paper.pdf",
            "host": "Zenodo",
            "via": "openalex",
        }],
    )
    opened = _article(
        article_id="W9",
        source="openalex",
        doi="10.1234/same",
        oa_status="gold",
        host_name="Zenodo",
        best_oa_url="https://zenodo.org/records/9/files/paper.pdf",
    )
    copies = other_copies(card, [closed, opened])
    assert copies == [
        CopyInfo("Zenodo", "https://zenodo.org/records/9/files/paper.pdf", True),
    ]
    reversed_copies = other_copies(card, [opened, closed])
    assert reversed_copies == copies


def test_open_peer_labels_one_of_five_selected_locations():
    locations = [
        {"url": f"https://example.org/copy/{i}", "host": f"Host {i}"}
        for i in range(COPY_LIMIT + 1)
    ]
    card = _article(
        article_id="123",
        source="pubmed",
        doi="10.1234/same",
        locations=locations,
    )
    peer = _article(
        article_id="W9",
        source="openalex",
        doi="10.1234/same",
        oa_status="gold",
        best_oa_url="https://example.org/copy/2",
    )
    copies = other_copies(card, [peer])
    assert _urls(copies) == [f"https://example.org/copy/{i}" for i in range(COPY_LIMIT)]
    assert copies[2].open_listed is True
    assert [item.open_listed for item in copies] == [False, False, True, False, False]


def test_sixth_open_url_sets_has_open_copy_without_joining_the_list():
    locations = [
        {"url": f"https://example.org/copy/{i}", "host": f"Host {i}"}
        for i in range(COPY_LIMIT)
    ]
    card = _article(
        article_id="123",
        source="pubmed",
        doi="10.1234/same",
        locations=locations,
    )
    peer = _article(
        article_id="W9",
        source="openalex",
        doi="10.1234/same",
        oa_status="gold",
        best_oa_url="https://example.org/copy/open",
        host_name="Zenodo",
        locations=[{
            "url": "https://example.org/copy/open",
            "host": "Zenodo",
            "via": "openalex",
        }],
    )
    found = other_copies_result(card, [peer])
    assert _urls(found.copies) == [f"https://example.org/copy/{i}" for i in range(COPY_LIMIT)]
    assert [item.open_listed for item in found.copies] == [False] * COPY_LIMIT
    assert found.has_open_copy is True


def test_cap_is_five():
    locations = [
        {"url": f"https://example.org/copy/{i}", "host": f"Host {i}"}
        for i in range(COPY_LIMIT + 3)
    ]
    copies = other_copies(_article(locations=locations))
    assert len(copies) == COPY_LIMIT
    assert _urls(copies) == [f"https://example.org/copy/{i}" for i in range(COPY_LIMIT)]


def test_no_other_copies_is_empty():
    assert other_copies(_article()) == []
    assert other_copies(_article(
        article_id="123",
        source="pubmed",
        locations=[{"url": "https://pubmed.ncbi.nlm.nih.gov/123/", "via": "pubmed"}],
    )) == []


@pytest.mark.parametrize("article, peers", [
    (None, None),
    ("paper", "rows"),
    ([], {"url": "https://example.org/x"}),
    ({"oa_status": {"nested": True}, "best_oa_url": 3, "locations": "nope"}, [None, 4, "x"]),
    ({"_extra": "nope", "source": "openalex"}, [{"locations": 12}]),
])
def test_odd_or_missing_data_never_raises(article, peers):
    assert other_copies(article, peers) == []


def test_fallback_where_is_publisher_page():
    copies = other_copies(_article(
        source="",
        locations=[{"url": "https://publisher.example/work"}],
    ))
    assert copies[0].where == "publisher page"


def _same_work_paper(*, article_id, source, oa_status=None, best_oa_url=None, **kwargs):
    paper = {
        "article_id": article_id,
        "source": source,
        "title": "Same work from two sources",
        "abstract": "An abstract that is long enough to store.",
        "year": "2020",
        "authors": ["Jane Doe"],
        "doi": "10.1234/same",
    }
    if oa_status is not None:
        paper["oa_status"] = oa_status
    if best_oa_url is not None:
        paper["best_oa_url"] = best_oa_url
    paper.update(kwargs)
    return paper


def _retained_card(db):
    rows = db.get_all_articles()
    assert len(rows) == 1
    card = rows[0]
    extra = db.conn.execute(
        "SELECT provenance, locations FROM article_extra "
        "WHERE article_id = ? AND source = ?",
        (card["article_id"], card["source"]),
    ).fetchone()
    if extra:
        card["provenance"] = json.loads(extra[0] or "{}")
        card["locations"] = json.loads(extra[1] or "[]")
    return card


def _merge_closed_pubmed_then(monkeypatch, incoming):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(":memory:")
    db.insert_articles([_same_work_paper(
        article_id="123",
        source="pubmed",
        oa_status="closed",
        best_oa_url="https://publisher.example/closed",
    )], dedupe=True)
    db.insert_articles([incoming], dedupe=True)
    return db, _retained_card(db)


def _zenodo_copy(copies):
    return [item for item in copies if item.url == "https://zenodo.org/paper.pdf"]


def test_merged_openalex_copy_is_open_when_retained_row_is_closed(monkeypatch):
    db, card = _merge_closed_pubmed_then(monkeypatch, _same_work_paper(
        article_id="W1",
        source="openalex",
        oa_status="gold",
        best_oa_url="https://zenodo.org/paper.pdf",
    ))
    try:
        assert access_state(card).state == OPEN_LISTED
        assert access_state(card).url == "https://zenodo.org/paper.pdf"
        copies = other_copies(card)
        assert _zenodo_copy(copies) == [
            CopyInfo("OpenAlex", "https://zenodo.org/paper.pdf", True),
        ]
        assert card["provenance"]["conflicts"]["oa_status"][0]["value"] == "gold"
        assert card["provenance"]["conflicts"]["best_oa_url"][0]["value"] == (
            "https://zenodo.org/paper.pdf"
        )
    finally:
        db.close()


def test_merged_closed_copy_is_not_labeled_open(monkeypatch):
    db, card = _merge_closed_pubmed_then(monkeypatch, _same_work_paper(
        article_id="W1",
        source="openalex",
        oa_status="closed",
        best_oa_url="https://zenodo.org/paper.pdf",
    ))
    try:
        assert access_state(card).state == "none_listed"
        copies = other_copies(card)
        assert _zenodo_copy(copies) == [
            CopyInfo("OpenAlex", "https://zenodo.org/paper.pdf", False),
        ]
    finally:
        db.close()


def test_merged_copy_without_oa_status_is_not_labeled_open(monkeypatch):
    db, card = _merge_closed_pubmed_then(monkeypatch, _same_work_paper(
        article_id="W1",
        source="openalex",
        best_oa_url="https://zenodo.org/paper.pdf",
    ))
    try:
        assert access_state(card).state == "none_listed"
        copies = other_copies(card)
        assert _zenodo_copy(copies) == [
            CopyInfo("OpenAlex", "https://zenodo.org/paper.pdf", False),
        ]
        assert "oa_status" not in card["provenance"]["conflicts"]
    finally:
        db.close()


def test_unrelated_provenance_oa_status_does_not_open_a_copy():
    copies = other_copies(_article(
        oa_status="closed",
        extra={
            "provenance": {
                "conflicts": {
                    "oa_status": {"value": "gold", "source": "openalex"},
                    "best_oa_url": {
                        "value": "https://publisher.example/closed.pdf",
                        "source": "pubmed",
                    },
                },
            },
        },
    ))
    assert copies == [
        CopyInfo("PubMed", "https://publisher.example/closed.pdf", False),
    ]


def test_unlicensed_crossref_provenance_url_stays_omitted():
    copies = other_copies(_article(
        extra={
            "provenance": {
                "conflicts": {
                    "oa_status": {"value": "gold", "source": "crossref"},
                    "best_oa_url": {
                        "value": "https://api.elsevier.com/content/article/doi/10",
                        "source": "crossref",
                    },
                },
            },
        },
    ))
    assert copies == []


def _vec(*values):
    return np.array(values, dtype=np.float32)


def _neighbor_paper():
    return {
        "article_id": "nb",
        "source": "doaj",
        "title": "A nearby open paper about zyptron",
        "abstract": "An abstract that is long enough to store.",
        "year": "2019",
        "authors": ["Ann Other"],
        "doi": "10.1234/other",
        "oa_status": "gold",
        "best_oa_url": "https://example.org/neighbor.pdf",
    }


def _seed_merged_library(pipe, retained, incoming):
    pipe.db.insert_articles([retained], dedupe=True)
    pipe.db.insert_articles([incoming], dedupe=True)
    card = _retained_card(pipe.db)
    pipe.db.insert_articles([_neighbor_paper()], dedupe=False)
    key = (card["article_id"], card["source"])
    pipe.db.insert_embeddings(
        {key: _vec(1.0, 0.0), ("nb", "doaj"): _vec(0.95, 0.1)},
        model_name="general",
    )
    pipe.db.upsert_note(key[0], key[1], starred=True)
    return card, key


def _combined_outputs(pipe, card, key):
    info = access_state(card)
    copies = other_copies(card)
    fields = pipe.db.get_article_access_fields()[key]
    filter_state = access_state(fields).state
    listed = pipe.search_similar(
        "Same work from two sources", top_k=10, lexical_boost=False, free_to_read=True,
    )
    suggestions = pipe.suggest_different_work([key])
    return info, copies, filter_state, listed, suggestions


def test_merge_conflicting_url_is_open_on_card_filter_copies_and_p28(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    pipe = LiteratureSearchPipeline(db_path=str(tmp_path / "merge-conflict.db"))
    monkeypatch.setattr(pipe.embedding_engine, "embed_query", lambda _q: _vec(1.0, 0.0))
    try:
        card, key = _seed_merged_library(
            pipe,
            _same_work_paper(
                article_id="123",
                source="pubmed",
                oa_status="closed",
                best_oa_url="https://publisher.example/closed",
            ),
            _same_work_paper(
                article_id="W1",
                source="openalex",
                oa_status="gold",
                best_oa_url="https://zenodo.org/paper.pdf",
                _extra={"locations": [{
                    "url": "https://zenodo.org/paper.pdf",
                    "host": "Zenodo",
                    "via": "openalex",
                }]},
            ),
        )
        info, copies, filter_state, listed, suggestions = _combined_outputs(
            pipe, card, key,
        )
        assert info.state == OPEN_LISTED
        assert info.url == "https://zenodo.org/paper.pdf"
        assert filter_state == OPEN_LISTED
        assert key in {(row["article_id"], row["source"]) for row in listed}
        assert _zenodo_copy(copies) == [
            CopyInfo("Zenodo", "https://zenodo.org/paper.pdf", True),
        ]
        assert suggestions == []
    finally:
        pipe.db.close()


def test_merge_filled_url_is_open_on_card_filter_copies_and_p28(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    pipe = LiteratureSearchPipeline(db_path=str(tmp_path / "merge-filled.db"))
    monkeypatch.setattr(pipe.embedding_engine, "embed_query", lambda _q: _vec(1.0, 0.0))
    try:
        card, key = _seed_merged_library(
            pipe,
            _same_work_paper(
                article_id="W1",
                source="openalex",
                oa_status="closed",
            ),
            _same_work_paper(
                article_id="hal-1",
                source="hal",
                oa_status="green",
                best_oa_url="https://hal.science/hal-1/document",
                _extra={"locations": [{
                    "url": "https://hal.science/hal-1/document",
                    "kind": "file",
                    "via": "hal",
                    "host": "HAL",
                }]},
            ),
        )
        info, copies, filter_state, listed, suggestions = _combined_outputs(
            pipe, card, key,
        )
        assert info.state == OPEN_LISTED
        assert info.url == "https://hal.science/hal-1/document"
        assert filter_state == OPEN_LISTED
        assert key in {(row["article_id"], row["source"]) for row in listed}
        assert [item for item in copies if "hal.science" in item.url] == [
            CopyInfo("HAL", "https://hal.science/hal-1/document", True),
        ]
        assert card["provenance"].get("best_oa_url") == "hal"
        assert suggestions == []
    finally:
        pipe.db.close()


def test_merge_equal_url_is_open_on_card_filter_copies_and_p28(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    pipe = LiteratureSearchPipeline(db_path=str(tmp_path / "merge-equal.db"))
    monkeypatch.setattr(pipe.embedding_engine, "embed_query", lambda _q: _vec(1.0, 0.0))
    try:
        shared = "https://example.org/same"
        card, key = _seed_merged_library(
            pipe,
            _same_work_paper(
                article_id="123",
                source="pubmed",
                oa_status="closed",
                best_oa_url=shared,
            ),
            _same_work_paper(
                article_id="W1",
                source="openalex",
                oa_status="gold",
                best_oa_url=shared,
                _extra={"locations": [{
                    "url": shared,
                    "via": "openalex",
                    "host": "Example",
                }]},
            ),
        )
        info, copies, filter_state, listed, suggestions = _combined_outputs(
            pipe, card, key,
        )
        assert info.state == OPEN_LISTED
        assert info.url == shared
        assert filter_state == OPEN_LISTED
        assert key in {(row["article_id"], row["source"]) for row in listed}
        assert any(item.url == shared and item.open_listed for item in copies)
        assert suggestions == []
    finally:
        pipe.db.close()


def _located_paper(article_id, source, status, url, **extra_loc):
    loc = {"url": url, "via": source, "host": source}
    loc.update(extra_loc)
    return _same_work_paper(
        article_id=article_id,
        source=source,
        oa_status=status,
        best_oa_url=url,
        _extra={"locations": [loc]},
    )


def test_merge_retained_gold_keeps_incoming_hal_url_closed(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    pipe = LiteratureSearchPipeline(db_path=str(tmp_path / "merge-hal-closed.db"))
    monkeypatch.setattr(pipe.embedding_engine, "embed_query", lambda _q: _vec(1.0, 0.0))
    open_url = "https://example.org/open"
    closed_url = "https://example.org/closed"
    try:
        card, key = _seed_merged_library(
            pipe,
            _located_paper("W1", "openalex", "gold", open_url),
            _located_paper("hal-1", "hal", "closed", closed_url),
        )
        info, copies, filter_state, listed, suggestions = _combined_outputs(
            pipe, card, key,
        )
        by_url = {item.url: item.open_listed for item in copies}
        assert info.state == OPEN_LISTED
        assert info.url == open_url
        assert filter_state == OPEN_LISTED
        assert key in {(row["article_id"], row["source"]) for row in listed}
        assert by_url[open_url] is True
        assert by_url[closed_url] is False
        assert suggestions == []
    finally:
        pipe.db.close()


def test_merge_openalex_filled_status_does_not_open_pubmed_url(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    pipe = LiteratureSearchPipeline(db_path=str(tmp_path / "merge-filled-status.db"))
    monkeypatch.setattr(pipe.embedding_engine, "embed_query", lambda _q: _vec(1.0, 0.0))
    closed_url = "https://example.org/closed"
    open_url = "https://example.org/open"
    try:
        card, key = _seed_merged_library(
            pipe,
            _located_paper("123", "pubmed", None, closed_url),
            _located_paper("W1", "openalex", "gold", open_url),
        )
        info, copies, filter_state, listed, suggestions = _combined_outputs(
            pipe, card, key,
        )
        by_url = {item.url: item.open_listed for item in copies}
        assert info.state == OPEN_LISTED
        assert info.url == open_url
        assert filter_state == OPEN_LISTED
        assert key in {(row["article_id"], row["source"]) for row in listed}
        assert by_url[open_url] is True
        assert by_url.get(closed_url) is False
        assert card["provenance"].get("oa_status") == "openalex"
        assert suggestions == []
    finally:
        pipe.db.close()


def test_merge_equal_url_with_retained_pubmed_location_is_open(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    pipe = LiteratureSearchPipeline(db_path=str(tmp_path / "merge-equal-located.db"))
    monkeypatch.setattr(pipe.embedding_engine, "embed_query", lambda _q: _vec(1.0, 0.0))
    shared = "https://example.org/same"
    try:
        card, key = _seed_merged_library(
            pipe,
            _located_paper("123", "pubmed", "closed", shared),
            _located_paper("W1", "openalex", "gold", shared),
        )
        info, copies, filter_state, listed, suggestions = _combined_outputs(
            pipe, card, key,
        )
        assert info.state == OPEN_LISTED
        assert info.url == shared
        assert filter_state == OPEN_LISTED
        assert key in {(row["article_id"], row["source"]) for row in listed}
        assert any(item.url == shared and item.open_listed for item in copies)
        assert suggestions == []
    finally:
        pipe.db.close()


def test_unowned_plus_licensed_crossref_opens_shared_url(tmp_path, monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    pipe = LiteratureSearchPipeline(db_path=str(tmp_path / "merge-cr-licensed.db"))
    monkeypatch.setattr(pipe.embedding_engine, "embed_query", lambda _q: _vec(1.0, 0.0))
    shared = "https://example.org/shared.pdf"
    try:
        card, key = _seed_merged_library(
            pipe,
            _same_work_paper(
                article_id="123",
                source="pubmed",
                oa_status="closed",
                best_oa_url=shared,
            ),
            _same_work_paper(
                article_id="10.1234/same",
                source="crossref",
                _extra={"locations": [{
                    "url": shared,
                    "via": "crossref",
                    "license": "https://creativecommons.org/licenses/by/4.0/",
                }]},
            ),
        )
        info, copies, filter_state, listed, suggestions = _combined_outputs(
            pipe, card, key,
        )
        assert info.state == OPEN_LISTED
        assert info.url == shared
        assert filter_state == OPEN_LISTED
        assert key in {(row["article_id"], row["source"]) for row in listed}
        assert any(item.url == shared and item.open_listed for item in copies)
        assert suggestions == []
    finally:
        pipe.db.close()


def test_licensed_unowned_plus_unlicensed_crossref_stays_closed(tmp_path, monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    pipe = LiteratureSearchPipeline(db_path=str(tmp_path / "merge-cr-unlicensed.db"))
    monkeypatch.setattr(pipe.embedding_engine, "embed_query", lambda _q: _vec(1.0, 0.0))
    shared = "https://example.org/shared.pdf"
    try:
        card, key = _seed_merged_library(
            pipe,
            _same_work_paper(
                article_id="123",
                source="pubmed",
                oa_status="closed",
                best_oa_url=shared,
                _extra={"locations": [{
                    "url": shared,
                    "license": "https://creativecommons.org/licenses/by/4.0/",
                }]},
            ),
            _same_work_paper(
                article_id="10.1234/same",
                source="crossref",
                _extra={"locations": [{
                    "url": shared,
                    "via": "crossref",
                    "kind": "text-mining",
                }]},
            ),
        )
        info, copies, filter_state, listed, suggestions = _combined_outputs(
            pipe, card, key,
        )
        assert info.state != OPEN_LISTED
        assert filter_state != OPEN_LISTED
        assert key not in {(row["article_id"], row["source"]) for row in listed}
        assert not any(item.url == shared and item.open_listed for item in copies)
        assert suggestions
    finally:
        pipe.db.close()


def test_repeated_unlicensed_crossref_keeps_owned_licence(tmp_path, monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(str(tmp_path / "repeat-cr.db"))
    shared = "https://example.org/shared.pdf"
    observed = "2026-10-29T08:00:00.000000Z"
    try:
        db.insert_articles([_same_work_paper(
            article_id="10.1234/same",
            source="crossref",
            _observed_at=observed,
            _extra={"locations": [{
                "url": shared,
                "via": "crossref",
                "license": "https://creativecommons.org/licenses/by/4.0/",
            }]},
        )], dedupe=True)
        incoming = _same_work_paper(
            article_id="10.1234/same",
            source="crossref",
            _observed_at=observed,
            _extra={"locations": [{
                "url": shared,
                "via": "crossref",
                "kind": "text-mining",
            }]},
        )
        db.insert_articles([incoming], dedupe=True)
        db.insert_articles([incoming], dedupe=True)
        card = _retained_card(db)
        observations = card["provenance"]["link_evidence"]["observations"]
        assert len(observations) == 2
        assert access_state(card).state == OPEN_LISTED
        assert access_state(card).url == shared
    finally:
        db.close()
