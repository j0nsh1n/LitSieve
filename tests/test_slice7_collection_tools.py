"""Behavior checks for Slice 7 collection reporting and duplicate review."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "static" / "js" / "simple_collection_tools.js"
PARTIAL = ROOT / "templates" / "partials" / "duplicate_tools.html"


def _run_node(body: str) -> dict:
    if not shutil.which("node"):
        pytest.skip("Node.js not installed")
    script = f"""
import fs from 'node:fs';
import vm from 'node:vm';

class Element {{
 constructor(tag = 'div') {{
  this.tagName = tag.toUpperCase();
  this.children = [];
  this.parentNode = null;
  this.dataset = {{}};
  this.attributes = {{}};
  this.listeners = {{}};
  this.className = '';
  this.textContent = '';
  this.hidden = false;
  this.disabled = false;
  this.checked = false;
  this.value = '';
 }}
 appendChild(child) {{ child.parentNode = this; this.children.push(child); if (child.id) elements.set(child.id, child); return child; }}
 insertBefore(child, before) {{
  child.parentNode = this;
  if (child.id) elements.set(child.id, child);
  const index = this.children.indexOf(before);
  this.children.splice(index < 0 ? this.children.length : index, 0, child);
  return child;
 }}
 replaceChildren(...children) {{ this.children = []; children.forEach((child) => this.appendChild(child)); }}
 addEventListener(name, fn) {{ this.listeners[name] = fn; }}
 setAttribute(name, value) {{ this.attributes[name] = String(value); }}
 querySelector(selector) {{ return this.selectors && this.selectors[selector] || null; }}
 querySelectorAll(selector) {{
  if (selector === '[data-duplicate-candidate]:checked') {{
   return this.descendants().filter((node) => node.attributes['data-duplicate-candidate'] !== undefined && node.checked);
  }}
  return [];
 }}
 descendants() {{ return this.children.flatMap((child) => [child, ...child.descendants()]); }}
 click() {{ return !this.disabled && this.listeners.click && this.listeners.click({{ preventDefault() {{}} }}); }}
}}

const elements = new Map();
const card = new Element('div');
const actions = new Element('div');
actions.className = 'lra-modal-actions';
card.appendChild(actions);
card.selectors = {{ '.lra-modal-actions': actions }};
const root = new Element('div');
root.selectors = {{ '[data-site-modal-card]': card }};
const document = {{
 readyState: 'complete',
 createElement: (tag) => new Element(tag),
 getElementById: (id) => elements.get(id) || null,
 querySelector(selector) {{
  if (selector === '[data-set-aside-check-duplicates]') return elements.get('check');
  if (selector.startsWith('input[name="simple-duplicate-threshold"]')) return elements.get('radio');
  return null;
 }},
 querySelectorAll(selector) {{
  if (selector === '[data-duplicate-candidate]:checked') return elements.get('preview').querySelectorAll(selector);
  return [];
 }},
 addEventListener() {{}},
}};

for (const id of ['check', 'apply', 'undo', 'status', 'preview', 'report-status', 'report-refresh', 'report', 'radio']) {{
 elements.set(id, new Element(id));
}}
elements.set('simple-duplicate-apply', elements.get('apply'));
elements.set('simple-duplicate-undo', elements.get('undo'));
elements.set('simple-duplicate-status', elements.get('status'));
elements.set('simple-duplicate-preview', elements.get('preview'));
elements.get('check').dataset = {{}};
elements.get('apply').dataset = {{}};
elements.get('undo').dataset = {{}};
elements.get('radio').checked = true;
elements.get('radio').value = '0.98';

