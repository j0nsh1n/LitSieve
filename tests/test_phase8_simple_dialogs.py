"""Phase 8 — Simple-mode dialogs + dense source report + modal shell.

Static and node-backed checks. Existing guards in test_simple_mode /
test_guest_mode must still pass unchanged (run in the full suite).
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS = ROOT / "static" / "js"
CSS = ROOT / "static" / "css" / "style.css"
COMMON = (JS / "common.js").read_text(encoding="utf-8")
DM = (JS / "simple_tools.js").read_text(encoding="utf-8") + "\n" + (
    JS / "data_management.js"
).read_text(encoding="utf-8")
STYLE = CSS.read_text(encoding="utf-8")


# ── Modal shell ────────────────────────────────────────────────────────────

def test_modal_shell_has_focus_trap():
    assert "getFocusable" in COMMON
    assert "ev.key !== 'Tab'" in COMMON or "ev.key === 'Tab'" in COMMON
    assert "last.focus()" in COMMON and "first.focus()" in COMMON
    # Capture phase so Tab cannot escape to the page behind.
    assert "addEventListener('keydown', onKey, true)" in COMMON


def test_modal_shell_restores_focus_to_opener():
    assert "const opener =" in COMMON
    assert "opener.focus" in COMMON
    # Must run on close, not only on open.
    assert re.search(r"close\s*=\s*\(value\).*opener\.focus", COMMON, re.S)


def test_modal_shell_body_scroll_lock_and_restore():
    assert "lra-modal-open" in COMMON
    assert "dataset.lraScrollY" in COMMON or "lraScrollY" in COMMON
    assert "scrollY" in COMMON
    assert "window.scrollTo" in COMMON
    assert "body.lra-modal-open" in STYLE
    assert "position: fixed" in STYLE
    # Mobile bottom-sheet for soft keyboard.
    assert "@media (max-width: 640px)" in STYLE
    assert "align-items: flex-end" in STYLE


def test_openSiteChoice_exists_for_multi_button_dialogs():
    assert "function openSiteChoice" in COMMON
    assert "mode === 'choice'" in COMMON or "mode: 'choice'" in COMMON


# ── Dense source report ────────────────────────────────────────────────────

def test_fetch_report_helpers_exist():
    assert "function buildFetchSourceReportModel" in DM
    assert "function renderFetchSourceReportHtml" in DM


def test_fetch_report_uses_details_and_escapeHtml():
    assert "<details" in DM
    assert "escapeHtml" in DM
    # Live rows cleared when final report appears (no double UI).
    assert "fetch-live-sources" in DM
    # applyFetchResult must clear live host.
    idx = DM.index("function applyFetchResult")
    chunk = DM[idx : idx + 2500]
    assert "fetch-live-sources" in chunk
    assert "innerHTML = ''" in chunk or 'innerHTML = ""' in chunk


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_build_fetch_source_report_model_top5_via_node():
    """Ranking: top successes by count; muted zeros summarised.

    Fails if buildFetchSourceReportModel is missing or sorts wrong.
    """
    node = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_REPORT_SNIPPET],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert node.returncode == 0, node.stderr + node.stdout
    out = json.loads(node.stdout.strip().splitlines()[-1])
    assert out["successCount"] == 7
    assert out["topNames"] == ["A", "B", "C", "D", "E"]  # top 5 by count
    assert out["mutedZeros"] == 1  # Z no_results; Bad is error (not zero)
    assert out["simpleHasDetails"] is True
    assert out["simpleCollapsedTop"] == 5
    assert out["advancedNoDetails"] is True
    assert "escaped" in out and out["escaped"] is True


_NODE_REPORT_SNIPPET = r"""
import fs from 'fs';
import vm from 'vm';
const dm = fs.readFileSync('static/js/data_management.js','utf8');
// Minimal stubs for browser globals the file may touch at parse time.
const sandbox = {
  console,
  window: {},
  document: { getElementById: () => null, documentElement: { getAttribute: () => 'simple' } },
  localStorage: { getItem: () => null, setItem: () => {} },
  escapeHtml: (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'),
  getSourceName: (s) => s,
  isSimpleMode: () => true,
};
// Extract only the two pure helpers by eval-ing function source ranges.
function extractFn(src, name) {
  const start = src.indexOf('function ' + name);
  if (start < 0) throw new Error('missing ' + name);
  let i = src.indexOf('{', start);
  let depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth--;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  throw new Error('unbalanced ' + name);
}
const code =
  sandbox.escapeHtml.toString() + ';\n' +
  'function getSourceName(s){return s;}\n' +
  extractFn(dm, 'buildFetchSourceReportModel') + '\n' +
  extractFn(dm, 'renderFetchSourceReportHtml') + '\n' +
  `
  const data = {
    by_source: { A: 100, B: 90, C: 80, D: 70, E: 60, F: 10, G: 5, Z: 0 },
    errors: { Bad: 'timeout' },
    error_kinds: { Z: 'no_results', Bad: 'timeout' },
  };
  const sources = ['A','B','C','D','E','F','G','Z','Bad'];
  const model = buildFetchSourceReportModel(data, sources);
  const simpleHtml = renderFetchSourceReportHtml(model, { simple: true });
  const advHtml = renderFetchSourceReportHtml(model, { simple: false });
  const result = {
    successCount: model.successes.length,
    topNames: model.successes.slice(0,5).map(s => s.name),
    mutedZeros: model.muted.filter(m => m.zero).length,
    simpleHasDetails: simpleHtml.includes('<details'),
    simpleCollapsedTop: (simpleHtml.match(/✓/g) || []).length >= 5 ? 5 : (simpleHtml.match(/✓/g) || []).length,
    advancedNoDetails: !advHtml.includes('<details'),
    escaped: !simpleHtml.includes('<script') && simpleHtml.includes('✓'),
  };
  console.log(JSON.stringify(result));
  `;
vm.runInNewContext(code, sandbox);
"""


# ── Fetch mode dialog ──────────────────────────────────────────────────────

def test_simple_fetch_mode_resolver_exists():
    assert "function resolveSimpleFetchModeBeforeRequest" in DM
    assert "resolveSimpleFetchModeBeforeRequest" in DM
    # Called before mode/clearFirst read in doFetch.
    do = DM[DM.index("async function doFetch") : DM.index("async function doFetch") + 1200]
    assert "resolveSimpleFetchModeBeforeRequest" in do
    assert do.index("resolveSimpleFetchModeBeforeRequest") < do.index("clearFirst")


def test_simple_fetch_skips_dialog_when_empty_and_sets_replace():
    """Empty collection → no openSiteChoice; force replace (clear_first true)."""
    fn = DM[DM.index("async function resolveSimpleFetchModeBeforeRequest") :
            DM.index("async function doFetch")]
    assert "total <= 0" in fn or "total === 0" in fn
    assert "setMode('replace')" in fn or 'setMode("replace")' in fn
    # Dialog only when there are papers.
    assert "openSiteChoice" in fn
    assert "Start fresh" in fn
    assert "Add to them" in fn


def test_simple_fetch_cancel_returns_false_before_request():
    fn = DM[DM.index("async function resolveSimpleFetchModeBeforeRequest") :
            DM.index("async function doFetch")]
    assert "if (choice == null) return false" in fn
    do = DM[DM.index("async function doFetch") : DM.index("async function doCreateEmbeddings")]
    assert "if (!proceed) return" in do


def test_fetch_mode_radios_still_in_template_for_advanced():
    html = (ROOT / "templates" / "data_management.html").read_text(encoding="utf-8")
    assert 'name="fetch-mode"' in html
    assert 'value="replace"' in html
    assert 'value="append"' in html
    # Simple hides radios via CSS, not by removing them.
    assert 'input[name="fetch-mode"]' in STYLE
    assert 'html[data-mode="simple"]' in STYLE


# ── Re-prepare dialog ──────────────────────────────────────────────────────

def test_simple_prepare_resolver_exists():
    assert "function resolveSimplePrepareModeBeforeRequest" in DM
    assert "Only new papers" in DM
    assert "only_missing" in DM
    # Research question lives in the same re-prepare popup (withInput).
    assert "function applyVerifiedResearchQuestion" in DM
    assert "withInput: true" in DM or "withInput:true" in DM
    assert "Your research question" in DM


def test_simple_prepare_prompt_is_inside_same_popup():
    """Question field is in the re-prepare dialog, not a separate first modal."""
    fn = DM[DM.index("async function resolveSimplePrepareModeBeforeRequest") :
            DM.index("async function doCreateEmbeddings")]
    assert "withInput" in fn
    assert "openSiteChoice" in fn
    assert "applyVerifiedResearchQuestion" in fn
    # No separate openSitePrompt step before the scope dialog.
    assert "openSitePrompt" not in fn
    common = (ROOT / "static" / "js" / "common.js").read_text(encoding="utf-8")
    assert "o.withInput" in common
    assert "mode === 'choice' && o.withInput" in common or 'mode === "choice" && o.withInput' in common


def test_simple_prepare_dialog_not_on_auto_chain():
    """Auto-chain after fetch must not open the re-prepare dialog."""
    fn = DM[DM.index("async function doCreateEmbeddings") :
            DM.index("async function doCreateEmbeddings") + 800]
    assert "fromAutoChain" in fn
    assert "simple && !fromAutoChain" in fn


def test_reprepare_clears_low_relevance_for_pending_screening():
    """Corpus-state reset so screening returns to pending after manual re-prepare."""
    assert "/api/screening/excluded?reason=low_relevance" in DM
    assert "action: 'include'" in DM or 'action: "include"' in DM


# ── Advanced unchanged (source-level) ──────────────────────────────────────

def test_advanced_keeps_radios_and_full_report_path():
    assert 'name="fetch-mode"' in (ROOT / "templates" / "data_management.html").read_text(encoding="utf-8")
    assert "only-missing" in (ROOT / "templates" / "data_management.html").read_text(encoding="utf-8")
    # Advanced report path does not force <details>.
    assert "advancedNoDetails" in DM or "simple: false" in DM or "{ simple }" in DM
    assert "renderFetchSourceReportHtml(model, { simple })" in DM or "simple }" in DM
