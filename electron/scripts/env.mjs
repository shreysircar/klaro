// Paths shared by the setup and test scripts. Mirrors backend/config.py and electron/main.js: the venv is
// <repo>/.venv, and the model and Ollama settings come from backend/config.py (asked of Python, never copied).
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const venvDir = path.join(repoRoot, '.venv');
export const venvPython = process.platform === 'win32'
  ? path.join(venvDir, 'Scripts', 'python.exe')
  : path.join(venvDir, 'bin', 'python');

// Child processes must speak UTF-8 whatever the Windows code page is.
export const utf8Env = { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' };
