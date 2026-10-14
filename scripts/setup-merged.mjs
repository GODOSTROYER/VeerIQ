import {constants, copyFileSync, existsSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {cwd: root, stdio: 'inherit', ...options});
    child.once('error', reject);
    child.once('exit', (code, signal) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} ${args.join(' ')} exited ${signal ? `on ${signal}` : `with code ${code}`}`));
    });
  });
}

async function main() {
  const envFile = path.join(root, '.env');
  if (!existsSync(envFile)) {
    const example = path.join(root, '.env.example');
    if (!existsSync(example)) throw new Error('.env.example is missing; cannot create local configuration.');
    try {
      copyFileSync(example, envFile, constants.COPYFILE_EXCL);
      console.log('Created .env from .env.example.');
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
    }
  }

  await run('npm', ['install', '--prefix', 'frontend']);
  await run('uv', ['sync', '--directory', 'backend']);
  await run('docker', ['compose', '-f', 'docker-compose.yml', 'up', '-d', '--wait']);
  console.log('Setup is ready. Start the merged app with npm run dev.');
}

main().catch((error) => {
  console.error(`Setup failed: ${error.message}`);
  process.exitCode = 1;
});
