"""Exercise the new theme UI flow through its real browser-side functions."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_theme_grouping_browse_preview_apply_and_exact_undo():
    result = subprocess.run(
        ["node", "-e", _HARNESS], capture_output=True, text=True, timeout=20, cwd=ROOT
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_theme_tools_partial_exposes_real_entrypoint():
    partial = (ROOT / "templates/partials/theme_tools.html").read_text()
    assert 'id="simple-group-by-theme"' in partial
    assert 'class="btn btn-secondary simple-tools-search-only"' in partial


_HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Element {
 constructor(tag='div', text='') {
  this.tagName=tag; this.textContent=text; this.children=[]; this.listeners={};
  this.id='';
  this.hidden=false; this.value=''; this.checked=false; this.disabled=false; this.open=false;
  this.attributes={}; this.className=''; this.classList={toggle(){}};
 }
 append(...nodes) { this.children.push(...nodes); }
 replaceChildren(...nodes) { this.children=[...nodes]; }
 addEventListener(type, fn) { this.listeners[type]=fn; }
 async fire(type) { if(type==='click'&&this.disabled)return;const fn=this.listeners[type]||this[`on${type}`];return fn?.({type, target:this}); }
 setAttribute(k,v) { this.attributes[k]=v; }
 showModal() { this.open=true; }
 close() { this.open=false; }
}
const elements = Object.fromEntries(['simple-group-by-theme'].map(id=>[id,new Element()]));
const calls=[]; let canceled=false; let currentLib='lib-one'; let switchDuringForm=false; let nextForm;
const clusters=[{cluster_id:2,cluster_label:'<img src=x onerror=alert(1)>',article_count:4}];
const body = new Element('body');
function findId(node,id){if(node.id===id)return node;for(const child of node.children||[]){const match=findId(child,id);if(match)return match;}return null;}
const ctx={
 console, encodeURIComponent, Number, String, Array, JSON, Error,
 document:{
  addEventListener(){}, getElementById(id){return elements[id]||findId(body,id);},
  createElement(tag){return new Element(tag);},
  createTextNode(text){return new Element('#text',text);},
  body,
 },
 pageLibraryId:()=>currentLib,
 openSiteForm:async opts=>{
  nextForm=opts;
  const methodRadios=['hdbscan','kmeans','hierarchical'].map(value=>Object.assign(new Element('input'),{value,checked:value==='hdbscan'}));
  const countRadios=['auto','fixed'].map(value=>Object.assign(new Element('input'),{value,checked:value==='auto'}));
  const fields={method:new Element(),count_mode:new Element(),n_clusters:new Element()};
  const root={querySelectorAll(selector){return selector.includes('method')?methodRadios:countRadios;},querySelector(selector){return fields[selector.match(/"([^"]+)"/)[1]];}};
  opts.onReady(root);
  assert.equal(fields.count_mode.hidden,true); assert.equal(fields.n_clusters.hidden,true);
  methodRadios[0].checked=false;methodRadios[1].checked=true;await methodRadios[1].fire('change');
  assert.equal(fields.count_mode.hidden,false);assert.equal(fields.n_clusters.hidden,true);
  countRadios[0].checked=false;countRadios[1].checked=true;await countRadios[1].fire('change');
  assert.equal(fields.n_clusters.hidden,false);
  if(switchDuringForm)currentLib='lib-two';
  return canceled?null:{method:'kmeans',count_mode:'fixed',n_clusters:'3'};
 },
 apiCall:async (path,opts={})=>{
  calls.push({path,opts});
  if(path==='/api/create-clusters') return {status:'started'};
  if(path==='/api/clusters/2/articles?include_abstract=true&library_id=lib-one') return {articles:[
   {article_id:'kept',source:'pubmed',title:'<script>safe</script>',abstract:'A <b>paper</b>',key_points:['point'],excluded:false},
   {article_id:'later',source:'pubmed',title:'Reason may change before undo',excluded:false},
   {article_id:'raced',source:'arxiv',title:'Excluded while popup was open',excluded:false},
   {article_id:'already',source:'arxiv',title:'Already set aside',excluded:true},
  ]};
  if(path==='/api/screening/excluded?reason=all&library_id=lib-one') return {items:[
   {article_id:'raced',source:'arxiv',reason:'wrong_population'},
   {article_id:'already',source:'arxiv',reason:'duplicate'},
  ]};
  if(path==='/api/screening/excluded?reason=cluster&library_id=lib-one') return {items:[
   {article_id:'kept',source:'pubmed',reason:'cluster'},
  ]};
  if(path==='/api/screening') return {status:'success'};
  throw new Error('unexpected '+path);
 },
 waitForJob:async (task,fill,label,wrap,fmt,timeout,opts)=>{assert.equal(task,'cluster');assert.equal(timeout,600000);return {status:'success',clusters};},
 simpleWaitMapOpts:(a,b)=>({mapMin:a,mapMax:b}), showSimpleBuffering(){}, hideSimpleBuffering(){},
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('static/js/simple_themes.js','utf8'),ctx);
function find(node, pred) { if(pred(node)) return node; for(const c of node.children||[]){const found=find(c,pred);if(found)return found;} return null; }
(async()=>{
 canceled=true; await ctx.launchSimpleThemeGrouping();
 assert.equal(calls.length,0,'cancel must not start a request');
 canceled=false; await ctx.launchSimpleThemeGrouping();
 assert.deepEqual(JSON.parse(JSON.stringify(nextForm.fields[0].options.map(o=>o.value))),['hdbscan','kmeans','hierarchical']);
 assert.equal(nextForm.validate({method:'hdbscan',count_mode:'fixed',n_clusters:''}),'');
 assert.equal(nextForm.validate({method:'kmeans',count_mode:'fixed',n_clusters:'3'}),'');
 assert.ok(nextForm.onReady);
 assert.equal(calls[0].path,'/api/create-clusters');
 assert.deepEqual(JSON.parse(JSON.stringify(calls[0].opts.body)),{method:'kmeans',n_clusters:3,wait:false,library_id:'lib-one'});
 const dialog=ctx.document.getElementById('simple-theme-tools'); assert.equal(dialog.open,true);
 assert.equal(dialog.attributes['aria-labelledby'],'simple-theme-tools-heading');
 assert.ok(find(dialog,n=>n.id==='simple-theme-tools-heading'));
 const row=ctx.document.getElementById('simple-theme-browser').children[0]; assert.ok(row);
 assert.ok(find(row,n=>n.tagName==='h3'&&n.textContent==='<img src=x onerror=alert(1)>'), 'label uses text nodes');
 const themeDetails=find(row,n=>n.tagName==='details');
 themeDetails.open=true;
 await themeDetails.fire('toggle');
 const get=calls.find(c=>c.path.includes('/articles?')); assert.ok(get); assert.ok(get.path.includes('include_abstract=true'));
 assert.ok(find(row,n=>n.textContent.includes('<script>safe</script>')));
 assert.equal(find(row,n=>n.tagName==='script'),null,'paper data is not parsed as markup');
 assert.equal(calls.some(c=>c.path==='/api/screening'),false,'grouping and browsing do not change screening');
 const previewButton=find(row,n=>n.tagName==='button'&&n.textContent==='Preview papers to set aside');
 await previewButton.fire('click');
 const preview=find(row,n=>n.className==='simple-theme-preview');
 const checkbox=find(preview,n=>n.tagName==='input'); assert.ok(checkbox); assert.equal(checkbox.checked,true);
 const apply=find(preview,n=>n.tagName==='button'&&n.textContent==='Set selected papers aside');
 await apply.fire('click');
 const exclude=calls.find(c=>c.path==='/api/screening'); assert.ok(exclude);
 assert.deepEqual(JSON.parse(JSON.stringify(exclude.opts.body)),{action:'exclude',reason:'cluster',items:[{article_id:'kept',source:'pubmed'},{article_id:'later',source:'pubmed'}],library_id:'lib-one'});
 assert.ok(calls.some(c=>c.path==='/api/screening/excluded?reason=all&library_id=lib-one'));
 assert.equal(ctx.document.getElementById('simple-theme-undo').hidden,false);
 await ctx.document.getElementById('simple-theme-undo').onclick();
 const include=calls.filter(c=>c.path==='/api/screening')[1];
 assert.deepEqual(JSON.parse(JSON.stringify(include.opts.body)),{action:'include',items:[{article_id:'kept',source:'pubmed'}],library_id:'lib-one'});
 assert.ok(calls.some(c=>c.path==='/api/screening/excluded?reason=cluster&library_id=lib-one'));
 const close=find(dialog,n=>n.tagName==='button'&&n.textContent==='Close themes');
 await close.fire('click'); assert.equal(dialog.open,false,'result browser closes as a dialog');
 ctx.openSiteForm=async opts=>({method:'hdbscan',count_mode:'auto',n_clusters:''});
 await ctx.launchSimpleThemeGrouping();
 const densityCall=calls.filter(c=>c.path==='/api/create-clusters').at(-1);
 assert.deepEqual(JSON.parse(JSON.stringify(densityCall.opts.body)),{method:'hdbscan',n_clusters:null,wait:false,library_id:'lib-one'});
 currentLib='lib-one'; switchDuringForm=true;
 ctx.openSiteForm=async()=>{currentLib='lib-two';return {method:'kmeans',count_mode:'fixed',n_clusters:'3'};};
 await ctx.launchSimpleThemeGrouping();
 assert.equal(ctx.document.getElementById('simple-theme-status').textContent,'Your selected library changed. Reload Search before grouping.');

 ctx._themeRenderBrowser([], 'lib-one');
 const emptyMessage=find(ctx.document.getElementById('simple-theme-browser'),n=>n.textContent.includes('No themes were found.'));
 assert.ok(emptyMessage,'empty results explain that no themes were found');

 currentLib='lib-one'; switchDuringForm=false;
 ctx.openSiteForm=async()=>({method:'kmeans',count_mode:'fixed',n_clusters:'3'});
 let resolveClusterStart;
 let showCount=0, hideCount=0;
 ctx.showSimpleBuffering=()=>{showCount++;};
 ctx.hideSimpleBuffering=()=>{hideCount++;};
 ctx.apiCall=async(path,opts={})=>{
  calls.push({path,opts});
  if(path==='/api/create-clusters')return new Promise(resolve=>{resolveClusterStart=resolve;});
  throw new Error('unexpected '+path);
 };
 const launchesBeforeRace=calls.filter(c=>c.path==='/api/create-clusters').length;
 const firstLaunch=ctx.launchSimpleThemeGrouping();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(ctx.document.getElementById('simple-group-by-theme').disabled,true);
 await ctx.launchSimpleThemeGrouping();
 assert.equal(calls.filter(c=>c.path==='/api/create-clusters').length-launchesBeforeRace,1,'busy guard prevents a second launch');
 assert.equal(hideCount,0,'second launch cannot hide the first wait screen');
 resolveClusterStart({status:'success',clusters:[]});
 await firstLaunch;
 assert.equal(showCount,1); assert.equal(hideCount,1,'successful grouping closes its wait screen');
 assert.equal(ctx.document.getElementById('simple-group-by-theme').disabled,false);

 ctx.apiCall=async(path,opts={})=>{
  calls.push({path,opts});
  if(path==='/api/create-clusters')throw new Error('temporary failure');
  throw new Error('unexpected '+path);
 };
 await ctx.launchSimpleThemeGrouping();
 assert.equal(hideCount,2,'failed grouping closes its wait screen');
 assert.equal(ctx.document.getElementById('simple-group-by-theme').disabled,false,'failure releases the launch guard');
 ctx.apiCall=async(path,opts={})=>{
  calls.push({path,opts});
  if(path==='/api/create-clusters')return {status:'success',clusters:[]};
  throw new Error('unexpected '+path);
 };
 await ctx.launchSimpleThemeGrouping();
 assert.equal(calls.filter(c=>c.path==='/api/create-clusters').length-launchesBeforeRace,3,'retry starts after failure releases the guard');

 // Apply disables before its read, and Undo remains disabled during its read.
 ctx.apiCall=async(path,opts={})=>{
  calls.push({path,opts});
  if(path==='/api/clusters/7/articles?include_abstract=true&library_id=lib-one')return {articles:[{article_id:'race',source:'pubmed',title:'Race',excluded:false}]};
  if(path==='/api/screening/excluded?reason=all&library_id=lib-one')return new Promise(resolve=>{resolveExcluded=resolve;});
  if(path==='/api/screening/excluded?reason=cluster&library_id=lib-one')return new Promise(resolve=>{resolveClusterUndo=resolve;});
  if(path==='/api/screening')return {status:'success'};
  throw new Error('unexpected '+path);
 };
 let resolveExcluded, resolveClusterUndo;
 ctx._themeRenderBrowser([{cluster_id:7,cluster_label:'Race theme',article_count:1}], 'lib-one');
 const raceRow=ctx.document.getElementById('simple-theme-browser').children[0];
 const raceDetails=find(raceRow,n=>n.tagName==='details'); raceDetails.open=true; await raceDetails.fire('toggle');
 await find(raceRow,n=>n.textContent==='Preview papers to set aside').fire('click');
 const raceApply=find(raceRow,n=>n.textContent==='Set selected papers aside');
 const allExclusionReadsBefore=calls.filter(c=>c.path==='/api/screening/excluded?reason=all&library_id=lib-one').length;
 const applying=raceApply.fire('click');
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(raceApply.disabled,true,'apply disables before refreshing exclusions');
 await raceApply.fire('click');
 assert.equal(calls.filter(c=>c.path==='/api/screening/excluded?reason=all&library_id=lib-one').length-allExclusionReadsBefore,1,'a second apply cannot start while refreshing exclusions');
 resolveExcluded({items:[]}); await applying;
 const undoButton=ctx.document.getElementById('simple-theme-undo');
 const clusterReadsBefore=calls.filter(c=>c.path==='/api/screening/excluded?reason=cluster&library_id=lib-one').length;
 const undoing=undoButton.fire('click');
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(undoButton.disabled,true,'undo is disabled while checking current cluster exclusions');
 await undoButton.fire('click');
 assert.equal(calls.filter(c=>c.path==='/api/screening/excluded?reason=cluster&library_id=lib-one').length-clusterReadsBefore,1,'a second undo cannot start while the first is checking');
 resolveClusterUndo({items:[{article_id:'race',source:'pubmed',reason:'cluster'}]}); await undoing;
 assert.equal(undoButton.disabled,false);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
