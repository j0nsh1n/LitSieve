"""Exercise Simple re-prepare confirmation, model selection, and wait flow."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_reprepare_cancel_is_inert_and_confirm_uses_catalog_and_simple_wait():
    result = subprocess.run(
        ["node", "-e", _HARNESS], cwd=ROOT, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr + result.stdout


_HARNESS = r"""
const fs=require('node:fs'); const vm=require('node:vm'); const assert=require('node:assert/strict');
const tools=fs.readFileSync('static/js/simple_tools.js','utf8');
const data=fs.readFileSync('static/js/collect.js','utf8');
function extract(src,name){let start=src.indexOf('async function '+name);if(start<0)start=src.indexOf('function '+name);if(start<0)throw Error('missing '+name);let i=src.indexOf('{',start),d=0;for(;i<src.length;i++){if(src[i]==='{')d++;else if(src[i]==='}'&&--d===0)return src.slice(start,i+1);}throw Error('unclosed '+name);}
class Element {
 constructor(value='',tag='div'){this.value=value;this.tag=tag;this.id='';this.textContent='';this.checked=false;this.hidden=false;this.disabled=false;this.selected=false;this.options=[];this.children=[];this.listeners={};this.style={};this.classList={toggle(){}};}
 append(...nodes){for(const node of nodes){this.children.push(node);if(this.tag==='select'&&node.tag==='option'){this.options.push(node);if(node.selected)this.value=node.value;if(this.options.length===1&&!this.options.some(o=>o.selected))this.value=this.options[0].value;}}}
 addEventListener(type,fn){this.listeners[type]=fn;}
 dispatchEvent(event){this.listeners[event.type]?.(event);}
 getAttribute(name){return name==='data-models'?this.models:null;}
 querySelectorAll(){return [];}
}
function findId(node,id){if(node.id===id)return node;for(const child of node.children||[]){const found=findId(child,id);if(found)return found;}return null;}
function makeRun(cancel, scope='only_missing'){
 const controls={};
 controls['only-missing']=new Element();controls['only-missing'].checked=false;
 controls['fetch-query']=new Element('old question');
 controls['simple-screen-query']=new Element('old research question');
 controls['embeddings-btn']=new Element();controls['embeddings-status']=new Element();
 controls['search-buffering-fill']=new Element();controls['search-buffering-label']=new Element();controls['search-buffering-progress']=new Element();
 controls['simple-screening-card']=new Element();controls['simple-screening-card'].hidden=true;
 controls['embedding-model-catalog']=new Element();
 controls['embedding-model-catalog'].models=JSON.stringify([
  {value:'general',label:'general · sentence-transformers/all-MiniLM-L6-v2'},
  {value:'specter',label:'specter · allenai/specter'},
 ]);
 const fieldsRoot=new Element();const localWrites=[];const requests=[];const waitCalls=[];const notifications=[];const prefChanges=[];
 const local={ [ 'lra_fetch_prefs_v1' ]: JSON.stringify({query:'old question',model:'general',modelManual:true}) };
 let modalClosed=false;
 let body={};
 const doc={
  getElementById(id){if(id==='simple-prepare-model'&&modalClosed)return null;return controls[id]||findId(fieldsRoot,id)||null;},
  createElement(tag){return new Element('',tag);},createTextNode(text){return new Element(String(text),'#text');},
  querySelector(){return null;},querySelectorAll(){return [];},
 };
 const root={querySelector(selector){return selector==='.lra-modal-fields'?fieldsRoot:null;}};
 const ctx={
  console, document:doc, window:{}, URL, Event, FETCH_PREFS_KEY:'lra_fetch_prefs_v1',
  localStorage:{getItem:key=>local[key]||null,setItem:(key,value)=>{localWrites.push([key,value]);local[key]=value;}},
  isSimpleMode:()=>true, pageLibraryId:()=> 'lib-1', _lastTotalArticles:0, _simpleScreenCounts:{},
  openSiteForm:async form=>{
   assert.equal(form.fields[0].id,'research_question');
   assert.equal(form.fields[0].value,'old research question');
   assert.equal(form.fields[1].value,'only_missing','only missing is the default');
   assert.deepEqual(JSON.parse(JSON.stringify(form.fields[1].options.map(o=>o.value))),['only_missing','all']);
   form.onReady(root);
   const disclosure=findId(fieldsRoot,'simple-reprepare-model-options');
   assert.equal(disclosure.tag,'details');assert.equal(disclosure.open,undefined);
   const model=findId(fieldsRoot,'simple-prepare-model');
   assert.deepEqual(JSON.parse(JSON.stringify(model.options.map(o=>o.value))),['general','specter']);
   assert.equal(model.value,'general','manual preference is selected from the allowed catalog');
   if(cancel){modalClosed=true;return null;}
   model.value='specter';
   body={research_question:'new research question',prepare_scope:scope};
   assert.equal(form.validate(body),'');
   modalClosed=true;assert.equal(doc.getElementById('simple-prepare-model'),null,'dialog controls are removed before the promise resolves');
   return body;
  },
  apiCall:async(path,options={})=>{
   requests.push({path,options});
   if(path==='/api/create-embeddings')return {status:'started'};
   if(path==='/api/screening/excluded?reason=low_relevance&library_id=lib-1')return {items:[{article_id:'low',source:'pubmed',reason:'low_relevance'}]};
   if(path==='/api/screening')return {status:'success'};
   throw Error('unexpected '+path);
  },
  waitForJob:async(...args)=>{waitCalls.push(args);return {status:'success',seconds:4,device:'cpu',embeddings_created:1,skipped_existing:0,articles_processed:1};},
  simpleWaitMapOpts:(min,max)=>({mapMin:min,mapMax:max}),
  showSimpleBuffering(){ctx.showCount++;},hideSimpleBuffering(){ctx.hideCount++;},
  showCount:0,hideCount:0,showNotification:(...a)=>notifications.push(a),
  setLoading(){},setStatus(){},saveFetchPrefs(){ctx.saveCount++;},saveCount:0,
  setConfirmedSimplePreparePreferences:(model,onlyMissing)=>prefChanges.push({model,onlyMissing}),
  setSimpleScreenSkipped(){},clearSimpleScreenUndoItems(){},
  holdSimpleWait(){},
  silentResolveDuplicatesAfterPrepare:async()=>null,
  loadPageData:async()=>{},refreshSimpleScreeningCard:async()=>{},
  withPageLibrary:body=>({...body,library_id:'lib-1'}),
  _simpleScreenCounts:{},
 };
 vm.createContext(ctx);
 vm.runInContext([
  extract(tools,'getResearchQuestionCandidate'),extract(tools,'applyVerifiedResearchQuestion'),
  extract(tools,'resolveSimplePrepareModeBeforeRequest'),
  tools.slice(tools.indexOf('function _simplePrepareModelCatalog'),tools.indexOf('// Per-database cap presets')),
  extract(data,'doCreateEmbeddings'),
 ].join('\n'),ctx);
 return {ctx,controls,requests,waitCalls,localWrites,local,prefChanges,notifications,fieldsRoot};
}
(async()=>{
 const canceled=makeRun(true);const before={question:canceled.controls['simple-screen-query'].value,fetch:canceled.controls['fetch-query'].value,scope:canceled.controls['only-missing'].checked,prefs:canceled.local['lra_fetch_prefs_v1']};
 const cancelResult=await canceled.ctx.doCreateEmbeddings({fromSimpleReprepare:true});
 assert.equal(cancelResult,null);assert.equal(canceled.requests.length,0);assert.equal(canceled.localWrites.length,0);assert.equal(canceled.ctx.saveCount,0);assert.equal(canceled.prefChanges.length,0);
 assert.deepEqual({question:canceled.controls['simple-screen-query'].value,fetch:canceled.controls['fetch-query'].value,scope:canceled.controls['only-missing'].checked,prefs:canceled.local['lra_fetch_prefs_v1']},before);

 const run=makeRun(false);const result=await run.ctx.doCreateEmbeddings({fromSimpleReprepare:true});assert.ok(result);
 const request=run.requests.find(r=>r.path==='/api/create-embeddings');assert.ok(request);
 assert.deepEqual(JSON.parse(JSON.stringify(request.options.body)),{model:'specter',only_missing:true,library_id:'lib-1'});
 assert.equal(run.controls['simple-screen-query'].value,'new research question');assert.equal(run.controls['fetch-query'].value,'old question');
 assert.deepEqual(run.prefChanges,[{model:'specter',onlyMissing:true}]);
 assert.equal(run.ctx.showCount,1);assert.equal(run.ctx.hideCount,1);
 assert.equal(run.waitCalls[0][0],'embed');assert.equal(run.waitCalls[0][1],'search-buffering-fill');assert.equal(run.waitCalls[0][5].mapMin,0);
 const reset=run.requests.find(r=>r.path==='/api/screening');assert.deepEqual(JSON.parse(JSON.stringify(reset.options.body)),{items:[{article_id:'low',source:'pubmed',reason:'low_relevance'}],action:'include',reason:'low_relevance',library_id:'lib-1'});

 const redo=makeRun(false,'all');await redo.ctx.doCreateEmbeddings({fromSimpleReprepare:true});
 const redoRequest=redo.requests.find(r=>r.path==='/api/create-embeddings');assert.equal(redoRequest.options.body.only_missing,false);
 assert.equal(redo.controls['only-missing'].checked,false);

 const failed=makeRun(false);failed.ctx.waitForJob=async()=>{throw Error('wait failed');};
 let rejected=false;try{await failed.ctx.doCreateEmbeddings({fromSimpleReprepare:true});}catch(_error){rejected=true;}
 assert.equal(rejected,true);assert.equal(failed.ctx.showCount,1);assert.equal(failed.ctx.hideCount,1);

 const auto=makeRun(false);auto.local['lra_fetch_prefs_v1']=JSON.stringify({model:'specter',modelManual:true});
 await auto.ctx.doCreateEmbeddings({fromAutoChain:true});
 const autoRequest=auto.requests.find(r=>r.path==='/api/create-embeddings');assert.equal(autoRequest.options.body.model,'specter');
 assert.equal(auto.waitCalls[0][5].mapMin,60,'auto-chain keeps its phase in the same wait screen');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
