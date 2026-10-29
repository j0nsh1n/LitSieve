"""Other listed copies of a starred paper: other_copies rules."""

from __future__ import annotations

import json

import pytest

from app.services.access import COPY_LIMIT, CopyInfo, access_state, other_copies
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
            {"url": "https://PMC.EXAMPLE.ORG/a/", "host": "PubMed Central"},
            {"url": "http://pmc.example.org/a", "host": "PMC"},
        ],
    ))
    assert len(copies) == 1
    assert copies[0].where == "PubMed Central"


def test_root_origin_slash_is_one_copy_and_does_not_eat_the_cap():
    copies = other_copies(_article(
        locations=[
            {"url": "https://example.org", "host": "Example"},
            {"url": "https://example.org/", "host": "Example slash"},
            {"url": "https://other.example/a", "host": "A"},
            {"url": "https://other.example/b", "host": "B"},
            {"url": "https://other.example/c", "host": "C"},
            {"url": "https://other.example/d", "host": "D"},
            {"url": "https://other.example/e", "host": "E"},
        ],
    ))
    urls = _urls(copies)
    origin_hits = [url for url in urls if url.rstrip("/") == "https://example.org"]
    assert len(origin_hits) == 1
    assert len(copies) == COPY_LIMIT
    assert "https://other.example/d" in urls
    assert "https://other.example/e" not in urls


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
        CopyInfo("Zenodo", "https://zenodo.org/records/9/files/paper.pdf", True),
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


def _same_work_paper(*, article_id, source, oa_status=None, best_oa_url=None):
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
        assert access_state(card).state == "none_listed"
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
