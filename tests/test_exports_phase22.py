"""Audit section 22.7-22.10: CSV formula injection, selection scores, RIS/BibTeX, library export."""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient
from test_integration_accounts import _register, app_module  # noqa: F401  (fixture)

from app import core
from app.routes import exports
from app.services.citations import article_to_bibtex, article_to_ris


def _csv_rows(text: str):
    return list(csv.reader(io.StringIO(text)))


def _seed(username: str, articles, clusters=None):
    uid = core.user_db.get_by_username(username)["id"]
    p = core.get_pipeline(uid)
    try:
        p.db.insert_articles(articles)
        if clusters:
            p.db.insert_clusters(clusters)
    finally:
        core.release_pipeline(uid)


def _paper(aid, title="Plain title", **extra):
    base = {
        "article_id": aid, "source": "pubmed", "title": title, "abstract": "",
        "year": "2024", "authors": ["Ng A"], "journal": "J Test",
    }
    base.update(extra)
    return base


def _post_selection(client, fmt, items):
    return client.post(
        "/api/export/selection",
        json={"format": fmt, "items": items},
        headers={"X-CSRF-Token": client.cookies.get("csrf_token", "")},
    )


# 22.7

def test_csv_text_cells_are_quote_prefixed():
    for lead in ("=", "+", "-", "@", "\t", "\r"):
        assert exports._csv_text(f"{lead}x") == f"'{lead}x"
    assert exports._csv_text("plain") == "plain"
    assert exports._csv_text("a=b") == "a=b"
    assert exports._csv_text(None) == ""


def test_library_csv_neutralises_formulas(app_module):
    client = TestClient(app_module.app)
    _register(client, "csvuser")
    _seed("csvuser", [_paper("p1", title='=HYPERLINK("x")', authors=["+1"], journal="@SUM(A1)")])
    uid = core.user_db.get_by_username("csvuser")["id"]
    p = core.get_pipeline(uid)
    try:
        p.db.upsert_note("p1", "pubmed", note="@SUM(A1)")
    finally:
        core.release_pipeline(uid)
    r = client.get("/api/export/library", params={"format": "csv"})
    assert r.status_code == 200, r.text
    row = _csv_rows(r.text)[1]
    assert row[0] == "'=HYPERLINK(\"x\")"
    assert row[3] == "'+1"
    assert row[2] == "'@SUM(A1)"
    assert row[11] == "'@SUM(A1)"


def test_library_csv_note_is_neutralised():
    out = exports._library_rows_to_csv([
        {"title": "ok", "authors": ["-2+3"], "note": "@SUM(A1)", "year": "2024",
         "cluster_id": -1, "article_id": "x", "source": "pubmed"},
    ])
    row = _csv_rows(out)[1]
    assert row[3] == "'-2+3"
    assert row[11] == "'@SUM(A1)"
    assert row[6] == "-1"  # an int we generated is not touched


# 22.8

def test_selection_csv_carries_page_scores_and_clusters(app_module):
    client = TestClient(app_module.app)
    _register(client, "seluser")
    papers = [_paper(f"p{i}", title=f"Paper {i}") for i in range(10)]
    clusters = {("p0", "pubmed"): (2, "Alpha group"), ("p1", "pubmed"): (3, "Beta group")}
    _seed("seluser", papers, clusters)
    items = [
        {"article_id": f"p{i}", "source": "pubmed", "similarity_score": 0.9 - i * 0.05}
        for i in range(10)
    ]
    r = _post_selection(client, "csv", items)
    assert r.status_code == 200, r.text
    rows = _csv_rows(r.text)[1:]
    assert len(rows) == 10
    assert [row[1] for row in rows] == [f"{0.9 - i * 0.05:.3f}" for i in range(10)]
    assert rows[0][10:12] == ["2", "Alpha group"]
    assert rows[1][10:12] == ["3", "Beta group"]
    assert rows[2][10:12] == ["", ""]  # unclustered only


