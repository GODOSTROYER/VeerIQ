import express from 'express';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {existsSync} from 'node:fs';
import {Store} from './store.mjs';
import {createSandbox} from './transport.mjs';
import {Engine} from './engine.mjs';
import {TOOLS,TASK} from './scope.mjs';

const root=fileURLToPath(new URL('../',import.meta.url)),store=new Store(join(root,'.data')),sandbox=await createSandbox();
const subscribers=new Map(),app=express();app.disable('x-powered-by');app.use(express.json({limit:'16kb'}));
app.use('/api',(req,res,next)=>{const origin=req.headers.origin;if(origin&&!['http://127.0.0.1:5173','http://localhost:5173',`http://127.0.0.1:${process.env.PORT??4310}`,`http://localhost:${process.env.PORT??4310}`].includes(origin))return res.status(403).json({error:'Origin not permitted.'});res.set('Cache-Control','no-store');next();});
const engine=new Engine({store,sandbox,onEvent:(id,event)=>{for(const res of subscribers.get(id)??[])res.write(`data: ${JSON.stringify(event)}\n\n`);}});
app.get('/api/config',(_,res)=>res.json({task:TASK,tools:TOOLS,armor_mode:process.env.ARMORIQ_MODE??'local',model_available:Boolean(process.env.LLM_API_KEY&&process.env.LLM_MODEL),study:{id:'FLOW-42',name:'Treatment response at week 12',n:240,synthetic:true}}));
app.get('/api/runs',(_,res)=>res.json(store.list()));
app.post('/api/runs',async(req,res)=>{try{const {goal,agent,attack}=req.body;if(attack!==undefined&&typeof attack!=='boolean')throw new Error('Attack setting must be true or false.');res.status(201).json(await engine.create({goal,agent,attack}));}catch(e){res.status(400).json({error:e.message});}});
app.get('/api/runs/:id',async(req,res)=>{const run=store.get(req.params.id);if(!run)return res.status(404).json({error:'Run not found.'});res.json({...run,events:store.events(run.id),effects:await sandbox.effects(run.id)});});
app.get('/api/runs/:id/events',(req,res)=>{
  if(!store.get(req.params.id))return res.status(404).end();
  res.set({'Content-Type':'text/event-stream','Connection':'keep-alive','Cache-Control':'no-cache'});res.flushHeaders();
  const list=subscribers.get(req.params.id)??new Set();list.add(res);subscribers.set(req.params.id,list);
  const after=Number(req.query.after??0);for(const event of store.events(req.params.id).filter(e=>e.seq>after))res.write(`data: ${JSON.stringify(event)}\n\n`);
  const heartbeat=setInterval(()=>res.write(': heartbeat\n\n'),15000);req.on('close',()=>{clearInterval(heartbeat);list.delete(res);if(!list.size)subscribers.delete(req.params.id);});
});
app.post('/api/runs/:id/approval',async(req,res)=>{try{if(typeof req.body.approved!=='boolean')throw new Error('Choose approve or keep internal.');res.json(await engine.approve(req.params.id,req.body));}catch(e){res.status(409).json({error:e.message});}});
app.get('/api/runs/:id/receipt',(req,res)=>{if(!store.get(req.params.id))return res.status(404).json({error:'Run not found.'});res.set('Content-Disposition',`attachment; filename="labline-${req.params.id}.json"`);res.json(store.receipt(req.params.id));});
if(existsSync(join(root,'dist')))app.use(express.static(join(root,'dist')));
const listener=app.listen(Number(process.env.PORT??4310),'127.0.0.1',()=>console.log(`VeerIQ API ready at http://127.0.0.1:${process.env.PORT??4310}`));
async function close(){for(const list of subscribers.values())for(const res of list)res.end();listener.close();for(const id of engine.contexts.keys())await engine.cleanup(id);await sandbox.close();store.close();process.exit(0);}
process.on('SIGINT',close);process.on('SIGTERM',close);
