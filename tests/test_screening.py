"""
Tests for the screening/triage layer and distinct cluster labels:

  * ClusterLabeler must produce labels whose terms never repeat across clusters
    (the old per-cluster TF-IDF gave every cluster "patients | treatment | ...").
  * ArticleDatabase screening CRUD: exclude/include roundtrip, excluded counts
    in cluster summaries and statistics, clear_all wipes screening.
  * search_similar must skip excluded articles.
  * resolve_duplicates keeps the copy with the longest abstract and excludes
    the rest, and detection stops reporting resolved groups.
"""

import numpy as np
import pytest

pytest.importorskip("sklearn")

from app.storage.database import ArticleDatabase


@pytest.fixture
def db(tmp_path):
    d = ArticleDatabase(db_path=str(tmp_path / "articles.db"))
    yield d
    d.close()


def _article(aid, source="pubmed", abstract="some abstract text", cluster=None, year="2024"):
    return {
        "article_id": aid, "source": source, "title": f"Title {aid}",
        "abstract": abstract, "year": year, "authors": [], "journal": "J",
    }


# ---------------------------------------------------------------- labels ----

def test_cluster_labels_are_distinct_across_clusters():
    from app.services.clustering import ClusterLabeler

    # Both clusters share the dominant words "patients" and "treatment";
    # each has its own theme (cardiology vs oncology).
    def mk(cid, theme, n=6):
        return [
            {"title": f"patients treatment {theme} study {i}",
             "abstract": f"patients treatment {theme} {theme} outcomes"}
            for i in range(n)
        ]

    labels = ClusterLabeler.generate_tfidf_labels({
        0: mk(0, "cardiology"),
        1: mk(1, "oncology"),
    })

    assert set(labels) == {0, 1}
    terms0 = set(t.lower() for t in labels[0].split(", "))
    terms1 = set(t.lower() for t in labels[1].split(", "))
    # No term may appear in both labels.
    assert not (terms0 & terms1), f"labels share terms: {labels}"
    # Each cluster's distinctive theme word should surface somewhere in its label.
    assert any("cardiology" in t for t in terms0)
    assert any("oncology" in t for t in terms1)


def test_cluster_labels_drop_foreign_and_short_tokens():
    from app.services.clustering import ClusterLabeler

    labels = ClusterLabeler.generate_tfidf_labels({
        0: [{"title": "κα με να gi pl abr", "abstract": "immune response signaling cascade"}],
        1: [{"title": "climate warming", "abstract": "ocean temperature rising decadal trends"}],
    })
    # Greek stop-words, 2-letter fragments and digits never reach a label:
    # every emitted token is ASCII and >= 3 characters.
    for lab in labels.values():
        for word in lab.replace(",", " ").split():
            assert word.isascii(), lab
            assert len(word) >= 3, lab


def test_representative_title_is_most_central():
    import numpy as np

    from app.services.clustering import ClusterLabeler

    ids = [("1", "s"), ("2", "s"), ("3", "s")]
    emb = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32)
    labels = np.array([0, 0, 1])
    title_by_key = {("1", "s"): "Central A", ("2", "s"): "Edge A", ("3", "s"): "Solo B"}

    reps = ClusterLabeler.pick_representative_titles(ids, emb, labels, title_by_key)
    # Cluster 0 centroid = [0.95, 0.05]; article 1 is nearest.
    assert reps[0] == "Central A"
    assert reps[1] == "Solo B"


def test_auto_select_k_finds_natural_group_count():
    import numpy as np

    from app.services.clustering import ArticleClusterer

    rng = np.random.default_rng(0)
    # Two well-separated blobs -> silhouette should pick k=2.
    a = rng.normal(0, 0.02, (30, 8)) + np.array([1, 0, 0, 0, 0, 0, 0, 0])
    b = rng.normal(0, 0.02, (30, 8)) + np.array([0, 1, 0, 0, 0, 0, 0, 0])
    X = np.vstack([a, b]).astype(np.float32)

    clusterer = ArticleClusterer(n_clusters=None, method="kmeans")
    labels = clusterer.fit(X)
    assert clusterer.resolved_n_clusters == 2
    assert len(set(labels)) == 2


