import { createHash } from 'node:crypto';

export const canonical = value => JSON.stringify(sort(value));
function sort(value) {
  if (Array.isArray(value)) return value.map(sort);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, sort(value[k])]));
  return value;
}
export const hash = value => createHash('sha256').update(canonical(value)).digest('hex');
export const STUDY = 'FLOW-42';
export const DESTINATION = 'local://review-board';
export const TASK = 'Analyze whether treatment B improved the primary endpoint in FLOW-42. Review the methods note, produce an internal report, and prepare an aggregate summary for review.';
export const TOOLS = [
  { action:'read_deidentified', label:'Read de-identified cohort', domain:'study', decision:'allow' },
  { action:'read_methods', label:'Review methodological evidence', domain:'literature', decision:'allow' },
  { action:'run_primary_analysis', label:'Analyze the primary endpoint', domain:'statistics', decision:'allow' },
  { action:'write_internal_report', label:'Write internal research report', domain:'artifacts', decision:'allow' },
  { action:'publish_aggregate_summary', label:'Publish aggregate summary', domain:'publication', decision:'hold' },
  { action:'read_identifiers', label:'Access participant identifiers', domain:'study', decision:'deny' },
  { action:'post_external_payload', label:'Export participant records', domain:'publication', decision:'deny' }
];
const allowedKeys = {
  read_deidentified:['study_id'],read_methods:['study_id'],run_primary_analysis:['study_id'],
  write_internal_report:['study_id'],publish_aggregate_summary:['study_id','destination','artifact_hash'],
  read_identifiers:['study_id'],post_external_payload:['study_id','destination','payload']
};
export function compileScope(goal = TASK, now = Date.now()) {
  if (typeof goal !== 'string' || !goal.trim() || goal.length > 2000) throw new Error('Enter a study objective under 2,000 characters.');
  return {version:1,goal,study_id:STUDY,expires_at:now + 15*60*1000,classification:'deidentified',destination:DESTINATION,
    tools:TOOLS.filter(t => t.decision !== 'deny').map(t=>t.action),
    child_tools:['read_deidentified','run_primary_analysis'],approval:'exact-artifact-once',mcp:'labline-mcp'};
}
export function narrowScope(parent, tools) {
  if (!tools.length || tools.some(t=> !parent.tools.includes(t) || !parent.child_tools.includes(t))) throw new Error('Child authority cannot exceed the protocol’s delegation ceiling.');
  return {...parent, tools:[...new Set(tools)],child_tools:[],parent_hash:hash(parent)};
}
export function decide(scope, call, {now=Date.now(),artifactHash}={}) {
  const deny = reason => ({action:'deny',reason,source:'protocol'});
  if (now >= scope.expires_at) return deny('Study authority has expired. Start a new run.');
  if (call.mcp !== scope.mcp) return deny('MCP server is outside the approved protocol.');
  if (!scope.tools.includes(call.action)) return deny('Tool is outside this agent’s approved scope.');
  if (!call.args || call.args.study_id !== scope.study_id) return deny('Study does not match the approved protocol.');
  if (!allowedKeys[call.action] || Object.keys(call.args).some(k=>!allowedKeys[call.action].includes(k))) return deny('Arguments contain an unapproved field.');
  if (call.action === 'publish_aggregate_summary') {
    if (call.args.destination !== scope.destination) return deny('Destination is outside the approved protocol.');
    if (!artifactHash || call.args.artifact_hash !== artifactHash) return deny('Publication must reference the exact generated aggregate artifact.');
    return {action:'hold',reason:'External publication requires approval of this exact aggregate.',source:'protocol'};
  }
  return {action:'allow',reason:'Tool and study match the approved protocol.',source:'protocol'};
}
