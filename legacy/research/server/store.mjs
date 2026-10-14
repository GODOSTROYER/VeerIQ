import { DatabaseSync } from 'node:sqlite';
import { mkdirSync,existsSync,readFileSync,writeFileSync } from 'node:fs';
import { generateKeyPairSync,sign,verify } from 'node:crypto';
import {canonical,hash} from './scope.mjs';

export class Store {
  constructor(directory) {
    mkdirSync(directory,{recursive:true});this.db=new DatabaseSync(`${directory}/labline.sqlite`);
    this.db.exec('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, state TEXT NOT NULL); CREATE TABLE IF NOT EXISTS events (run_id TEXT, seq INTEGER, record TEXT NOT NULL, PRIMARY KEY(run_id,seq));');
    const path=`${directory}/local-signing-key.pem`;
    if(!existsSync(path)){const keys=generateKeyPairSync('ed25519');writeFileSync(path,keys.privateKey.export({type:'pkcs8',format:'pem'}),{mode:0o600});writeFileSync(`${directory}/local-public-key.pem`,keys.publicKey.export({type:'spki',format:'pem'}));}
    this.privateKey=readFileSync(path);this.publicKey=readFileSync(`${directory}/local-public-key.pem`,'utf8');
    // Sessions and MCP state are process-bound: never resume a held action after restart.
    for(const row of this.db.prepare('SELECT id,state FROM runs').all()) {const run=JSON.parse(row.state);if(['running','awaiting_approval'].includes(run.status)){run.status='interrupted';run.pending=null;this.save(run);}}
  }
  save(run){this.db.prepare('INSERT OR REPLACE INTO runs(id,state) VALUES(?,?)').run(run.id,JSON.stringify(run));}
  get(id){const row=this.db.prepare('SELECT state FROM runs WHERE id=?').get(id);return row?JSON.parse(row.state):null;}
  list(){return this.db.prepare('SELECT state FROM runs ORDER BY rowid DESC LIMIT 20').all().map(r=>JSON.parse(r.state));}
  events(id){return this.db.prepare('SELECT record FROM events WHERE run_id=? ORDER BY seq').all(id).map(r=>JSON.parse(r.record));}
  append(id,event) {
    const prior=this.db.prepare('SELECT record FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1').get(id);
    const last=prior?JSON.parse(prior.record):null;
    const record={...event,seq:(last?.seq??0)+1,time:new Date().toISOString(),previous_hash:last?.hash??null};
    record.hash=hash(record);this.db.prepare('INSERT INTO events VALUES(?,?,?)').run(id,record.seq,JSON.stringify(record));return record;
  }
  seal(value){return {value,hash:hash(value),signature:sign(null,Buffer.from(canonical(value)),this.privateKey).toString('base64'),public_key:this.publicKey,issuer:'VeerIQ local evidence key (not ArmorIQ)'};}
  receipt(id){const run=this.get(id);return this.seal({schema:'labline.receipt.v1',run,events:this.events(id)});}
  close(){this.db.close();}
}
export function verifyReceipt(receipt) {
  if(receipt.hash!==hash(receipt.value)||!verify(null,Buffer.from(canonical(receipt.value)),receipt.public_key,Buffer.from(receipt.signature,'base64')))return false;
  let previous=null;
  return receipt.value.events.every((e,i)=>{const {hash:checksum,...record}=e;const ok=e.seq===i+1&&e.previous_hash===previous&&hash(record)===checksum;previous=checksum;return ok;});
}
