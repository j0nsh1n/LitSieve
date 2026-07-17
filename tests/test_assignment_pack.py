"""Phase R3: assignment hand-in pack + soft checklist."""

from __future__ import annotations

import io
import os
import pathlib
import shutil
import zipfile

import pytest

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

for _dep in (
    "fastapi", "httpx", "Bio", "sklearn", "plotly", "tqdm",
    "slowapi", "jwt", "passlib", "multipart", "requests", "dotenv",
):
    pytest.importorskip(_dep)

from assignment_pack import (
    HANDIN_README,
    build_assignment_zip,
    evaluate_assignment_checklist,
    library_rows_to_csv,
)
from database import ArticleDatabase
from fastapi.testclient import TestClient
from sample_corpus import get_sample_articles


def _seed_mixed(db: ArticleDatabase):
    arts = [
        {
            "article_id": "a1",
            "source": "pubmed",
            "title": "A systematic review of tutoring programs",
            "abstract": "This systematic review synthesizes 20 trials of tutoring.",
            "year": "2020",
            "authors": ["A A"],
            "journal": "J",
        },
        {
            "article_id": "a2",
            "source": "eric",
            "title": "Classroom trial of feedback",
            "abstract": "In this randomized controlled trial, 100 students were assigned.",
            "year": "2021",
            "authors": ["B B"],
            "journal": "J",
        },
        {
            "article_id": "a3",
            "source": "openalex",
            "title": "Observational notes on labs",
            "abstract": "A prospective cohort study followed 50 students for one year.",
            "year": "2019",
            "authors": ["C C"],
            "journal": "J",
        },
    ]
    db.insert_articles(arts, dedupe=False)
    # Exclude one so included set is smaller.
    db.exclude_articles([("a3", "openalex")], reason="off_topic")
    db.upsert_note("a1", "pubmed", note="Use for intro", starred=True)


def test_library_rows_to_csv_has_starred_and_note(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "c.db"))
    try:
        _seed_mixed(db)
        rows = db.get_library_export_rows(scope="included")
        csv_body = library_rows_to_csv(rows)
        header = csv_body.splitlines()[0]
        assert "Starred" in header
        assert "Note" in header
        assert "Use for intro" in csv_body
        assert "yes" in csv_body  # starred
    finally:
        db.close()


def test_build_assignment_zip_contents(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "z.db"))
    try:
        _seed_mixed(db)
        raw = build_assignment_zip(db)
        zf = zipfile.ZipFile(io.BytesIO(raw))
        names = set(zf.namelist())
        assert names == {
            "screening_report.txt",
            "included_papers.csv",
            "included_papers.ris",
            "README_handin.txt",
        }
        report = zf.read("screening_report.txt").decode()
        assert "SCREENING REPORT" in report or "INCLUDED" in report.upper()
        csv_body = zf.read("included_papers.csv").decode()
        assert "Starred" in csv_body
        assert "systematic review" in csv_body.lower() or "tutoring" in csv_body.lower()
        # Excluded paper should not be in included CSV.
        assert "Observational notes" not in csv_body
        ris = zf.read("included_papers.ris").decode()
        assert "TY  -" in ris or ris == ""
        readme = zf.read("README_handin.txt").decode()
        assert "Starred" in readme
        assert "Note" in readme
        assert "soft" in HANDIN_README.lower() or "process" in readme.lower()
    finally:
        db.close()


def test_checklist_soft_hints(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "h.db"))
    try:
        _seed_mixed(db)
        # min_included=2, min_sources=2, require review — should pass with 2 included + review
        ok = evaluate_assignment_checklist(
            db, min_sources=2, min_included=2, require_review=True,
        )
        assert ok["included"] == 2
        assert ok["unique_sources"] == 2
        assert ok["review_like_count"] >= 1
        assert ok["all_ok"] is True
        assert ok["soft"] is True

        # Harder targets fail softly without blocking concept.
        miss = evaluate_assignment_checklist(
            db, min_sources=10, min_included=50, require_review=True,
        )
        assert miss["all_ok"] is False
        assert any(not h["ok"] for h in miss["hints"])
        assert "download" in miss["message"].lower() or "soft" in miss["message"].lower()
    finally:
        db.close()


def test_sample_corpus_has_science_and_civics():
    arts = get_sample_articles()
    assert len(arts) >= 26
    blob = " ".join(a["title"] + " " + a["abstract"] for a in arts).lower()
    assert "heat" in blob or "microplastic" in blob or "ocean" in blob
    assert "voter" in blob or "municipal" in blob or "legislative" in blob


@pytest.fixture
def app_client(tmp_path, monkeypatch):
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
    return main


def test_http_assignment_pack_and_checklist(app_client):
    main = app_client
    c = TestClient(main.app)
    r = c.post(
        "/register",
        data={
            "username": "handin_user",
            "password": "tpw-fixture-0001",
            "password_confirm": "tpw-fixture-0001",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    csrf = {"X-CSRF-Token": c.cookies.get("csrf_token")}

    # Load sample so pack has content.
    r = c.post("/api/load-sample-corpus", json={"clear_first": True}, headers=csrf)
    assert r.status_code == 200

    pack = c.get("/api/export/assignment-pack")
    assert pack.status_code == 200, pack.text[:300]
    assert "zip" in (pack.headers.get("content-type") or "").lower() or pack.content[:2] == b"PK"
    zf = zipfile.ZipFile(io.BytesIO(pack.content))
    assert "screening_report.txt" in zf.namelist()
    assert "included_papers.csv" in zf.namelist()

    check = c.get(
        "/api/assignment-checklist?min_sources=1&min_included=5&require_review=false"
    )
    assert check.status_code == 200
    body = check.json()
    assert body["soft"] is True
    assert "hints" in body
    assert body["included"] >= 20
