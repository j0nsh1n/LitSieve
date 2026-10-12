"""Behavior checks for source-level fetch progress and timeout reports."""

import json
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_fetch_source_states_and_timeouts_via_node():
    node = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_PROGRESS_SNIPPET],
        cwd=".",
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert node.returncode == 0, node.stderr + node.stdout
    out = json.loads(node.stdout.strip().splitlines()[-1])
    assert out["live"] == [
        "queued",
        "waiting on openaire (62s)",
        "7 papers",
        "timed out (1 paper)",
    ]
    assert out["reportTimeouts"] == 1
    assert out["reportErrors"] == 1
    assert "timed out (1 paper)" in out["report"]
    assert "1 papers" not in " ".join(out["live"]) + out["report"]
    assert "✗ Bad [rate_limited]: temporary failure" in out["report"]
    assert "1 timed out" in out["report"]
    assert "1 with an error" in out["report"]


_NODE_PROGRESS_SNIPPET = r"""
import fs from 'fs';
import vm from 'vm';
const dm = fs.readFileSync('static/js/collect.js', 'utf8');
const host = { innerHTML: '' };
const sandbox = {
  console,
  window: {},
  document: { getElementById: (id) => id === 'fetch-live-sources' ? host : null },
  escapeHtml: (value) => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  getSourceName: (source) => source,
};
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
const code = [
  'const console = sandbox.console;',
  'const document = sandbox.document;',
  'const getSourceName = sandbox.getSourceName;',
  'const escapeHtml = sandbox.escapeHtml;',
  extractFn(dm, 'renderFetchLiveSources'),
  extractFn(dm, 'buildFetchSourceReportModel'),
  extractFn(dm, 'renderFetchSourceReportHtml'),
  `
    renderFetchLiveSources({
      sources: ['queued', 'openaire', 'pubmed', 'timeout'],
      by_source: { pubmed: 7, timeout: 1 },
      source_status: { pubmed: 'ok', timeout: 'timeout' },
      source_progress: {
        queued: { state: 'queued', elapsed_seconds: 0 },
        openaire: { state: 'running', elapsed_seconds: 62 },
        pubmed: { state: 'done', elapsed_seconds: 1 },
        timeout: { state: 'done', elapsed_seconds: 60, error_kind: 'timeout' },
      },
    });
    const live = [...host.innerHTML.matchAll(/<span class="fetch-live-detail">(.*?)<\\/span>/g)].map((m) => m[1]);
    const data = {
      by_source: { pubmed: 7, timeout: 1 },
      errors: { timeout: 'deadline exceeded', Bad: 'temporary failure' },
      error_kinds: { timeout: 'timeout', Bad: 'rate_limited' },
      source_progress: { timeout: { state: 'done', error_kind: 'timeout' } },
    };
    const model = buildFetchSourceReportModel(data, ['pubmed', 'timeout', 'Bad']);
    const report = renderFetchSourceReportHtml(model);
    console.log(JSON.stringify({
      live,
      reportTimeouts: model.timeouts.length,
      reportErrors: model.muted.filter((row) => !row.zero).length,
      report,
    }));
  `,
].join('\n');
vm.runInNewContext(code, { sandbox, host });
"""
