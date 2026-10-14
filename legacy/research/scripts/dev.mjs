import {spawn} from 'node:child_process';
const children=[spawn(process.execPath,['--env-file-if-exists=.env','--watch','server/index.mjs'],{stdio:'inherit'}),spawn(process.execPath,['node_modules/vite/bin/vite.js'],{stdio:'inherit'})];
let stopping=false;function close(){if(stopping)return;stopping=true;for(const p of children)p.kill('SIGTERM');setTimeout(()=>process.exit(0),500);}
process.on('SIGINT',close);process.on('SIGTERM',close);for(const p of children)p.on('exit',close);
