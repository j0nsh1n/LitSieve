"""UI hook contracts for Reader Mode (string-level, no browser)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_reader_button_lives_in_shared_ai_actions():
    js = (ROOT / "static" / "js" / "common.js").read_text(encoding="utf-8")
    start = js.index("function renderKeyPointsHtml")
    chunk = js[start:start + 2500]
    assert "reader-mode-btn" in chunk
    assert "ai-actions" in chunk
    assert "show_ai_buttons" in chunk
    assert "Explain this study" in chunk


def test_reader_js_loaded_in_both_modes():
    search = (ROOT / "templates" / "search.html").read_text(encoding="utf-8")
    clusters = (ROOT / "templates" / "clusters.html").read_text(encoding="utf-8")
    assert "reader.js?v=" in search
    assert "reader.js?v=" in clusters


def test_reader_js_avoids_overclaim_words():
    js = (ROOT / "static" / "js" / "reader.js").read_text(encoding="utf-8")
    low = js.lower()
    for banned in ("clinically verified", "medically accurate", "guaranteed"):
        assert banned not in low
    assert "verified_no_automatic_issues" not in js
    assert "Automatic checks found no obvious issues" in js
