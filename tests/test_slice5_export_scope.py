"""Simple export scope routing and page-library isolation regressions."""

from __future__ import annotations

import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path

import pytest
from conftest import TEST_PASSWORD

REPO = Path(__file__).resolve().parents[1]

for _dep in ("fastapi", "httpx", "Bio", "sklearn", "slowapi", "jwt", "bcrypt", "multipart", "requests", "dotenv"):
    pytest.importorskip(_dep)

from fastapi.testclient import TestClient

from app import core
from app.storage.user_db import UserDatabase


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    from app import main

    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setattr(core, "_pipelines", OrderedDict())
    monkeypatch.setattr(core, "_pipeline_refcounts", {})
    monkeypatch.setattr(core, "_all_progress", OrderedDict())
    yield main
    for pipeline in core._pipelines.values():
        pipeline.close()
    db.conn.close()


def _register(client, username):
    response = client.post("/register", data={
        "username": username, "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD,
    }, follow_redirects=False)
    assert response.status_code == 302, response.text


def _insert_paper(client, title):
    uid = core.user_db.get_by_username("exportscope")['id']
    pipeline = core.get_pipeline(uid)
    try:
        pipeline.db.insert_articles([{
            "article_id": title, "source": "pubmed", "title": title,
            "abstract": "", "year": "2024", "authors": [], "journal": "",
        }])
    finally:
        core.release_pipeline(uid)


def test_page_library_export_is_bound_and_rejects_foreign_or_invalid_ids(app_module):
    client = TestClient(app_module.app)
    _register(client, "exportscope")
    first_id = client.get('/api/libraries').json()['active_id']
    _insert_paper(client, 'Paper in first library')
    created = client.post('/api/libraries', json={'name': 'Second'}, headers={
        'X-CSRF-Token': client.cookies.get('csrf_token', ''),
    })
    assert created.status_code == 200, created.text
    second_id = created.json()['library']['id']
    _insert_paper(client, 'Paper in second library')

    stale_tab_export = client.get('/api/export/library', params={
        'library_id': first_id, 'format': 'txt', 'scope': 'all',
    })
    assert stale_tab_export.status_code == 200
    assert 'Paper in first library' in stale_tab_export.text
    assert 'Paper in second library' not in stale_tab_export.text

    assert client.get('/api/export/library', params={'library_id': 'missing'}).status_code == 400
    other = TestClient(app_module.app)
    _register(other, 'exportscopeother')
    foreign_id = other.get('/api/libraries').json()['active_id']
    assert client.get('/api/export/library', params={'library_id': foreign_id}).status_code == 400
    assert client.get('/api/export/library', params={'library_id': second_id}).status_code == 200
    selected = client.post('/api/export/selection', params={'library_id': first_id}, json={
        'format': 'txt', 'items': [{'article_id': 'Paper in first library', 'source': 'pubmed'}],
    }, headers={'X-CSRF-Token': client.cookies.get('csrf_token', '')})
    assert selected.status_code == 200
    assert 'Paper in first library' in selected.text
    assert client.post('/api/export/selection', params={'library_id': foreign_id}, json={
        'items': [{'article_id': 'Paper in first library', 'source': 'pubmed'}],
    }, headers={'X-CSRF-Token': client.cookies.get('csrf_token', '')}).status_code == 400


HARNESS = r"""
const fs = require('node:fs'); const vm = require('node:vm'); const assert = require('node:assert/strict');
class Element {
 constructor() { this.value=''; this.hidden=true; this.textContent=''; this.dataset={}; this.listeners={}; this.attributes={}; this.style={removeProperty(){},setProperty(){}}; this.classList={toggle(){},contains(){return false}}; }
 addEventListener(type, fn) { this.listeners[type]=fn; } removeAttribute(k){delete this.attributes[k];} setAttribute(k,v){this.attributes[k]=v;}
 appendChild(){} click(){downloads++;} remove(){} getAttribute(){return '';} }
const els={}; const el=(id)=>els[id] ||= new Element(); let choices=[]; let downloads=0; let calls=[];
let pageLibrary = 'page-lib'; let fail = false;
const sandbox={console, URLSearchParams, Element, document:{addEventListener(){},getElementById:el,querySelector(){return null},querySelectorAll(){return[]},documentElement:{getAttribute(){return 'simple'}},createElement(){return new Element()},body:new Element()},
 window:{getComputedStyle(){return {position:'static'}},addEventListener(){}}, isSimpleMode(){return true}, syncSimplePanelClearance(){}, pageLibraryId(){return pageLibrary},
 openSiteChoice:async (opts)=>{assert.ok(Array.isArray(opts.choices)); choices.push(opts); if(opts.onReady) opts.onReady({querySelector:()=>el('actions')}); const pick=picks.shift(); if(pick==='switch') {pageLibrary='another';return 'csv'} return pick}, showNotification(){}, fetch:async (url,options)=>{calls.push({url,options});return {ok:!fail,json:async()=>({detail:'Download denied'}),blob:async()=>({}),headers:{get(){return ''}}}}, URL:{createObjectURL(){return 'blob:x'},revokeObjectURL(){}},
 visibleResults:()=>[{article_id:'b',source:'p'},{article_id:'a',source:'p'}], lastResults:[], librarySourceCounts:{pubmed:2}};
let picks=['all','csv']; vm.createContext(sandbox); vm.runInContext(fs.readFileSync('static/js/search.js','utf8'),sandbox);
vm.runInContext(`librarySourceCounts={pubmed:2};`,sandbox);
(async()=>{
 sandbox.updateSimpleSearchPanel(false); assert.equal(el('search-simple-panel').hidden,false);
 await sandbox.promptSimpleExportScope();
 assert.deepEqual(Array.from(choices[0].choices,x=>x.value),['all','included','excluded',null]);
 assert.equal(el('actions').id,'simple-export-scope');
 assert.equal(calls[0].url,'/api/export/library?scope=all&format=csv&library_id=page-lib');
 assert.equal(downloads,1);
 for(const choice of [[null],['all',null]]) {picks=choice;await sandbox.promptSimpleExportScope();}
 assert.equal(calls.length,1);assert.equal(downloads,1);
 vm.runInContext(`lastResults=[{article_id:'b',source:'pubmed'},{article_id:'a',source:'pubmed'}];`,sandbox);
 picks=['results','ris'];await sandbox.promptSimpleExportScope();
 assert.equal(choices.at(-2).choices[0].value,'results');
 assert.equal(calls[1].url,'/api/export/selection?library_id=page-lib');
 assert.deepEqual(JSON.parse(calls[1].options.body).items,[{article_id:'b',source:'pubmed'},{article_id:'a',source:'pubmed'}]);
 picks=['all','switch'];await sandbox.promptSimpleExportScope();assert.equal(calls.length,2);
 pageLibrary='page-lib';fail=true;picks=['included','txt'];await sandbox.promptSimpleExportScope();
 assert.equal(downloads,2);assert.equal(el('simple-export-status').textContent,'Download denied');
 vm.runInContext(`lastResults=[];librarySourceCounts={};`,sandbox);
 sandbox.updateSimpleSearchPanel(false);assert.equal(el('search-simple-panel').hidden,true);
})().catch(e=>{console.error(e);process.exitCode=1});
"""


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js not installed')
def test_simple_export_scope_uses_library_export_and_cancel_does_not_download():
    result = subprocess.run(['node', '-e', HARNESS], cwd=REPO, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr + result.stdout
