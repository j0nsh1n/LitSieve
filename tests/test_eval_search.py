"""Offline tests for the search-benchmark harness (no provider calls)."""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("eval_search", REPO / "tools" / "eval_search.py")
ev = importlib.util.module_from_spec(_spec)
sys.modules["eval_search"] = ev
assert _spec.loader is not None
_spec.loader.exec_module(ev)

TINY = REPO / "tests" / "fixtures" / "eval_search" / "tiny"


def _write_questions(path: Path) -> None:
    path.write_text(json.dumps({
        "questions": [{
            "id": "Q1",
            "text": "How do later school start times affect sleep duration among adolescents?",
            "topic": "health",
        }]
    }), encoding="utf-8")


class _FakeFetcher:
    def __init__(self, email: str = "") -> None:
        self.sent_query = None

    def search_and_fetch(self, query: str, max_results: int = 50):
        self.sent_query = f"SENT:{query}"
        return [{
            "article_id": "10.1234/paper-0",
            "source": "openalex",
            "title": "Later school start times increase adolescent sleep duration",
            "abstract": "Sleep duration increased.",
            "year": "2018",
            "authors": ["Doe J"],
            "journal": "Sleep Health",
            "work_type": "journal-article",
            "doi": "10.1234/paper-0",
        }]


def _patch_embeddings(monkeypatch) -> None:
    from app.services.embeddings import EmbeddingEngine

    def embed_articles(self, articles, batch_size=32, progress_callback=None):
        out = {}
        for article in articles:
            vec = np.zeros(8, dtype=np.float32)
            title = (article.get("title") or "").lower()
            if "sleep" in title:
                vec[0] = 1.0
            elif "new deal" in title:
                vec[1] = 1.0
            else:
                vec[2] = 1.0
            out[(article["article_id"], article["source"])] = vec
        return out

    def embed_query(self, query_text: str):
        vec = np.zeros(8, dtype=np.float32)
        text = (query_text or "").lower()
        if "sleep" in text:
            vec[0] = 1.0
        elif "new deal" in text:
            vec[1] = 1.0
        else:
            vec[2] = 1.0
        return vec

    monkeypatch.setattr(EmbeddingEngine, "embed_articles", embed_articles)
    monkeypatch.setattr(EmbeddingEngine, "embed_query", embed_query)
    monkeypatch.setattr(ev, "available_ram_gb", lambda: 16.0)


def test_assign_split_is_stable():
    assert ev.assign_split("10.1234/paper-0") == "dev"
    assert ev.assign_split("10.1234/paper-1") == "test"
    assert ev.assign_split("10.1234/paper-0") == "dev"


def test_ndcg_hand_computed():
    # Ranked worst-first: incidental (0) then direct_answer (3).
    # DCG@10 = 3 / log2(3). IDCG@10 = 3 / log2(2) = 3.
    keys = ["k-inc", "k-dir"]
    labels = {"k-inc": "incidental", "k-dir": "direct_answer"}
    expected = (3.0 / math.log2(3)) / 3.0
    assert ev.ndcg_at(keys, labels, 10) == pytest.approx(expected, rel=1e-12)


def test_cohen_kappa_hand_computed():
    # A: D, M, B, I  B: D, B, B, I  → po=0.75, pe=0.25, κ=2/3.
    first = ["direct_answer", "mechanism_or_implementation", "background", "incidental"]
    second = ["direct_answer", "background", "background", "incidental"]
    assert ev.cohen_kappa(first, second) == pytest.approx(2.0 / 3.0, rel=1e-12)


def test_capture_refuses_inside_repo(tmp_path):
    qfile = tmp_path / "q.json"
    _write_questions(qfile)
    inside = ev.REPO_ROOT / "tools" / "bench" / "should-not-write"
    with pytest.raises(SystemExit, match="refusing to write corpus inside the repo"):
        ev.main(["capture", "--question-set", str(qfile), "--out", str(inside)])
    assert not inside.exists()


