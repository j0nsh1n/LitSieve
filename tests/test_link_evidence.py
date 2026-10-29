"""Per-source link evidence: reducer, adapters, and read-time witnesses."""

from __future__ import annotations

import copy
import itertools
import json
import os
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from app.services import access as access_mod
from app.services.access import (
    NONE_LISTED,
    OPEN_LISTED,
    access_state,
    link_access,
    other_copies_payload,
    other_copies_result,
)
from app.services.link_evidence import (
    ANY_TEXT,
    LINK_EVIDENCE_KEY,
    SOURCE_ADAPTER_BASES,
    SOURCE_ADAPTER_SHAPES,
    canonical_json,
    evidence_url_key,
    incoming_record_from_article,
    location_matches_adapter,
    merge_link_evidence,
    observation_from_record,
    observation_matches_adapter,
    serialize_link_evidence,
)
from app.services.pipeline import FETCHERS, LiteratureSearchPipeline
from app.storage import dbconn
from app.storage.database import ArticleDatabase
from app.storage.shares import generate_share_code
from app.storage.user_db import UserDatabase

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


PUBMED_CLOSED = "https://example.org/pubmed-closed"
OPENALEX_OPEN = "https://example.org/openalex-open"
NEVER_MERGED_OPEN = "https://example.org/oa.pdf"


def _access_row(db, article_id=None, source=None):
    fields = db.get_article_access_fields()
    if article_id is None:
        key = next(iter(fields))
    else:
        key = (article_id, source)
    row = dict(fields[key])
    row["article_id"] = key[0]
    row["source"] = key[1]
    return row


def _redeem(udb, owner_id, owner_lib, student_id, student_lib):
    share = udb.create_share(
        owner_user_id=owner_id,
        owner_library_id=owner_lib,
        title_snapshot="Clone",
        code=generate_share_code(),
    )
    udb.record_redemption(share["id"], student_id, student_lib)
    return share


def _assert_no_open(row, *, closed_url=None):
    card = access_state(row)
    copies = other_copies_result(row)
    payload = other_copies_payload(
        {(str(row.get("article_id") or "id"), str(row.get("source") or "src")): row},
    )
    assert card.state != OPEN_LISTED
    assert card.url is None
    assert copies.has_open_copy is False
    assert not any(item.open_listed for item in copies.copies)
    assert not any(item.get("has_open_copy") for item in payload)
    if closed_url:
        assert card.url != closed_url
        assert not any(
            item.url == closed_url and item.open_listed for item in copies.copies
        )


def test_legacy_row_without_evidence_is_not_open(monkeypatch, tmp_path):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(str(tmp_path / "owner.db"))
    try:
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold",
            best_oa_url=NEVER_MERGED_OPEN,
        )])
        db.conn.execute("DELETE FROM article_extra")
        db.conn.commit()
        row = db.get_all_articles()[0]
        _assert_no_open(row, closed_url=NEVER_MERGED_OPEN)
        pipe = LiteratureSearchPipeline(db_path=str(tmp_path / "owner.db"))
        try:
            articles = [{"article_id": "W1", "source": "openalex"}]
            pipe._attach_access(articles)
            assert articles[0]["access"]["state"] != OPEN_LISTED
            listed = pipe.search_similar(
                "Same work from two sources", top_k=10, lexical_boost=False,
                free_to_read=True,
            )
            assert listed == []
        finally:
            pipe.close()
    finally:
        db.close()


def test_cloned_merged_row_pubmed_url_never_open(monkeypatch, tmp_path):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    from app.storage import shares as shares_mod

    owner_path = tmp_path / "owner" / "articles.db"
    clone_path = tmp_path / "clone" / "articles.db"
    owner_path.parent.mkdir(parents=True)
    udb = UserDatabase(db_path=str(tmp_path / "users.db"))
    owner = udb.create_user("owner", "hash")
    student = udb.create_user("student", "hash")
    monkeypatch.setattr(
        shares_mod,
        "library_db_path",
        lambda user, library: owner_path if user == owner["id"] else clone_path,
    )
    db = ArticleDatabase(str(owner_path))
    try:
        db.insert_articles([_paper(
            "123", "pubmed", best_oa_url=PUBMED_CLOSED,
        )])
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold", best_oa_url=OPENALEX_OPEN,
        )])
        owner_row = _access_row(db, "123", "pubmed")
        card = access_state(owner_row)
        copies = other_copies_result(owner_row)
        assert card.state == OPEN_LISTED
        assert card.url == OPENALEX_OPEN
        by_url = {item.url: item.open_listed for item in copies.copies}
        assert by_url.get(PUBMED_CLOSED) is False
        assert copies.has_open_copy is True
    finally:
        db.close()

    shares_mod.clone_library_data(owner["id"], "lib", student["id"], "cloned")
    _redeem(udb, owner["id"], "lib", student["id"], "cloned")
    clone_db = ArticleDatabase(str(clone_path))
    try:
        extras = clone_db.conn.execute(
            "SELECT COUNT(*) FROM article_extra"
        ).fetchone()[0]
        assert extras == 0
        row = _access_row(clone_db, "123", "pubmed")
        assert row["oa_status"] == "gold"
        assert row["best_oa_url"] == PUBMED_CLOSED
        _assert_no_open(row, closed_url=PUBMED_CLOSED)
        pipe = LiteratureSearchPipeline(db_path=str(clone_path))
        try:
            articles = [{"article_id": "123", "source": "pubmed"}]
            pipe._attach_access(articles)
            assert articles[0]["access"]["state"] != OPEN_LISTED
            assert "url" not in articles[0]["access"]
        finally:
            pipe.close()
    finally:
        clone_db.close()


