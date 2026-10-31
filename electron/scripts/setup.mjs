// One-command setup, run by `npm run setup` and before `npm run dev`. Idempotent: every step checks first.
// This is the only part of Klaro that uses the network (pip, and the one-time model download from
// huggingface.co). At run time nothing leaves the machine. KLARO_SKIP_SETUP=1 skips it.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { repoRoot, utf8Env, venvDir, venvPython } from './env.mjs';

if (process.env.KLARO_SKIP_SETUP === '1') {
  console.log('[setup] skipped (KLARO_SKIP_SETUP=1)');
  process.exit(0);
}

const MIN = [3, 11];
const t0 = Date.now();
const step = (n, msg) => console.log(`[setup ${n}/5 +${Math.round((Date.now() - t0) / 1000)}s] ${msg}`);
const fail = (msg) => {
  console.error(`\n[setup] ${msg}\n`);
  process.exit(1);
};
const run = (cmd, args, opts = {}) =>
  spawnSync(cmd, args, { cwd: repoRoot, env: utf8Env, shell: false, windowsHide: true, ...opts });

// "py -3.13" style launchers first on Windows; the newest supported minor version first elsewhere.
function pythonCandidates() {
  const minors = ['3.13', '3.12', '3.11'];
  return process.platform === 'win32'
    ? [...minors.map((v) => ['py', `-${v}`]), ['py', '-3'], ['python'], ['python3']]
    : [...minors.map((v) => [`python${v}`]), ['python3'], ['python']];
}

function versionOf(cmd, args) {
  const r = run(cmd, [...args, '-c', 'import sys; print("%d.%d.%d" % sys.version_info[:3])'], { encoding: 'utf8' });
  const m = r.status === 0 && /^(\d+)\.(\d+)\.(\d+)/.exec(r.stdout.trim());
  return m ? m.slice(1).map(Number) : null; // null: not installed, or the Microsoft Store stub
}

const atLeast = (v) => v[0] > MIN[0] || (v[0] === MIN[0] && v[1] >= MIN[1]);

function findPython() {
  for (const [cmd, ...args] of pythonCandidates()) {
    const v = versionOf(cmd, args);
    if (v && atLeast(v)) return { cmd, args, version: v.join('.') };
  }
  const where = process.platform === 'win32' ? 'https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH")' : 'https://www.python.org/downloads/ or `brew install python@3.12`';
  return fail(`Python ${MIN.join('.')}+ was not found. Install it from ${where}, then run this again.`);
}

// 1-2. Python and the venv.
const venvVersion = fs.existsSync(venvPython) ? versionOf(venvPython, []) : null;
if (venvVersion && atLeast(venvVersion)) {
  step(1, `using the existing virtual environment (${path.relative(repoRoot, venvDir)})`);
  step(2, 'virtual environment OK');
} else {
  const py = findPython();
  step(1, `found Python ${py.version} (${[py.cmd, ...py.args].join(' ')})`);
  step(2, 'creating the virtual environment .venv');
  fs.rmSync(venvDir, { recursive: true, force: true }); // a half-made venv from an interrupted run
  const r = run(py.cmd, [...py.args, '-m', 'venv', venvDir], { stdio: 'inherit' });
  if (r.status !== 0) fail('Could not create .venv. On Debian/Ubuntu install python3-venv; otherwise see the output above.');
}

// 3. Python packages, only when requirements.txt changed.
const reqFile = path.join(repoRoot, 'requirements.txt');
const hashFile = path.join(venvDir, '.klaro-requirements-hash');
const reqHash = createHash('sha256').update(fs.readFileSync(reqFile, 'utf8').replace(/\r\n/g, '\n')).digest('hex');
if (fs.existsSync(hashFile) && fs.readFileSync(hashFile, 'utf8').trim() === reqHash) {
  step(3, 'Python packages are up to date');
} else {
  step(3, 'installing Python packages from requirements.txt (downloads from pypi.org; the first run is several minutes and ~1 GB)');
  const r = run(venvPython, ['-m', 'pip', 'install', '--disable-pip-version-check', '-r', reqFile], { stdio: 'inherit' });
  if (r.status !== 0) fail('pip install failed. Check your internet connection and the output above, then run `npm run setup` again.');
  fs.writeFileSync(hashFile, reqHash);
}

// The paths and the Ollama settings come from backend/config.py, so there is one source of truth.
const cfg = run(venvPython, ['-c', [
  'import json',
  'from backend import config as c',
  'up, has = c.ollama_status()',
  'print(json.dumps({"models": str(c.MODELS_DIR), "url": c.OLLAMA_URL, "tag": c.MODEL_TAG, "up": up, "has": has}))',
].join('\n')], { encoding: 'utf8' });
if (cfg.status !== 0) fail(`Could not read backend/config.py:\n${cfg.stderr}`);
const conf = JSON.parse(cfg.stdout.trim().split('\n').pop());

// 4. Translation model.
const check = () => run(venvPython, ['-m', 'backend.translation.translator', '--check'], { encoding: 'utf8' });
if (check().status === 0) {
  step(4, `German to English translation model OK (${conf.models})`);
} else {
  step(4, 'downloading the German to English translation model from huggingface.co (one time, about 310 MB)');
  const r = run(venvPython, ['-m', 'backend.translation.fetch_model'], { stdio: 'inherit', env: { ...utf8Env, HF_HUB_DISABLE_SYMLINKS_WARNING: '1' } });
  if (r.status !== 0) fail('The model download failed. Check your internet connection, then run `npm run setup` again (it resumes).');
}

// 5. Ollama: never fatal, the app's setup screen guides the user as well.
if (!conf.up) {
  step(5, `Ollama is not reachable at ${conf.url}. Install it from https://ollama.com/download and start it, then run: ollama pull ${conf.tag}`);
} else if (!conf.has) {
  step(5, `Ollama is running but the model is missing. Run: ollama pull ${conf.tag}`);
} else {
  step(5, `Ollama is running and has ${conf.tag}`);
}
console.log(`[setup] done in ${Math.round((Date.now() - t0) / 1000)}s`);