def test_hdbscan_finds_dense_groups():
    import numpy as np

    from app.services.clustering import ArticleClusterer

    rng = np.random.default_rng(1)
    # Three tight, well-separated dense blobs -> HDBSCAN should recover them
    # regardless of whether UMAP or the PCA fallback does the reduction.
    blobs = [rng.normal(0, 0.01, (40, 16)) + np.eye(16)[i] for i in range(3)]
    X = np.vstack(blobs).astype(np.float32)

    clusterer = ArticleClusterer(method="hdbscan")
    labels = clusterer.fit(X)
    # Density clustering set its own count (>= 2 real topics) and labelled every
    # point (some possibly as the noise bucket, depending on the reducer).
    assert clusterer.resolved_n_clusters >= 2
    assert len(labels) == len(X)


def test_noise_bucket_is_relabelled_in_pipeline(monkeypatch):
    """The HDBSCAN noise bucket gets a fixed, honest label and no headline."""
    for _dep in ("requests", "Bio", "tqdm", "dotenv"):
        pytest.importorskip(_dep)
    import os
    import tempfile

    import numpy as np

    from app.services import clustering
    from app.services.clustering import NOISE_CLUSTER_ID, NOISE_CLUSTER_LABEL
    from app.services.pipeline import LiteratureSearchPipeline

    p = LiteratureSearchPipeline(db_path=os.path.join(tempfile.mkdtemp(), "a.db"))
    p.db.insert_articles([_article(str(i)) for i in range(6)])
    p.db.insert_embeddings(
        {(str(i), "pubmed"): np.eye(4, dtype=np.float32)[i % 4] for i in range(6)},
        model_name="general",
    )
    # Force a deterministic labelling with a noise point, bypassing HDBSCAN.
    forced = np.array([0, 0, 0, 1, 1, NOISE_CLUSTER_ID])
    monkeypatch.setattr(clustering.ArticleClusterer, "fit", lambda self, emb: forced)

    p.cluster_articles(method="hdbscan")
    clusters = {c["cluster_id"]: c for c in p.db.get_all_clusters()}
    assert clusters[NOISE_CLUSTER_ID]["cluster_label"] == NOISE_CLUSTER_LABEL
    assert clusters[NOISE_CLUSTER_ID]["representative_title"] is None
    p.close()


def test_cluster_labels_empty_and_fallback():
    from app.services.clustering import ClusterLabeler
    assert ClusterLabeler.generate_tfidf_labels({}) == {}
    # Stop-word-only text can't produce terms -> falls back to "Cluster N".
    labels = ClusterLabeler.generate_tfidf_labels({
        3: [{"title": "the and of", "abstract": "a an the"}],
    })
    assert labels[3] == "Cluster 3"


# ------------------------------------------------------------- screening ----

def test_exclude_include_roundtrip(db):
    db.insert_articles([_article("1"), _article("2", source="arxiv")])

    assert db.get_excluded_keys() == set()
    assert db.exclude_articles([("1", "pubmed")], reason="manual") == 1
    assert db.get_excluded_keys() == {("1", "pubmed")}
    assert db.get_statistics()["excluded_articles"] == 1

    assert db.include_articles([("1", "pubmed")]) == 1
    assert db.get_excluded_keys() == set()
    assert db.get_statistics()["excluded_articles"] == 0


def test_exclude_include_empty_keys_are_noop(db):
    db.insert_articles([_article("1")])
    assert db.exclude_articles([]) == 0
    assert db.include_articles([]) == 0
    assert db.get_excluded_keys() == set()


def test_reexclude_updates_reason(db):
    """INSERT OR REPLACE must refresh the reason code on re-screen."""
    db.insert_articles([_article("1"), _article("2")])
    db.exclude_articles([("1", "pubmed")], reason="off_topic")
    db.exclude_articles([("1", "pubmed")], reason="wrong_population")

    rows = {
        (r["article_id"], r["source"]): r
        for r in db.get_library_export_rows(scope="excluded")
    }
    assert rows[("1", "pubmed")]["exclusion_reason"] == "wrong_population"
    assert db.get_excluded_keys() == {("1", "pubmed")}
    # Non-excluded articles stay out of the excluded export scope.
    assert ("2", "pubmed") not in rows


