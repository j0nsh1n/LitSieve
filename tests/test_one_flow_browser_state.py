"""Legacy layout preferences cannot select a second workflow."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_layout_notice_is_once_and_never_writes_a_mode():
    result = subprocess.run(
        ["node", "-e", NODE_NOTICE], cwd=ROOT,
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    cases = json.loads(result.stdout)
    assert cases["advanced"]["shown"] == 1
    assert cases["advanced"]["afterDismiss"] == 0
    assert cases["advanced"]["writes"] == [["litsieve_one_flow_notice_v1", "1"]]
    # A new browser stored no mode, so it has no old layout to relearn (19.4).
    assert cases["unset"]["shown"] == 0
    assert cases["unset"]["writes"] == [["litsieve_one_flow_notice_v1", "1"]]
    assert cases["simple"]["shown"] == 0
    assert cases["simple"]["writes"] == [["litsieve_one_flow_notice_v1", "1"]]
    assert cases["otherPage"]["writes"] == []
    assert cases["otherPage"]["shown"] == 0


def test_retired_mode_controls_are_absent_from_runtime():
    for path in (ROOT / "static" / "js").glob("*.js"):
        text = path.read_text()
        for removed in ("isSimpleMode", "setUiMode", "mode-toggle", "ui_mode_seed", "data-mode"):
            assert not re.search(r"\b" + re.escape(removed) + r"\b", text), (path.name, removed)
        if path.name != "common.js":
            assert "uiMode" not in text, path.name
    for path in (ROOT / "templates").rglob("*.html"):
        text = path.read_text()
        for removed in ("mode-toggle", "data-mode", "ui_mode", "search-title-advanced"):
            assert not re.search(r"\b" + re.escape(removed) + r"\b", text), (path.name, removed)
    for name in ("data_management", "statistics", "clusters"):
        assert not (ROOT / "templates" / f"{name}.html").exists()
        assert not (ROOT / "static" / "js" / f"{name}.js").exists()


def test_collect_empty_state_keeps_the_static_pan():
    text = (ROOT / "templates" / "partials" / "collect_ui.html").read_text()
    assert 'class="sieve-anim sieve-still empty-state-card" aria-hidden="true"' in text
    assert 'class="sieve-pan"' in text


NODE_NOTICE = r"""
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync('static/js/common.js', 'utf8');
const fn = source.slice(source.indexOf('function showOneFlowNotice()'),
    source.indexOf("document.addEventListener('DOMContentLoaded', showOneFlowNotice)"));
const results = {};
for (const previous of ['advanced', 'unset', 'simple', 'otherPage']) {
    const stored = new Map(previous === 'unset' ? [] : [['uiMode', previous]]);
    const writes = [], visible = [];
    function element() {
        return {children: [], setAttribute(){}, append(...nodes){this.children.push(...nodes)},
            addEventListener(event, handler){this[event] = handler},
            remove(){visible.splice(visible.indexOf(this), 1)}};
    }
    const sandbox = {
        localStorage: {getItem:key=>stored.get(key) || null,
            setItem(key,value){writes.push([key,value]);stored.set(key,value)}},
        document: {getElementById:()=>previous === 'otherPage' ? null : {},
            querySelector:()=>({prepend:node=>visible.push(node)}), createElement:element},
    };
    vm.runInNewContext(fn + ';showOneFlowNotice();showOneFlowNotice();', sandbox);
    const shown = visible.length;
    if (shown) {
        const notice = visible[0];
        if (!notice.children[0].textContent.includes('Save your work')) throw Error('Missing tool locations');
        notice.children[1].click();
    }
    results[previous] = {shown, afterDismiss: visible.length, writes};
}
console.log(JSON.stringify(results));
"""
