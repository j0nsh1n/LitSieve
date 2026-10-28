#!/usr/bin/env python3
"""Search-quality harness: capture a frozen corpus, replay ranking, score labels.

Network is used only by ``capture``. Replay, score and labelsheet are offline.
Frozen provider records stay under scratch and are never committed.

  python tools/eval_search.py capture --question-set tools/bench/questions.json \\
      --out ~/HealthDatabaseAccess-scratch/bench/baseline_v1 --max-results 50
  python tools/eval_search.py replay --corpus ~/HealthDatabaseAccess-scratch/bench/baseline_v1 \\
      --out ~/HealthDatabaseAccess-scratch/bench/baseline_v1_results.json
  python tools/eval_search.py labelsheet --results ... --out ~/HealthDatabaseAccess-scratch/bench/labelsheets
  python tools/eval_search.py score --results ... --labels tools/bench/labels
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.content.source_catalog import TOPIC_PACKS, TOPIC_SOURCE_HINTS
from app.services.citations import article_doi, citation_model
from app.services.pipeline import FETCHERS, LiteratureSearchPipeline
from app.version import APP_VERSION

logger = logging.getLogger("eval_search")

SCRATCH_BENCH = Path.home() / "HealthDatabaseAccess-scratch" / "bench"
DEFAULT_QUESTIONS = REPO_ROOT / "tools" / "bench" / "questions.json"
TOP_K = 30
DEV_RATIO = 60
MIN_RAM_GB = 6.0

CATEGORIES = (
    "direct_answer",
    "mechanism_or_implementation",
    "experience_or_context",
    "background",
    "related_subject",
    "incidental",
    "unclassified",
)
RELEVANT = frozenset({"direct_answer", "mechanism_or_implementation"})
TOPIC_ONLY = frozenset({"related_subject", "incidental"})
GAINS = {
    "direct_answer": 3.0,
    "mechanism_or_implementation": 2.0,
    "experience_or_context": 1.0,
    "background": 1.0,
}
LABEL_FIELDS = (
    "key",
    "title",
    "labeller",
    "category",
    "rationale",
    "work_type",
    "access_state",
    "checked_at",
    "inspection_depth",
    "duplicate_of",
    "split",
    "use_in_paper",
)

RankerFn = Callable[..., Dict[str, Any]]


def git_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def available_ram_gb() -> float:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError):
        return 0.0
    return 0.0


def require_ram() -> None:
    gb = available_ram_gb()
    if gb < MIN_RAM_GB:
        raise SystemExit(
            f"available memory {gb:.2f} GiB is below {MIN_RAM_GB:.0f} GiB; stopping"
        )


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(jsonable(payload), ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def path_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def assert_outside_repo(out: Path) -> None:
    resolved = out.expanduser().resolve()
    if path_inside(resolved, REPO_ROOT):
        raise SystemExit(f"refusing to write corpus inside the repo: {resolved}")


def stable_key(article: Mapping[str, Any]) -> str:
    doi = article_doi(dict(article))
    if doi:
        return doi.lower()
    source = str(article.get("source") or "unknown")
    aid = str(article.get("article_id") or "")
    return f"{source}:{aid}"


def assign_split(key: str, *, dev_ratio: int = DEV_RATIO) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    n = int.from_bytes(digest[:8], "big")
    return "dev" if (n % 100) < dev_ratio else "test"


def sources_for_topic(topic: str) -> List[str]:
    name = (topic or "").strip().lower()
    if name == "history":
        for pack in TOPIC_PACKS:
            if pack.get("id") == "pack_history":
                return list(pack.get("sources") or [])
    hints = TOPIC_SOURCE_HINTS.get(name)
    if hints:
        return list(hints)
    raise SystemExit(f"unknown topic {topic!r}; expected a catalog topic")


def load_questions(path: Path) -> List[Dict[str, Any]]:
    data = load_json(path)
    rows = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        raise SystemExit(f"no questions in {path}")
    out: List[Dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise SystemExit(f"question entries must be objects in {path}")
        qid = str(raw.get("id") or "").strip()
        text = str(raw.get("text") or "").strip()
        topic = str(raw.get("topic") or "").strip()
        if not qid or not text or not topic:
            raise SystemExit(f"each question needs id, text and topic in {path}")
        out.append({"id": qid, "text": text, "topic": topic})
    return out


def dcg(gains: Sequence[float], k: int) -> float:
    total = 0.0
    for i, gain in enumerate(gains[:k], start=1):
        total += float(gain) / math.log2(i + 1)
    return total


def ndcg_at(
    ranked_keys: Sequence[str],
    labels: Mapping[str, str],
    k: int = 10,
) -> float:
    gains = [GAINS.get(labels.get(key, ""), 0.0) for key in ranked_keys[:k]]
    ideal = sorted(
        (GAINS.get(cat, 0.0) for cat in labels.values()),
        reverse=True,
    )
    denom = dcg(ideal, k)
    if denom <= 0:
        return 0.0
    return dcg(gains, k) / denom


def cohen_kappa(first: Sequence[str], second: Sequence[str]) -> Optional[float]:
    if not first or len(first) != len(second):
        return None
    n = len(first)
    po = sum(a == b for a, b in zip(first, second)) / n
    cats = set(first) | set(second)
    pe = 0.0
    for cat in cats:
        pe += (first.count(cat) / n) * (second.count(cat) / n)
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1.0 - pe)


def _hit_snapshot(article: Mapping[str, Any], rank: int) -> Dict[str, Any]:
    snap = {
        "rank": rank,
        "key": stable_key(article),
        "article_id": article.get("article_id"),
        "source": article.get("source"),
        "title": article.get("title") or "",
        "year": article.get("year") or "",
        "journal": article.get("journal") or "",
        "work_type": article.get("work_type"),
        "doi": article.get("doi") or article_doi(dict(article)),
        "container_title": article.get("container_title"),
        "similarity_score": article.get("similarity_score"),
        "semantic_score": article.get("semantic_score"),
        "lexical_score": article.get("lexical_score"),
    }
    return snap


def rank_baseline(
    pipeline: LiteratureSearchPipeline,
    query: str,
    top_k: int = TOP_K,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    on = pipeline.search_similar(query, top_k=top_k, lexical_boost=True)
    t_on = time.perf_counter() - t0
    t1 = time.perf_counter()
    off = pipeline.search_similar(query, top_k=top_k, lexical_boost=False)
    t_off = time.perf_counter() - t1
    return {
        "rankings": {
            "lexical_on": [_hit_snapshot(a, i) for i, a in enumerate(on, start=1)],
            "lexical_off": [_hit_snapshot(a, i) for i, a in enumerate(off, start=1)],
        },
        "timings": {
            "lexical_on_s": round(t_on, 4),
            "lexical_off_s": round(t_off, 4),
        },
    }


RANKERS: Dict[str, RankerFn] = {
    "baseline": rank_baseline,
}


def register_ranker(name: str, fn: RankerFn) -> None:
    """P2.2 / P2.5 plug an alternative ranker in without rewriting replay."""
    RANKERS[name] = fn


def _fetch_one(
    source: str,
    query: str,
    max_results: int,
) -> Tuple[str, List[Dict[str, Any]], Optional[str], Optional[str], str, float]:
    from app.fetchers.base import (
        FetchError,
        check_fetch_deadline,
        classify_error,
        set_cancel_check,
        set_fetch_deadline,
        source_fetch_budget,
    )

    fetcher_cls = FETCHERS.get(source)
    sent_query = query
    started = time.monotonic()
    if fetcher_cls is None:
        return source, [], "Unknown source", "error", query, 0.0
    set_cancel_check(None)
    set_fetch_deadline(time.monotonic() + source_fetch_budget())
    fetcher = None
    try:
        fetcher = fetcher_cls(email="")
        articles = fetcher.search_and_fetch(query, max_results) or []
        sent_query = getattr(fetcher, "sent_query", None) or query
        elapsed = time.monotonic() - started
        if not articles:
            check_fetch_deadline()
            return source, [], None, "no_results", sent_query, elapsed
        return source, articles, None, None, sent_query, elapsed
    except FetchError as exc:
        if fetcher is not None:
            sent_query = getattr(fetcher, "sent_query", None) or query
        return (
            source,
            list(exc.articles or []),
            str(exc),
            exc.kind,
            sent_query,
            time.monotonic() - started,
        )
    except Exception as exc:
        if fetcher is not None:
            sent_query = getattr(fetcher, "sent_query", None) or query
        return (
            source,
            [],
            str(exc),
            classify_error(exc),
            sent_query,
            time.monotonic() - started,
        )
    finally:
        set_cancel_check(None)
        set_fetch_deadline(None)


def capture_question(
    question: Mapping[str, Any],
    sources: Sequence[str],
    max_results: int,
    dest: Path,
) -> Dict[str, Any]:
    query = str(question["text"])
    files: Dict[str, Any] = {}
    workers = min(len(sources), 6) or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_one, src, query, max_results): src for src in sources
        }
        for future in as_completed(futures):
            source, articles, error, error_kind, sent_query, elapsed = future.result()
            report_error = error
            if error_kind == "no_results" and not error:
                report_error = None
            kind = error_kind if report_error or error_kind == "no_results" else None
            payload = [jsonable(a) for a in articles]
            path = dest / f"{source}.json"
            write_json(path, payload)
            files[source] = {
                "path": path.name,
                "sha256": sha256_file(path),
                "count": len(payload),
                "error": report_error,
                "error_kind": kind,
                "sent_query": sent_query,
                "elapsed_s": round(elapsed, 3),
            }
            print(
                f"  {question['id']} {source}: {len(payload)} "
                f"kind={kind or 'ok'}",
                flush=True,
            )
    for source in sources:
        if source not in files:
            path = dest / f"{source}.json"
            write_json(path, [])
            files[source] = {
                "path": path.name,
                "sha256": sha256_file(path),
                "count": 0,
                "error": "missing",
                "error_kind": "error",
                "sent_query": query,
                "elapsed_s": 0.0,
            }
    report = {}
    for src, row in files.items():
        item = {k: v for k, v in row.items() if k != "path"}
        item["file"] = row["path"]
        report[src] = item
    write_json(dest / "report.json", report)
    return files


def cmd_capture(args: argparse.Namespace) -> int:
    assert_outside_repo(Path(args.out))
    questions = load_questions(Path(args.question_set))
    override: List[str] = []
    for item in args.sources or []:
        override.extend(s.strip() for s in str(item).split(",") if s.strip())
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(timezone.utc).isoformat()
    sha = git_sha()
    manifest_questions: List[Dict[str, Any]] = []
    for question in questions:
        sources = override or sources_for_topic(str(question["topic"]))
        dest = out / str(question["id"])
        dest.mkdir(parents=True, exist_ok=True)
        print(f"capture {question['id']} sources={','.join(sources)}", flush=True)
        files = capture_question(question, sources, args.max_results, dest)
        manifest_questions.append({
            "id": question["id"],
            "text": question["text"],
            "topic": question["topic"],
            "sources": list(sources),
            "files": files,
        })
    manifest = {
        "captured_at": captured_at,
        "git_sha": sha,
        "app_version": APP_VERSION,
        "max_results": args.max_results,
        "question_set": str(Path(args.question_set)),
        "sources_override": override,
        "questions": manifest_questions,
    }
    write_json(out / "manifest.json", manifest)
    print(f"wrote {out / 'manifest.json'}", flush=True)
    return 0


def load_corpus_articles(question_dir: Path) -> List[Dict[str, Any]]:
    articles: List[Dict[str, Any]] = []
    for path in sorted(question_dir.glob("*.json")):
        if path.name in {"report.json", "manifest.json"}:
            continue
        payload = load_json(path)
        if isinstance(payload, list):
            articles.extend(a for a in payload if isinstance(a, dict))
    return articles


def _limit_embed_threads() -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    os.environ.setdefault("MKL_NUM_THREADS", "4")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def cmd_replay(args: argparse.Namespace) -> int:
    ranker_name = args.ranker or "baseline"
    ranker = RANKERS.get(ranker_name)
    if ranker is None:
        raise SystemExit(
            f"unknown ranker {ranker_name!r}; known: {', '.join(sorted(RANKERS))}"
        )
    corpus = Path(args.corpus).expanduser().resolve()
    manifest_path = corpus / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"no manifest at {manifest_path}")
    manifest = load_json(manifest_path)
    work_root = Path(args.work_dir).expanduser().resolve() if args.work_dir else (
        SCRATCH_BENCH / "work" / corpus.name
    )
    work_root.mkdir(parents=True, exist_ok=True)
    _limit_embed_threads()
    require_ram()
    results: Dict[str, Any] = {
        "corpus": str(corpus),
        "manifest_git_sha": manifest.get("git_sha"),
        "replay_git_sha": git_sha(),
        "ranker": ranker_name,
        "top_k": TOP_K,
        "questions": [],
    }
    for qrow in manifest.get("questions") or []:
        qid = str(qrow.get("id") or "")
        query = str(qrow.get("text") or "")
        qdir = corpus / qid
        articles = load_corpus_articles(qdir)
        db_path = work_root / qid / "articles.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            db_path.unlink()
        require_ram()
        pipeline = LiteratureSearchPipeline(db_path=str(db_path), embedding_model="general")
        try:
            if articles:
                pipeline.db.insert_articles(articles, dedupe=True)
            t_emb = time.perf_counter()
            stored = pipeline.db.get_all_articles()
            if stored:
                embeddings = pipeline.embedding_engine.embed_articles(stored)
                pipeline.db.insert_embeddings(embeddings, "general")
                pipeline.invalidate_corpus_cache()
            embed_s = time.perf_counter() - t_emb
            ranked = ranker(pipeline, query, TOP_K)
        finally:
            pipeline.db.close()
        timings = dict(ranked.get("timings") or {})
        timings["embed_s"] = round(embed_s, 4)
        results["questions"].append({
            "id": qid,
            "text": query,
            "topic": qrow.get("topic"),
            "n_captured": len(articles),
            "n_library": len(stored),
            "rankings": ranked.get("rankings") or {},
            "timings": timings,
        })
        print(
            f"replay {qid}: library={len(stored)} "
            f"embed={timings['embed_s']:.2f}s",
            flush=True,
        )
    out = Path(args.out).expanduser().resolve()
    write_json(out, results)
    print(f"wrote {out}", flush=True)
    return 0


def _read_label_rows(path: Path) -> List[Dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    rows: List[Dict[str, str]] = []
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
        if isinstance(payload, dict) and "labels" in payload:
            payload = payload["labels"]
        if not isinstance(payload, list):
            raise SystemExit(f"label file {path} must be a list")
        for item in payload:
            if isinstance(item, dict):
                rows.append({k: str(item.get(k) or "") for k in LABEL_FIELDS})
        return rows
    reader = csv.DictReader(io.StringIO(text))
    for item in reader:
        rows.append({k: str(item.get(k) or "") for k in LABEL_FIELDS})
    return rows


def load_labels(labels_dir: Path) -> Dict[str, List[Dict[str, str]]]:
    by_qid: Dict[str, List[Dict[str, str]]] = {}
    if not labels_dir.is_dir():
        return by_qid
    for path in sorted(labels_dir.iterdir()):
        if path.suffix.lower() not in {".json", ".csv"}:
            continue
        stem = path.stem
        qid = stem.split(".", 1)[0]
        by_qid.setdefault(qid, []).extend(_read_label_rows(path))
    return by_qid


def _primary_and_second(
    rows: Sequence[Mapping[str, str]],
) -> Tuple[Dict[str, Dict[str, str]], Optional[Dict[str, Dict[str, str]]]]:
    by_labeller: Dict[str, List[Mapping[str, str]]] = {}
    for row in rows:
        name = (row.get("labeller") or "owner").strip() or "owner"
        by_labeller.setdefault(name, []).append(row)
    names = sorted(by_labeller)
    if "owner" in by_labeller:
        names = ["owner"] + [n for n in names if n != "owner"]
    primary_name = names[0]
    primary = {r["key"]: dict(r) for r in by_labeller[primary_name] if r.get("key")}
    second = None
    if len(names) > 1:
        second = {r["key"]: dict(r) for r in by_labeller[names[1]] if r.get("key")}
    return primary, second


def _split_of(row: Mapping[str, str], key: str) -> str:
    split = (row.get("split") or "").strip().lower()
    if split in {"dev", "test"}:
        return split
    return assign_split(key)


def _export_types(article: Mapping[str, Any]) -> Tuple[str, str]:
    model = citation_model(dict(article))
    return model.ris_ty, model.bibtex_type


def _duplicate_rate(hits: Sequence[Mapping[str, Any]]) -> float:
    if not hits:
        return 0.0
    seen: Dict[str, int] = {}
    for hit in hits:
        doi = str(hit.get("doi") or "").strip().lower()
        ident = doi if doi else str(hit.get("key") or "")
        seen[ident] = seen.get(ident, 0) + 1
    extras = sum(n - 1 for n in seen.values() if n > 1)
    return extras / len(hits)


def _in_split(split_filter: str, split: str) -> bool:
    if split_filter in {"", "all"}:
        return True
    return split == split_filter


def score_question(
    qrow: Mapping[str, Any],
    label_rows: Sequence[Mapping[str, str]],
    split_filter: str,
    ranking_name: str = "lexical_on",
) -> Dict[str, Any]:
    primary, second = _primary_and_second(label_rows)
    hits = list((qrow.get("rankings") or {}).get(ranking_name) or [])
    keys = [str(h.get("key") or "") for h in hits]
    labelled_keys = {
        key: row for key, row in primary.items()
        if _in_split(split_filter, _split_of(row, key))
    }
    cats = {key: row.get("category", "") for key, row in labelled_keys.items()}
    top5 = keys[:5]
    top10 = keys[:10]
    rel5 = sum(1 for k in top5 if cats.get(k) in RELEVANT)
    rel10 = sum(1 for k in top10 if cats.get(k) in RELEVANT)
    topic10 = sum(1 for k in top10 if cats.get(k) in TOPIC_ONLY)
    unlabelled10 = sum(1 for k in top10 if k not in labelled_keys)
    type_checked = 0
    type_ok = 0
    export_ok = 0
    for hit in hits[:TOP_K]:
        key = str(hit.get("key") or "")
        row = labelled_keys.get(key)
        if not row:
            continue
        labelled_type = (row.get("work_type") or "").strip()
        if not labelled_type:
            continue
        type_checked += 1
        stored = str(hit.get("work_type") or "").strip()
        if stored == labelled_type:
            type_ok += 1
        expect_article = {
            "article_id": hit.get("article_id") or key,
            "source": hit.get("source") or "openalex",
            "title": hit.get("title") or "",
            "journal": hit.get("journal") or hit.get("container_title") or "Journal",
            "work_type": labelled_type,
        }
        got_article = {
            "article_id": hit.get("article_id") or key,
            "source": hit.get("source") or "openalex",
            "title": hit.get("title") or "",
            "journal": hit.get("journal") or hit.get("container_title") or "",
            "work_type": hit.get("work_type"),
            "doi": hit.get("doi"),
            "container_title": hit.get("container_title"),
        }
        if _export_types(got_article) == _export_types(expect_article):
            export_ok += 1
    kappa = None
    if second:
        paired_a: List[str] = []
        paired_b: List[str] = []
        for key, row in labelled_keys.items():
            other = second.get(key)
            if not other:
                continue
            a_cat = (row.get("category") or "").strip()
            b_cat = (other.get("category") or "").strip()
            if a_cat and b_cat:
                paired_a.append(a_cat)
                paired_b.append(b_cat)
        kappa = cohen_kappa(paired_a, paired_b)
    timings = qrow.get("timings") or {}
    return {
        "id": qrow.get("id"),
        "ranking": ranking_name,
        "split": split_filter or "all",
        "n_ranked": len(hits),
        "relevant@5": rel5,
        "relevant@10": rel10,
        "ndcg@10": round(ndcg_at(keys, cats, 10), 4),
        "topic_only@10": topic10,
        "unlabelled@10": unlabelled10,
        "type_checked": type_checked,
        "type_accuracy": round(type_ok / type_checked, 4) if type_checked else None,
        "export_accuracy": round(export_ok / type_checked, 4) if type_checked else None,
        "duplicate_rate": round(_duplicate_rate(hits[:TOP_K]), 4),
        "kappa": None if kappa is None else round(kappa, 4),
        "embed_s": timings.get("embed_s"),
        "lexical_on_s": timings.get("lexical_on_s"),
        "lexical_off_s": timings.get("lexical_off_s"),
    }


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)


def _print_table(rows: Sequence[Mapping[str, Any]]) -> None:
    cols = (
        "id", "ranking", "relevant@5", "relevant@10", "ndcg@10",
        "topic_only@10", "unlabelled@10", "type_accuracy", "export_accuracy",
        "duplicate_rate", "kappa",
    )
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print(header)
    print("  ".join("-" * widths[c] for c in cols))
    for row in rows:
        print("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in cols))


def cmd_score(args: argparse.Namespace) -> int:
    results = load_json(Path(args.results))
    labels = load_labels(Path(args.labels))
    split_filter = args.split or "all"
    scored: List[Dict[str, Any]] = []
    for qrow in results.get("questions") or []:
        qid = str(qrow.get("id") or "")
        rankings = qrow.get("rankings") or {}
        names = list(rankings) or ["lexical_on"]
        for name in names:
            scored.append(score_question(qrow, labels.get(qid, []), split_filter, name))
    overall_on = [r for r in scored if r.get("ranking") == "lexical_on"]
    overall = {
        "id": "OVERALL",
        "ranking": "lexical_on",
        "split": split_filter,
        "relevant@5": _mean([r.get("relevant@5") for r in overall_on]),
        "relevant@10": _mean([r.get("relevant@10") for r in overall_on]),
        "ndcg@10": _mean([r.get("ndcg@10") for r in overall_on]),
        "topic_only@10": _mean([r.get("topic_only@10") for r in overall_on]),
        "unlabelled@10": _mean([r.get("unlabelled@10") for r in overall_on]),
        "type_accuracy": _mean([r.get("type_accuracy") for r in overall_on]),
        "export_accuracy": _mean([r.get("export_accuracy") for r in overall_on]),
        "duplicate_rate": _mean([r.get("duplicate_rate") for r in overall_on]),
        "kappa": _mean([r.get("kappa") for r in overall_on]),
    }
    table = [*scored, overall]
    _print_table(table)
    payload = {
        "results": str(Path(args.results)),
        "labels": str(Path(args.labels)),
        "split": split_filter,
        "questions": scored,
        "overall": overall,
    }
    out = Path(args.out) if args.out else Path(args.results).with_name(
        Path(args.results).stem + ".scores.json"
    )
    write_json(out, payload)
    print(f"wrote {out}", flush=True)
    return 0


def labeller_readme() -> str:
    return (
        "Label each row from the title, and from the abstract if you look it up. "
        "Models do not write these labels.\n\n"
        "Categories\n"
        "- direct_answer: the paper is about the relationship the question asks.\n"
        "- mechanism_or_implementation: how or why that relationship works, "
        "or how a policy was carried out.\n"
        "- experience_or_context: first-hand accounts or the setting, "
        "not the analysis itself.\n"
        "- background: useful period, place, or people, without answering "
        "the question.\n"
        "- related_subject: same topic words, a different question.\n"
        "- incidental: barely about the topic.\n"
        "- unclassified: you cannot tell from the title and abstract.\n\n"
        "Fill work_type, access_state, and checked_at (an ISO date).\n"
        "inspection_depth is metadata_only, abstract, or full_text.\n"
        "duplicate_of is the other row's key, or blank.\n"
        "use_in_paper is cite, background, or skip.\n"
        "Leave split as written. A hash of the key assigns about 60% to dev "
        "and 40% to test.\n"
    )


def pooled_hits(qrow: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rankings = qrow.get("rankings") or {}
    on = list(rankings.get("lexical_on") or [])
    off = list(rankings.get("lexical_off") or [])
    best: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for hit in on + off:
        key = str(hit.get("key") or "")
        if not key:
            continue
        if key not in best:
            best[key] = dict(hit)
            order.append(key)
        else:
            prev = best[key]
            prev_rank = prev.get("rank") or TOP_K
            new_rank = hit.get("rank") or TOP_K
            if new_rank < prev_rank:
                merged = dict(hit)
                merged["rank"] = new_rank
                best[key] = merged
    on_rank = {str(h.get("key")): h.get("rank") for h in on}
    off_rank = {str(h.get("key")): h.get("rank") for h in off}
    rows = []
    for key in order:
        hit = best[key]
        row = dict(hit)
        row["rank_lexical_on"] = on_rank.get(key)
        row["rank_lexical_off"] = off_rank.get(key)
        rows.append(row)
    return rows


def cmd_labelsheet(args: argparse.Namespace) -> int:
    results = load_json(Path(args.results))
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text(labeller_readme(), encoding="utf-8")
    for qrow in results.get("questions") or []:
        qid = str(qrow.get("id") or "Q")
        path = out / f"{qid}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    *LABEL_FIELDS,
                    "rank_lexical_on",
                    "rank_lexical_off",
                    "source",
                    "article_id",
                    "year",
                    "journal",
                ],
            )
            writer.writeheader()
            for hit in pooled_hits(qrow):
                key = str(hit.get("key") or "")
                writer.writerow({
                    "key": key,
                    "title": hit.get("title") or "",
                    "labeller": "",
                    "category": "",
                    "rationale": "",
                    "work_type": hit.get("work_type") or "",
                    "access_state": "",
                    "checked_at": "",
                    "inspection_depth": "",
                    "duplicate_of": "",
                    "split": assign_split(key) if key else "",
                    "use_in_paper": "",
                    "rank_lexical_on": hit.get("rank_lexical_on") or "",
                    "rank_lexical_off": hit.get("rank_lexical_off") or "",
                    "source": hit.get("source") or "",
                    "article_id": hit.get("article_id") or "",
                    "year": hit.get("year") or "",
                    "journal": hit.get("journal") or "",
                })
        print(f"wrote {path}", flush=True)
    print(f"wrote {out / 'README.md'}", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="Fetch and freeze provider records")
    cap.add_argument("--question-set", required=True)
    cap.add_argument("--out", required=True)
    cap.add_argument("--sources", nargs="*", default=None)
    cap.add_argument("--max-results", type=int, default=50)
    cap.set_defaults(func=cmd_capture)

    rep = sub.add_parser("replay", help="Embed and rank a frozen corpus offline")
    rep.add_argument("--corpus", required=True)
    rep.add_argument("--out", required=True)
    rep.add_argument("--ranker", default="baseline")
    rep.add_argument("--work-dir", default=None)
    rep.set_defaults(func=cmd_replay)

    sco = sub.add_parser("score", help="Score a replay against human labels")
    sco.add_argument("--results", required=True)
    sco.add_argument("--labels", required=True)
    sco.add_argument("--split", choices=("dev", "test", "all"), default="all")
    sco.add_argument("--out", default=None)
    sco.set_defaults(func=cmd_score)

    lab = sub.add_parser("labelsheet", help="Write blank CSVs for a human labeller")
    lab.add_argument("--results", required=True)
    lab.add_argument("--out", required=True)
    lab.set_defaults(func=cmd_labelsheet)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