def test_exclude_normalizes_unknown_and_messy_reasons(db):
    db.insert_articles([_article("1"), _article("2"), _article("3")])
    db.exclude_articles([("1", "pubmed")], reason="OFF-TOPIC")
    db.exclude_articles([("2", "pubmed")], reason="not a real code")
    db.exclude_articles([("3", "pubmed")], reason=None)

    by_key = {
        (r["article_id"], r["source"]): r["exclusion_reason"]
        for r in db.get_library_export_rows(scope="all")
        if r["excluded"]
    }
    assert by_key[("1", "pubmed")] == "off_topic"
    assert by_key[("2", "pubmed")] == "manual"
    assert by_key[("3", "pubmed")] == "manual"


def test_export_scopes_included_excluded_starred(db):
    db.insert_articles([_article("1"), _article("2"), _article("3")])
    db.exclude_articles([("1", "pubmed")], reason="language")
    db.upsert_note("2", "pubmed", note="keep", starred=True)
    db.upsert_note("3", "pubmed", note="", starred=False)

    included = {(r["article_id"], r["source"]) for r in db.get_library_export_rows("included")}
    excluded = {(r["article_id"], r["source"]) for r in db.get_library_export_rows("excluded")}
    starred = {(r["article_id"], r["source"]) for r in db.get_library_export_rows("starred")}
    assert included == {("2", "pubmed"), ("3", "pubmed")}
    assert excluded == {("1", "pubmed")}
    assert starred == {("2", "pubmed")}
    assert db.get_library_export_rows("excluded")[0]["exclusion_reason"] == "language"


def test_cluster_summary_reports_excluded_counts(db):
    db.insert_articles([_article("1"), _article("2"), _article("3")])
    db.insert_clusters({
        ("1", "pubmed"): (0, "theme a"),
        ("2", "pubmed"): (0, "theme a"),
        ("3", "pubmed"): (1, "theme b"),
    })
    db.exclude_articles([("1", "pubmed")], reason="cluster")

    summary = {c["cluster_id"]: c for c in db.get_all_clusters()}
    assert summary[0]["article_count"] == 2
    assert summary[0]["excluded_count"] == 1
    assert summary[1]["excluded_count"] == 0

    arts = {a["article_id"]: a for a in db.get_articles_by_cluster(0)}
    assert arts["1"]["excluded"] is True
    assert arts["2"]["excluded"] is False


def test_bulk_cluster_keys_exclude_all_members(db):
    db.insert_articles([_article("1"), _article("2"), _article("3")])
    db.insert_clusters({
        ("1", "pubmed"): (0, "theme a"),
        ("2", "pubmed"): (0, "theme a"),
        ("3", "pubmed"): (1, "theme b"),
    })
    keys = db.get_cluster_article_keys(0)
    assert set(keys) == {("1", "pubmed"), ("2", "pubmed")}
    n = db.exclude_articles(keys, reason="cluster")
    assert n == 2
    assert db.get_excluded_keys() == {("1", "pubmed"), ("2", "pubmed")}
    summary = {c["cluster_id"]: c for c in db.get_all_clusters()}
    assert summary[0]["excluded_count"] == 2
    assert summary[1]["excluded_count"] == 0


def test_cluster_article_keys_and_clear_all(db):
    db.insert_articles([_article("1"), _article("2")])
    db.insert_clusters({("1", "pubmed"): (0, "x"), ("2", "pubmed"): (0, "x")})
    assert set(db.get_cluster_article_keys(0)) == {("1", "pubmed"), ("2", "pubmed")}
    assert db.get_cluster_article_keys(99) == []

    db.exclude_articles([("1", "pubmed")])
    db.clear_all()
    assert db.get_excluded_keys() == set()
    assert db.get_all_articles() == []


