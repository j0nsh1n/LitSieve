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


def test_labelsheet_output(tmp_path, monkeypatch):
    _patch_embeddings(monkeypatch)
    results = tmp_path / "results.json"
    work = tmp_path / "work"
    assert ev.main([
        "replay", "--corpus", str(TINY), "--out", str(results),
        "--work-dir", str(work),
    ]) == 0
    sheets = tmp_path / "sheets"
    assert ev.main(["labelsheet", "--results", str(results), "--out", str(sheets)]) == 0
    readme = (sheets / "README.md").read_text(encoding="utf-8")
    assert "direct_answer" in readme
    assert "Models do not write these labels" in readme
    with (sheets / "Q1.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    keys = {row["key"] for row in rows}
    assert "10.1234/paper-0" in keys
    by_key = {row["key"]: row for row in rows}
    assert by_key["10.1234/paper-0"]["split"] == "dev"
    assert by_key["10.1234/paper-1"]["split"] == "test"
    assert by_key["10.1234/paper-0"]["category"] == ""
    assert by_key["10.1234/paper-0"]["labeller"] == ""


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
