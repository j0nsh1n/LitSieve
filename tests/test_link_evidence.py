"""Per-source link evidence: reducer, adapters, legacy merge detection."""

from __future__ import annotations

import itertools
import json
import os
import random

import pytest

from app.services.access import (
    OPEN_LISTED,
    access_state,
    link_access,
)
from app.services.link_evidence import (
    LINK_EVIDENCE_KEY,
    canonical_json,
    incoming_record_from_article,
    is_never_merged,
    merge_link_evidence,
    serialize_link_evidence,
)
from app.storage import dbconn
from app.storage.database import ArticleDatabase

if os.environ.get("CI"):
    import sqlcipher3 as sqlcipher  # noqa: F401
else:
    sqlcipher = pytest.importorskip(
        "sqlcipher3", reason="sqlcipher3-binary not installed (pip install -r requirements.txt)"
    )


def _paper(article_id, source, **kwargs):
    row = {
        "article_id": article_id,
        "source": source,
        "title": "Same work from two sources",
        "abstract": "An abstract that is long enough to store.",
        "year": "2020",
        "authors": ["Jane Doe"],
        "doi": "10.1234/same",
    }
    row.update(kwargs)
    return row


def _incoming(source, rec_id, url, status, observed_at, **extra):
    article = _paper(
        rec_id,
        source,
        oa_status=status,
        best_oa_url=url,
        host_name=extra.pop("host_name", None),
    )
    locations = extra.pop("locations", None)
    if locations is None and url:
        loc = {"url": url, "via": source}
        loc.update(extra)
        locations = [loc]
    return incoming_record_from_article(
        article, {"locations": locations or []}, observed_at,
    )


def test_is_never_merged_single_source_row(monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(":memory:")
    try:
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold",
            best_oa_url="https://example.org/oa.pdf",
            _extra={"provenance": {"oa_status": "openalex", "doi": "openalex"}},
        )])
        extra = db.conn.execute(
            "SELECT provenance FROM article_extra WHERE article_id=? AND source=?",
            ("W1", "openalex"),
        ).fetchone()
        row = {
            "source": "openalex",
            "provenance": json.loads(extra[0]),
        }
        assert is_never_merged(row) is True
    finally:
        db.close()


def test_is_never_merged_filled_field_row(monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(":memory:")
    try:
        db.insert_articles([_paper("123", "pubmed")])
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold",
            best_oa_url="https://example.org/oa.pdf",
        )])
        extra = db.conn.execute("SELECT provenance FROM article_extra").fetchone()
        row = {"source": "pubmed", "provenance": json.loads(extra[0])}
        assert row["provenance"].get("oa_status") == "openalex"
        assert is_never_merged(row) is False
    finally:
        db.close()


def test_is_never_merged_conflict_row(monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(":memory:")
    try:
        db.insert_articles([_paper(
            "123", "pubmed", oa_status="closed",
            best_oa_url="https://publisher.example/closed",
        )])
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold",
            best_oa_url="https://zenodo.org/paper.pdf",
        )])
        extra = db.conn.execute("SELECT provenance FROM article_extra").fetchone()
        row = {"source": "pubmed", "provenance": json.loads(extra[0])}
        assert "conflicts" in row["provenance"]
        assert is_never_merged(row) is False
    finally:
        db.close()


def test_is_never_merged_null_provenance():
    assert is_never_merged({"source": "pubmed"}) is True
    assert is_never_merged({"source": "pubmed", "provenance": None}) is True
    assert is_never_merged({"source": "pubmed", "provenance": {}}) is True
    assert is_never_merged({"source": "pubmed", "provenance": "{}"}) is True


def test_reducer_ignores_claimed_link_evidence():
    incoming = _incoming(
        "openalex", "W1", "https://example.org/oa.pdf", "gold",
        "2026-10-29T08:00:00.000000Z",
    )
    incoming["extra"] = {
        LINK_EVIDENCE_KEY: {"version": 1, "observations": [{"forged": True}]},
        "provenance": {LINK_EVIDENCE_KEY: {"version": 1, "observations": []}},
        "locations": incoming["locations"],
    }
    merged = merge_link_evidence(None, incoming)
    assert merged["version"] == 1
    assert merged["observations"][0]["source"] == "openalex"
    assert "forged" not in canonical_json(merged)


def test_reducer_idempotent_and_order_independent():
    stamp = "2026-10-29T08:00:00.000000Z"
    records = [
        _incoming("pubmed", "123", "https://publisher.example/closed", "closed", stamp),
        _incoming("openalex", "W1", "https://zenodo.org/a.pdf", "gold", stamp),
        _incoming(
            "hal", "hal-1", "https://hal.science/hal-1/document", "green", stamp,
            kind="file", host="HAL",
        ),
        _incoming(
            "doaj", "doaj-1", "https://example.org/full.pdf", "gold", stamp,
            kind="fulltext",
        ),
    ]
    first = None
    for order in itertools.permutations(records):
        evidence = None
        for item in order:
            evidence = merge_link_evidence(evidence, item)
        if first is None:
            first = evidence
        assert evidence == first
        again = merge_link_evidence(evidence, order[0])
        assert again == evidence


