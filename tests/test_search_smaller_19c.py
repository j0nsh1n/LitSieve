"""Audit 19.15 and the Looks polish items."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _slice(source, start, end):
    i = source.index(start)
    return source[i:source.index(end, i + len(start))]


def test_source_chips_reload_when_new_papers_open_search():
    sync = _slice(_read("static", "js", "simple_tools.js"), "function syncSimpleOnePageState(", "\n}\n")
    assert "applyAvailableSources();" in sync
    assert "_sourcesLoadedForReady !== ready" in sync


def test_a_failed_look_save_shows_the_old_look_again():
    picker = _slice(_read("static", "js", "account.js"), "function wireLookPicker()", "async function loadLibraryManager()")
    assert "const previous = document.documentElement.getAttribute('data-look');" in picker
    assert "if (previous) paintLook(previous);" in picker


def test_reprepare_status_does_not_stay_on_preparing():
    rep = _slice(_read("static", "js", "simple_tools.js"), "async function simpleToolsReprepare()", "function _waitForEmbedJob(")
    assert "status.textContent = result ? 'Papers are ready for search.' : '';" in rep


def test_topic_area_cards_work_from_the_keyboard():
    grid = _slice(_read("static", "js", "collect.js"), "function renderTopicGrid()", "/* Areas: the topic comes first;")
    assert "card.setAttribute('role', 'button');" in grid
    assert "card.tabIndex = 0;" in grid
    assert "ev.key !== 'Enter' && ev.key !== ' '" in grid
    assert ".topic-card:focus-visible" in _read("static", "css", "style.css")


def test_no_escape_html_inside_a_quoted_attribute():
    for path in (ROOT / "static" / "js").glob("*.js"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            for m in re.finditer(r"\$\{escapeHtml\(", line):
                before = line[: m.start()]
                assert not re.search(r'=\s*"[^"]*$', before), f"{path.name}:{n}"


def test_one_reader_escape_listener_at_a_time():
    reader = _read("static", "js", "reader.js")
    assert "let clearActiveEscape = null;" in reader
    arm = _slice(reader, "const armEscape = () => {", "const scrollToAbstract")
    assert "if (clearActiveEscape) clearActiveEscape();" in arm


def test_public_copy_says_narrow_it_down():
    for rel in ("templates/landing.html", "app/content/feature_guides.py"):
        assert "quick screen" not in _read(*rel.split("/")).lower(), rel


def test_closed_rows_show_star_and_note_marks():
    search = _read("static", "js", "search.js")
    card = _slice(search, "function buildResultCard(", "function renderResults(")
    assert "resultMarksHtml(starred, !!String(noteVal).trim())" in card
    assert "starMark.hidden = !next;" in search
    assert "noteMark.hidden = !noteField.value.trim();" in search
    css = _read("static", "css", "style.css")
    assert ".result-row.is-open .result-marks { display: none; }" in css


def test_save_note_says_saved_only_after_the_request():
    search = _read("static", "js", "search.js")
    save = _slice(search, "const saveBtn = card.querySelector('.note-save');", "const notRelBtn")
    assert save.index("'Saving…'") < save.index("await apiCall('/api/notes'") < save.index("saveBtn.textContent = 'Saved';")


def test_more_like_this_brings_its_banner_into_view():
    seed = _slice(_read("static", "js", "search.js"), "async function doMoreLikeThisPaper(", "function setSearchRequestPending(")
    assert "banner.scrollIntoView({ block: 'start'" in seed


def test_skip_is_kept_once_the_library_id_is_known():
    skip = _slice(_read("static", "js", "simple_tools.js"), "function setSimpleScreenSkipped(", "\n}\n")
    assert "ensureActiveLibraryId().then(" in skip


def test_danger_buttons_use_a_dark_ink_on_the_light_dark_mode_red():
    css = _read("static", "css", "style.css")
    rule = _slice(css, ".btn-danger {", "}")
    assert "color: var(--on-err);" in rule
    assert css.count("--on-err: #241512;") == 2
