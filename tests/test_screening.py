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

from database import ArticleDatabase


@pytest.fixture
def db(tmp_path):
    d = ArticleDatabase(db_path=str(tmp_path / "articles.db"))
    yield d
    d.close()


def _article(aid, source="pubmed", abstract="some abstract text", cluster=None):
    return {
        "article_id": aid, "source": source, "title": f"Title {aid}",
        "abstract": abstract, "year": "2024", "authors": [], "journal": "J",
    }


# ---------------------------------------------------------------- labels ----

def test_cluster_labels_are_distinct_across_clusters():
    from clustering import ClusterLabeler

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
    from clustering import ClusterLabeler

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

    from clustering import ClusterLabeler

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

    from clustering import ArticleClusterer

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

    from clustering import ArticleClusterer

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

    import clustering
    from clustering import NOISE_CLUSTER_ID, NOISE_CLUSTER_LABEL
    from pipeline import LiteratureSearchPipeline

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
    from clustering import ClusterLabeler
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


def test_cluster_article_keys_and_clear_all(db):
    db.insert_articles([_article("1"), _article("2")])
    db.insert_clusters({("1", "pubmed"): (0, "x"), ("2", "pubmed"): (0, "x")})
    assert set(db.get_cluster_article_keys(0)) == {("1", "pubmed"), ("2", "pubmed")}

    db.exclude_articles([("1", "pubmed")])
    db.clear_all()
    assert db.get_excluded_keys() == set()
    assert db.get_all_articles() == []


# -------------------------------------------------------------- pipeline ----

@pytest.fixture
def pipe(tmp_path):
    for _dep in ("requests", "Bio", "tqdm", "dotenv"):
        pytest.importorskip(_dep)
    from pipeline import LiteratureSearchPipeline
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

    # Resolved groups stop showing up in detection.
    assert pipe.detect_duplicates(threshold=0.95) == []

    # And resolving again is a no-op.
    assert pipe.resolve_duplicates(threshold=0.95) == {"groups": 0, "excluded": 0}
