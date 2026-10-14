import {existsSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const backend = path.join(root, 'backend');
const python = process.platform === 'win32'
  ? path.join(backend, '.venv', 'Scripts', 'python.exe')
  : path.join(backend, '.venv', 'bin', 'python');

if (!existsSync(python)) {
  console.error('Backend Python is missing. Run npm run setup first.');
  process.exit(1);
}

const env = {...process.env};
env.REWINDSAFE_ENFORCEMENT = 'offline';
env.REWINDSAFE_LLM_PROVIDER = 'auto';
env.REWINDSAFE_PLANNER = 'scripted';
env.DATABASE_URL = 'postgresql://rewindsafe:rewindsafe@127.0.0.1:5436/veeriq';
env.REWINDSAFE_TEST_ADMIN_DSN ??= 'postgresql://rewindsafe:rewindsafe@127.0.0.1:5436/postgres';
for (const key of [
  'ARMORIQ_API_KEY',
  'ANTHROPIC_API_KEY',
  'OPENAI_API_KEY',
  'GROQ_API_KEY',
]) env[key] = '';

const child = spawn(python, ['-m', 'pytest'], {
  cwd: backend,
  env,
  stdio: 'inherit',
});

child.once('error', (error) => {
  console.error(`Could not start the RewindSafe test runner: ${error.message}`);
  process.exitCode = 1;
});
child.once('exit', (code, signal) => {
  process.exitCode = code ?? (signal ? 1 : 0);
});