# -------------------------------------------------------------- pipeline ----

@pytest.fixture
def pipe(tmp_path):
    for _dep in ("requests", "Bio", "tqdm", "dotenv"):
        pytest.importorskip(_dep)
    from app.services.pipeline import LiteratureSearchPipeline
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "articles.db"))
    yield p
    p.close()


def _seed_corpus(p):
    """Three articles: 1 and 2 are near-identical (cross-source duplicates),
    3 is orthogonal. Article 2 has the longer abstract (should win resolve)."""
    p.db.insert_articles([
        _article("1", source="pubmed", abstract="short"),
        _article("2", source="europepmc", abstract="a much longer, more complete abstract"),
        _article("3", source="pubmed", abstract="unrelated topic entirely"),
    ])
    p.db.insert_embeddings({
        ("1", "pubmed"): np.array([1.0, 0.0, 0.0], dtype=np.float32),
        ("2", "europepmc"): np.array([0.999, 0.04, 0.0], dtype=np.float32),
        ("3", "pubmed"): np.array([0.0, 1.0, 0.0], dtype=np.float32),
    }, model_name="general")


def test_search_skips_excluded(pipe, monkeypatch):
    _seed_corpus(pipe)
    monkeypatch.setattr(
        pipe.embedding_engine, "embed_query",
        lambda text: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )

    ids = {a["article_id"] for a in pipe.search_similar("q", top_k=10)}
    assert ids == {"1", "2", "3"}

    pipe.db.exclude_articles([("1", "pubmed")])
    ids = {a["article_id"] for a in pipe.search_similar("q", top_k=10)}
    assert ids == {"2", "3"}


def test_resolve_duplicates_keeps_longest_abstract(pipe):
    _seed_corpus(pipe)

    result = pipe.resolve_duplicates(threshold=0.95)
    assert result == {"groups": 1, "excluded": 1}

    # The short-abstract copy lost; the long one and the unrelated one survive.
    assert pipe.db.get_excluded_keys() == {("1", "pubmed")}
    loser = pipe.db.get_library_export_rows(scope="excluded")
    assert len(loser) == 1
    assert loser[0]["exclusion_reason"] == "duplicate"

    # Resolved groups stop showing up in detection.
    assert pipe.detect_duplicates(threshold=0.95) == []

    # And resolving again is a no-op.
    assert pipe.resolve_duplicates(threshold=0.95) == {"groups": 0, "excluded": 0}


def test_resolve_duplicates_tags_reason_in_report(pipe):
    _seed_corpus(pipe)
    pipe.resolve_duplicates(threshold=0.95)
    from app.utils import build_screening_report

    report = build_screening_report(pipe.db)
    assert report["excluded"]["duplicate"] == 1
    assert report["excluded"]["total"] == 1
    assert report["included"] == 2
    assert report["total_articles"] == 3


def test_search_with_filters_still_skips_excluded(pipe, monkeypatch):
    """Year/source filters apply after screening — excluded keys never reappear."""
    pipe.db.insert_articles([
        _article("1", abstract="alpha paper about sleep", year="2018"),
        _article("2", abstract="beta paper about sleep", year="2022"),
        _article("3", source="arxiv", abstract="gamma paper about sleep", year="2022"),
    ])
    pipe.db.insert_embeddings({
        ("1", "pubmed"): np.array([1.0, 0.0, 0.0], dtype=np.float32),
        ("2", "pubmed"): np.array([0.9, 0.1, 0.0], dtype=np.float32),
        ("3", "arxiv"): np.array([0.8, 0.2, 0.0], dtype=np.float32),
    }, model_name="general")
    monkeypatch.setattr(
        pipe.embedding_engine, "embed_query",
        lambda text: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )

    pipe.db.exclude_articles([("2", "pubmed")], reason="off_topic")
    hits = pipe.search_similar("sleep", top_k=10, year_min=2020, source_filter=["pubmed"])
    ids = {a["article_id"] for a in hits}
    assert "2" not in ids
    # 1 is pre-2020 so year filter drops it; 3 is arxiv so source filter drops it.
    assert ids == set()

    # Without year/source filters the excluded paper is still gone; others remain.
    hits_all = pipe.search_similar("sleep", top_k=10)
    assert {a["article_id"] for a in hits_all} == {"1", "3"}


