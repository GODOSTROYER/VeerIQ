import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {compileScope,narrowScope,decide,hash,DESTINATION} from '../server/scope.mjs';
import {Store,verifyReceipt} from '../server/store.mjs';
import {Dispatcher} from '../server/dispatcher.mjs';
import {createSandbox} from '../server/transport.mjs';
import {Engine} from '../server/engine.mjs';
import {createArmor} from '../server/armoriq.mjs';
import {analyze} from '../server/data.mjs';

const call=(action,args={})=>({mcp:'labline-mcp',action,args:{study_id:'FLOW-42',...args}});
test('protocol rejects tools, wrong resources, hidden arguments and changed destinations',()=>{
  const scope=compileScope();
  const cases=[call('post_external_payload'),call('read_identifiers'),call('unknown'),call('read_deidentified',{study_id:'FLOW-99'}),call('read_deidentified',{query:'select *'}),call('publish_aggregate_summary',{destination:'https://attacker.invalid',artifact_hash:'abc'}),call('publish_aggregate_summary',{destination:DESTINATION,artifact_hash:'tampered'}),{...call('read_deidentified'),mcp:'attacker-mcp'}];
  for(const c of cases)assert.equal(decide(scope,c,{artifactHash:'abc'}).action,'deny');
  assert.equal(decide(scope,call('run_primary_analysis')).action,'allow');
  assert.equal(decide(scope,call('publish_aggregate_summary',{destination:DESTINATION,artifact_hash:'abc'}),{artifactHash:'abc'}).action,'hold');
});
test('expired authority fails closed',()=>{const scope=compileScope('Analyze FLOW-42',0);assert.equal(decide(scope,call('read_deidentified'),{now:scope.expires_at}).action,'deny');});
test('delegation is an intersection, never a union',()=>{
  const scope=compileScope();assert.throws(()=>narrowScope(scope,['publish_aggregate_summary']));assert.throws(()=>narrowScope(scope,['read_identifiers']));
  for(const t of scope.child_tools){const child=narrowScope(scope,[t]);assert(child.tools.every(x=>scope.tools.includes(x)));assert.equal(decide(child,call('write_internal_report')).action,'deny');}
});
test('canonical hashes ignore key ordering and detect value changes',()=>{assert.equal(hash({b:2,a:1}),hash({a:1,b:2}));assert.notEqual(hash({a:1}),hash({a:2}));});
test('statistical report is deterministic, aggregates only, and detects seeded treatment effect',()=>{
  const a=analyze(),b=analyze();assert.deepEqual(a,b);assert.equal(a.n,240);assert(a.effect>2&&a.effect<4);assert(a.confidence[0]>0);assert(a.p_value<.01);assert(!JSON.stringify(a).includes('P0001'));
});
test('dispatcher never executes on DENY, HOLD, backend outage or inconsistent verdict',async()=>{
  let entered=0;const events=[];const dispatcher=new Dispatcher({sandbox:{call:async()=>{entered++;}},emit:(_,e)=>events.push(e)}),run={id:randomUUID(),scope:compileScope(),artifact_hash:'abc'};
  const allow={mode:'local',check:async()=>({allowed:true,action:'allow'})};
  await dispatcher.attempt(run,call('read_identifiers'),{armor:allow});
  await dispatcher.attempt(run,call('publish_aggregate_summary',{destination:DESTINATION,artifact_hash:'abc'}),{armor:allow});
  await dispatcher.attempt(run,call('read_deidentified'),{armor:{check:async()=>{throw new Error('offline');}}});
  await dispatcher.attempt(run,call('read_deidentified'),{armor:{check:async()=>({allowed:false,action:'allow'})}});
  assert.equal(entered,0);assert.equal(events.length,4);assert(events.every(e=>e.executed===false));
});
test('sponsor telemetry failure does not roll back or replay completed tools',async()=>{
  let entered=0;const dispatcher=new Dispatcher({sandbox:{call:async()=>{entered++;return {ok:true};}},emit:()=>{}});
  const result=await dispatcher.attempt({id:randomUUID(),scope:compileScope()},call('read_deidentified'),{armor:{check:async()=>({action:'allow',allowed:true}),report:async()=>{throw new Error('telemetry offline');}}});assert(result.result.ok);assert.equal(entered,1);
});
test('live SDK adapter obtains token, maps decisions and closes lifecycle',async()=>{
  let started,checked,closed=0;const session={startPlan:async steps=>{started=steps;return {planHash:'official-plan',merkleRoot:'root'};},check:async(name,args)=>{checked={name,args};return {allowed:false,action:'block',reason:'tool-not-in-plan'};},close:async()=>closed++};
  const armor=await createArmor(compileScope(),randomUUID(),{mode:'live',clientFactory:()=>({forUser:()=>({startSession:opts=>{assert.equal(opts.mode,'sdk');return session;}})})});
  assert.equal(armor.proof.plan_hash,'official-plan');assert(!started.some(s=>s.name.endsWith('read_identifiers')));const result=await armor.check(call('read_identifiers'));assert.equal(result.action,'deny');assert.equal(checked.name,'labline-mcp__read_identifiers');await armor.close();assert.equal(closed,1);
});
test('live mode cannot silently become local when credentials are absent',async()=>{
  const key=process.env.ARMORIQ_API_KEY,email=process.env.ARMORIQ_USER_EMAIL;delete process.env.ARMORIQ_API_KEY;delete process.env.ARMORIQ_USER_EMAIL;
  try{await assert.rejects(createArmor(compileScope(),randomUUID(),{mode:'live'}),/No local fallback/);}finally{if(key)process.env.ARMORIQ_API_KEY=key;if(email)process.env.ARMORIQ_USER_EMAIL=email;}
});
test('audit receipt detects alteration, deletion and reordering',()=>{
  const dir=mkdtempSync(join(tmpdir(),'labline-audit-')),store=new Store(dir),id=randomUUID();try{store.save({id,status:'completed'});store.append(id,{decision:'allow'});store.append(id,{decision:'deny'});const receipt=store.receipt(id);assert(verifyReceipt(receipt));for(const transform of [v=>v.events[0].decision='allow-all',v=>v.events.pop(),v=>v.events.reverse()]){const tampered=structuredClone(receipt);transform(tampered.value);assert.equal(verifyReceipt(tampered),false);}}finally{store.close();rmSync(dir,{recursive:true,force:true});}
});
async function until(store,id){for(let i=0;i<500;i++){const run=store.get(id);if(run.status!=='running')return run;await new Promise(r=>setTimeout(r,10));}throw new Error('Workflow timed out.');}
test('real MCP end-to-end: attack blocked, recovery completes, exact approval executes once',async()=>{
  const dir=mkdtempSync(join(tmpdir(),'labline-e2e-')),store=new Store(dir),sandbox=await createSandbox(),engine=new Engine({store,sandbox,pace:0});
  try{
    const start=await engine.create({attack:true}),run=await until(store,start.id);assert.equal(run.status,'awaiting_approval');assert(run.report);
    let effects=await sandbox.effects(run.id);assert.equal(effects.counts.read_identifiers??0,0);assert.equal(effects.counts.post_external_payload??0,0);assert.deepEqual(effects.canary,{requests:0,bytes:0});assert.equal(effects.counts.publish_aggregate_summary??0,0);
    const payload={approval_id:run.pending.id,call_hash:run.pending.call_hash,approved:true};await assert.rejects(engine.approve(run.id,{...payload,call_hash:'wrong'}));
    const approvals=await Promise.allSettled([engine.approve(run.id,payload),engine.approve(run.id,payload)]);assert.equal(approvals.filter(r=>r.status==='fulfilled').length,1);
    effects=await sandbox.effects(run.id);assert.equal(effects.counts.publish_aggregate_summary,1);assert.equal(effects.published.artifact_hash,run.artifact_hash);assert(verifyReceipt(store.receipt(run.id)));await assert.rejects(engine.approve(run.id,payload));
    assert.equal(store.events(run.id).filter(e=>e.kind==='tool'&&e.decision==='deny').length,3);
  }finally{for(const id of engine.contexts.keys())await engine.cleanup(id);await sandbox.close();store.close();rmSync(dir,{recursive:true,force:true});}
});
test('real MCP: rejecting or expiring an approval produces no publication',async()=>{
  const dir=mkdtempSync(join(tmpdir(),'labline-approvals-')),store=new Store(dir),sandbox=await createSandbox(),engine=new Engine({store,sandbox,pace:0});
  try{for(const expired of [false,true]){const start=await engine.create({attack:false}),run=await until(store,start.id);if(expired){run.pending.expires_at=0;store.save(run);}await engine.approve(run.id,{approval_id:run.pending.id,call_hash:run.pending.call_hash,approved:!expired?false:true});const effects=await sandbox.effects(run.id);assert.equal(effects.counts.publish_aggregate_summary??0,0);assert.equal(store.get(run.id).status,expired?'expired':'completed');}}finally{for(const id of engine.contexts.keys())await engine.cleanup(id);await sandbox.close();store.close();rmSync(dir,{recursive:true,force:true});}
});
test('canary positive control detects a real unguarded sandbox export',async()=>{const sandbox=await createSandbox(),id=randomUUID();try{await sandbox.call('post_external_payload',{study_id:'FLOW-42',destination:'ignored.invalid',payload:{run_id:id,rows:['synthetic-control']}},{id});const effects=await sandbox.effects(id);assert.equal(effects.counts.post_external_payload,1);assert.equal(effects.canary.requests,1);assert(effects.canary.bytes>0);}finally{await sandbox.close();}});
test('restart invalidates pending work instead of resuming publication',()=>{const dir=mkdtempSync(join(tmpdir(),'labline-restart-'));let store=new Store(dir);const id=randomUUID();store.save({id,status:'awaiting_approval',pending:{id:'old'}});store.close();store=new Store(dir);try{assert.equal(store.get(id).status,'interrupted');assert.equal(store.get(id).pending,null);}finally{store.close();rmSync(dir,{recursive:true,force:true});}});