def test_reducer_keeps_equal_urls_from_two_sources():
    stamp = "2026-10-29T08:00:00.000000Z"
    shared = "https://example.org/same"
    evidence = merge_link_evidence(
        None,
        _incoming("pubmed", "123", shared, "closed", stamp),
    )
    evidence = merge_link_evidence(
        evidence,
        _incoming("openalex", "W1", shared, "gold", stamp),
    )
    sources = {obs["source"] for obs in evidence["observations"]}
    assert sources == {"pubmed", "openalex"}
    assert link_access(evidence, shared).open_listed is True


def test_reducer_does_not_delete_valid_evidence():
    stamp = "2026-10-29T08:00:00.000000Z"
    open_url = "https://zenodo.org/a.pdf"
    evidence = merge_link_evidence(
        None,
        _incoming("openalex", "W1", open_url, "gold", stamp),
    )
    evidence = merge_link_evidence(
        evidence,
        _incoming("pubmed", "123", "https://publisher.example/closed", "closed", stamp),
    )
    evidence = merge_link_evidence(
        evidence,
        _incoming("openalex", "W1", open_url, "closed", "2026-10-29T09:00:00.000000Z"),
    )
    assert link_access(evidence, open_url).open_listed is True
    assert len(evidence["observations"]) == 3


def test_seeded_random_merge_sequences():
    seed = 20261029
    rng = random.Random(seed)
    stamp = "2026-10-29T08:00:00.000000Z"
    sources = ["pubmed", "openalex", "hal", "doaj"]
    for n in (2, 3, 4):
        chosen = sources[:n]
        records = []
        for source in chosen:
            url = f"https://example.org/{source}.pdf"
            status = "gold" if source != "pubmed" else "closed"
            extra = {}
            if source == "hal":
                extra = {"kind": "file", "host": "HAL"}
                status = "green"
            if source == "doaj":
                extra = {"kind": "fulltext"}
            records.append(_incoming(source, source, url, status, stamp, **extra))
        rng.shuffle(records)
        evidence = None
        for item in records:
            evidence = merge_link_evidence(evidence, item)
        repeated = merge_link_evidence(evidence, records[0])
        assert repeated == evidence
        for item in records:
            url = item["best_oa_url"]
            decision = link_access(evidence, url)
            if item["source"] == "pubmed":
                assert decision.open_listed is False
            else:
                assert decision.open_listed is True, (seed, item["source"], decision)


def test_http_does_not_authorize_https():
    stamp = "2026-10-29T08:00:00.000000Z"
    evidence = merge_link_evidence(
        None,
        _incoming("openalex", "W1", "http://example.org/a.pdf", "gold", stamp),
    )
    assert link_access(evidence, "http://example.org/a.pdf").open_listed is True
    assert link_access(evidence, "https://example.org/a.pdf").open_listed is False


def test_unreadable_existing_evidence_fails_the_write(monkeypatch, tmp_path):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(str(tmp_path / "bad-ev.db"))
    try:
        db.insert_articles([_paper("123", "pubmed")])
        db.conn.execute(
            "UPDATE article_extra SET provenance = 'not-json' "
            "WHERE article_id = ? AND source = ?",
            ("123", "pubmed"),
        )
        db.conn.commit()
        stats = db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold",
            best_oa_url="https://example.org/oa.pdf",
        )])
        assert stats["dropped"] == 1
        stored = db.conn.execute(
            "SELECT provenance FROM article_extra WHERE article_id=? AND source=?",
            ("123", "pubmed"),
        ).fetchone()[0]
        assert stored == "not-json"
    finally:
        db.close()


