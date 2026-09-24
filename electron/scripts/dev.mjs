// `npm run dev`: start Vite on a free port, then Electron pointed at it. Electron starts the Python API.
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import electron from 'electron';
import { createServer } from 'vite';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const server = await createServer({ configFile: path.join(root, 'vite.config.mjs') });
await server.listen();
const url = server.resolvedUrls.local[0];
console.log(`Renderer dev server: ${url}`);

const child = spawn(electron, [root, ...process.argv.slice(2)], { stdio: 'inherit', env: { ...process.env, KLARO_RENDERER_URL: url } });
child.on('exit', async (code) => {
  await server.close();
  process.exit(code ?? 0);
});
