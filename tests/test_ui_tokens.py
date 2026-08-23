"""Phase 7 design-system tokens, scale discipline, and fetch-progress narrative.

Locks the type / spacing / radius scales in style.css so hand-tuned values
cannot silently multiply again. Also covers the live per-source progress
fields on the server (by_source / source_status) — client string greps alone
are not enough. Simple/guest guards remain the proof of presentation-only flow.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CSS = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")


# Documented in docs/UI_REFRESH_PLAN.md Part 1.
REQUIRED_TOKENS = (
    # type
    "--fs-xs",
    "--fs-sm",
    "--fs-base",
    "--fs-md",
    "--fs-lg",
    "--fs-xl",
    "--fs-2xl",
    "--fs-3xl",
    # line-height + measure
    "--lh-tight",
    "--lh-snug",
    "--lh-normal",
    "--lh-relaxed",
    "--measure",
    # spacing
    "--space-1",
    "--space-2",
    "--space-3",
    "--space-4",
    "--space-5",
    "--space-6",
    "--space-7",
    "--space-8",
    # radii
    "--radius-sm",
    "--radius-md",
    "--radius-full",
    # preserved colour/motion (must still exist)
    "--accent",
    "--text-body",
    "--elev-1",
    "--dur-fast",
    "--ease-soft",
    "--focus-ring",
)


def _root_block() -> str:
    """First :root { ... } block (token home)."""
    m = re.search(r":root\s*\{", CSS)
    assert m, ":root block missing"
    start = m.end()
    depth = 1
    i = start
    while i < len(CSS) and depth:
        if CSS[i] == "{":
            depth += 1
        elif CSS[i] == "}":
            depth -= 1
        i += 1
    return CSS[start : i - 1]


def test_root_defines_documented_scale_tokens():
    root = _root_block()
    missing = [t for t in REQUIRED_TOKENS if t not in root]
    assert not missing, f"missing from :root: {missing}"


def test_spacing_utilities_use_space_tokens():
    """Class names stay; values must come from the spacing scale."""
    for cls in (".u-mt-sm", ".u-mt-md", ".u-mt-lg", ".u-mt-xl", ".u-mt-form"):
        m = re.search(rf"{re.escape(cls)}\s*\{{[^}}]*margin-top\s*:\s*([^;]+);", CSS)
        assert m, f"{cls} missing"
        assert "var(--space-" in m.group(1), f"{cls} not on spacing scale: {m.group(1)}"


def test_preserved_colour_motion_tokens_still_present():
    """Phase 7 adds alongside existing tokens — never rename/remove them."""
    for t in ("--accent", "--text-body", "--elev-1", "--dur-fast", "--ease-soft", "--focus-ring"):
        assert t in CSS, t


def _css_without_comments() -> str:
    return re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)


def _decl_values(prop: str) -> list[str]:
    """Property values for `prop:`; skip @supports (padding: …) false matches."""
    out = []
    for m in re.finditer(rf"(?<![\w-]){re.escape(prop)}\s*:\s*([^;]+);", _css_without_comments()):
        v = m.group(1).strip()
        if "{" in v or "}" in v:
            continue
        out.append(v)
    return out


def _literal_lengths(value: str) -> list[str]:
    """rem/px/em lengths that are not already inside var(...)."""
    # Strip var(...) so we do not count token definitions' resolved forms in use sites.
    stripped = re.sub(r"var\([^)]*\)", "", value)
    return re.findall(r"[0-9.]+(?:rem|px|em)\b", stripped)


def test_font_size_scale_discipline():
    """At most 8 type steps — only --fs-* tokens (plus 0)."""
    allowed_vars = {
        "--fs-xs",
        "--fs-sm",
        "--fs-base",
        "--fs-md",
        "--fs-lg",
        "--fs-xl",
        "--fs-2xl",
        "--fs-3xl",
    }
    used = set()
    for v in _decl_values("font-size"):
        v_clean = v.replace("!important", "").strip()
        if v_clean in ("0", "inherit", "smaller", "larger"):
            continue
        lits = _literal_lengths(v_clean)
        assert not lits, f"literal font-size {v_clean!r}"
        for tok in re.findall(r"var\((--fs-[\w]+)\)", v_clean):
            used.add(tok)
            assert tok in allowed_vars, tok
    assert len(used) <= 8, f"too many type tokens in use: {sorted(used)}"
    assert used, "no --fs-* font-size usage found"


def test_border_radius_scale_discipline():
    """At most 4 radius steps — only --radius-* tokens (plus 0).

    Teal Soft adds --radius-lg (18px cards) on top of sm/md/full.
    """
    allowed = {"--radius-sm", "--radius-md", "--radius-lg", "--radius-full"}
    used = set()
    for v in _decl_values("border-radius"):
        v_clean = v.replace("!important", "").strip()
        lits = _literal_lengths(v_clean)
        # 0 is fine; no raw 8px/12px/18px etc.
        assert not lits, f"literal border-radius {v_clean!r}"
        for tok in re.findall(r"var\((--radius-[\w]+)\)", v_clean):
            used.add(tok)
            assert tok in allowed, tok
    assert len(used) <= 4, sorted(used)
    assert used


def test_teal_soft_radius_tokens():
    """Teal Soft: --radius-sm/md/lg are 8/12/18px (was quad-notice 6/10).

    --radius-lg is now a real token (cards, dialogs, rails), not a fallback.
    """
    root = _root_block()
    for name, want in (("--radius-sm", "8px"), ("--radius-md", "12px"), ("--radius-lg", "18px")):
        m = re.search(rf"{name}\s*:\s*([^;]+);", root)
        assert m, f"missing {name} in :root"
        assert m.group(1).strip() == want, f"{name}={m.group(1)!r}, want {want}"
    # No bare fallbacks left now that --radius-lg is defined.
    assert "var(--radius-lg, " not in _css_without_comments()


def test_padding_uses_spacing_scale_only():
    """Padding lengths come from --space-* (or 0 / env / max / calc of those)."""
    for prop in (
        "padding",
        "padding-top",
        "padding-right",
        "padding-bottom",
        "padding-left",
    ):
        for v in _decl_values(prop):
            lits = _literal_lengths(v)
            assert not lits, f"{prop}: literal length(s) {lits} in {v!r}"


def test_fetch_live_sources_markup_and_renderer():
    """Waiting state: live per-source list is reserved and rendered from API data."""
    dm_html = (REPO / "templates" / "partials" / "collect_ui.html").read_text(encoding="utf-8")
    assert 'id="fetch-live-sources"' in dm_html
    dm_js = (REPO / "static" / "js" / "data_management.js").read_text(encoding="utf-8")
    assert "function renderFetchLiveSources" in dm_js
    assert "by_source" in dm_js
    assert "source_status" in dm_js
    # Must not invent progress — only fields from the progress payload.
    assert "searching…" in dm_js or "searching..." in dm_js
    css = CSS
    assert ".fetch-live-sources" in css
    assert ".skeleton-card" in css
    assert "shimmer" in css


def test_search_optimistic_star_and_skeletons():
    search = (REPO / "static" / "js" / "search.js").read_text(encoding="utf-8")
    assert "function showResultSkeletons" in search
    assert "showResultSkeletons" in search
    # Failed search must clear skeletons (not leave infinite loading rows).
    assert "function clearResultSkeletonsOnError" in search
    assert "clearResultSkeletonsOnError" in search
    # Not-relevant undo strip is tracked per row; Undo disabled while exclude pending.
    assert "return strip" in search
    not_rel = search[
        search.find("notRelBtn.addEventListener") : search.find(
            "function replaceCardWithUndo"
        )
    ]
    assert "const strip = replaceCardWithUndo" in not_rel
    assert "querySelector('.not-relevant-undo.is-pending')" not in not_rel
    assert "undoBtn.disabled = false" in not_rel or "undoBtn.disabled=false" in not_rel
    # Optimistic star flips UI before await (note-save appears earlier in the file).
    start = search.find("starBtn.addEventListener")
    assert start != -1
    star_block = search[start : start + 600]
    assert "classList.toggle('is-starred'" in star_block
    assert star_block.find("classList.toggle") < star_block.find("await apiCall")


def test_mobile_380_has_overflow_guard_and_tap_targets():
    """380px treatment is a real layout: no horizontal scroll intent, 44px taps."""
    css = CSS
    block = css[css.find("@media (max-width: 380px)") :]
    assert "overflow-x: hidden" in block or "overflow-x:hidden" in block
    assert "min-height: 2.75rem" in CSS  # 44px-class targets used on small screens
    assert "flex-direction: column" in block  # form-row stacks
    # Library switcher stays reachable (do not hide the wrap).
    assert ".nav-library-wrap { display: none" not in block
    assert ".nav-library-wrap { display: none; }" not in block


def test_simple_results_clear_the_fixed_export_bar():
    """Results padding tracks the measured bar, with 40vh as fallback."""
    css = CSS
    assert "--simple-panel-h" in css
    assert "40vh" in css
    search = (REPO / "static" / "js" / "search.js").read_text(encoding="utf-8")
    assert "function syncSimplePanelClearance" in search
    assert "ResizeObserver" in search
    assert "--simple-panel-h" in search


def test_notifications_stack_above_site_modals():
    css = CSS
    # Modal root is 1200; toasts must sit above a full-viewport bottom sheet.
    assert "z-index: 1300" in css or "z-index:1300" in css
    modal = css[css.find(".lra-modal-root") : css.find(".lra-modal-root") + 400]
    assert "1200" in modal


def test_prefers_reduced_motion_covers_shimmer():
    """One reduce block must kill infinite shimmer (progress + skeletons)."""
    css = CSS
    assert css.count("@media (prefers-reduced-motion: reduce)") >= 1
    # Skeleton shimmer is the Phase 7 loading animation.
    assert "shimmer" in css
    reduce_blocks = re.split(r"@media \(prefers-reduced-motion: reduce\)", css)[1:]
    joined = "\n".join(reduce_blocks)
    assert "skeleton" in joined.lower() or "animation: none" in joined
    assert "animation-duration: 0.01ms" in joined or "animation-duration:0.01ms" in joined


# --- Server-side progress narrative (Phase 7 waiting states) -----------------
# These fail if sources/by_source/source_status are dropped from the progress
# slot. Client-side string greps alone do not prove the server publishes them.


def test_fresh_progress_slot_declares_fetch_narrative_fields():
    """A new progress slot must declare empty sources / by_source / source_status."""
    from app import core

    uid = "test-progress-fresh-uid"
    with core._progress_lock:
        core._all_progress.pop(uid, None)
    try:
        with core._progress_lock:
            fetch = core._ensure_progress(uid)["fetch"]
            assert "sources" in fetch
            assert "by_source" in fetch
            assert "source_status" in fetch
            assert fetch["sources"] == []
            assert fetch["by_source"] == {}
            assert fetch["source_status"] == {}
    finally:
        with core._progress_lock:
            core._all_progress.pop(uid, None)


def test_progress_backfills_narrative_fields_without_clobbering():
    """Pre-Phase-7 in-flight slots get empty narrative keys; done/total stay put."""
    from app import core

    uid = "test-progress-backfill-uid"
    with core._progress_lock:
        core._all_progress.pop(uid, None)
        # Shape that existed before the live narrative fields were added.
        core._all_progress[uid] = {
            "fetch": {"active": True, "done": 1, "total": 3},
            "embed": {
                "active": False,
                "done": 0,
                "total": 0,
                "result": None,
                "error": None,
                "cancel": False,
                "articles_so_far": 0,
                "message": "",
            },
        }
    try:
        with core._progress_lock:
            fetch = core._ensure_progress(uid)["fetch"]
            assert fetch["active"] is True
            assert fetch["done"] == 1
            assert fetch["total"] == 3
            assert fetch["sources"] == []
            assert fetch["by_source"] == {}
            assert fetch["source_status"] == {}
    finally:
        with core._progress_lock:
            core._all_progress.pop(uid, None)


def test_run_multi_fetch_publishes_per_source_counts_including_failures(monkeypatch):
    """Progress must record every source, including rate-limited failures (muted UI)."""
    from app import core
    from app.routes import corpus as corpus_routes

    uid = "test-progress-live-uid"
    with core._progress_lock:
        core._all_progress.pop(uid, None)

    monkeypatch.setattr(corpus_routes.quota, "is_over_quota", lambda _uid, **_k: False)
    monkeypatch.setattr(
        corpus_routes.quota,
        "usage_report",
        lambda _uid: {
            "used_mb": 0.0,
            "limit_mb": 0,
            "percent": 0.0,
            "over_limit": False,
        },
    )

    class _DB:
        def clear_all(self):
            return None

    class _Pipe:
        def __init__(self):
            self.db = _DB()

        def invalidate_corpus_cache(self):
            return None

        def fetch_articles_parallel(
            self,
            *,
            query,
            sources,
            max_results,
            email,
            progress_callback,
            cancel_check,
            into_staging=False,
        ):
            # Match real pipeline callback shape (done, total, **extra).
            steps = [
                ("pubmed", 142, None),
                ("europepmc", 89, None),
                ("semanticscholar", 0, "rate_limited"),
            ]
            arts = 0
            out = {}
            for i, (src, count, kind) in enumerate(steps, 1):
                arts += count
                progress_callback(
                    i,
                    len(sources),
                    articles_so_far=arts,
                    source=src,
                    source_count=count,
                    error_kind=kind,
                )
                out[src] = {
                    "count": count,
                    "error": "rate limited" if kind == "rate_limited" else None,
                    "error_kind": kind,
                }
            return out

    try:
        corpus_routes._run_multi_fetch(
            _Pipe(),
            query="climate",
            sources=["pubmed", "europepmc", "semanticscholar"],
            max_results=100,
            email=None,
            clear_first=False,
            uid=uid,
        )
        with core._progress_lock:
            fetch = core._all_progress[uid]["fetch"]
            assert fetch["by_source"] == {
                "pubmed": 142,
                "europepmc": 89,
                "semanticscholar": 0,
            }
            assert fetch["source_status"]["semanticscholar"] == "rate_limited"
            assert fetch["source_status"]["pubmed"] == "ok"
            assert fetch["source_status"]["europepmc"] == "ok"
            # Failing source must be present for the muted narrative row.
            assert "semanticscholar" in fetch["by_source"]
            assert fetch["sources"] == ["pubmed", "europepmc", "semanticscholar"]
    finally:
        with core._progress_lock:
            core._all_progress.pop(uid, None)


def test_phase8_info_text_is_body_scale():
    """Phase 8 C-borrowing: explanatory copy is body size, not fine print."""
    css = CSS
    # .info-text block must set --fs-base (not only --fs-sm).
    m = re.search(r"\.info-text\s*\{[^}]+\}", css)
    assert m, ".info-text rule missing"
    block = m.group(0)
    assert "var(--fs-base)" in block, block
    m2 = re.search(r"\.help-text\s*\{[^}]+\}", css)
    assert m2, ".help-text rule missing"
    assert "var(--fs-sm)" in m2.group(0)
    # Dark grounds are Teal Soft (was newsprint #1c1a15 / #242118).
    assert "--bg: #0d1012" in css or "--bg:#0d1012" in css
    assert "--surface: #161a1d" in css or "--surface:#161a1d" in css


def _css_block_tokens(block: str) -> dict[str, str]:
    """`--name: value` declarations inside one CSS rule body."""
    return {
        m.group(1): re.sub(r"\s+", " ", m.group(2)).strip()
        for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block)
    }


def test_phase10_dark_blocks_stay_in_parity():
    """Phase 10: prefers-color-scheme dark and [data-theme=dark] must match.

    These two blocks have drifted before. Every token they both define must
    have the same value so system-dark and toggled-dark stay identical.
    """
    css = CSS
    pref = re.search(
        r"@media\s*\(\s*prefers-color-scheme\s*:\s*dark\s*\)\s*\{"
        r"\s*:root:not\(\[data-theme=\"light\"\]\)\s*\{([^}]+)\}",
        css,
    )
    explicit = re.search(r"\[data-theme=\"dark\"\]\s*\{([^}]+)\}", css)
    assert pref, "prefers-color-scheme dark block missing"
    assert explicit, "[data-theme=dark] block missing"
    a = _css_block_tokens(pref.group(1))
    b = _css_block_tokens(explicit.group(1))
    assert a, "no tokens in prefers-color-scheme dark"
    assert b, "no tokens in [data-theme=dark]"
    shared = set(a) & set(b)
    assert shared, "dark blocks share no tokens"
    drifted = {k: (a[k], b[k]) for k in sorted(shared) if a[k] != b[k]}
    assert not drifted, f"dark blocks drifted: {drifted}"
    # Teal Soft dark grounds (both blocks).
    for tokens in (a, b):
        assert tokens.get("--bg") == "#0d1012"
        assert tokens.get("--surface") == "#161a1d"
        assert tokens.get("--text") == "#e9eef0"
        assert tokens.get("--text-soft") == "#98a3aa"
        assert tokens.get("--rule") == "#232a2e"
        assert tokens.get("--accent") == "#5eead4"
        assert tokens.get("--ok") == "#6ee7a8"
        assert tokens.get("--on-accent") == "#062421"


def test_teal_soft_light_tokens():
    """Live accent is Teal Soft; success green must not collide with it."""
    root = _root_block()
    tokens = _css_block_tokens(root)
    assert tokens.get("--bg") == "#f7f8f8"
    assert tokens.get("--surface") == "#ffffff"
    assert tokens.get("--accent") == "#0f766e"
    assert tokens.get("--accent-hover") == "#0b5c56"
    assert tokens.get("--ok") == "#15803d"
    assert tokens.get("--ok") != tokens.get("--accent")
    assert tokens.get("--on-accent") == "#fff"
    # Amber was #a8700f = 4.21:1 on white, under AA. Darkened for contrast.
    assert tokens.get("--warn") == "#96640c"
    assert "Public Sans" in tokens.get("--font-sans", "")
    assert "var(--font-sans)" in tokens.get("--font-serif", "")


def test_public_sans_is_self_hosted():
    """CSP is font-src 'self' — no Google Fonts CDN. Titles share Public Sans."""
    css = CSS
    assert "/static/fonts/public-sans-latin.woff2" in css
    assert "fraunces" not in css.lower()
    assert "fonts.googleapis.com" not in css
    assert "fonts.gstatic.com" not in css
    fonts = REPO / "static" / "fonts"
    assert (fonts / "public-sans-latin.woff2").is_file()
    assert not (fonts / "fraunces-latin.woff2").exists()


def test_body_background_is_flat():
    """No paper grain or radial wash on the page canvas."""
    assert "feTurbulence" not in CSS
    body = CSS[CSS.find("\nbody {") : CSS.find("\n::selection")]
    assert "background-image" not in body
    assert "background: var(--bg)" in body


def test_phase8_search_workbench_and_score_meter():
    """Query rail + numeric score meter are presentation contracts."""
    search_html = (REPO / "templates" / "search.html").read_text(encoding="utf-8")
    assert "search-workbench" in search_html
    assert "search-rail" in search_html
    assert 'id="page-help"' in search_html
    # Save-your-work panel sits in the rail (pinned under scroll) so Results is full width.
    rail = search_html[search_html.find("search-rail") : search_html.find("search-main")]
    main = search_html[search_html.find("search-main") :]
    assert "search-rail-scroll" in rail
    assert "simple_search_panel" in rail
    assert "simple_search_panel" not in main
    # Panel must be outside the scroll region so it cannot scroll away.
    scroll_end = rail.find("/.search-rail-scroll")
    panel_at = rail.find("simple_search_panel")
    assert scroll_end != -1 and panel_at > scroll_end
    js = (REPO / "static" / "js" / "search.js").read_text(encoding="utf-8")
    assert "score-meter" in js
    assert "score-meter-fill" in js
    assert "--score-pct" in js
    assert "result-row" in js
    # Hover title defines the 0–1 similarity score for users.
    assert "scoreHelp" in js
    assert "Similarity score (0–1)" in js
    # Low/Medium/High tier labels no longer drive the result chrome.
    assert "simTier" not in js
    css = CSS
    assert ".search-workbench" in css
    assert ".score-meter-fill" in css
    assert "var(--score-pct" in css
    assert "cursor: help" in css


def test_phase8_page_help_on_app_shell_pages():
    """Help is one summonable panel on Search, DM, Clean up, Clusters, Account."""
    common = (REPO / "static" / "js" / "common.js").read_text(encoding="utf-8")
    assert "function initPageHelp" in common
    for name in (
        "search.html",
        "data_management.html",
        "statistics.html",
        "clusters.html",
        "account.html",
    ):
        html = (REPO / "templates" / name).read_text(encoding="utf-8")
        assert 'id="page-help-toggle"' in html, name
        assert 'id="page-help"' in html, name
        assert "page-help-body" in html, name


def test_phase8_workbench_shell_splits_workflow_and_tools():
    """Direction B: shell-primary (steps) vs shell-tools (utilities)."""
    base = (REPO / "templates" / "base.html").read_text(encoding="utf-8")
    assert "app-shell" in base
    assert "shell-primary" in base
    assert "shell-tools" in base
    assert 'id="nav-links-panel"' in base
    assert 'id="mode-toggle"' in base
    # Workflow still lives under primary; tools under shell-tools.
    primary = base[base.find("shell-primary") : base.find("shell-tools")]
    tools = base[base.find("shell-tools") :]
    assert "nav-links-panel" in primary
    assert "mode-toggle" in tools
    assert "nav-library-select" in tools
    css = CSS
    assert ".shell-primary" in css
    assert ".shell-tools" in css