let activeLibrary = 'library-a';
const requests = [];
let resolvePreview = {{ groups: 1, excluded: 3, candidates: [
 {{ article_id: 'a', source: 'pubmed', title: '<script>loser</script>', year: '2024', abstract: 'A complete abstract.', keeper: {{ article_id: 'keep-a', source: 'pubmed', title: 'Kept copy' }} }},
 {{ article_id: 'b', source: 'arxiv', title: 'Already excluded', abstract: 'B abstract.', keeper: {{ title: 'Kept B' }} }},
 {{ article_id: 'c', source: 'doaj', title: 'Old duplicate', abstract: 'C abstract.', keeper: {{ title: 'Kept C' }} }},
] }};
let confirmResult = true;
let excludedAll = [
 {{ article_id: 'b', source: 'arxiv', reason: 'off_topic' }},
 {{ article_id: 'c', source: 'doaj', reason: 'duplicate' }},
];
let excludedDuplicates = [
 {{ article_id: 'a', source: 'pubmed', reason: 'duplicate' }},
 {{ article_id: 'c', source: 'doaj', reason: 'duplicate' }},
 {{ article_id: 'other', source: 'pubmed', reason: 'duplicate' }},
];
const sandbox = {{
 console,
 document,
 URLSearchParams,
 Set,
 _lastFetchSourceReportText: 'OpenAlex: timed out (2 papers)',
 selectedTopics: new Set(['health', 'biology']),
 pageLibraryId: () => activeLibrary,
 withPageLibrary: (body) => ({{ ...body, library_id: activeLibrary }}),
 getSourceName: (key) => key === 'xss' ? '<img src=x onerror=alert(1)>' : key.toUpperCase(),
 openSiteAlert(options) {{ options.onReady(root); return Promise.resolve(); }},
 openSiteConfirm: async () => confirmResult,
 loadSimpleSetAsideList: async () => {{}},
 refreshSimpleScreeningCard: async () => {{}},
 apiCall: async (path, options = {{}}) => {{
  requests.push({{ path, options }});
  if (path === '/api/statistics?library_id=library-a') return {{
   total_articles: 5, sources: {{ xss: 3, pubmed: 2 }}, year_counts: {{ '2020': 2, unknown: 1, '2024': 2 }},
  }};
  if (path === '/api/coverage') return {{
   articles_by_source: {{ pubmed: 2 }},
   suggestions: [{{ source: 'xss', name: '<img src=x onerror=alert(1)>', tip: 'Recommended for health' }}],
  }};
  if (path === '/api/resolve-duplicates') return resolvePreview;
  if (path.startsWith('/api/screening/excluded?') && path.includes('reason=all')) return {{ items: excludedAll }};
  if (path.startsWith('/api/screening/excluded?') && path.includes('reason=duplicate')) return {{ items: excludedDuplicates }};
  if (path === '/api/screening' && options.method === 'POST') return {{ count: options.body.items.length }};
  throw new Error(`unexpected request ${{path}}`);
 }},
}};

const source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
vm.runInNewContext(source, sandbox);
{body}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_report_refresh_renders_counts_coverage_and_partial_fetch_safely():
    out = _run_node(
        """
await sandbox.openCollectionReport();
await new Promise((resolve) => setImmediate(resolve));
await elements.get('simple-collection-report-refresh').click();
const report = elements.get('simple-what-we-fetched');
const text = (node) => [node.textContent, ...node.descendants().map((child) => child.textContent)].join(' ');
console.log(JSON.stringify({
 reportId: report.id,
 report: text(report),
 calls: requests.map((request) => ({ path: request.path, body: request.options.body })),
 topics: requests.find((request) => request.path === '/api/coverage').options.body.topics,
 scopedCoverage: requests.find((request) => request.path === '/api/coverage').options.body.library_id,
 refreshEnabled: elements.get('simple-collection-report-refresh').disabled === false,
 status: elements.get('simple-collection-report-status').textContent,
 unsafeHtmlAssignments: report.descendants().some((child) => child.innerHTML),
}));
"""
    )
    assert out["reportId"] == "simple-what-we-fetched"
    assert "PUBMED  2" in out["report"]
    assert "<img src=x onerror=alert(1)>  3" in out["report"]
    assert "2024  2" in out["report"] and "2020  2" in out["report"]
    assert "Year not listed  1" in out["report"]
    assert "Recommended for health" in out["report"]
    assert "OpenAlex: timed out (2 papers)" in out["report"]
    assert out["topics"] == ["health", "biology"]
    assert out["scopedCoverage"] == "library-a"
    assert sum(request["path"] == "/api/coverage" for request in out["calls"]) == 2
    assert all("fetch" not in request["path"] for request in out["calls"])
    assert out["refreshEnabled"] is True and out["status"] == ""
    assert out["unsafeHtmlAssignments"] is False


def test_coverage_error_keeps_counts_and_leaves_refresh_enabled():
    out = _run_node(
        """
const original = sandbox.apiCall;
sandbox.apiCall = async (path, options) => {
 if (path === '/api/coverage') throw new Error('coverage unavailable');
 return original(path, options);
};
await sandbox.openCollectionReport();
await new Promise((resolve) => setImmediate(resolve));
const report = elements.get('simple-what-we-fetched');
console.log(JSON.stringify({
 report: report.descendants().map((child) => child.textContent).join(' '),
 status: elements.get('simple-collection-report-status').textContent,
 refreshEnabled: elements.get('simple-collection-report-refresh').disabled === false,
}));
"""
    )
    assert "PUBMED  2" in out["report"]
    assert "coverage unavailable" in out["status"]
    assert out["refreshEnabled"] is True