def test_cloned_never_merged_row_opens_after_clone_fetch(monkeypatch, tmp_path):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    from app.storage import shares as shares_mod

    owner_path = tmp_path / "owner" / "articles.db"
    clone_path = tmp_path / "clone" / "articles.db"
    owner_path.parent.mkdir(parents=True)
    udb = UserDatabase(db_path=str(tmp_path / "users.db"))
    owner = udb.create_user("owner", "hash")
    student = udb.create_user("student", "hash")
    monkeypatch.setattr(
        shares_mod,
        "library_db_path",
        lambda user, library: owner_path if user == owner["id"] else clone_path,
    )
    db = ArticleDatabase(str(owner_path))
    try:
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold", best_oa_url=NEVER_MERGED_OPEN,
        )])
        owner_row = _access_row(db, "W1", "openalex")
        assert access_state(owner_row).state == OPEN_LISTED
        assert access_state(owner_row).url == NEVER_MERGED_OPEN
    finally:
        db.close()

    shares_mod.clone_library_data(owner["id"], "lib", student["id"], "cloned")
    _redeem(udb, owner["id"], "lib", student["id"], "cloned")
    clone_db = ArticleDatabase(str(clone_path))
    try:
        row = _access_row(clone_db, "W1", "openalex")
        _assert_no_open(row, closed_url=NEVER_MERGED_OPEN)
        clone_db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold", best_oa_url=NEVER_MERGED_OPEN,
            _observed_at="2026-10-29T12:00:00.000000Z",
        )])
        fetched = _access_row(clone_db, "W1", "openalex")
        card = access_state(fetched)
        copies = other_copies_result(fetched)
        assert card.state == OPEN_LISTED
        assert card.url == NEVER_MERGED_OPEN
        p28_eligible = card.state != OPEN_LISTED and not copies.has_open_copy
        assert p28_eligible is False
    finally:
        clone_db.close()


def test_legacy_merged_conflict_copy_is_not_open(monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(":memory:")
    try:
        db.insert_articles([_paper(
            "123", "pubmed", oa_status="closed",
            best_oa_url="https://publisher.example/closed",
        )])
        db.conn.execute(
            "UPDATE article_extra SET provenance = ?",
            (json.dumps({
                "conflicts": {
                    "oa_status": [{"value": "gold", "source": "openalex"}],
                    "best_oa_url": [{
                        "value": "https://example.org/oa",
                        "source": "openalex",
                    }],
                },
            }),),
        )
        db.conn.commit()
        extra = db.conn.execute("SELECT provenance FROM article_extra").fetchone()
        row = db.get_all_articles()[0]
        row["provenance"] = json.loads(extra[0])
        assert access_state(row).state == "none_listed"
        found = other_copies_result(row)
        by_url = {item.url: item.open_listed for item in found.copies}
        assert by_url.get("https://example.org/oa") is False
        assert found.has_open_copy is False
    finally:
        db.close()


def test_fresh_evidence_keeps_ordinary_legacy_links(monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(":memory:")
    stamp = "2026-10-29T08:00:00.000000Z"
    try:
        db.insert_articles([_paper("1", "pubmed", _observed_at=stamp)])
        db.conn.execute(
            "UPDATE article_extra SET provenance = ?, locations = ?",
            (
                json.dumps({"conflicts": {
                    "journal": [{"source": "hal", "value": "Other"}],
                }}),
                json.dumps([{"url": "https://example.org/doc", "host": "Legacy"}]),
            ),
        )
        db.conn.commit()
        before = other_copies_result(_article_with_extra(db))
        assert [item.url for item in before.copies] == ["https://example.org/doc"]
        assert before.copies[0].open_listed is False
        db.insert_articles([_paper("1", "pubmed", _observed_at=stamp)])
        after = other_copies_result(_article_with_extra(db))
        assert [item.url for item in after.copies] == ["https://example.org/doc"]
        assert after.copies[0].open_listed is False
        stored = json.loads(db.conn.execute(
            "SELECT locations FROM article_extra"
        ).fetchone()[0])
        assert stored == [{"url": "https://example.org/doc", "host": "Legacy"}]
    finally:
        db.close()


def _article_with_extra(db):
    row = db.get_all_articles()[0]
    extra = db.conn.execute(
        "SELECT provenance, locations FROM article_extra"
    ).fetchone()
    row["provenance"] = extra[0]
    row["locations"] = extra[1]
    return row


_URL_IDENTITY_CASES = [
    ("scheme", "http://example.org/doc", "https://example.org/doc", False),
    ("slash", "https://example.org/doc", "https://example.org/doc/", False),
    ("fragment", "https://example.org/doc#a", "https://example.org/doc#b", False),
    ("query", "https://example.org/doc?a=1", "https://example.org/doc?a=2", False),
    ("query order", "https://example.org/doc?a=1&b=2", "https://example.org/doc?b=2&a=1", False),
    ("path case", "https://example.org/Doc", "https://example.org/doc", False),
    ("host case", "https://EXAMPLE.org/doc", "https://example.org/doc", True),
    ("https default port", "https://example.org:443/doc", "https://example.org/doc", True),
    ("http default port", "http://example.org:80/doc", "http://example.org/doc", True),
    ("https nondefault 80", "https://example.org:80/doc", "https://example.org/doc", False),
    ("http nondefault 443", "http://example.org:443/doc", "http://example.org/doc", False),
    ("ipv6 default port", "https://[2001:db8::1]:443/doc", "https://[2001:db8::1]/doc", True),
    ("ipv6 port collision", "https://[2001:db8::1]:8080/doc", "https://[2001:db8::1:8080]/doc", False),
    ("credentials", "https://alice@example.org/doc", "https://bob@example.org/doc", False),
]


def test_ipv6_identity_keeps_host_brackets():
    closed = "https://[2001:db8::1]:8080/doc"
    opened = "https://[2001:db8::1:8080]/doc"
    assert evidence_url_key(closed) == "https://[2001:db8::1]:8080/doc"
    assert evidence_url_key(opened) == "https://[2001:db8::1:8080]/doc"
    assert evidence_url_key(closed) != evidence_url_key(opened)
    assert evidence_url_key("https://[2001:db8::1]:443/doc") == "https://[2001:db8::1]/doc"


@pytest.mark.parametrize("name, closed, opened, same", _URL_IDENTITY_CASES)
def test_p24_does_not_move_open_label_across_url_identity(
    monkeypatch, name, closed, opened, same,
):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(":memory:")
    stamp = "2026-10-29T08:00:00.000000Z"
    try:
        assert (evidence_url_key(closed) == evidence_url_key(opened)) is same
        db.insert_articles([_paper(
            "123", "pubmed", oa_status="closed", best_oa_url=closed,
            _observed_at=stamp,
        )])
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold", best_oa_url=opened,
            _observed_at=stamp,
        )])
        extra = db.conn.execute("SELECT provenance FROM article_extra").fetchone()
        row = db.get_all_articles()[0]
        row["provenance"] = json.loads(extra[0])
        evidence = row["provenance"][LINK_EVIDENCE_KEY]
        assert link_access(evidence, closed).open_listed is same
        assert link_access(evidence, opened).open_listed is True
        found = other_copies_result(row)
        by_url = {item.url: item.open_listed for item in found.copies}
        if same:
            assert access_state(row).state == OPEN_LISTED
        else:
            assert access_state(row).url == opened
            assert by_url.get(closed) is not True
            open_urls = [item.url for item in found.copies if item.open_listed]
            assert closed not in open_urls
            if opened != access_state(row).url:
                assert opened in open_urls
            if name == "ipv6 port collision":
                mainrow = dict(row, source="openaire", article_id=closed)
                maincopies = other_copies_result(mainrow)
                assert maincopies.has_open_copy is True
                assert any(
                    item.url == opened and item.open_listed
                    for item in maincopies.copies
                )
    finally:
        db.close()