def test_capture_writes_outside_repo(tmp_path, monkeypatch):
    qfile = tmp_path / "q.json"
    _write_questions(qfile)
    monkeypatch.setattr(ev, "FETCHERS", {"openalex": _FakeFetcher})
    monkeypatch.setattr(ev, "sources_for_topic", lambda topic: ["openalex"])
    out = tmp_path / "corpus"
    assert ev.main([
        "capture", "--question-set", str(qfile), "--out", str(out),
        "--sources", "openalex", "--max-results", "5",
    ]) == 0
    articles = json.loads((out / "Q1" / "openalex.json").read_text(encoding="utf-8"))
    assert articles[0]["doi"] == "10.1234/paper-0"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    file_info = manifest["questions"][0]["files"]["openalex"]
    assert file_info["count"] == 1
    assert file_info["sent_query"].startswith("SENT:")
    assert file_info["error_kind"] is None
    assert file_info["sha256"]


def test_replay_determinism(tmp_path, monkeypatch):
    _patch_embeddings(monkeypatch)
    first = tmp_path / "r1.json"
    second = tmp_path / "r2.json"
    work = tmp_path / "work"
    args = [
        "replay", "--corpus", str(TINY), "--ranker", "baseline",
        "--work-dir", str(work),
    ]
    assert ev.main([*args, "--out", str(first)]) == 0
    # Fresh DB so insert/embed run again.
    for db in work.glob("*/articles.db"):
        db.unlink()
    assert ev.main([*args, "--out", str(second)]) == 0
    a = json.loads(first.read_text(encoding="utf-8"))
    b = json.loads(second.read_text(encoding="utf-8"))
    on_a = [h["key"] for h in a["questions"][0]["rankings"]["lexical_on"]]
    on_b = [h["key"] for h in b["questions"][0]["rankings"]["lexical_on"]]
    off_a = [h["key"] for h in a["questions"][0]["rankings"]["lexical_off"]]
    off_b = [h["key"] for h in b["questions"][0]["rankings"]["lexical_off"]]
    assert on_a == on_b
    assert off_a == off_b
    assert on_a[0] == "10.1234/paper-0"


def test_replay_hits_carry_stored_work_type(tmp_path, monkeypatch):
    """Replay snapshots must copy type, DOI and container from the corpus row.

    Ranking reads SEARCH_ARTICLE_COLUMNS, so a DOI that is not the article_id
    and a container_title never appear unless the harness joins the stored row.
    """
    _patch_embeddings(monkeypatch)
    corpus = tmp_path / "corpus"
    qdir = corpus / "Q1"
    qdir.mkdir(parents=True)
    articles = [{
        "article_id": "W999typed",
        "source": "openalex",
        "title": "Later school start times increase adolescent sleep duration",
        "abstract": "Sleep duration increased.",
        "year": "2018",
        "authors": ["Doe J"],
        "journal": "Sleep Series",
        "work_type": "book-chapter",
        "doi": "10.9999/typed-chapter",
        "container_title": "Parent Book of Sleep",
    }]
    (qdir / "openalex.json").write_text(json.dumps(articles), encoding="utf-8")
    (corpus / "manifest.json").write_text(json.dumps({
        "git_sha": "testdata",
        "questions": [{
            "id": "Q1",
            "text": "How do later school start times affect sleep duration among adolescents?",
            "topic": "health",
        }],
    }), encoding="utf-8")
    results = tmp_path / "results.json"
    assert ev.main([
        "replay", "--corpus", str(corpus), "--out", str(results),
        "--work-dir", str(tmp_path / "work"),
    ]) == 0
    hits = json.loads(results.read_text(encoding="utf-8"))["questions"][0]["rankings"]["lexical_on"]
    assert hits
    hit = hits[0]
    assert hit["work_type"] == "book-chapter"
    assert hit["doi"] == "10.9999/typed-chapter"
    assert hit["container_title"] == "Parent Book of Sleep"


