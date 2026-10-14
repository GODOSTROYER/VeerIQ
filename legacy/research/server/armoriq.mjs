import {ArmorIQClient} from '@armoriq/sdk';
export async function createArmor(scope,id,{mode=process.env.ARMORIQ_MODE??'local',clientFactory}={}) {
  if(!['local','live'].includes(mode))throw new Error('ARMORIQ_MODE must be local or live.');
  if(mode==='local')return {mode:'local',proof:null,check:async()=>({action:'allow',allowed:true,reason:'Local protocol gate; ArmorIQ backend not connected.',source:'local'}),close:async()=>{}};
  if(!clientFactory&&(!process.env.ARMORIQ_API_KEY||!process.env.ARMORIQ_USER_EMAIL))throw new Error('Live ArmorIQ requires ARMORIQ_API_KEY and ARMORIQ_USER_EMAIL. No local fallback.');
  const client=clientFactory?clientFactory():new ArmorIQClient({apiKey:process.env.ARMORIQ_API_KEY,timeout:10000,maxRetries:0});
  const session=client.forUser(process.env.ARMORIQ_USER_EMAIL??'test@example.invalid').startSession({mode:'sdk',defaultMcpName:scope.mcp,validitySeconds:900,trueReanchor:false,sessionId:id});
  try{
    const token=await session.startPlan(scope.tools.map(action=>({name:`${scope.mcp}__${action}`,args:{study_id:scope.study_id}})),scope.goal);
    return {mode:'live',proof:{plan_hash:token.planHash??token.plan_hash??null,merkle_root:token.merkleRoot??token.merkle_root??null,issuer:'ArmorIQ'},
      async check(call){const d=await session.check(`${call.mcp}__${call.action}`,call.args);return {...d,action:d.action==='block'?'deny':d.action,source:'armoriq'};},
      report:async(call,result)=>session.report(`${call.mcp}__${call.action}`,call.args,result),close:()=>session.close()};
  }catch(error){await session.close('error');throw error;}
}