def test_malformed_evidence_does_not_open_or_use_legacy():
    url = "https://example.org/shared"
    for raw in (
        {"version": 2, "observations": []},
        {"version": 1, "observations": "broken"},
        "not-json",
    ):
        row = {
            "source": "openalex",
            "oa_status": "gold",
            "best_oa_url": url,
            "provenance": {LINK_EVIDENCE_KEY: raw},
        }
        assert access_state(row).state == "none_listed"
        assert link_access(raw, url).open_listed is False


def test_incomplete_observation_is_not_a_witness():
    url = "https://example.org/doc"
    evidence = {
        "version": 1,
        "observations": [{
            "locations": [{"url": url, "basis": "oa_best", "oa_status": "gold"}],
        }],
    }
    decision = link_access(evidence, url)
    assert decision.open_listed is False
    assert decision.witnesses == ()
    assert access_state({
        "source": "pubmed",
        "provenance": {LINK_EVIDENCE_KEY: evidence},
    }).state == "none_listed"


@pytest.mark.parametrize("field, value", [
    ("source", {"bad": "source"}),
    ("source_record_id", ["W1"]),
    ("observed_at", {"bad": "time"}),
])
def test_wrong_typed_ownership_is_not_a_witness(field, value):
    url = "https://example.org/shared"
    evidence = {
        "version": 1,
        "observations": [{
            "source": "openalex",
            "source_record_id": "W1",
            "observed_at": "2026-10-29T08:00:00.000000Z",
            "locations": [{
                "url": url, "basis": "oa_best", "oa_status": "gold",
            }],
        }],
    }
    evidence["observations"][0][field] = value
    decision = link_access(evidence, url)
    assert decision.open_listed is False
    assert decision.witnesses == ()
    assert "{'bad': 'source'}" not in str(decision.witnesses)
    assert "['W1']" not in str(decision.witnesses)
    assert "{'bad': 'time'}" not in str(decision.witnesses)
    row = {
        "source": "openalex",
        "article_id": "W1",
        "oa_status": "gold",
        "best_oa_url": url,
        "provenance": {LINK_EVIDENCE_KEY: evidence},
    }
    assert access_state(row).state == "none_listed"
    found = other_copies_result(row)
    assert found.has_open_copy is False
    assert not any(item.open_listed for item in found.copies)


@pytest.mark.parametrize("field, value", [
    ("source", {"bad": "source"}),
    ("source_record_id", ["W1"]),
    ("observed_at", {"bad": "time"}),
])
def test_wrong_typed_ownership_is_left_unchanged_on_write(monkeypatch, field, value):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    url = "https://example.org/shared"
    stamp = "2026-10-29T08:00:00.000000Z"
    paper = _paper(
        "W1", "openalex", oa_status="gold", best_oa_url=url, _observed_at=stamp,
    )
    for staging in (False, True):
        db = ArticleDatabase(":memory:")
        try:
            if staging:
                db.ensure_staging_articles()
            db.insert_articles([paper], staging=staging)
            table = "staging_article_extra" if staging else "article_extra"
            stored = json.loads(db.conn.execute(
                f"SELECT provenance FROM {table}"
            ).fetchone()[0])
            stored[LINK_EVIDENCE_KEY]["observations"][0][field] = value
            before = json.dumps(stored)
            db.conn.execute(f"UPDATE {table} SET provenance = ?", (before,))
            db.conn.commit()
            result = db.insert_articles(
                [dict(paper, journal="Changed journal")], staging=staging,
            )
            after = db.conn.execute(f"SELECT provenance FROM {table}").fetchone()[0]
            assert result["updated"] == 0
            assert result["dropped"] == 1
            assert after == before
        finally:
            db.close()


def test_broken_locations_list_rejects_the_row_update(monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    db = ArticleDatabase(":memory:")
    stamp = "2026-10-29T08:00:00.000000Z"
    url = "https://example.org/shared"
    try:
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold", best_oa_url=url,
            _observed_at=stamp,
        )])
        old = {
            LINK_EVIDENCE_KEY: {
                "version": 1,
                "observations": [{"source": "openalex", "locations": "broken"}],
            },
        }
        db.conn.execute(
            "UPDATE article_extra SET provenance = ?",
            (json.dumps(old),),
        )
        db.conn.commit()
        result = db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold", best_oa_url=url,
            _observed_at=stamp,
        )])
        assert result["updated"] == 0
        assert result["dropped"] == 1
        stored = json.loads(db.conn.execute(
            "SELECT provenance FROM article_extra"
        ).fetchone()[0])
        assert stored == old
    finally:
        db.close()


@pytest.mark.parametrize("unsupported", [
    {"original-payload": {"retain-this": "value"}},
    "keep-me",
])
def test_malformed_unsupported_is_left_byte_for_byte(monkeypatch, unsupported):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    url = "https://example.org/shared"
    stamp = "2026-10-29T08:00:00.000000Z"
    paper = _paper(
        "W1", "openalex", oa_status="gold", best_oa_url=url, _observed_at=stamp,
    )
    db = ArticleDatabase(":memory:")
    try:
        db.insert_articles([paper])
        stored = json.loads(db.conn.execute(
            "SELECT provenance FROM article_extra"
        ).fetchone()[0])
        stored[LINK_EVIDENCE_KEY]["unsupported"] = unsupported
        before = json.dumps(stored)
        db.conn.execute("UPDATE article_extra SET provenance = ?", (before,))
        db.conn.commit()
        result = db.insert_articles([paper])
        after = db.conn.execute("SELECT provenance FROM article_extra").fetchone()[0]
        assert result["updated"] == 0
        assert result["dropped"] == 1
        assert after == before
        assert json.loads(after)[LINK_EVIDENCE_KEY]["unsupported"] == unsupported
    finally:
        db.close()


