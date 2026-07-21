"""Unit + endpoint tests for RIS / BibTeX citation export."""

import os
import pathlib
import shutil

import pytest

for _dep in (
    "fastapi", "httpx", "Bio", "sklearn", "plotly", "tqdm",
    "slowapi", "jwt", "passlib", "multipart", "requests", "dotenv",
):
    pytest.importorskip(_dep)

from fastapi.testclient import TestClient

from citations import article_to_bibtex, article_to_ris, collection_to_ris


def _sample_crossref():
    return {
        "article_id": "10.1234/ab.cd",
        "source": "crossref",
        "title": "Ocean {Warming} Trends",
        "abstract": "Seas are\nwarming rapidly.",
        "year": "2021",
        "authors": ["Ada Lovelace", "Grace Hopper"],
        "journal": "Nature Climate",
    }


def _sample_pubmed_no_year():
    return {
        "article_id": "12345",
        "source": "pubmed",
        "title": "A clinical trial",
        "abstract": "Methods and results.",
        "year": "Unknown",
        "authors": ["Doe J"],
        "journal": "Lancet",
    }


def test_ris_multi_author_and_doi_rules():
    ris = article_to_ris(_sample_crossref())
    assert "TY  - JOUR" in ris
    assert "AU  - Ada Lovelace" in ris
    assert "AU  - Grace Hopper" in ris
    assert "DO  - 10.1234/ab.cd" in ris
    assert "PY  - 2021" in ris
    assert "AB  - Seas are warming rapidly." in ris
    assert ris.rstrip().endswith("ER  -") or "ER  - " in ris
    assert ris.endswith("\n") or ris.rstrip().endswith("ER  -")

    pubmed = article_to_ris(_sample_pubmed_no_year())
    assert "DO  - " not in pubmed
    assert "PY  - " not in pubmed
    assert "ER  - " in pubmed


def test_bibtex_key_authors_and_escape():
    bib = article_to_bibtex(_sample_crossref())
    assert "@article{crossref_10_1234_ab_cd," in bib
    assert "Ada Lovelace and Grace Hopper" in bib
    assert r"Ocean \{Warming\} Trends" in bib
    assert "doi = {10.1234/ab.cd}" in bib
    assert "note = {Source: crossref}" in bib

    pubmed = article_to_bibtex(_sample_pubmed_no_year())
    assert "doi =" not in pubmed
    assert "year =" not in pubmed

    latexy = article_to_bibtex({
        "article_id": "1",
        "source": "pubmed",
        "title": "Gene p_value costs $100",
        "abstract": "",
        "year": "2020",
        "authors": [],
        "journal": "",
    })
    assert r"p\_value" in latexy
    assert r"\$100" in latexy


def test_collection_to_ris_joins():
    out = collection_to_ris([_sample_crossref(), _sample_pubmed_no_year()])
    assert out.count("TY  - JOUR") == 2
    assert out.count("ER  - ") == 2


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
    os.environ["DEBUG"] = "true"
    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)

    import importlib
    main = importlib.import_module("main")
    from user_db import UserDatabase
    main.user_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    main._pipelines.clear()
    main._pipeline_refcounts.clear()
    main._all_progress.clear()
    main._pending_close.clear()
    return main


def _register(client, username="citeuser"):
    r = client.post(
        "/register",
        data={"username": username, "password": "tpw-fixture-0001", "password_confirm": "tpw-fixture-0001"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text


def test_export_library_ris_endpoint(app_module):
    main = app_module
    c = TestClient(main.app)
    _register(c)

    # Touch pipeline so user_data dir exists, then seed one article.
    assert c.get("/api/statistics").status_code == 200
    uid = main.user_db.get_by_username("citeuser")["id"]
    p = main.get_pipeline(uid)
    try:
        p.db.insert_articles([{
            "article_id": "999",
            "source": "pubmed",
            "title": "Endpoint Paper",
            "abstract": "Abstract body",
            "year": "2020",
            "authors": ["Tester"],
            "journal": "J Test",
        }])
    finally:
        main.release_pipeline(uid)

    resp = c.get("/api/export/library?format=ris&scope=all")
    assert resp.status_code == 200
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd.lower()
    assert "library.ris" in cd
    assert "TY  - JOUR" in resp.text
    assert "Endpoint Paper" in resp.text

    # Selection export (what Search uses for "these results")
    csrf = c.cookies.get("csrf_token")
    sel = c.post(
        "/api/export/selection",
        json={
            "format": "ris",
            "items": [{"article_id": "999", "source": "pubmed"}],
        },
        headers={"X-CSRF-Token": csrf} if csrf else {},
    )
    assert sel.status_code == 200, sel.text
    assert "search_results.ris" in (sel.headers.get("content-disposition") or "")
    assert "Endpoint Paper" in sel.text
    assert "TY  - JOUR" in sel.text


def test_screening_report_endpoint_empty(app_module):
    main = app_module
    c = TestClient(main.app)
    _register(c, "reportuser")

    r = c.get("/api/screening-report?format=json")
    assert r.status_code == 200
    body = r.json()
    assert body["total_articles"] == 0
    assert body["excluded"]["total"] == 0
    assert body["included"] == 0

    txt = c.get("/api/screening-report?format=txt")
    assert txt.status_code == 200
    assert "SCREENING REPORT - 0 papers collected" in txt.text
    assert "attachment" in txt.headers.get("content-disposition", "").lower()
    assert "screening_report.txt" in txt.headers.get("content-disposition", "")
