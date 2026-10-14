import {readFileSync} from 'node:fs';
import {verifyReceipt} from '../server/store.mjs';
const path=process.argv[2],trusted=process.argv[3];
if(!path){console.error('Usage: npm run verify-receipt -- receipt.json [trusted-public-key.pem]');process.exit(1);}
try{const receipt=JSON.parse(readFileSync(path,'utf8'));const keyMatches=!trusted||receipt.public_key.trim()===readFileSync(trusted,'utf8').trim();if(!keyMatches||!verifyReceipt(receipt)){console.error('Receipt verification FAILED.');process.exitCode=1;}else{console.log(`Receipt signature and event chain verified (${receipt.value.events.length} events).`);console.log(trusted?'Signer matches the supplied trusted public key.':'Embedded-key consistency only; signer identity is not independently verified.');}}catch(error){console.error(`Cannot verify receipt: ${error.message}`);process.exitCode=1;}
