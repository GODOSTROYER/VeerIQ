import {canonical,decide,hash} from './scope.mjs';

export class Dispatcher {
  constructor({store,sandbox,emit}){this.store=store;this.sandbox=sandbox;this.emit=emit;}
  async attempt(run,call,{scope=run.scope,armor,actor='researcher',approved=false}={}) {
    const started=performance.now();
    // Deep-copy before checking: the same immutable payload is checked and executed.
    call=JSON.parse(canonical(call));
    const argsHash=hash(call);
    const local=decide(scope,call,{artifactHash:run.artifact_hash});
    let sponsor;
    try{sponsor=await armor.check(call);}catch{sponsor={action:'deny',reason:'Enforcement service unavailable. Tool execution stopped.',source:'armoriq'};}
    let decision=local;
    if(sponsor.action==='deny'||sponsor.allowed!==true&&sponsor.action!=='hold')decision={...sponsor,action:'deny'};
    else if(!['allow','hold','deny'].includes(sponsor.action))decision={action:'deny',reason:'Unrecognized runtime decision. Execution stopped.',source:sponsor.source??'runtime'};
    else if(local.action!=='deny'&&sponsor.action==='hold')decision=sponsor;
    if(approved&&decision.action==='hold'&&sponsor.action==='allow')decision={action:'allow',reason:'Exact artifact approved; protocol and runtime checks passed.',source:armor.mode==='live'?'armoriq + protocol':'protocol'};
    const event={kind:'tool',actor,tool:call.action,mcp:call.mcp,decision:decision.action,reason:decision.reason,source:decision.source,args_hash:argsHash,study_id:call.args.study_id,latency_ms:Number((performance.now()-started).toFixed(2)),executed:false};
    if(decision.action!=='allow') {this.emit(run,event);return {decision,result:null,argsHash};}
    let result;
    try{result=await this.sandbox.call(call.action,call.args,run);event.executed=true;this.emit(run,event);}
    catch(error){this.emit(run,{...event,kind:'error',decision:'error',reason:error.message});throw error;}
    // Telemetry is corroboration, never authority. A reporting failure cannot replay an effect.
    try{await armor.report?.(call,{status:'completed'});}catch{this.emit(run,{kind:'telemetry',decision:'info',reason:'Tool completed; sponsor telemetry reporting was unavailable.'});}
    return {decision,result,argsHash};
  }
}
