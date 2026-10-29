"""Different-work suggestions: difference line and in-memory picker."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.different_work import (
    FALLBACK_DIFFERENCE,
    MIN_SIMILARITY,
    difference_line,
    pick_different_work,
)
from app.services.link_evidence import SOURCE_ADAPTER_SHAPES
from app.services.pipeline import LiteratureSearchPipeline
from app.services.question_concepts import question_concepts
from app.storage.database import ArticleDatabase


def test_year_difference():
    assert difference_line({"year": "2008"}, {"year": "2019"}) == "2019 vs 2008"


def test_type_difference():
    assert difference_line(
        {"year": "2008", "work_type": "journal-article"},
        {"year": "2008", "work_type": "review-article"},
    ) == "review article vs journal article"


def test_year_and_type_together():
    assert difference_line(
        {"year": "2008", "work_type": "journal-article"},
        {"year": "2019", "work_type": "review-article"},
    ) == "2019 vs 2008; review article vs journal article"


def test_concept_covers_and_reverse():
    concepts = question_concepts(
        "How did New Deal policies affect African Americans during the Great Depression?"
    )
    starred = {
        "title": "State income growth in 1933",
        "abstract": "Spending during the Great Depression.",
    }
    other = {
        "title": "New Deal policies and African Americans",
        "abstract": "How New Deal policies reached African Americans.",
    }
    line = difference_line(starred, other, concepts)
    assert line.startswith("covers New Deal policies")
    assert "African Americans" in line
    reverse = difference_line(other, starred, concepts)
    assert "does not cover New Deal policies" in reverse
    assert "African Americans" in reverse


def test_fallback_when_nothing_differs():
    assert difference_line({"year": "2019"}, {"year": "2019"}) == FALLBACK_DIFFERENCE
    assert difference_line({}, {}) == FALLBACK_DIFFERENCE


def test_missing_year_or_type_is_skipped():
    assert difference_line({"year": "2008"}, {"year": None}) == FALLBACK_DIFFERENCE
    assert difference_line(
        {"work_type": "journal-article"}, {"work_type": ""},
    ) == FALLBACK_DIFFERENCE


def _open(article_id, score, **kwargs):
    row = {
        "article_id": article_id,
        "source": kwargs.pop("source", "openalex"),
        "title": kwargs.pop("title", article_id),
        "similarity_score": score,
        "access": {
            "state": "open_listed",
            "url": kwargs.pop("url", f"https://example.org/{article_id}.pdf"),
        },
    }
    row.update(kwargs)
    return row


def test_pick_orders_by_similarity_and_caps_at_three():
    seed = {"article_id": "seed", "source": "pubmed"}
    ranked = [
        _open("a", 0.80),
        _open("b", 0.70),
        _open("c", 0.60),
        _open("d", 0.55),
    ]
    picked = pick_different_work(seed, ranked)
    assert [row["article_id"] for row in picked] == ["a", "b", "c"]


def test_pick_reorders_cosine_before_cap():
    seed = {"article_id": "seed", "source": "pubmed"}
    ranked = [
        _open("dated1", 0.70),
        _open("dated2", 0.60),
        _open("dated3", 0.55),
        _open("undated", 0.90),
    ]
    picked = pick_different_work(seed, ranked)
    assert [row["article_id"] for row in picked] == ["undated", "dated1", "dated2"]


def test_pick_drops_below_similarity_cut():
    seed = {"article_id": "seed", "source": "pubmed"}
    ranked = [
        _open("near", MIN_SIMILARITY),
        _open("far", MIN_SIMILARITY - 0.01),
    ]
    picked = pick_different_work(seed, ranked)
    assert [row["article_id"] for row in picked] == ["near"]


def test_pick_skips_closed_and_same_work():
    seed = {"article_id": "seed", "source": "pubmed", "doi": "10.1234/same"}
    ranked = [
        {
            "article_id": "closed",
            "source": "crossref",
            "similarity_score": 0.9,
            "access": {"state": "none_listed"},
        },
        _open("peer", 0.88, doi="10.1234/same"),
        _open("seed", 0.99, source="pubmed"),
        _open("ok", 0.70),
    ]
    picked = pick_different_work(seed, ranked, same_work_keys={("blocked", "openalex")})
    assert [row["article_id"] for row in picked] == ["ok"]


def _paper(article_id, source, title, abstract, **kwargs):
    article = {
        "article_id": article_id,
        "source": source,
        "title": title,
        "abstract": abstract,
        "year": kwargs.pop("year", "2020"),
        "authors": [],
        "journal": "J",
    }
    article.update(kwargs)
    source = article.get("source")
    url = article.get("best_oa_url")
    shape = SOURCE_ADAPTER_SHAPES.get(source)
    if shape and url:
        kinds = shape["kind"]
        kind = None
        if None not in kinds:
            for item in ("pdf", "file", "fulltext", "landing"):
                if item in kinds:
                    kind = item
                    break
        if kind:
            extra = dict(article.get("_extra") or {})
            extra.setdefault("locations", [{
                "url": url,
                "kind": kind,
                "via": source,
            }])
            article["_extra"] = extra
    return article


def _vec(*values):
    return np.array(values, dtype=np.float32)


def _seed_library(db: ArticleDatabase):
    db.insert_articles([
        _paper(
            "seed", "crossref", "Closed seed on zyptron",
            "A closed paper about the zyptron pathway.",
            year="2008", work_type="journal-article", doi="10.1234/seed",
        ),
        _paper(
            "copied", "crossref", "Closed seed with an open peer",
            "Closed, but another row is the same work.",
            year="2008", work_type="journal-article", doi="10.1234/copied",
        ),
        _paper(
            "open-a", "openalex", "Open zyptron review",
            "An open review of the zyptron pathway.",
            year="2019", work_type="review-article", doi="10.1234/a",
            oa_status="gold", best_oa_url="https://example.org/a.pdf",
        ),
        _paper(
            "open-b", "doaj", "Open zyptron notes",
            "More zyptron notes.",
            year="2018", work_type="journal-article", doi="10.1234/b",
            oa_status="gold", best_oa_url="https://example.org/b.pdf",
        ),
        _paper(
            "open-c", "zenodo", "Open zyptron dataset paper",
            "Zyptron measurements.",
            year="2017", work_type="journal-article", doi="10.1234/c",
            oa_status="gold", best_oa_url="https://example.org/c.pdf",
        ),
        _paper(
            "open-d", "plos", "Fourth open zyptron paper",
            "Still about zyptron.",
            year="2016", work_type="journal-article", doi="10.1234/d",
            oa_status="gold", best_oa_url="https://example.org/d.pdf",
        ),
        _paper(
            "closed-near", "pubmed", "Closed neighbor",
            "Closed zyptron neighbor.",
            year="2015", doi="10.1234/closed",
        ),
        _paper(
            "same-doi", "openalex", "Same work open copy",
            "Open copy of the copied seed.",
            year="2008", doi="10.1234/copied",
            oa_status="gold", best_oa_url="https://example.org/same.pdf",
        ),
        _paper(
            "aside", "arxiv", "Set aside open zyptron",
            "Set aside but open.",
            year="2014", doi="10.1234/aside",
            oa_status="gold", best_oa_url="https://example.org/aside.pdf",
        ),
        _paper(
            "weak", "eric", "Unrelated gardening",
            "Tomatoes and soil.",
            year="2013", doi="10.1234/weak",
            oa_status="gold", best_oa_url="https://example.org/weak.pdf",
        ),
    ], dedupe=False)
    db.insert_embeddings(
        {
            ("seed", "crossref"): _vec(1.0, 0.0),
            ("copied", "crossref"): _vec(1.0, 0.0),
            ("open-a", "openalex"): _vec(0.95, 0.1),
            ("open-b", "doaj"): _vec(0.85, 0.2),
            ("open-c", "zenodo"): _vec(0.75, 0.3),
            ("open-d", "plos"): _vec(0.65, 0.4),
            ("closed-near", "pubmed"): _vec(0.99, 0.01),
            ("same-doi", "openalex"): _vec(0.2, 0.98),
            ("aside", "arxiv"): _vec(0.8, 0.15),
            ("weak", "eric"): _vec(0.2, 0.98),
        },
        model_name="general",
    )
    db.upsert_note("seed", "crossref", starred=True)
    db.upsert_note("copied", "crossref", starred=True)
    db.exclude_articles([("aside", "arxiv")], reason="duplicate")


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "different-work.db"))
    _seed_library(p.db)
    monkeypatch.setattr(
        p.embedding_engine, "embed_query",
        lambda _q: _vec(1.0, 0.0),
    )
    yield p
    p.db.close()


def test_pipeline_skips_closed_same_work_set_aside_and_weak(pipe):
    rows = pipe.suggest_different_work([("seed", "crossref")])
    assert len(rows) == 1
    urls = [item["url"] for item in rows[0]["suggestions"]]
    titles = [item["title"] for item in rows[0]["suggestions"]]
    assert "https://example.org/a.pdf" in urls
    assert "https://example.org/same.pdf" not in urls
    assert "https://example.org/aside.pdf" not in urls
    assert "https://example.org/weak.pdf" not in urls
    assert "Closed neighbor" not in titles


def test_pipeline_caps_at_three(pipe):
    rows = pipe.suggest_different_work([("seed", "crossref")])
    assert len(rows[0]["suggestions"]) == 3
    urls = [item["url"] for item in rows[0]["suggestions"]]
    assert urls == [
        "https://example.org/a.pdf",
        "https://example.org/b.pdf",
        "https://example.org/c.pdf",
    ]


def test_pipeline_difference_line_uses_year_and_type(pipe):
    rows = pipe.suggest_different_work([("seed", "crossref")])
    first = rows[0]["suggestions"][0]
    assert first["difference"] == "2019 vs 2008; review article vs journal article"
    assert "Open copy listed" not in first
    assert first["url"].startswith("https://")


def test_pipeline_skips_when_an_open_other_copy_exists(pipe):
    assert pipe.suggest_different_work([("copied", "crossref")]) == []


def test_pipeline_skips_when_the_only_open_url_is_sixth(tmp_path, monkeypatch):
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "sixth-open.db"))
    locations = [
        {"url": f"https://example.org/copy/{i}", "host": f"Host {i}", "via": "pubmed"}
        for i in range(5)
    ]
    p.db.insert_articles([
        _paper(
            "seed", "pubmed", "Closed seed with five closed copies",
            "A closed paper about the zyptron pathway.",
            year="2008", doi="10.1234/sixth",
            oa_status="closed",
            _extra={"locations": locations},
        ),
        _paper(
            "peer", "openalex", "Same work open copy",
            "Open copy of the seed at a sixth URL.",
            year="2008", doi="10.1234/sixth",
            oa_status="gold",
            best_oa_url="https://example.org/copy/open",
        ),
        _paper(
            "nb", "doaj", "Nearby open zyptron",
            "An open neighbor about zyptron.",
            year="2019", doi="10.1234/nb",
            oa_status="gold",
            best_oa_url="https://example.org/nb.pdf",
        ),
    ], dedupe=False)
    p.db.insert_embeddings(
        {
            ("seed", "pubmed"): _vec(1.0, 0.0),
            ("nb", "doaj"): _vec(0.95, 0.1),
        },
        model_name="general",
    )
    p.db.upsert_note("seed", "pubmed", starred=True)
    monkeypatch.setattr(
        p.embedding_engine, "embed_query",
        lambda _q: _vec(1.0, 0.0),
    )
    try:
        assert p.suggest_different_work([("seed", "pubmed")]) == []
    finally:
        p.db.close()


def test_pipeline_keeps_closest_undated_when_year_bound_groups_last(
    tmp_path, monkeypatch,
):
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "undated-order.db"))
    p.db.insert_articles([
        _paper(
            "seed", "crossref", "Closed seed",
            "A closed paper about the zyptron pathway.",
            year="2008", doi="10.1234/seed",
        ),
        _paper(
            "undated", "openalex", "Closest undated",
            "Open zyptron neighbor with no year.",
            year="", doi="10.1234/u",
            oa_status="gold", best_oa_url="https://example.org/undated.pdf",
        ),
        _paper(
            "dated1", "doaj", "Dated one",
            "Weaker dated zyptron paper.",
            year="2020", doi="10.1234/d1",
            oa_status="gold", best_oa_url="https://example.org/d1.pdf",
        ),
        _paper(
            "dated2", "zenodo", "Dated two",
            "Another weaker dated zyptron paper.",
            year="2020", doi="10.1234/d2",
            oa_status="gold", best_oa_url="https://example.org/d2.pdf",
        ),
        _paper(
            "dated3", "plos", "Dated three",
            "The weakest dated zyptron paper.",
            year="2020", doi="10.1234/d3",
            oa_status="gold", best_oa_url="https://example.org/d3.pdf",
        ),
    ], dedupe=False)
    p.db.insert_embeddings(
        {
            ("seed", "crossref"): _vec(1.0, 0.0),
            ("undated", "openalex"): _vec(1.0, 0.01),
            ("dated1", "doaj"): _vec(1.0, 0.5),
            ("dated2", "zenodo"): _vec(1.0, 0.6),
            ("dated3", "plos"): _vec(1.0, 0.7),
        },
        model_name="general",
    )
    p.db.upsert_note("seed", "crossref", starred=True)
    monkeypatch.setattr(
        p.embedding_engine, "embed_query",
        lambda _q: _vec(1.0, 0.0),
    )
    try:
        rows = p.suggest_different_work(
            [("seed", "crossref")], year_min=2000,
        )
        urls = [item["url"] for item in rows[0]["suggestions"]]
        assert urls[0] == "https://example.org/undated.pdf"
        assert "https://example.org/undated.pdf" in urls
        assert len(urls) == 3
    finally:
        p.db.close()


def test_pipeline_empty_without_embeddings(tmp_path, monkeypatch):
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "no-emb.db"))
    p.db.insert_articles([
        _paper("seed", "crossref", "Closed", "n.", doi="10.1/x"),
        _paper(
            "open-a", "openalex", "Open", "n.",
            oa_status="gold", best_oa_url="https://example.org/a.pdf",
        ),
    ], dedupe=False)
    p.db.upsert_note("seed", "crossref", starred=True)
    monkeypatch.setattr(p.embedding_engine, "embed_query", lambda _q: _vec(1.0, 0.0))
    try:
        assert p.suggest_different_work([("seed", "crossref")]) == []
    finally:
        p.db.close()


def _select_statements(statements):
    return [sql for sql in statements if sql.lstrip()[:6].upper() == "SELECT"]


def _full_access_reads(selects):
    """SELECTs that load locations/provenance for the whole library."""
    found = []
    for sql in selects:
        compact = " ".join(sql.split()).lower()
        if "article_extra" not in compact:
            continue
        if "locations" not in compact:
            continue
        if " in (" in compact:
            continue
        found.append(sql)
    return found


def test_one_request_bounds_selects_and_full_access_reads(pipe):
    pipe.suggest_different_work([("seed", "crossref")])
    statements = []
    pipe.db.conn.set_trace_callback(statements.append)
    try:
        rows = pipe.suggest_different_work([("seed", "crossref")])
    finally:
        pipe.db.conn.set_trace_callback(None)
    assert rows
    selects = _select_statements(statements)
    assert len(selects) <= 9
    assert len(_full_access_reads(selects)) <= 1
    projection = [
        sql for sql in selects
        if "trim(doi)" in " ".join(sql.split()).lower()
        and "article_extra" not in sql.lower()
        and "locations" not in sql.lower()
    ]
    assert len(projection) == 1