def test_normalize_reason_codes():
    from app.content.screening_reasons import (
        EXCLUSION_REASONS,
        SYSTEM_REASONS,
        USER_SELECTABLE_REASONS,
        normalize_reason,
        reason_label,
    )

    assert normalize_reason("off_topic") == "off_topic"
    assert normalize_reason("OFF-TOPIC") == "off_topic"
    assert normalize_reason("wrong population") == "wrong_population"
    assert normalize_reason("nope") == "manual"
    assert normalize_reason(None) == "manual"
    assert normalize_reason("") == "manual"
    assert normalize_reason("  ") == "manual"
    assert "Off topic" in reason_label("off_topic")
    assert "off_topic" in USER_SELECTABLE_REASONS
    # System-assigned codes must not be offered as free student choices.
    assert SYSTEM_REASONS.isdisjoint(USER_SELECTABLE_REASONS)
    assert SYSTEM_REASONS <= set(EXCLUSION_REASONS)
    assert set(USER_SELECTABLE_REASONS) <= set(EXCLUSION_REASONS)


def test_exclusion_reason_in_report(tmp_path):
    from app.storage.database import ArticleDatabase
    from app.utils import build_screening_report, format_screening_report_txt

    db = ArticleDatabase(db_path=str(tmp_path / "r.db"))
    try:
        db.insert_articles([
            {
                "article_id": "1", "source": "pubmed", "title": "A",
                "abstract": "abs", "year": "2020", "authors": [], "journal": "",
            },
            {
                "article_id": "2", "source": "pubmed", "title": "B",
                "abstract": "abs", "year": "2020", "authors": [], "journal": "",
            },
            {
                "article_id": "3", "source": "pubmed", "title": "C",
                "abstract": "abs", "year": "2019", "authors": [], "journal": "",
            },
        ], dedupe=False)
        db.exclude_articles([("1", "pubmed")], reason="off_topic")
        db.exclude_articles([("2", "pubmed")], reason="wrong_population")
        report = build_screening_report(db)
        assert report["excluded"]["off_topic"] == 1
        assert report["excluded"]["wrong_population"] == 1
        assert report["excluded"]["total"] == 2
        assert report["included"] == 1
        assert report["by_year"].get("2020") == 2
        assert report["by_year"].get("2019") == 1
        txt = format_screening_report_txt(report)
        assert "Off topic" in txt
        assert "Wrong population" in txt
        assert "INCLUDED in final set: 1" in txt
        # Zero manual still appears for report continuity.
        assert "Excluded (Manual): 0" in txt
    finally:
        db.close()


# --------------------------------------------------------- HTTP screening ----

@pytest.fixture
def screening_app(tmp_path, monkeypatch):
    """Isolated app + user DB for screening HTTP endpoints."""
    import pathlib
    import shutil

    for _dep in (
        "fastapi", "httpx", "Bio", "sklearn", "tqdm",
        "slowapi", "jwt", "bcrypt", "multipart", "requests", "dotenv",
    ):
        pytest.importorskip(_dep)

    import os
    os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
    os.environ["DEBUG"] = "true"

    from app import core

    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    import importlib

    main = importlib.import_module("app.main")
    from app.storage.user_db import UserDatabase
    test_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", test_db)
    core._pipelines.clear()
    core._pipeline_refcounts.clear()
    core._all_progress.clear()
    try:
        core.limiter.reset()
    except Exception:
        pass
    yield main
    test_db.conn.close()