def test_labelsheet_output(tmp_path, monkeypatch):
    _patch_embeddings(monkeypatch)
    results = tmp_path / "results.json"
    work = tmp_path / "work"
    assert ev.main([
        "replay", "--corpus", str(TINY), "--out", str(results),
        "--work-dir", str(work),
    ]) == 0
    payload = json.loads(results.read_text(encoding="utf-8"))
    ranked = [h["key"] for h in payload["questions"][0]["rankings"]["lexical_on"]]
    sheets = tmp_path / "sheets"
    assert ev.main(["labelsheet", "--results", str(results), "--out", str(sheets)]) == 0
    readme = (sheets / "README.md").read_text(encoding="utf-8")
    assert "direct_answer" in readme
    assert "Models do not write these labels" in readme
    assert "Q*.html" in readme
    assert "CSV" in readme
    with (sheets / "Q1.csv").open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(ev.SHEET_COLUMNS)
        assert reader.fieldnames[:4] == ["key", "title", "abstract", "link"]
        assert reader.fieldnames[4:13] == [
            "category", "rationale", "use_in_paper", "work_type", "access_state",
            "checked_at", "inspection_depth", "duplicate_of", "labeller",
        ]
        assert reader.fieldnames[-2:] == ["rank_lexical_on", "rank_lexical_off"]
        rows = list(reader)
    keys = [row["key"] for row in rows]
    assert "10.1234/paper-0" in keys
    assert keys != ranked
    by_key = {row["key"]: row for row in rows}
    paper0 = by_key["10.1234/paper-0"]
    assert paper0["split"] == "dev"
    assert by_key["10.1234/paper-1"]["split"] == "test"
    assert paper0["category"] == ""
    assert paper0["labeller"] == ""
    assert paper0["work_type"] == ""
    assert paper0["abstract"] == (
        "A trial of later start times found longer sleep among adolescents."
    )
    assert paper0["link"] == "https://doi.org/10.1234/paper-0"
    assert paper0["container"] == "Sleep Health"
    assert paper0["stored_type"] == "journal-article"
    pubmed = by_key["pubmed:999000"]
    assert pubmed["link"] == "https://pubmed.ncbi.nlm.nih.gov/999000/"
    assert pubmed["abstract"].startswith("Lighting conditions")
    page = (sheets / "Q1.html").read_text(encoding="utf-8")
    assert "How do later school start times affect sleep duration among adolescents?" in page
    assert paper0["title"] in page
    assert paper0["abstract"] in page
    assert paper0["link"] in page
    assert "10.1234/paper-0" in page
    assert "rank_lexical" not in page
    assert "<link" not in page
    assert "src=" not in page
    second = tmp_path / "sheets2"
    assert ev.main(["labelsheet", "--results", str(results), "--out", str(second)]) == 0
    with (second / "Q1.csv").open(encoding="utf-8") as handle:
        again = [row["key"] for row in csv.DictReader(handle)]
    assert again == keys


