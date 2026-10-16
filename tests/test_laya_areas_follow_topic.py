"""Audit 19.6: Laya's topic areas follow every topic change.

Runs the real area functions from static/js/collect.js in a Node VM with a
stubbed /api/topic-area, replaying the four ways the page used to lose track.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync('static/js/collect.js', 'utf8');
const cut = (a, b) => src.slice(src.indexOf(a), src.indexOf(b, src.indexOf(a)));
const code = [
  cut("let areasSource = 'none';", 'function openAreaPicker('),
  cut('function toggleTopic(', '/** Model that best matches'),
  'let _areaPickSeq = 0;',
  cut('async function pickAreasFromTopic(', '/** Tell the server how Laya'),
].join('\n');
const answers = JSON.parse(process.argv[1]);
const els = {};
const el = (id) => (els[id] = els[id] || {
  id, hidden: true, value: '', textContent: '',
  append() {}, addEventListener() {}, classList: {toggle() {}, add() {}, remove() {}},
});
const sandbox = {
  console, Set, Promise,
  TOPICS: [{id: 'biology'}, {id: 'physics'}, {id: 'health'}, {id: 'chemistry'}],
  selectedTopics: new Set(),
  document: {
    getElementById: (id) => (id === 'fetch-query' || id.startsWith('collect-areas-offer') ? el(id) : null),
    querySelectorAll: () => [],
    createElement: () => ({textContent: ''}),
  },
  apiCall: async (url, opts) => answers[opts.body.topic] || {available: false},
  updateRecommendedSources() {}, applyModelRecommendation() {}, saveFetchPrefs() {},
  refreshCoverage() {}, updateGettingStartedChecklist() {},
};
vm.runInNewContext(code + `
this.state = () => ({selected: [...selectedTopics].sort(), source: areasSource,
  laya: [...layaAreas].sort(), offer: document.getElementById('collect-areas-offer').hidden ? [] : _areaOffer});
this.type = async (topic) => { document.getElementById('fetch-query').value = topic; await pickAreasFromTopic(topic); return this.state(); };
this.click = (id) => { toggleTopic(id, {classList: {add() {}, remove() {}}}); return this.state(); };
`, sandbox);
(async () => {
  const out = {};
  out.algae = await sandbox.type('photosynthesis in algae');
  out.unsure = await sandbox.type('a general overview of everything');
  out.lasers = await sandbox.type('Lasers');
  out.click = sandbox.click('chemistry');
  out.afterClick = await sandbox.type('photosynthesis in algae');
  console.log(JSON.stringify(out));
})();
"""

ANSWERS = {
    "photosynthesis in algae": {"available": True, "topics": [{"id": "biology"}]},
    "Lasers": {"available": True, "topics": [{"id": "physics"}]},
    "a general overview of everything": {"available": True, "topics": []},
}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_laya_areas_follow_every_topic_change():
    result = subprocess.run(
        ["node", "-e", HARNESS, json.dumps(ANSWERS)],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)

    assert out["algae"] == {"selected": ["biology"], "source": "laya", "laya": ["biology"], "offer": []}
    # Unsure: the old Biology pick goes instead of staying "picked from your topic".
    assert out["unsure"]["selected"] == []
    assert out["unsure"]["source"] == "none"
    # A six-letter topic is asked about too.
    assert out["lasers"]["selected"] == ["physics"]
    # A hand click adds Chemistry as the student's choice; Physics is still Laya's.
    assert out["click"]["selected"] == ["chemistry", "physics"]
    assert out["click"]["laya"] == ["physics"]
    assert out["click"]["source"] == "manual"
    # A new topic after a hand click: the hand choice stays, Laya's own earlier
    # Physics goes, and the new pick is offered rather than ignored.
    assert out["afterClick"]["selected"] == ["chemistry"]
    assert out["afterClick"]["offer"] == ["biology"]


def test_find_re_asks_when_layas_pick_was_for_another_topic():
    js = (ROOT / "static" / "js" / "collect.js").read_text()
    assert "if (selectedTopics.size === 0 || (layaAreas.size && layaTopic !== query)) {" in js