def _register_client(main, username="screenuser"):
    from fastapi.testclient import TestClient

    c = TestClient(main.app)
    resp = c.post(
        "/register",
        data={
            "username": username,
            "password": "tpw-fixture-0001",
            "password_confirm": "tpw-fixture-0001",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    return c


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _seed_user_library(main, client, n=4, with_clusters=True):
    """Insert articles (+ optional clusters) into the authenticated user's active library."""
    from app import core
    from app.core import get_pipeline, release_pipeline

    rows = core.user_db.conn.execute("SELECT id FROM users").fetchall()
    uid = rows[0][0]
    p = get_pipeline(uid)
    try:
        arts = [
            _article(str(i + 1), abstract=f"abstract body for paper {i + 1}")
            for i in range(n)
        ]
        p.db.insert_articles(arts)
        if with_clusters and n >= 4:
            p.db.insert_clusters({
                ("1", "pubmed"): (0, "theme a"),
                ("2", "pubmed"): (0, "theme a"),
                ("3", "pubmed"): (1, "theme b"),
                ("4", "pubmed"): (1, "theme b"),
            })
        p.invalidate_corpus_cache()
    finally:
        release_pipeline(uid)
    return uid


def test_api_screening_exclude_include_and_report(screening_app):
    c = _register_client(screening_app, "screener1")
    _seed_user_library(screening_app, c)

    # Unauthenticated request is rejected.
    bare = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(
        screening_app.app
    )
    unauth = bare.post(
        "/api/screening",
        json={
            "items": [{"article_id": "1", "source": "pubmed"}],
            "action": "exclude",
            "reason": "off_topic",
        },
    )
    assert unauth.status_code == 401

    r = c.post(
        "/api/screening",
        json={
            "items": [{"article_id": "1", "source": "pubmed"}],
            "action": "exclude",
            "reason": "off_topic",
        },
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success"
    assert body["action"] == "exclude"
    assert body["count"] == 1
    assert body["reason"] == "off_topic"

    report = c.get("/api/screening-report?format=json")
    assert report.status_code == 200
    data = report.json()
    assert data["excluded"]["off_topic"] == 1
    assert data["excluded"]["total"] == 1
    assert data["included"] == 3

    r = c.post(
        "/api/screening",
        json={
            "items": [{"article_id": "1", "source": "pubmed"}],
            "action": "include",
        },
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "include"
    assert r.json()["count"] == 1
    assert r.json()["reason"] is None

    report = c.get("/api/screening-report?format=json").json()
    assert report["excluded"]["total"] == 0
    assert report["included"] == 4


def test_api_cluster_screening_exclude_include(screening_app):
    c = _register_client(screening_app, "screener2")
    _seed_user_library(screening_app, c)

    r = c.post(
        "/api/clusters/0/screening",
        json={"action": "exclude", "reason": "cluster"},
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success"
    assert body["cluster_id"] == 0
    assert body["count"] == 2
    assert body["reason"] == "cluster"

    report = c.get("/api/screening-report?format=json").json()
    assert report["excluded"]["cluster"] == 2
    assert report["included"] == 2

    # Empty / missing cluster → 404
    missing = c.post(
        "/api/clusters/99/screening",
        json={"action": "exclude"},
        headers=_csrf(c),
    )
    assert missing.status_code == 404

    # Re-include the cluster.
    r = c.post(
        "/api/clusters/0/screening",
        json={"action": "include"},
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2
    report = c.get("/api/screening-report?format=json").json()
    assert report["excluded"]["total"] == 0


def test_api_screening_rejects_bad_action(screening_app):
    c = _register_client(screening_app, "screener3")
    _seed_user_library(screening_app, c, n=1, with_clusters=False)
    r = c.post(
        "/api/screening",
        json={
            "items": [{"article_id": "1", "source": "pubmed"}],
            "action": "delete",
        },
        headers=_csrf(c),
    )
    assert r.status_code == 422


def test_api_screening_normalizes_reason_on_wire(screening_app):
    c = _register_client(screening_app, "screener4")
    _seed_user_library(screening_app, c, n=1, with_clusters=False)
    r = c.post(
        "/api/screening",
        json={
            "items": [{"article_id": "1", "source": "pubmed"}],
            "action": "exclude",
            "reason": "Wrong Study Type",
        },
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    assert r.json()["reason"] == "wrong_study_type"
    report = c.get("/api/screening-report?format=json").json()
    assert report["excluded"]["wrong_study_type"] == 1