def test_replace_fetch_unions_surviving_evidence(monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    url = "https://example.org/open"
    first = _paper(
        "W1", "openalex", oa_status="gold", best_oa_url=url,
        _observed_at="2026-10-29T08:00:00.000000Z",
    )
    later = _paper(
        "W1", "openalex", oa_status="closed", best_oa_url=url,
        _observed_at="2026-10-29T09:00:00.000000Z",
    )
    empty = _paper(
        "W1", "openalex", oa_status="closed",
        _observed_at="2026-10-29T10:00:00.000000Z",
    )
    db = ArticleDatabase(":memory:")
    try:
        db.insert_articles([first])
        before = json.loads(db.conn.execute(
            "SELECT provenance FROM article_extra"
        ).fetchone()[0])[LINK_EVIDENCE_KEY]
        db.ensure_staging_articles()
        db.insert_articles([later], staging=True)
        db.insert_articles([empty], staging=True)
        db.replace_from_staging()
        after = json.loads(db.conn.execute(
            "SELECT provenance FROM article_extra"
        ).fetchone()[0])[LINK_EVIDENCE_KEY]
        assert all(item in after["observations"] for item in before["observations"])
        assert len(after["observations"]) >= 3
        row = {"source": "openalex", "provenance": {LINK_EVIDENCE_KEY: after}}
        assert access_state(row).state == OPEN_LISTED
        db2 = ArticleDatabase(":memory:")
        db2.insert_articles([first])
        db2.insert_articles([later])
        db2.insert_articles([empty])
        appended = json.loads(db2.conn.execute(
            "SELECT provenance FROM article_extra"
        ).fetchone()[0])[LINK_EVIDENCE_KEY]
        assert after == appended
        db2.close()
    finally:
        db.close()


def test_replace_fetch_evidence_union_rolls_back_then_retries(monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    url = "https://example.org/open"
    db = ArticleDatabase(":memory:")
    try:
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold", best_oa_url=url,
            _observed_at="2026-10-29T08:00:00.000000Z",
        )])
        live = db.conn.execute("SELECT provenance FROM article_extra").fetchone()[0]
        db.ensure_staging_articles()
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="closed", best_oa_url=url,
            _observed_at="2026-10-29T09:00:00.000000Z",
        )], staging=True)
        db.conn.execute(
            """
            CREATE TRIGGER fail_extra_copy BEFORE INSERT ON article_extra
            BEGIN SELECT RAISE(ABORT, 'injected swap failure'); END
            """
        )
        db.conn.commit()
        with pytest.raises(dbconn.integrity_errors(), match="injected swap failure"):
            db.replace_from_staging()
        assert db.conn.execute(
            "SELECT provenance FROM article_extra"
        ).fetchone()[0] == live
        db.conn.execute("DROP TRIGGER fail_extra_copy")
        db.conn.commit()
        assert db.replace_from_staging() == 1
        after = json.loads(db.conn.execute(
            "SELECT provenance FROM article_extra"
        ).fetchone()[0])[LINK_EVIDENCE_KEY]
        assert len(after["observations"]) == 2
        row = {"source": "openalex", "provenance": {LINK_EVIDENCE_KEY: after}}
        assert access_state(row).state == OPEN_LISTED
    finally:
        db.close()


def test_copies_scan_each_observation_once(monkeypatch):
    calls = {"n": 0}
    real = access_mod._witness_from_location

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(access_mod, "_witness_from_location", wrapped)
    n = 200
    observations = []
    for i in range(n):
        observations.append({
            "source": "openalex",
            "source_record_id": "W1",
            "observed_at": f"t{i:04}",
            "locations": [{
                "url": "https://example.org/doc",
                "oa_status": "gold",
                "licence": None,
                "licence_scope": None,
                "kind": None,
                "host": None,
                "basis": "oa_best",
                "details": {},
            }],
        })
    row = {
        "source": "pubmed",
        "article_id": "1",
        "provenance": {LINK_EVIDENCE_KEY: {
            "version": 1,
            "observations": observations,
        }},
    }
    found = other_copies_result(row)
    assert len(found.copies) == 1
    assert found.copies[0].open_listed is True
    assert found.has_open_copy is True
    assert calls["n"] == n


def _clone_setup(monkeypatch, tmp_path):
    from app.storage import shares as shares_mod

    owner_path = tmp_path / "owner" / "articles.db"
    clone_path = tmp_path / "clone" / "articles.db"
    owner_path.parent.mkdir(parents=True)
    udb = UserDatabase(db_path=str(tmp_path / "users.db"))
    owner = udb.create_user("owner", "hash")
    student = udb.create_user("student", "hash")
    monkeypatch.setattr(
        shares_mod,
        "library_db_path",
        lambda user, library: owner_path if user == owner["id"] else clone_path,
    )
    return shares_mod, udb, owner, student, owner_path, clone_path


def test_clone_library_data_drops_extra_and_is_not_open(monkeypatch, tmp_path):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    shares_mod, _udb, owner, student, owner_path, clone_path = _clone_setup(
        monkeypatch, tmp_path,
    )
    db = ArticleDatabase(str(owner_path))
    try:
        db.insert_articles([_paper(
            "123", "pubmed", best_oa_url=PUBMED_CLOSED,
        )])
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold", best_oa_url=OPENALEX_OPEN,
        )])
    finally:
        db.close()
    shares_mod.clone_library_data(owner["id"], "lib", student["id"], "cloned")
    clone_db = ArticleDatabase(str(clone_path))
    try:
        extras = clone_db.conn.execute(
            "SELECT COUNT(*) FROM article_extra"
        ).fetchone()[0]
        assert extras == 0
        row = _access_row(clone_db, "123", "pubmed")
        _assert_no_open(row, closed_url=PUBMED_CLOSED)
    finally:
        clone_db.close()


