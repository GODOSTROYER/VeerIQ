import {existsSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const backend = path.join(root, 'backend');
const python = process.platform === 'win32'
  ? path.join(backend, '.venv', 'Scripts', 'python.exe')
  : path.join(backend, '.venv', 'bin', 'python');
const vite = path.join(root, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js');

for (const [name, file] of [['Backend Python', python], ['Frontend Vite', vite]]) {
  if (!existsSync(file)) {
    console.error(`${name} is missing. Run npm run setup first.`);
    process.exit(1);
  }
}

const children = [
  spawn(python, ['-m', 'uvicorn', 'rewindsafe.api.app:app', '--host', '127.0.0.1', '--port', '8020'], {
    cwd: backend,
    stdio: 'inherit',
    detached: process.platform !== 'win32',
  }),
  spawn(process.execPath, [vite, '--host', '127.0.0.1', '--port', '5173', '--strictPort'], {
    cwd: path.join(root, 'frontend'),
    stdio: 'inherit',
    detached: process.platform !== 'win32',
  }),
];

let stopping = false;
let remaining = children.length;
let exitCode = 0;

function signalChild(child, signal) {
  if (!child.pid) return;
  try {
    if (process.platform !== 'win32') process.kill(-child.pid, signal);
    else child.kill(signal);
  } catch (error) {
    if (error.code !== 'ESRCH') throw error;
  }
}

function stop(signal = 'SIGTERM', code = 0) {
  if (stopping) return;
  stopping = true;
  exitCode = code;
  for (const child of children) signalChild(child, signal);
  const forceStop = setTimeout(() => {
    for (const child of children) signalChild(child, 'SIGKILL');
  }, 5000);
  forceStop.unref();
}

process.on('SIGINT', () => stop('SIGINT', 130));
process.on('SIGTERM', () => stop('SIGTERM', 143));

for (const child of children) {
  child.once('error', (error) => {
    console.error(`Could not start a merged development service: ${error.message}`);
    stop('SIGTERM', 1);
  });
  child.once('exit', (code, signal) => {
    remaining -= 1;
    if (!stopping) stop('SIGTERM', code ?? (signal ? 1 : 0));
    if (remaining === 0) process.exitCode = exitCode;
  });
}

console.log('RewindSafe API: http://127.0.0.1:8020');
console.log('VeerIQ frontend: http://127.0.0.1:5173');