def test_selection_csv_ignores_bad_scores_and_labels(app_module):
    client = TestClient(app_module.app)
    _register(client, "baduser")
    _seed("baduser", [_paper("a", title="Alpha study"), _paper("b", title="Beta trial"), _paper("c", title="Gamma cohort")])
    r = _post_selection(client, "csv", [
        {"article_id": "a", "source": "pubmed", "similarity_score": 7.5},
        {"article_id": "b", "source": "pubmed", "similarity_score": -1.0, "cluster_label": "x" * 500},
        {"article_id": "c", "source": "pubmed", "similarity_score": 0.5, "cluster_label": "Sent label"},
    ])
    assert r.status_code == 200, r.text
    rows = _csv_rows(r.text)[1:]
    assert rows[0][1] == ""
    assert rows[1][1] == "-1.000" and rows[1][11] == ""
    assert rows[2][1] == "0.500" and rows[2][11] == "Sent label"


def test_clean_score_bounds():
    assert exports._clean_score(2) == 2.0
    assert exports._clean_score(-1) == -1.0
    for bad in (2.01, -1.01, float("nan"), float("inf"), "0.5", True, None):
        assert exports._clean_score(bad) is None


# 22.9

def test_ris_writes_doi_for_any_doi_shaped_id():
    plos = {"article_id": "10.1371/journal.pone.0001", "source": "plos", "title": "T"}
    oa = {"article_id": "10.5281/zenodo.123", "source": "openaire", "title": "T"}
    bio = {"article_id": "10.1101/2024.01.01.123456", "source": "biorxiv", "title": "T"}
    pm = {"article_id": "12345", "source": "pubmed", "title": "T"}
    assert "DO  - 10.1371/journal.pone.0001" in article_to_ris(plos).splitlines()
    assert "DO  - 10.5281/zenodo.123" in article_to_ris(oa).splitlines()
    assert "DO  - 10.1101/2024.01.01.123456" in article_to_ris(bio).splitlines()
    assert "DO  -" not in article_to_ris(pm)
    assert "doi = {10.5281/zenodo.123}" in article_to_bibtex(oa)
    assert "doi = " not in article_to_bibtex(pm)


@pytest.mark.parametrize("journal", ["", None, "   ", "Unknown journal", "unknown journal."])
def test_ris_omits_placeholder_journal(journal):
    ris = article_to_ris({"article_id": "1", "source": "pubmed", "title": "T", "journal": journal})
    assert "JO  -" not in ris
    assert "JO  - Nature" in article_to_ris({"article_id": "1", "source": "pubmed", "journal": "Nature"})


def test_ris_abstract_has_no_html():
    ris = article_to_ris({
        "article_id": "1", "source": "europepmc", "title": "T",
        "abstract": "<h4>Background</h4><p>Cells &amp; <i>tissue</i> grew.</p>",
    })
    ab = [ln for ln in ris.splitlines() if ln.startswith("AB  - ")]
    assert ab == ["AB  - Background Cells & tissue grew."]
    assert "<" not in ab[0]


def test_bibtex_url_is_raw_but_never_breaks_the_entry():
    url = "https://example.org/a_b%20c#frag~x"
    entry = article_to_bibtex({"article_id": url, "source": "openaire", "title": "T"})
    assert f"url = {{{url}}}" in entry
    broken = article_to_bibtex({"article_id": "http://x.org/a}b", "source": "openaire", "title": "T"})
    assert "url = " not in broken
    broken = article_to_bibtex({"article_id": "http://x.org/a\nb", "source": "openaire", "title": "T"})
    assert "url = " not in broken


# 22.10

def test_library_export_runs_in_thread_and_is_rate_limited(app_module, monkeypatch):
    client = TestClient(app_module.app)
    _register(client, "libuser")
    _seed("libuser", [_paper("p1")])

    calls = []
    real = exports.run_in_thread

    def recording(fn, *args, **kwargs):
        calls.append(fn.__name__)
        return real(fn, *args, **kwargs)

    monkeypatch.setattr(exports, "run_in_thread", recording)
    statuses = [client.get("/api/export/library", params={"format": "csv"}).status_code for _ in range(11)]
    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429
    assert calls and set(calls) == {"_build_library_export"}