def test_join_race_clone_is_not_open(monkeypatch, tmp_path):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    from app import core
    from app.storage import shares as shares_mod

    owner_path = tmp_path / "race-owner.db"
    clone_path = tmp_path / "race-clone.db"
    udb = UserDatabase(db_path=str(tmp_path / "users.db"))
    owner = udb.create_user("race-owner", "hash")
    student = udb.create_user("race-student", "hash")
    monkeypatch.setattr(core, "user_db", udb)
    db = ArticleDatabase(str(owner_path))
    try:
        db.insert_articles([_paper("seed", "pubmed", best_oa_url=PUBMED_CLOSED)])
        db.insert_articles([_paper(
            "oa", "openalex", oa_status="gold", best_oa_url=OPENALEX_OPEN,
        )])
    finally:
        db.close()
    share = udb.create_share(
        owner_user_id=owner["id"],
        owner_library_id="source",
        title_snapshot="Source",
        code=generate_share_code(),
    )
    observed = {}
    held = []

    def concurrent_read(*_args, **_kwargs):
        q = core.get_pipeline(student["id"], "new-clone")
        held.append(q)
        row = q.db.get_article_access_fields()[("seed", "pubmed")]
        row = dict(row)
        row["article_id"] = "seed"
        row["source"] = "pubmed"
        observed["during_join"] = access_state(row).state
        observed["during_join_open"] = other_copies_result(row).has_open_copy

    with patch.object(
        shares_mod, "library_db_path",
        side_effect=lambda uid, lid: owner_path if uid == owner["id"] else clone_path,
    ), patch.object(core, "library_db_path", return_value=clone_path), patch.object(
        core, "ensure_libraries",
    ), patch.object(
        shares_mod, "library_exists", return_value=True,
    ), patch.object(
        shares_mod, "get_active_library_id", return_value="old",
    ), patch.object(
        shares_mod, "create_library_with_unique_name",
        return_value={"library": {"id": "new-clone", "name": "Clone"}},
    ), patch.object(
        shares_mod, "set_active_library", side_effect=concurrent_read,
    ), patch.object(
        shares_mod, "list_libraries",
        return_value={"libraries": [{"id": "old"}, {"id": "new-clone"}]},
    ):
        shares_mod.join_share(udb, student["id"], "race-student", share["code"])
        q = held[0]
        row = q.db.get_article_access_fields()[("seed", "pubmed")]
        row = dict(row)
        row["article_id"] = "seed"
        row["source"] = "pubmed"
        _assert_no_open(row, closed_url=PUBMED_CLOSED)
        assert observed["during_join"] == NONE_LISTED
        assert observed["during_join_open"] is False
        core.release_pipeline(student["id"], "new-clone")


def test_owner_deletion_clone_stays_closed(monkeypatch, tmp_path):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    shares_mod, udb, owner, student, owner_path, clone_path = _clone_setup(
        monkeypatch, tmp_path,
    )
    db = ArticleDatabase(str(owner_path))
    try:
        db.insert_articles([_paper("seed", "pubmed", best_oa_url=PUBMED_CLOSED)])
        db.insert_articles([_paper(
            "oa", "openalex", oa_status="gold", best_oa_url=OPENALEX_OPEN,
        )])
    finally:
        db.close()
    shares_mod.clone_library_data(owner["id"], "lib", student["id"], "lifecycle")
    _redeem(udb, owner["id"], "lib", student["id"], "lifecycle")
    pipe = LiteratureSearchPipeline(db_path=str(clone_path))
    try:
        row = _access_row(pipe.db, "seed", "pubmed")
        _assert_no_open(row, closed_url=PUBMED_CLOSED)
        assert udb.delete_user(owner["id"])
        _assert_no_open(
            _access_row(pipe.db, "seed", "pubmed"),
            closed_url=PUBMED_CLOSED,
        )
    finally:
        pipe.close()
    fresh = LiteratureSearchPipeline(db_path=str(clone_path))
    try:
        _assert_no_open(
            _access_row(fresh.db, "seed", "pubmed"),
            closed_url=PUBMED_CLOSED,
        )
    finally:
        fresh.close()


def test_unmarked_clone_without_evidence_is_not_open(monkeypatch, tmp_path):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    udb = UserDatabase(db_path=str(tmp_path / "users.db"))
    owner = udb.create_user("owner", "hash")
    student = udb.create_user("student", "hash")
    db = ArticleDatabase(str(tmp_path / "racing.db"))
    try:
        db.insert_articles([_paper(
            "W1", "openalex", oa_status="gold", best_oa_url=NEVER_MERGED_OPEN,
        )])
        db.conn.execute("DELETE FROM article_extra")
        db.conn.commit()
    finally:
        db.close()
    pipe = LiteratureSearchPipeline(db_path=str(tmp_path / "racing.db"))
    try:
        row = _access_row(pipe.db, "W1", "openalex")
        _assert_no_open(row, closed_url=NEVER_MERGED_OPEN)
        _redeem(udb, owner["id"], "lib", student["id"], "racing-clone")
        _assert_no_open(
            _access_row(pipe.db, "W1", "openalex"),
            closed_url=NEVER_MERGED_OPEN,
        )
        articles = [{"article_id": "W1", "source": "openalex"}]
        pipe._attach_access(articles)
        assert articles[0]["access"]["state"] != OPEN_LISTED
    finally:
        pipe.close()


@pytest.mark.parametrize("name, changes", [
    ("crossref_oa_best", {"source": "crossref"}),
    ("hal_oa_best", {"source": "hal"}),
    ("pubmed_doaj_fulltext", {
        "source": "pubmed",
        "locations": [{
            "url": "https://example.org/shared",
            "basis": "doaj_fulltext",
            "oa_status": "closed",
            "kind": "landing",
        }],
    }),
])
def test_malformed_source_basis_is_never_open_and_preserved(
    monkeypatch, name, changes,
):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    url = "https://example.org/shared"
    stamp = "2026-10-29T08:00:00.000000Z"
    paper = _paper(
        "W1", "openalex", oa_status="gold", best_oa_url=url, _observed_at=stamp,
    )
    db = ArticleDatabase(":memory:")
    try:
        db.insert_articles([paper])
        stored = json.loads(db.conn.execute(
            "SELECT provenance FROM article_extra"
        ).fetchone()[0])
        stored[LINK_EVIDENCE_KEY]["observations"][0].update(changes)
        before = json.dumps(stored)
        db.conn.execute("UPDATE article_extra SET provenance = ?", (before,))
        db.conn.commit()
        row = _access_row(db, "W1", "openalex")
        _assert_no_open(row, closed_url=url)
        decision = link_access(stored[LINK_EVIDENCE_KEY], url)
        assert decision.open_listed is False
        result = db.insert_articles([dict(
            paper, oa_status="closed", journal="Changed journal",
        )])
        after = db.conn.execute("SELECT provenance FROM article_extra").fetchone()[0]
        assert result["updated"] == 0
        assert result["dropped"] == 1
        assert after == before
        article = db.conn.execute(
            "SELECT journal, oa_status FROM articles"
        ).fetchone()
        assert article[0] != "Changed journal"
        assert json.loads(after)[LINK_EVIDENCE_KEY]["observations"][0]["source"] == (
            changes.get("source") or "openalex"
        )
    finally:
        db.close()
    assert name