def test_labelsheet_html_escapes(tmp_path):
    corpus = tmp_path / "corpus"
    qdir = corpus / "Q1"
    qdir.mkdir(parents=True)
    articles = [
        {
            "article_id": "10.1234/x",
            "source": "crossref",
            "title": 'Foo <script>alert(1)</script> & "Bar"',
            "abstract": "A <b>bold</b> abstract.",
            "year": "2019",
            "journal": "Sleep Health",
            "container_title": "Sleep & Dreams",
            "work_type": "journal-article",
            "doi": "10.1234/x",
        },
        {
            "article_id": "999",
            "source": "pubmed",
            "title": "No doi paper",
            "abstract": "Plain abstract.",
            "year": "2017",
            "journal": "Sleep Health",
            "work_type": "review-article",
            "doi": None,
        },
    ]
    (qdir / "crossref.json").write_text(json.dumps(articles), encoding="utf-8")
    results = {
        "corpus": str(corpus),
        "questions": [{
            "id": "Q1",
            "text": "Does later start <help> sleep?",
            "rankings": {
                "lexical_on": [
                    {
                        "rank": 1, "key": "10.1234/x",
                        "title": articles[0]["title"], "source": "crossref",
                        "article_id": "10.1234/x", "year": "2019",
                        "journal": "Sleep Health", "work_type": None,
                    },
                    {
                        "rank": 2, "key": "pubmed:999",
                        "title": "No doi paper", "source": "pubmed",
                        "article_id": "999", "year": "2017",
                        "journal": "Sleep Health", "work_type": None,
                    },
                ],
                "lexical_off": [],
            },
        }],
    }
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")
    sheets = tmp_path / "sheets"
    assert ev.main(["labelsheet", "--results", str(results_path), "--out", str(sheets)]) == 0
    page = (sheets / "Q1.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "&lt;help&gt;" in page
    assert "&lt;b&gt;bold&lt;/b&gt;" in page
    assert "Sleep &amp; Dreams" in page
    assert "https://doi.org/10.1234/x" in page
    assert "https://pubmed.ncbi.nlm.nih.gov/999/" in page
    with (sheets / "Q1.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_key = {row["key"]: row for row in rows}
    assert by_key["10.1234/x"]["container"] == "Sleep & Dreams"
    assert by_key["10.1234/x"]["stored_type"] == "journal-article"
    assert by_key["pubmed:999"]["stored_type"] == "review-article"
    assert by_key["pubmed:999"]["link"] == "https://pubmed.ncbi.nlm.nih.gov/999/"
    expected = ev.shuffle_sheet_rows("Q1", [{"key": "10.1234/x"}, {"key": "pubmed:999"}])
    assert [row["key"] for row in rows] == [row["key"] for row in expected]
    second = tmp_path / "sheets2"
    assert ev.main(["labelsheet", "--results", str(results_path), "--out", str(second)]) == 0
    with (second / "Q1.csv").open(encoding="utf-8") as handle:
        again = [row["key"] for row in csv.DictReader(handle)]
    assert again == [row["key"] for row in rows]


def test_shuffle_sheet_rows_is_stable_and_not_rank_order():
    ranked = [{"key": f"k{i}", "rank_lexical_on": str(i + 1)} for i in range(10)]
    first = ev.shuffle_sheet_rows("Q1", ranked)
    second = ev.shuffle_sheet_rows("Q1", ranked)
    assert [row["key"] for row in first] == [row["key"] for row in second]
    assert [row["key"] for row in first] != [row["key"] for row in ranked]
    other = ev.shuffle_sheet_rows("Q2", ranked)
    assert [row["key"] for row in other] != [row["key"] for row in first]


def test_score_metrics(tmp_path):
    results = {
        "questions": [{
            "id": "Q1",
            "text": "sleep",
            "rankings": {
                "lexical_on": [
                    {
                        "rank": 1, "key": "k-inc", "title": "inc",
                        "work_type": "journal-article", "source": "openalex",
                        "article_id": "a", "journal": "Sleep",
                    },
                    {
                        "rank": 2, "key": "k-dir", "title": "dir",
                        "work_type": "journal-article", "source": "openalex",
                        "article_id": "b", "journal": "Sleep",
                    },
                    {
                        "rank": 3, "key": "k-rel", "title": "rel",
                        "work_type": "book", "source": "openalex",
                        "article_id": "c", "journal": "",
                    },
                ],
            },
            "timings": {"embed_s": 0.1, "lexical_on_s": 0.01, "lexical_off_s": 0.01},
        }]
    }
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    labels_dir.joinpath("Q1.json").write_text(json.dumps([
        {
            "key": "k-inc", "title": "inc", "labeller": "owner",
            "category": "incidental", "work_type": "journal-article",
            "split": "dev",
        },
        {
            "key": "k-dir", "title": "dir", "labeller": "owner",
            "category": "direct_answer", "work_type": "journal-article",
            "split": "dev",
        },
        {
            "key": "k-rel", "title": "rel", "labeller": "owner",
            "category": "related_subject", "work_type": "book",
            "split": "dev",
        },
        {
            "key": "k-inc", "title": "inc", "labeller": "second",
            "category": "incidental", "work_type": "journal-article",
            "split": "dev",
        },
        {
            "key": "k-dir", "title": "dir", "labeller": "second",
            "category": "background", "work_type": "journal-article",
            "split": "dev",
        },
        {
            "key": "k-rel", "title": "rel", "labeller": "second",
            "category": "related_subject", "work_type": "book",
            "split": "dev",
        },
    ]), encoding="utf-8")
    out = tmp_path / "scores.json"
    assert ev.main([
        "score", "--results", str(results_path), "--labels", str(labels_dir),
        "--split", "all", "--out", str(out),
    ]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    row = payload["questions"][0]
    assert row["relevant@5"] == 1
    assert row["relevant@10"] == 1
    assert row["topic_only@10"] == 2
    assert row["unlabelled@10"] == 0
    expected_ndcg = (3.0 / math.log2(3)) / 3.0
    assert row["ndcg@10"] == pytest.approx(expected_ndcg, abs=1e-4)
    assert row["type_accuracy"] == 1.0
    assert row["export_accuracy"] == 1.0
    # owner vs second on three keys: agree, disagree, agree → po=2/3.
    assert row["kappa"] is not None


def test_bm25_scores_stay_in_unit_interval():
    from app.services.lexical import bm25_scores

    docs = [
        "later school start times and adolescent sleep duration sleep sleep",
        "unrelated mining geology quartz",
        "",
    ]
    scores = bm25_scores("later school start times sleep", docs)
    assert len(scores) == 3
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores[0] > scores[1]
    assert scores[1] == 0.0 or scores[1] < scores[0]
    empty = bm25_scores("zzzznotaword", docs)
    assert empty == [0.0, 0.0, 0.0]


def test_p22_ranker_is_registered():
    assert "p22_sweep" in ev.RANKERS
    names = [name for name, *_ in ev.p22_configs()]
    assert len(names) == 48
    assert "blend_w0.3_tfidf_raw" in names
    assert "bonus_w0.15_bm25_keywords" in names


def test_p22_sweep_replay_uses_keywords_query(tmp_path, monkeypatch):
    _patch_embeddings(monkeypatch)
    results = tmp_path / "results.json"
    assert ev.main([
        "replay", "--corpus", str(TINY), "--ranker", "p22_sweep",
        "--work-dir", str(tmp_path / "work"), "--out", str(results),
    ]) == 0
    payload = json.loads(results.read_text(encoding="utf-8"))
    rankings = payload["questions"][0]["rankings"]
    assert "lexical_on" in rankings
    assert "blend_w0.3_tfidf_raw" in rankings
    assert "bonus_w0.1_bm25_keywords" in rankings
    raw_q = ev.lexical_query_text(
        "How do later school start times affect sleep duration among adolescents?",
        "raw",
    )
    key_q = ev.lexical_query_text(
        "How do later school start times affect sleep duration among adolescents?",
        "keywords",
    )
    assert "How" in raw_q
    assert "How" not in key_q
    assert "sleep" in key_q
    assert "adolescents" in key_q


def test_choose_p22_prefers_simple_near_best():
    scored = []
    for qid in ("Q1", "Q2"):
        scored.append({"id": qid, "ranking": "lexical_on", "ndcg@10": 0.40})
        scored.append({"id": qid, "ranking": "bonus_w0.3_bm25_keywords", "ndcg@10": 0.50})
        scored.append({"id": qid, "ranking": "bonus_w0.05_tfidf_keywords", "ndcg@10": 0.495})
        scored.append({"id": qid, "ranking": "blend_w0.05_tfidf_raw", "ndcg@10": 0.494})
        scored.append({"id": qid, "ranking": "bonus_w0.3_tfidf_raw", "ndcg@10": 0.30})
    choice = ev.choose_p22(scored)
    # 0.50 is best; 0.494 and 0.495 are inside 0.01; smallest w + tfidf + blend + raw wins.
    assert choice["name"] == "blend_w0.05_tfidf_raw"
    assert choice["beats_baseline"] is True


def test_leave_one_out_p22_picks_on_the_other_questions():
    scored = []
    for qid, bonus, blend in (
        ("Q1", 0.52, 0.515),
        ("Q2", 0.52, 0.515),
        ("Q3", 0.52, 0.20),
    ):
        scored.append({"id": qid, "ranking": "lexical_on", "ndcg@10": 0.40})
        scored.append({"id": qid, "ranking": "bonus_w0.3_bm25_keywords", "ndcg@10": bonus})
        scored.append({"id": qid, "ranking": "blend_w0.05_tfidf_raw", "ndcg@10": blend})
        scored.append({"id": qid, "ranking": "bonus_w0.3_tfidf_raw", "ndcg@10": 0.30})
    loo = ev.leave_one_out_p22(scored, top_n=2)
    names = [row["name"] for row in loo["top"]]
    assert names[0] == "bonus_w0.3_bm25_keywords"
    assert names[1] == "blend_w0.05_tfidf_raw"
    by_held = {fold["held_out"]: fold for fold in loo["folds"]}
    assert by_held["Q3"]["picked"] == "blend_w0.05_tfidf_raw"
    assert by_held["Q3"]["held_ndcg"] == 0.20
    assert by_held["Q3"]["beats_held_baseline"] is False
    assert by_held["Q1"]["picked"] == "bonus_w0.3_bm25_keywords"
    assert by_held["Q1"]["held_ndcg"] == 0.52
    assert by_held["Q1"]["beats_held_baseline"] is True


def _loo_held_out_fixture(held_a: float) -> list:
    scored = []
    for qid, a_score, b_score in (
        ("Q1", 0.6, 0.5),
        ("Q2", 0.6, 0.5),
        ("Q3", held_a, 0.8),
    ):
        scored.append({"id": qid, "ranking": "lexical_on", "ndcg@10": 0.4})
        scored.append({"id": qid, "ranking": "bonus_w0.2_bm25_keywords", "ndcg@10": a_score})
        scored.append({"id": qid, "ranking": "blend_w0.3_tfidf_raw", "ndcg@10": b_score})
    return scored


def test_leave_one_out_p22_held_out_scores_do_not_change_the_fold_pick():
    low = ev.leave_one_out_p22(_loo_held_out_fixture(0.0), top_n=1)
    high = ev.leave_one_out_p22(_loo_held_out_fixture(1.0), top_n=1)
    low_pick = next(fold["picked"] for fold in low["folds"] if fold["held_out"] == "Q3")
    high_pick = next(fold["picked"] for fold in high["folds"] if fold["held_out"] == "Q3")
    assert low_pick == high_pick == "bonus_w0.2_bm25_keywords"


def test_leave_one_out_p22_held_out_cannot_swap_the_shortlist_boundary():
    names = [
        "blend_w0.05_tfidf_raw",
        "blend_w0.1_tfidf_raw",
        "blend_w0.15_tfidf_raw",
        "blend_w0.2_tfidf_raw",
        "blend_w0.25_tfidf_raw",
        "blend_w0.3_tfidf_raw",
    ]
    train_scores = [0.90, 0.50, 0.49, 0.48, 0.47, 0.46]

    def scored_for(held_rest: float) -> list:
        rows = []
        for qid in ("Q1", "Q2", "Q3"):
            rows.append({"id": qid, "ranking": "lexical_on", "ndcg@10": 0.4})
            for name, train in zip(names, train_scores):
                ndcg = train if qid != "Q3" else (0.0 if name == names[0] else held_rest)
                rows.append({"id": qid, "ranking": name, "ndcg@10": ndcg})
        return rows

    low = ev.leave_one_out_p22(scored_for(0.0), top_n=5)
    high = ev.leave_one_out_p22(scored_for(1.0), top_n=5)
    low_pick = next(fold["picked"] for fold in low["folds"] if fold["held_out"] == "Q3")
    high_pick = next(fold["picked"] for fold in high["folds"] if fold["held_out"] == "Q3")
    assert low_pick == high_pick == names[0]


def _tiny_p22_score_inputs(tmp_path: Path):
    results = {
        "questions": [{
            "id": "Q1",
            "text": "sleep",
            "rankings": {
                "lexical_on": [{
                    "rank": 1, "key": "k-dir", "title": "dir",
                    "work_type": "journal-article", "source": "openalex",
                    "article_id": "b", "journal": "Sleep",
                }],
                "bonus_w0.2_bm25_keywords": [{
                    "rank": 1, "key": "k-dir", "title": "dir",
                    "work_type": "journal-article", "source": "openalex",
                    "article_id": "b", "journal": "Sleep",
                }],
                "blend_w0.3_tfidf_raw": [{
                    "rank": 1, "key": "k-inc", "title": "inc",
                    "work_type": "journal-article", "source": "openalex",
                    "article_id": "a", "journal": "Sleep",
                }],
            },
            "timings": {"embed_s": 0.1, "lexical_on_s": 0.01, "lexical_off_s": 0.01},
        }]
    }
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    labels_dir.joinpath("Q1.json").write_text(json.dumps([
        {
            "key": "k-dir", "title": "dir", "labeller": "owner",
            "category": "direct_answer", "work_type": "journal-article",
            "split": "test",
        },
        {
            "key": "k-inc", "title": "inc", "labeller": "owner",
            "category": "incidental", "work_type": "journal-article",
            "split": "test",
        },
    ]), encoding="utf-8")
    return results_path, labels_dir


def test_cmd_score_refuses_p22_test_and_all_splits(tmp_path, capsys):
    results_path, labels_dir = _tiny_p22_score_inputs(tmp_path)
    out = tmp_path / "scores.json"
    table = tmp_path / "table.md"
    for split in ("test", "all"):
        if out.exists():
            out.unlink()
        assert ev.main([
            "score", "--results", str(results_path), "--labels", str(labels_dir),
            "--split", split, "--out", str(out), "--table", str(table),
        ]) == 2
        assert not out.exists()
        assert not table.exists()
        captured = capsys.readouterr()
        assert "score-test" in captured.out
        assert "Dev split only" not in captured.out


def test_cmd_score_p22_dev_writes_choice(tmp_path):
    results_path, labels_dir = _tiny_p22_score_inputs(tmp_path)
    # Dev labels so choose_p22 sees a question.
    labels_dir.joinpath("Q1.json").write_text(json.dumps([
        {
            "key": "k-dir", "title": "dir", "labeller": "owner",
            "category": "direct_answer", "work_type": "journal-article",
            "split": "dev",
        },
    ]), encoding="utf-8")
    out = tmp_path / "dev.json"
    table = tmp_path / "table.md"
    assert ev.main([
        "score", "--results", str(results_path), "--labels", str(labels_dir),
        "--split", "dev", "--out", str(out), "--table", str(table),
    ]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["split"] == "dev"
    assert payload["choice"]["name"]
    assert payload["leave_one_out"]["folds"]
    text = table.read_text(encoding="utf-8")
    assert "Dev split only" in text
    assert payload["choice"]["name"] in text


def test_score_test_uses_saved_choice_once(tmp_path):
    results_path, labels_dir = _tiny_p22_score_inputs(tmp_path)
    chosen = "bonus_w0.2_bm25_keywords"
    dev_path = tmp_path / "dev.json"
    dev_path.write_text(json.dumps({
        "choice": {"name": chosen, "overall_ndcg": 0.5},
    }), encoding="utf-8")
    out = tmp_path / "test.json"
    table = tmp_path / "table.md"
    argv = [
        "score-test", "--results", str(results_path), "--labels", str(labels_dir),
        "--dev-scores", str(dev_path), "--out", str(out), "--table", str(table),
    ]
    assert ev.main(argv) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["split"] == "test"
    assert payload["choice"]["name"] == chosen
    assert payload["leave_one_out"] is None
    names = sorted({row["ranking"] for row in payload["questions"]})
    assert names == ["bonus_w0.2_bm25_keywords", "lexical_on"]
    text = table.read_text(encoding="utf-8")
    assert text.startswith("# P2.2 word-bonus sweep\n")
    assert "Test split." in text
    assert "Dev split only" not in text
    stamp = Path(str(out) + ".test-stamp.json")
    assert stamp.is_file()
    first = out.read_text(encoding="utf-8")
    assert ev.main(argv) == 3
    assert out.read_text(encoding="utf-8") == first
    assert "other" not in stamp.read_text(encoding="utf-8")


def test_p22_test_stamp_blocks_a_second_claim(tmp_path):
    path = tmp_path / "scores.json.test-stamp.json"
    assert ev.claim_test_stamp(path, "bonus_w0.2_bm25_keywords") is True
    assert ev.claim_test_stamp(path, "other") is False
    saved = path.read_text(encoding="utf-8")
    assert "bonus_w0.2_bm25_keywords" in saved
    assert "other" not in saved


def test_score_test_command_is_wired():
    parser = ev.build_parser()
    held = parser.parse_args([
        "score-test", "--results", "r.json", "--labels", "labels",
        "--dev-scores", "dev.json", "--out", "test.json",
    ])
    assert held.func is ev.cmd_score_test
    score = parser.parse_args(["score", "--results", "r.json", "--labels", "labels"])
    assert score.split == "dev"
