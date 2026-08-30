import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createExplorerController, capturePayload, initialDraft, reevaluationPayload, RESULT_LABELS, sourceMode } from '../src/explorer-state.js';

const preparation = id => ({decision_id:id,status:'issued',question:`Exact question for ${id}?`,
  capture_session_id:`session-${id}`,profile_hash:`profile-${id}`,gap_id:`gap-${id}`,question_hash:`question-${id}`,
  historical_relations:[], candidate_source_mode:'configured_mechanically_grounded_example_candidates',
  metric_schema:[{metric_key:'restore_success',unit:'ratio',minimum:0,maximum:1,minimum_window_days:1}],
  example_observations:{world_time:'2026-09-08T12:00:00Z',observations:[{metric_key:'restore_success',value:0.8,unit:'ratio',window_days:1,observed_at:'2026-09-08T12:00:00Z'}]}});
const captured = p => ({decision_id:p.decision_id,status:'capture_verified',capture_binding:capturePayload(p),historical_relations:[]});
const evaluated = (id,result) => ({decision_id:id,status:'reevaluated',safe_reuse_result:result,
  current_matches:{M:'matches'},admitted_observations:[],limiting_requirements:[],reason_codes:[],evaluation_hash:'eval',replay_hash:'eval'});
const ok = data => ({ok:true,json:async()=>data});
function fixture() {
  const calls=[]; const queue=[];
  const controller=createExplorerController(async (url,options)=>{calls.push({url,options});return queue.shift()});
  return {controller,calls,queue};
}
async function ready(f,id='D-205') {
  const p=preparation(id); f.queue.push(ok(p)); await f.controller.select(id);
  f.queue.push(ok(captured(p)));await f.controller.capture();return p;
}
test('Explorer loads case registration from API without choosing a canned case',async()=>{
  const f=fixture();f.queue.push(ok({cases:[{decision_id:'D-104'},{decision_id:'D-205'}]}));await f.controller.loadCases();
  assert.equal(f.calls[0].url,'/api/cases');assert.equal(f.controller.getSnapshot().cases.length,2);assert.equal(f.controller.getSnapshot().selected,null);
});
test('same controller uses exact issued question and capture bindings for either case',async()=>{
  for(const id of ['D-104','D-205']) {const f=fixture();const p=await ready(f,id);
    assert.equal(f.controller.getSnapshot().preparation.question,p.question);
    assert.deepEqual(JSON.parse(f.calls[1].options.body),capturePayload(p));assert.equal(f.calls[1].url,`/api/cases/${id}/capture`);
  }
});
test('T1 controls derive only from schema and optional server example data',()=>{
  const p=preparation('D-205');assert.equal(initialDraft(p).observations[0].value,'0.8');
  assert.equal(initialDraft({...p,example_observations:null}).observations[0].value,'');
  const payload=reevaluationPayload(p,initialDraft(p));assert.deepEqual(Object.keys(payload).sort(),['capture','observations','world_time']);
  assert.deepEqual(Object.keys(payload.observations[0]).sort(),['metric_key','observed_at','unit','value','window_days']);
});
test('D-205 edited observation updates result only after new server response',async()=>{
  const f=fixture();await ready(f);f.queue.push(ok(evaluated('D-205','reuse_not_authorized')));await f.controller.reevaluate();
  assert.equal(RESULT_LABELS[f.controller.getSnapshot().result.safe_reuse_result],'REUSE NOT AUTHORIZED');
  f.controller.edit(0,'value','1.00');assert.equal(f.controller.getSnapshot().result,null);assert.equal(f.controller.getSnapshot().stale,true);
  f.queue.push(ok(evaluated('D-205','reuse_authorized')));await f.controller.reevaluate();
  assert.equal(JSON.parse(f.calls.at(-1).options.body).observations[0].value,1);
  assert.equal(RESULT_LABELS[f.controller.getSnapshot().result.safe_reuse_result],'REUSE AUTHORIZED');assert.equal(f.controller.getSnapshot().stale,false);
  assert.equal(f.controller.getSnapshot().submitted.observations[0].value,1);
});
test('all three server outcomes render generically, not from numeric values',async()=>{
  for(const result of Object.keys(RESULT_LABELS)) {const f=fixture();await ready(f,'D-104');f.queue.push(ok(evaluated('D-104',result)));await f.controller.reevaluate();assert.equal(f.controller.getSnapshot().result.safe_reuse_result,result);}
});
test('switching case immediately clears capture, draft and result and aborts stale requests',async()=>{
  const f=fixture();await ready(f);let resolve;f.queue.push(new Promise(r=>resolve=r));const old=f.controller.reevaluate();
  const oldSignal=f.calls.at(-1).options.signal;f.queue.push(ok(preparation('D-104')));const next=f.controller.select('D-104');
  assert.equal(f.controller.getSnapshot().capture,null);assert.equal(f.controller.getSnapshot().result,null);assert.equal(f.controller.getSnapshot().draft,null);assert.equal(oldSignal.aborted,true);
  await next;resolve(ok(evaluated('D-205','reuse_authorized')));await old;
  assert.equal(f.controller.getSnapshot().selected,'D-104');assert.equal(f.controller.getSnapshot().result,null);
});
test('out-of-order preparation cannot overwrite the selected case',async()=>{
  const f=fixture();let resolve;f.queue.push(new Promise(r=>resolve=r));const first=f.controller.select('D-104');
  f.queue.push(ok(preparation('D-205')));await f.controller.select('D-205');resolve(ok(preparation('D-104')));await first;
  assert.equal(f.controller.getSnapshot().preparation.decision_id,'D-205');
});
test('failed reevaluation and malformed success never produce a fallback result',async()=>{
  const f=fixture();await ready(f);f.queue.push({ok:false,status:409,json:async()=>({message:'binding mismatch'})});await f.controller.reevaluate();
  assert.equal(f.controller.getSnapshot().error,'binding mismatch');assert.equal(f.controller.getSnapshot().result,null);
  f.queue.push(ok(evaluated('D-104','reuse_authorized')));await f.controller.reevaluate();assert.equal(f.controller.getSnapshot().result,null);assert.equal(f.controller.getSnapshot().status,'error');
});
test('pending capture grants no authority; response must verify exact binding',async()=>{
  const f=fixture(),p=preparation('D-205');f.queue.push(ok(p));await f.controller.select('D-205');let resolve;
  f.queue.push(new Promise(r=>resolve=r));const request=f.controller.capture();assert.equal(f.controller.getSnapshot().capture,null);
  resolve(ok({...captured(p),capture_binding:{}}));await request;assert.equal(f.controller.getSnapshot().capture,null);
});
test('editing while reevaluation is pending invalidates its eventual result',async()=>{
  const f=fixture();await ready(f);let resolve;f.queue.push(new Promise(r=>resolve=r));const pending=f.controller.reevaluate();
  f.controller.edit(0,'value','0.9');resolve(ok(evaluated('D-205','reuse_authorized')));await pending;assert.equal(f.controller.getSnapshot().result,null);
});
test('source-mode label distinguishes configured examples from Gemini evidence',()=>{
  assert.equal(sourceMode(preparation('D-205').candidate_source_mode),'Configured grounded example evidence');
  assert.equal(sourceMode('unknown'),'Evidence mode: unknown');
});
test('shared component gates T1 on verified capture and has no case-specific semantics',()=>{
  const jsx=readFileSync(new URL('../src/Explorer.jsx',import.meta.url),'utf8');const state=readFileSync(new URL('../src/explorer-state.js',import.meta.url),'utf8');
  for(const name of ['D-104','D-205','Apex','Beacon','Orion']) {assert.ok(!jsx.includes(name));assert.ok(!state.includes(name));}
  assert.match(jsx,/!state\.capture \?/);assert.match(jsx,/\{p\.question\}/);assert.match(jsx,/No live Gemini execution is claimed/);
  assert.match(jsx,/state\.result &&/);assert.match(jsx,/state\.stale &&/);assert.match(jsx,/RESULT_LABELS\[state\.result\.safe_reuse_result\]/);
});
test('Explorer navigation does not reuse the delegated Proof button selector',()=>{
  const main=readFileSync(new URL('../src/main.jsx',import.meta.url),'utf8');
  assert.match(main,/<a className="explorer-entry" href="#explore">Explore Decision Recall<\/a>/);
  assert.doesNotMatch(main,/<a[^>]*className="[^"]*proof-button/);
});