def _load_source_fixture(name):
    path = Path(__file__).resolve().parent / "fixtures" / "sources" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _real_adapter_articles():
    from app.fetchers.arxiv import ARXIV_NS, ATOM_NS, ArXivFetcher
    from app.fetchers.biorxiv import BioRxivFetcher, MedRxivFetcher
    from app.fetchers.clinicaltrials import ClinicalTrialsFetcher
    from app.fetchers.crossref import CrossRefFetcher
    from app.fetchers.doaj import DOAJFetcher
    from app.fetchers.eric import ERICFetcher
    from app.fetchers.europepmc import EuropePMCFetcher
    from app.fetchers.hal import HALFetcher
    from app.fetchers.nasa_ads import NASAADSFetcher
    from app.fetchers.openaire import OpenAIREFetcher
    from app.fetchers.openalex import OpenAlexFetcher
    from app.fetchers.plos import PLOSFetcher
    from app.fetchers.semanticscholar import SemanticScholarFetcher
    from app.fetchers.zenodo import ZenodoFetcher

    articles = []

    def add(source, article):
        assert article is not None, f"{source} fixture produced no article"
        articles.append((source, article))

    add("openalex", OpenAlexFetcher()._parse_work(
        _load_source_fixture("openalex_article_oa.json")["results"][0],
    ))
    add("openalex", OpenAlexFetcher()._parse_work(
        _load_source_fixture("openalex_article_closed.json")["results"][0],
    ))
    add("crossref", CrossRefFetcher()._parse_item(
        _load_source_fixture("crossref_book.json")["message"]["items"][0],
    ))
    add("doaj", DOAJFetcher()._parse_result(
        _load_source_fixture("doaj_oa_article.json")["results"][0],
    ))
    add("hal", HALFetcher()._parse(
        _load_source_fixture("hal_file.json")["response"]["docs"][0],
    ))
    add("hal", HALFetcher()._parse(
        _load_source_fixture("hal_notice.json")["response"]["docs"][0],
    ))
    add("zenodo", ZenodoFetcher()._parse_record(
        _load_source_fixture("zenodo_open.json")["hits"]["hits"][0],
    ))
    add("zenodo", ZenodoFetcher()._parse_record(
        _load_source_fixture("zenodo_restricted.json")["hits"]["hits"][0],
    ))
    add("semanticscholar", SemanticScholarFetcher()._parse_paper(
        _load_source_fixture("s2_paper.json"),
    ))
    add("eric", ERICFetcher()._parse_doc(
        _load_source_fixture("eric_journal.json")["response"]["docs"][0],
    ))
    add("europepmc", EuropePMCFetcher()._parse_article(
        _load_source_fixture("europepmc_oa_pmc.json")["resultList"]["result"][0],
    ))
    add("clinicaltrials", ClinicalTrialsFetcher()._parse_study(
        _load_source_fixture("clinicaltrials_studies.json")["studies"][0],
    ))
    add("nasa_ads", NASAADSFetcher()._parse_doc(
        _load_source_fixture("nasa_ads_doc.json")["response"]["docs"][0],
    ))
    add("openaire", OpenAIREFetcher()._parse(
        _load_source_fixture("openaire_publications.json")["response"]["results"]["result"][0],
    ))
    add("plos", PLOSFetcher()._parse(
        _load_source_fixture("plos_search_parenthesised.json")["response"]["docs"][0],
    ))
    add("biorxiv", BioRxivFetcher()._parse_article(
        _load_source_fixture("europepmc_ppr_biorxiv.json")["resultList"]["result"][0],
    ))
    add("medrxiv", MedRxivFetcher()._parse_article(
        _load_source_fixture("europepmc_ppr_medrxiv.json")["resultList"]["result"][0],
    ))
    root = ET.parse(
        Path(__file__).resolve().parent / "fixtures" / "sources" / "arxiv_and_query.xml",
    ).getroot()
    ns = {"a": ATOM_NS, "ax": ARXIV_NS}
    add("arxiv", ArXivFetcher()._parse_entry(root.findall("a:entry", ns)[0], ns))
    return articles


_REQUIRED_ADAPTERS = frozenset({
    "hal", "openalex", "doaj", "crossref", "zenodo", "openaire", "europepmc",
})
_ADAPTER_STAMP = "2026-10-29T12:00:00.000000Z"
_TYPE_MUTATIONS = (
    ("source", "not-a-source"),
    ("basis", {"bad": "basis"}),
    ("kind", {"bad": "kind"}),
    ("licence", {"bad": "licence"}),
    ("licence_scope", {"bad": "scope"}),
)
_STRING_MUTATIONS = (
    ("basis", "forged_basis"),
    ("kind", "not-an-adapter-kind"),
    ("licence", "https://example.org/forged-licence"),
    ("licence_scope", "record"),
)
_IMPOSSIBLE_KINDS = (
    ("openalex", "not-an-adapter-kind"),
    ("zenodo", "landing"),
    ("europepmc", "text-mining"),
    ("biorxiv", "landing"),
    ("semanticscholar", "file"),
)


def _observation_from_article(article):
    extra = article.get("_extra") if isinstance(article.get("_extra"), dict) else {}
    return observation_from_record(
        incoming_record_from_article(article, extra, _ADAPTER_STAMP),
    )


def _real_adapter_observations():
    return [
        _observation_from_article(article)
        for _source, article in _real_adapter_articles()
    ]


def _typical_kind(source):
    kinds = SOURCE_ADAPTER_SHAPES[source]["kind"]
    for item in ("pdf", "file", "fulltext", "landing"):
        if item in kinds:
            return item
    return None


