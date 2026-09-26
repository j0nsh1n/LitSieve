"""Set aside list (Phase 13, slice 1): every exclusion reason, with restore.

Before this, a Simple student could restore only ``low_relevance`` (Narrow it
down's Undo). Duplicate copies and Not relevant papers could come back only
from the Advanced Clusters page. The list shows every reason in plain words
and restores one paper, one group, or undoes the last restore.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_screening import (  # noqa: F401  (fixtures register by import)
    _article,
    _csrf,
    _register_client,
    _seed_corpus,
    _seed_user_library,
    pipe,
    screening_app,
)

from app.storage.database import ArticleDatabase

REPO = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return REPO.joinpath(*parts).read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    a = text.find(start)
    assert a >= 0, f"missing {start!r}"
    b = text.find(end, a + len(start))
    return text[a:b if b >= 0 else None]


@pytest.fixture
def db(tmp_path):
    d = ArticleDatabase(db_path=str(tmp_path / "articles.db"))
    yield d
    d.close()


# ------------------------------------------------------------------ storage --

def test_excluded_items_list_every_reason_with_title_and_year(db):
    db.insert_articles([_article("1"), _article("2"), _article("3"), _article("4")])
    db.exclude_articles([("1", "pubmed")], reason="duplicate")
    db.exclude_articles([("2", "pubmed")], reason="off_topic")
    db.exclude_articles([("3", "pubmed")], reason="low_relevance")

    items = db.get_excluded_items()
    assert {(i["article_id"], i["reason"]) for i in items} == {
        ("1", "duplicate"), ("2", "off_topic"), ("3", "low_relevance"),
    }
    first = next(i for i in items if i["article_id"] == "1")
    assert first["title"] == "Title 1"
    assert first["year"] == "2024"
    assert first["journal"] == "J"
    assert first["source"] == "pubmed"

    only = db.get_excluded_items("off_topic")
    assert [i["article_id"] for i in only] == ["2"]
    assert db.get_excluded_items("language") == []


def test_set_aside_group_labels_are_plain_words():
    from app.content.screening_reasons import (
        EXCLUSION_REASONS,
        SET_ASIDE_GROUP_ORDER,
        set_aside_group_label,
    )

    assert set_aside_group_label("duplicate") == "Duplicate copies"
    assert set_aside_group_label("low_relevance") == "Set aside by Narrow it down"
    assert set_aside_group_label("off_topic") == "Marked not relevant"
    # Every reason the app can write has a place in the list and a readable name.
    for code in EXCLUSION_REASONS:
        assert code in SET_ASIDE_GROUP_ORDER, code
        label = set_aside_group_label(code)
        assert "_" not in label and label[0].isupper(), (code, label)


def test_restored_paper_returns_to_search(pipe, monkeypatch):
    import numpy as np

    _seed_corpus(pipe)
    monkeypatch.setattr(
        pipe.embedding_engine, "embed_query",
        lambda text: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )
    pipe.db.exclude_articles([("1", "pubmed")], reason="duplicate")
    assert {a["article_id"] for a in pipe.search_similar("q", top_k=10)} == {"2", "3"}

    keys = [(i["article_id"], i["source"]) for i in pipe.db.get_excluded_items("duplicate")]
    pipe.db.include_articles(keys)
    assert {a["article_id"] for a in pipe.search_similar("q", top_k=10)} == {"1", "2", "3"}


# --------------------------------------------------------------------- HTTP --

def _exclude(c, article_id, reason):
    r = c.post(
        "/api/screening",
        json={"items": [{"article_id": article_id, "source": "pubmed"}],
              "action": "exclude", "reason": reason},
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text


def test_api_lists_every_reason_grouped_and_restores_one(screening_app):
    c = _register_client(screening_app, "setaside1")
    _seed_user_library(screening_app, c, n=4, with_clusters=False)
    _exclude(c, "1", "duplicate")
    _exclude(c, "2", "off_topic")
    _exclude(c, "3", "low_relevance")

    body = c.get("/api/screening/excluded").json()
    assert body["reason"] == "all"
    assert body["count"] == 3
    items = {i["article_id"]: i for i in body["items"]}
    assert items["1"]["reason"] == "duplicate"
    assert items["1"]["label"] == "Duplicate copies"
    assert items["1"]["title"] == "Title 1"
    assert items["1"]["year"] == "2024"
    # Groups come in the order the student acted last, then the app's.
    assert [(g["reason"], g["count"]) for g in body["groups"]] == [
        ("off_topic", 1), ("low_relevance", 1), ("duplicate", 1),
    ]
    assert body["groups"][0]["label"] == "Marked not relevant"

    # Narrow it down's Undo still asks for one reason and gets only that.
    narrow = c.get("/api/screening/excluded?reason=low_relevance").json()
    assert narrow["reason"] == "low_relevance"
    assert [i["article_id"] for i in narrow["items"]] == ["3"]

    # Restore the duplicate copy: the thing no Simple screen could do before.
    r = c.post(
        "/api/screening",
        json={"items": [{"article_id": "1", "source": "pubmed"}], "action": "include"},
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    after = c.get("/api/screening/excluded").json()
    assert after["count"] == 2
    assert "1" not in {i["article_id"] for i in after["items"]}
    report = c.get("/api/screening-report?format=json").json()
    assert report["included"] == 2
    assert report["excluded"]["duplicate"] == 0


def test_api_excluded_list_requires_login(screening_app):
    bare = TestClient(screening_app.app)
    assert bare.get("/api/screening/excluded").status_code == 401


# ------------------------------------------------------------------- static --

def test_simple_has_the_set_aside_list_and_two_ways_in():
    card = _read("templates", "partials", "simple_screening_card.html")
    assert 'id="simple-set-aside-modal"' in card
    assert 'id="simple-set-aside-btn"' in card, "More menu entry"
    assert 'id="simple-set-aside-groups"' in card
    assert 'id="simple-set-aside-again"' in card, "one-click undo of a restore"
    assert "data-set-aside-close" in card
    panel = _read("templates", "partials", "simple_search_panel.html")
    assert 'id="funnel-set-aside-btn"' in panel, "the funnel's Removed count opens it"

    js = _read("static", "js", "simple_tools.js")
    # Wired with the dock (runs on load), not with the screening card, whose
    # wiring waits until the papers have embeddings.
    wiring = _between(js, "function wireSimpleToolsStrip", "\n}\n")
    assert "'simple-set-aside-btn')" in wiring and "'funnel-set-aside-btn')" in wiring
    assert "openSimpleSetAsideModal" in wiring
    assert "data-set-aside-close" in wiring
    assert "doSetAsideAgain" in wiring
    card_wiring = _between(js, "function wireSimpleScreeningCard", "\n}\n")
    assert "openSimpleSetAsideModal" not in card_wiring


def test_list_asks_for_every_reason_and_restores_through_screening_include():
    js = _read("static", "js", "simple_tools.js")
    load = _between(js, "async function loadSimpleSetAsideList", "\nfunction renderSimpleSetAsideGroups")
    assert "apiCall('/api/screening/excluded')" in load, "no reason filter: every group"
    assert "low_relevance" not in load

    restore = _between(js, "async function restoreSetAside", "\n/** One-click undo")
    assert "'/api/screening'" in restore
    assert "action: 'include'" in restore
    assert "clearSimpleScreenUndoItems()" in restore, "Narrow it down's cached Undo is stale after a restore"

    again = _between(js, "async function doSetAsideAgain", "\nlet _simpleScreenWired")
    assert "action: 'exclude', reason: last.reason" in again


def test_narrow_it_down_undo_and_start_over_still_touch_only_low_relevance():
    """Start over and Re-prepare must not bring back duplicates or Not relevant."""
    js = _read("static", "js", "simple_tools.js")
    for start, end in (
        ("async function fetchLowRelevanceUndoItems", "\n}\n"),
        ("async function doSimpleScreenUndo", "\n}\n"),
        ("async function resetSearchAndNarrowingForStartOver", "\n}\n"),
    ):
        fn = _between(js, start, end)
        assert "/api/screening/excluded?reason=low_relevance" in fn, start
    dm = _read("static", "js", "data_management.js")
    assert "/api/screening/excluded?reason=low_relevance" in dm
    assert "apiCall('/api/screening/excluded')" not in dm


def test_funnel_button_shows_only_when_something_is_removed():
    search = _read("static", "js", "search.js")
    fn = _between(search, "function fillSimpleRailStats", "\n}\n")
    assert "funnel-set-aside-btn" in fn
    assert "hidden = removed <= 0" in fn


def test_set_aside_styles_use_tokens_only():
    css = _read("static", "css", "style.css")
    block = _between(css, "/* Set aside list:", "\n@media")
    assert ".set-aside-groups" in block and ".set-aside-row" in block
    assert "#" not in block, "no literal colours"
    assert "px" not in block, "no literal lengths"
