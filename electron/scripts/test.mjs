// `npm test` from the repo root: the renderer's node tests, then the Python unit tests in the venv.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { repoRoot, utf8Env, venvPython } from './env.mjs';

const run = (cmd, args) => spawnSync(cmd, args, { cwd: repoRoot, env: utf8Env, stdio: 'inherit', shell: false });
const node = run(process.execPath, ['--test', 'electron/renderer/src/highlight.test.mjs', 'electron/renderer/src/layout.test.mjs']);
// backend/ has no __init__.py files, so unittest discovery cannot walk it: name the modules.
const modules = fs.readdirSync(path.join(repoRoot, 'backend', 'evaluation'))
  .filter((f) => /^test_.*\.py$/.test(f))
  .map((f) => `backend.evaluation.${f.slice(0, -3)}`);
modules.push('scripts.finetune.test_finetune');
const py = run(venvPython, ['-m', 'unittest', ...modules]);
process.exit(node.status || py.status || 0);