def test_report_count_bars_use_each_series_max_and_keep_safe_labels():
    out = _run_node(
        """
const host = new Element('div');
sandbox.renderCollectionReportData(host, {
 total_articles: 22,
 sources: { pubmed: 2, arxiv: 10, xss: 3 },
 year_counts: { '2020': 2, unknown: 1, '2024': 4 },
}, { suggestions: [] });
const sections = host.children.filter((node) => node.tagName === 'SECTION');
const items = (section) => section.descendants().filter((node) => node.tagName === 'LI').map((item) => {
 const label = item.children.find((node) => node.tagName === 'SPAN');
 const bar = item.children.find((node) => node.tagName === 'PROGRESS');
 const count = item.children.filter((node) => node.tagName === 'SPAN').at(-1);
 return { label: label.textContent, count: count.textContent, max: bar.max, value: bar.value, aria: bar.attributes['aria-label'] };
});
console.log(JSON.stringify({ sources: items(sections[0]), years: items(sections[1]) }));
"""
    )
    source_bars = out["sources"]
    pubmed = next(row for row in source_bars if row["label"] == "PUBMED")
    assert (pubmed["max"], pubmed["value"], pubmed["count"]) == (10, 2, "2")
    assert all(row["max"] == 10 for row in source_bars)
    xss = next(row for row in source_bars if row["label"] == "<img src=x onerror=alert(1)>")
    assert xss["aria"] == "Papers: <img src=x onerror=alert(1)>"
    assert [row["label"] for row in out["years"]] == ["2024", "2020", "Year not listed"]
    assert all(row["max"] == 4 for row in out["years"])
    assert out["years"][-1]["value"] == 1


def test_duplicate_preview_is_read_only_then_apply_and_undo_exact_keys():
    out = _run_node(
        """
for (const threshold of [0.99, 0.98, 0.95]) {
 elements.get('radio').value = String(threshold);
 await elements.get('check').click();
}
const previewCalls = requests.filter((request) => request.path === '/api/resolve-duplicates');
const previewHasAll = elements.get('preview').children.length === 3;
const previewText = elements.get('preview').descendants().map((child) => child.textContent).join(' ');
confirmResult = false;
await elements.get('apply').click();
const postsAfterCancel = requests.filter((request) => request.path === '/api/screening');
confirmResult = true;
await elements.get('apply').click();
const applyPost = requests.find((request) => request.path === '/api/screening');
activeLibrary = 'library-b';
await elements.get('undo').click();
const postsAfterWrongLibraryUndo = requests.filter((request) => request.path === '/api/screening').length;
activeLibrary = 'library-a';
await elements.get('undo').click();
const posts = requests.filter((request) => request.path === '/api/screening');
console.log(JSON.stringify({
 thresholds: previewCalls.map((request) => request.options.body.threshold),
 previewsOnly: previewCalls.every((request) => request.options.body.preview === true),
 libraries: previewCalls.map((request) => request.options.body.library_id),
 previewHasAll, previewText,
 postsAfterCancel: postsAfterCancel.length,
 applyBody: applyPost && applyPost.options.body,
 postsAfterWrongLibraryUndo,
 undoBody: posts[1] && posts[1].options.body,
 finalStatus: elements.get('status').textContent,
}));
"""
    )
    assert out["thresholds"] == [0.99, 0.98, 0.95]
    assert out["previewsOnly"] is True
    assert out["libraries"] == ["library-a"] * 3
    assert out["previewHasAll"] is True
    assert "A complete abstract." in out["previewText"]
    assert out["postsAfterCancel"] == 0
    assert out["applyBody"] == {
        "items": [{"article_id": "a", "source": "pubmed"}],
        "action": "exclude",
        "reason": "duplicate",
        "library_id": "library-a",
    }
    assert out["postsAfterWrongLibraryUndo"] == 1
    assert out["undoBody"] == {
        "items": [{"article_id": "a", "source": "pubmed"}],
        "action": "include",
        "library_id": "library-a",
    }


def test_duplicate_error_clears_loading_and_keeps_retry_available():
    out = _run_node(
        """
sandbox.apiCall = async () => { throw new Error('temporary failure'); };
await elements.get('check').click();
console.log(JSON.stringify({
 disabled: elements.get('check').disabled,
 status: elements.get('status').textContent,
 errorClass: elements.get('status').className,
}));
"""
    )
    assert out["disabled"] is False
    assert out["status"] == "temporary failure"
    assert "is-error" in out["errorClass"]


def test_duplicate_partial_is_the_real_control_not_a_parity_marker():
    partial = PARTIAL.read_text(encoding="utf-8")
    assert 'data-set-aside-check-duplicates' in partial
    assert 'value="0.99"' in partial
    assert 'value="0.98" checked' in partial
    assert 'value="0.95"' in partial