def test_four_source_merge_evidence_size(monkeypatch, tmp_path):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(str(tmp_path / "size.db"))
    stamp = "2026-10-29T08:00:00.000000Z"
    try:
        db.insert_articles([_paper(
            "123", "pubmed", oa_status="closed",
            best_oa_url="https://publisher.example/closed",
            _observed_at=stamp,
        )])
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold",
            best_oa_url="https://zenodo.org/record/1/files/a.pdf",
            _observed_at=stamp,
            _extra={"locations": [{
                "url": "https://zenodo.org/record/1/files/a.pdf",
                "host": "Zenodo",
                "via": "openalex",
                "version": "publishedVersion",
            }]},
        )])
        db.insert_articles([_paper(
            "hal-1", "hal", oa_status="green",
            best_oa_url="https://hal.science/hal-1/document",
            _observed_at=stamp,
            _extra={"locations": [{
                "url": "https://hal.science/hal-1/document",
                "kind": "file",
                "host": "HAL",
                "via": "hal",
            }]},
        )])
        db.insert_articles([_paper(
            "doaj-1", "doaj", oa_status="gold",
            best_oa_url="https://doaj.example/full.pdf",
            _observed_at=stamp,
            _extra={"locations": [{
                "url": "https://doaj.example/full.pdf",
                "kind": "fulltext",
                "via": "doaj",
            }]},
        )])
        extra = db.conn.execute("SELECT provenance FROM article_extra").fetchone()[0]
        evidence = json.loads(extra)[LINK_EVIDENCE_KEY]
        blob = serialize_link_evidence(evidence)
        size_path = tmp_path / "evidence-size.txt"
        size_path.write_text(str(len(blob.encode("utf-8"))))
        assert len(evidence["observations"]) == 4
        assert len(blob.encode("utf-8")) > 0
        print(f"EVIDENCE_SIZE_BYTES={len(blob.encode('utf-8'))}")
    finally:
        db.close()


def test_sqlcipher_round_trip_keeps_decisions(tmp_path, monkeypatch):
    monkeypatch.setenv(dbconn.ENV_KEY, "a-test-key")
    path = tmp_path / "enc.db"
    stamp = "2026-10-29T08:00:00.000000Z"
    db = ArticleDatabase(str(path))
    try:
        db.insert_articles([_paper(
            "123", "pubmed", oa_status="closed",
            best_oa_url="https://publisher.example/closed",
            _observed_at=stamp,
        )])
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold",
            best_oa_url="https://zenodo.org/paper.pdf",
            _observed_at=stamp,
        )])
    finally:
        db.close()
    db = ArticleDatabase(str(path))
    try:
        extra = db.conn.execute("SELECT provenance FROM article_extra").fetchone()
        row = db.get_all_articles()[0]
        row["provenance"] = json.loads(extra[0])
        assert access_state(row).state == OPEN_LISTED
        assert access_state(row).url == "https://zenodo.org/paper.pdf"
        assert link_access(
            row["provenance"][LINK_EVIDENCE_KEY],
            "https://zenodo.org/paper.pdf",
        ).open_listed is True
        assert link_access(
            row["provenance"][LINK_EVIDENCE_KEY],
            "https://publisher.example/closed",
        ).open_listed is False
    finally:
        db.close()


def test_crossref_needs_entry_licence():
    stamp = "2026-10-29T08:00:00.000000Z"
    licensed = merge_link_evidence(None, incoming_record_from_article(
        _paper("10.1/x", "crossref"),
        {"locations": [{
            "url": "https://example.org/cc.pdf",
            "via": "crossref",
            "license": "https://creativecommons.org/licenses/by/4.0/",
        }]},
        stamp,
    ))
    assert link_access(licensed, "https://example.org/cc.pdf").open_listed is True
    unlicensed = merge_link_evidence(None, incoming_record_from_article(
        _paper("10.1/x", "crossref"),
        {"locations": [{
            "url": "https://example.org/cc.pdf",
            "via": "crossref",
            "kind": "text-mining",
        }]},
        stamp,
    ))
    assert link_access(unlicensed, "https://example.org/cc.pdf").open_listed is False


def test_hal_needs_file_basis():
    stamp = "2026-10-29T08:00:00.000000Z"
    file_obs = merge_link_evidence(None, incoming_record_from_article(
        _paper("hal-1", "hal", oa_status="green",
               best_oa_url="https://hal.science/hal-1/document"),
        {"locations": [{
            "url": "https://hal.science/hal-1/document",
            "kind": "file",
            "via": "hal",
            "host": "HAL",
        }]},
        stamp,
    ))
    assert link_access(file_obs, "https://hal.science/hal-1/document").open_listed is True
    notice = merge_link_evidence(None, incoming_record_from_article(
        _paper("hal-2", "hal"),
        {"locations": [{
            "url": "https://hal.science/hal-2",
            "kind": "landing",
            "via": "hal",
        }]},
        stamp,
    ))
    decision = link_access(notice, "https://hal.science/hal-2")
    assert decision.open_listed is False


def test_missing_evidence_is_not_open():
    assert link_access(None, "https://example.org/a").open_listed is False
    assert link_access({"version": 1, "observations": []}, "https://example.org/a").open_listed is False
    assert "missing_evidence" in link_access(None, "https://example.org/a").reasons


def test_clone_drops_extra_never_merged_still_uses_legacy(monkeypatch, tmp_path):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(str(tmp_path / "clone.db"))
    try:
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold",
            best_oa_url="https://example.org/oa.pdf",
        )])
        db.conn.execute("DELETE FROM article_extra")
        db.conn.commit()
        row = db.get_all_articles()[0]
        assert is_never_merged(row) is True
        assert access_state(row).state == OPEN_LISTED
    finally:
        db.close()
