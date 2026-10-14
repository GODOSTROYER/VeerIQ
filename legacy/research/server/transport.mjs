import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {createServer} from 'node:http';
import {randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';

export async function createSandbox() {
  const counters=new Map(), token=randomUUID();
  const sink=createServer((req,res)=>{
    if(req.method!=='POST'||req.headers['x-canary-token']!==token){res.writeHead(403);return res.end();}
    let data='',bytes=0;req.on('data',chunk=>{bytes+=chunk.length;data+=chunk;});
    req.on('end',()=>{try{const payload=JSON.parse(data);const id=payload.run_id;const prior=counters.get(id)??{requests:0,bytes:0};counters.set(id,{requests:prior.requests+1,bytes:prior.bytes+bytes});res.writeHead(200);res.end('{}');}catch{res.writeHead(400);res.end();}});
  });
  await new Promise((resolve,reject)=>{sink.once('error',reject);sink.listen(0,'127.0.0.1',resolve);});
  const transport=new StdioClientTransport({command:process.execPath,args:[fileURLToPath(new URL('./tools.mjs',import.meta.url))],env:{...process.env,CANARY_URL:`http://127.0.0.1:${sink.address().port}`,CANARY_TOKEN:token},stderr:'pipe'});
  const client=new Client({name:'labline-guarded-dispatcher',version:'0.1.0'});await client.connect(transport);
  return {
    async call(action,args,run){const result=await client.callTool({name:action,arguments:{...args,run_id:run.id,...(action==='read_methods'?{attack:run.attack}:{})}});if(result.isError)throw new Error(result.content[0]?.text??'MCP tool failed.');return JSON.parse(result.content[0].text);},
    async effects(id){const result=await client.callTool({name:'inspect_effects',arguments:{run_id:id}});return {...JSON.parse(result.content[0].text),canary:counters.get(id)??{requests:0,bytes:0}};},
    async close(){await client.close();await new Promise(resolve=>sink.close(resolve));}
  };
}