def _synthetic_adapter_observations():
    observations = []
    for source in FETCHERS:
        extra = {}
        status = "gold"
        kind = _typical_kind(source)
        if kind:
            extra["kind"] = kind
        if source == "hal":
            extra["host"] = "HAL"
            status = "green"
        elif source == "crossref":
            extra["license"] = "https://creativecommons.org/licenses/by/4.0/"
            status = None
        rec = _incoming(
            source, f"{source}-id", f"https://example.org/{source}", status,
            _ADAPTER_STAMP, **extra,
        )
        observations.append(observation_from_record(rec))
    return observations


def _value_allowed_for_source(source, field, value):
    if field == "source":
        return False
    allowed = SOURCE_ADAPTER_SHAPES[source][field]
    if value in allowed:
        return True
    return ANY_TEXT in allowed and isinstance(value, str)


def _shape_mutations(obs):
    yield from _TYPE_MUTATIONS
    if not obs.get("locations"):
        return
    source = obs["source"]
    for field, value in _STRING_MUTATIONS:
        if not _value_allowed_for_source(source, field, value):
            yield field, value


def test_every_adapter_output_matches_the_allow_list():
    assert set(SOURCE_ADAPTER_SHAPES) == set(FETCHERS)
    assert set(SOURCE_ADAPTER_BASES) == set(FETCHERS)
    real = _real_adapter_observations()
    assert real, "real parser fixtures produced no observations"
    real_sources = {obs["source"] for obs in real}
    assert "doaj" in real_sources
    assert _REQUIRED_ADAPTERS <= real_sources
    for obs in real:
        assert observation_matches_adapter(obs), obs
        for loc in obs["locations"]:
            assert location_matches_adapter(obs["source"], loc), (obs["source"], loc)
    synthetics = _synthetic_adapter_observations()
    assert any(
        obs["source"] == "crossref"
        and any(
            loc.get("basis") == "crossref_entry" and loc.get("licence")
            for loc in obs["locations"]
        )
        for obs in synthetics
    )
    combined = real + synthetics
    for obs in synthetics:
        assert observation_matches_adapter(obs), obs
        for loc in obs["locations"]:
            assert location_matches_adapter(obs["source"], loc), (obs["source"], loc)
    assert {obs["source"] for obs in combined} == set(FETCHERS)


def test_real_adapter_outputs_fail_when_each_shape_field_mutates():
    real = _real_adapter_observations()
    assert real, "real parser fixtures produced no observations"
    assert any(obs["source"] == "doaj" for obs in real)
    for obs in real + _synthetic_adapter_observations():
        assert observation_matches_adapter(obs)
        for field, value in _shape_mutations(obs):
            mutated = copy.deepcopy(obs)
            if field == "source":
                mutated["source"] = value
            elif not mutated["locations"]:
                continue
            else:
                mutated["locations"][0][field] = value
            assert not observation_matches_adapter(mutated), (obs["source"], field, value)
            if field != "source" and mutated["locations"]:
                assert not location_matches_adapter(
                    obs["source"], mutated["locations"][0],
                ), (obs["source"], field, value)


def test_real_doaj_and_real_adapter_list_are_required():
    articles = _real_adapter_articles()
    assert articles
    assert any(source == "doaj" for source, _article in articles)


def _seed_vector():
    return np.array([1.0, 0.0], dtype=np.float32)


def _neighbor_vector():
    return np.array([0.95, 0.1], dtype=np.float32)


def _open_neighbor_paper():
    return _paper(
        "nb", "doaj", doi="10.9999/neighbor", oa_status="gold",
        best_oa_url="https://example.org/neighbor.pdf",
        title="A neighboring open paper",
        _observed_at=_ADAPTER_STAMP,
        _extra={"locations": [{
            "url": "https://example.org/neighbor.pdf",
            "kind": "fulltext",
            "via": "doaj",
        }]},
    )


def _pipe_with_neighbor(db_path, seed):
    pipe = LiteratureSearchPipeline(db_path=str(db_path))
    pipe.embedding_engine.embed_query = lambda _q: _seed_vector()
    pipe.db.insert_articles([seed], dedupe=False)
    pipe.db.insert_articles([_open_neighbor_paper()], dedupe=False)
    key = (seed["article_id"], seed["source"])
    pipe.db.insert_embeddings(
        {key: _seed_vector(), ("nb", "doaj"): _neighbor_vector()},
        model_name="general",
    )
    pipe.db.upsert_note(*key, starred=True)
    return pipe, key


def _assert_readers(pipe, key, *, expect_open):
    row = _access_row(pipe.db, key[0], key[1])
    cards = [{"article_id": key[0], "source": key[1]}]
    pipe._attach_access(cards)
    copies = other_copies_result(row)
    listed = pipe.search_similar(
        "Same work from two sources", top_k=10, lexical_boost=False,
        free_to_read=True,
    )
    free = key in {(item["article_id"], item["source"]) for item in listed}
    different = len(pipe.suggest_different_work([key]))
    if expect_open:
        assert cards[0]["access"]["state"] == OPEN_LISTED
        assert free is True
        assert copies.has_open_copy is True
        assert different == 0
    else:
        assert cards[0]["access"]["state"] != OPEN_LISTED
        assert free is False
        assert copies.has_open_copy is False
        assert different == 1


def _assert_refresh_preserves(paper, evidence, *, staging):
    db = ArticleDatabase(":memory:")
    try:
        if staging:
            db.ensure_staging_articles()
        db.insert_articles([paper], staging=staging)
        table = "staging_article_extra" if staging else "article_extra"
        articles = "staging_articles" if staging else "articles"
        raw = json.dumps({LINK_EVIDENCE_KEY: evidence})
        db.conn.execute(f"UPDATE {table} SET provenance = ?", (raw,))
        db.conn.commit()
        before_article = db.conn.execute(f"SELECT * FROM {articles}").fetchall()
        result = db.insert_articles(
            [dict(paper, journal="Changed by refresh")], staging=staging,
        )
        after = db.conn.execute(f"SELECT provenance FROM {table}").fetchone()[0]
        assert result["updated"] == 0
        assert result["dropped"] == 1
        assert after == raw
        assert before_article == db.conn.execute(f"SELECT * FROM {articles}").fetchall()
    finally:
        db.close()


def _real_observation_for(source):
    for parsed_source, article in _real_adapter_articles():
        if parsed_source != source:
            continue
        obs = _observation_from_article(article)
        if obs["locations"]:
            return obs
    kind = _typical_kind(source)
    extra = {"kind": kind} if kind else {}
    return observation_from_record(_incoming(
        source, f"{source}-id", f"https://example.org/{source}", "gold",
        _ADAPTER_STAMP, **extra,
    ))


