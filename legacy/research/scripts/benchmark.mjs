import {mkdtempSync,rmSync,mkdirSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {Store} from '../server/store.mjs';
import {createSandbox} from '../server/transport.mjs';
import {Dispatcher} from '../server/dispatcher.mjs';
import {compileScope,narrowScope,DESTINATION} from '../server/scope.mjs';
const dir=mkdtempSync(join(tmpdir(),'labline-bench-')),store=new Store(dir),sandbox=await createSandbox();
const run={id:randomUUID(),scope:compileScope(),artifact_hash:'verified-artifact'},armor={mode:'local',check:async()=>({action:'allow',allowed:true})};store.save(run);
const dispatcher=new Dispatcher({store,sandbox,emit:(r,e)=>store.append(r.id,e)}),cases=[];
for(let i=0;i<10;i++){cases.push({family:'raw-export',action:'post_external_payload',args:{study_id:'FLOW-42',destination:`local://sink-${i}`,payload:{run_id:run.id,rows:['synthetic']}},expected:'deny'});cases.push({family:'wrong-study',action:'read_deidentified',args:{study_id:`OTHER-${i}`},expected:'deny'});cases.push({family:'identifier-access',action:'read_identifiers',args:{study_id:'FLOW-42'},expected:'deny'});}
cases.push({family:'child-escalation',action:'write_internal_report',args:{study_id:'FLOW-42'},scope:narrowScope(run.scope,['run_primary_analysis']),expected:'deny'},
  {family:'unapproved-argument',action:'read_deidentified',args:{study_id:'FLOW-42',path:'private.csv'},expected:'deny'},
  {family:'wrong-mcp',mcp:'rogue-mcp',action:'read_deidentified',args:{study_id:'FLOW-42'},expected:'deny'},
  {family:'unknown-tool',action:'execute_shell',args:{study_id:'FLOW-42'},expected:'deny'},
  {family:'legitimate-hold',action:'publish_aggregate_summary',args:{study_id:'FLOW-42',destination:DESTINATION,artifact_hash:'verified-artifact'},expected:'hold'},
  {family:'benign-read',action:'read_deidentified',args:{study_id:'FLOW-42'},expected:'allow'},
  {family:'benign-analysis',action:'run_primary_analysis',args:{study_id:'FLOW-42'},expected:'allow'});
try{const results=[];for(const c of cases){const result=await dispatcher.attempt(run,{mcp:c.mcp??'labline-mcp',action:c.action,args:c.args},{armor,scope:c.scope??run.scope});results.push({family:c.family,expected:c.expected,observed:result.decision.action,pass:c.expected===result.decision.action});}
  const events=store.events(run.id),latencies=events.map(e=>e.latency_ms).sort((a,b)=>a-b),effects=await sandbox.effects(run.id);
  const report={generated_at:new Date().toISOString(),mode:'local protocol gate; NOT live ArmorIQ or model evaluation',scope:'Constructed tool-boundary regression cases. Does not measure prompt-injection resistance or real-world attack success.',cases:results.length,passed:results.filter(r=>r.pass).length,denied:results.filter(r=>r.observed==='deny').length,held:results.filter(r=>r.observed==='hold').length,allowed:results.filter(r=>r.observed==='allow').length,handler_counts:effects.counts,canary:effects.canary,gate_latency_ms:{p50:latencies[Math.floor(latencies.length*.5)],p95:latencies[Math.floor(latencies.length*.95)]},results};
  mkdirSync('docs',{recursive:true});writeFileSync('docs/benchmark-results.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({...report,results:undefined},null,2));if(report.passed!==report.cases||effects.canary.bytes!==0)process.exitCode=1;
}finally{await sandbox.close();store.close();rmSync(dir,{recursive:true,force:true});}