def test_real_positive_parser_output_is_open_on_readers(monkeypatch, tmp_path):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    source, article = next(
        (parsed, row) for parsed, row in _real_adapter_articles() if parsed == "doaj"
    )
    seed = dict(article)
    seed["_observed_at"] = _ADAPTER_STAMP
    pipe, key = _pipe_with_neighbor(tmp_path / "real-open.db", seed)
    try:
        _assert_readers(pipe, key, expect_open=True)
    finally:
        pipe.close()
    assert source == "doaj"


@pytest.mark.parametrize("source, bad_kind", _IMPOSSIBLE_KINDS)
def test_impossible_kind_is_closed_and_preserved(monkeypatch, tmp_path, source, bad_kind):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    original = _real_observation_for(source)
    assert original["locations"]
    assert observation_matches_adapter(original)
    obs = copy.deepcopy(original)
    obs["locations"][0]["kind"] = bad_kind
    assert observation_matches_adapter(obs) is False
    assert location_matches_adapter(source, obs["locations"][0]) is False
    url = obs["locations"][0]["url"]
    evidence = {"version": 1, "observations": [obs]}
    seed = _paper(
        "seed", "openalex", oa_status="gold", best_oa_url=url,
        doi="10.1234/impossible-kind",
        _observed_at=_ADAPTER_STAMP,
    )
    pipe, key = _pipe_with_neighbor(tmp_path / f"{source}-readers.db", seed)
    try:
        raw = json.dumps({LINK_EVIDENCE_KEY: evidence})
        pipe.db.conn.execute(
            "UPDATE article_extra SET provenance = ? "
            "WHERE article_id = ? AND source = ?",
            (raw, key[0], key[1]),
        )
        pipe.db.conn.commit()
        _assert_readers(pipe, key, expect_open=False)
        row = _access_row(pipe.db, key[0], key[1])
        _assert_no_open(row, closed_url=url)
        assert link_access(evidence, url).open_listed is False
    finally:
        pipe.close()
    for staging in (False, True):
        _assert_refresh_preserves(seed, evidence, staging=staging)


def _doaj_fulltext_observation(changes):
    loc = {
        "url": "https://example.org/doaj",
        "basis": "doaj_fulltext",
        "kind": "fulltext",
        "oa_status": "gold",
        "licence": None,
        "licence_scope": None,
    }
    loc.update(changes)
    return {
        "source": "doaj",
        "source_record_id": "D1",
        "observed_at": "2026-10-29T12:00:00Z",
        "locations": [loc],
    }


@pytest.mark.parametrize("name, changes", [
    ("landing_closed", {"kind": "landing", "oa_status": "closed"}),
    ("kind_mapping", {"kind": {"bad": "kind"}}),
    ("impossible_licence_scope", {
        "licence": "https://creativecommons.org/licenses/by/4.0/",
        "licence_scope": "entry",
    }),
])
def test_doaj_injected_shapes_are_not_witnesses(monkeypatch, name, changes):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    url = "https://example.org/doaj"
    obs = _doaj_fulltext_observation(changes)
    assert observation_matches_adapter(obs) is False
    assert location_matches_adapter("doaj", obs["locations"][0]) is False
    evidence = {"version": 1, "observations": [obs]}
    assert link_access(evidence, url).open_listed is False
    row = _paper("seed", "openalex", oa_status="gold", best_oa_url=url)
    row["provenance"] = {LINK_EVIDENCE_KEY: evidence}
    _assert_no_open(row, closed_url=url)
    db = ArticleDatabase(":memory:")
    try:
        seed = _paper("seed", "openalex", oa_status="gold", best_oa_url=url)
        db.insert_articles([seed])
        raw = json.dumps({LINK_EVIDENCE_KEY: evidence})
        db.conn.execute("UPDATE article_extra SET provenance = ?", (raw,))
        db.conn.commit()
        result = db.insert_articles([dict(seed, journal="Changed by refresh")])
        after = db.conn.execute("SELECT provenance FROM article_extra").fetchone()[0]
        assert result["updated"] == 0
        assert result["dropped"] == 1
        assert after == raw
        journal = db.conn.execute("SELECT journal FROM articles").fetchone()[0]
        assert journal != "Changed by refresh"
    finally:
        db.close()
    assert name


def test_wrong_typed_kind_is_not_a_witness():
    url = "https://example.org/doc"
    loc = {
        "url": url,
        "basis": "oa_best",
        "oa_status": "gold",
        "kind": {"bad": "kind"},
        "licence": None,
        "licence_scope": None,
    }
    assert location_matches_adapter("openalex", loc) is False
    evidence = {
        "version": 1,
        "observations": [{
            "source": "openalex",
            "source_record_id": "W1",
            "observed_at": "2026-10-29T12:00:00.000000Z",
            "locations": [loc],
        }],
    }
    assert observation_matches_adapter(evidence["observations"][0]) is False
    assert link_access(evidence, url).open_listed is False
    row = _paper("W1", "openalex", oa_status="gold", best_oa_url=url)
    row["provenance"] = {LINK_EVIDENCE_KEY: evidence}
    _assert_no_open(row, closed_url=url)


@pytest.mark.parametrize("source, loc", [
    ("doaj", {
        "url": "https://example.org/fulltext",
        "basis": "doaj_fulltext",
        "kind": "fulltext",
        "oa_status": "gold",
        "licence": "https://creativecommons.org/licenses/by/4.0/",
        "licence_scope": None,
    }),
    ("hal", {
        "url": "https://hal.science/hal-1/document",
        "basis": "hal_file",
        "kind": "file",
        "oa_status": "green",
        "licence": "https://creativecommons.org/licenses/by/4.0/",
        "licence_scope": None,
    }),
])
def test_licence_rejected_where_adapter_emits_none(source, loc):
    assert location_matches_adapter(source, loc) is False
    evidence = {
        "version": 1,
        "observations": [{
            "source": source,
            "source_record_id": "rec",
            "observed_at": "2026-10-29T12:00:00.000000Z",
            "locations": [loc],
        }],
    }
    assert observation_matches_adapter(evidence["observations"][0]) is False
    assert link_access(evidence, loc["url"]).open_listed is False
