// Main process: spawn the Python API, wait for /health, then load the renderer.
const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const { execFile, spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const REPO_ROOT = path.join(__dirname, '..');
const HEALTH_TIMEOUT_MS = 30000;

let backend = null;
let apiBase = null;
let dataDir = null; // absolute, from /health
let logStream = null;

// <userData>/logs/backend.log: everything the Python backend prints, for bug reports. One file per launch;
// the previous launch is kept as backend.previous.log.
function openLog() {
  const dir = path.join(app.getPath('userData'), 'logs');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'backend.log');
  try {
    fs.renameSync(file, path.join(dir, 'backend.previous.log'));
  } catch { /* first launch, or the old log is locked: it gets overwritten below */ }
  logStream = fs.createWriteStream(file, { flags: 'w', encoding: 'utf8' });
  logStream.on('error', () => { logStream = null; }); // logging must never take the app down
  logStream.write(`Klaro ${app.getVersion()} on ${process.platform} ${process.arch}, ${new Date().toISOString()}\n`);
}
const log = (chunk) => logStream?.write(chunk);

function backendCommand() {
  if (app.isPackaged) {
    // ponytail: the PyInstaller binary is not built yet; this is where electron-builder will put it.
    const exe = process.platform === 'win32' ? 'klaro-backend.exe' : 'klaro-backend';
    return { cmd: path.join(process.resourcesPath, 'klaro-backend', exe), args: [], cwd: process.resourcesPath };
  }
  const python = process.platform === 'win32'
    ? path.join(REPO_ROOT, '.venv', 'Scripts', 'python.exe')
    : path.join(REPO_ROOT, '.venv', 'bin', 'python');
  return { cmd: python, args: ['-m', 'backend.api'], cwd: REPO_ROOT };
}

// Resolves with the API base URL once the backend prints `KLARO_PORT=<n>`.
function startBackend() {
  return new Promise((resolve, reject) => {
    const { cmd, args, cwd } = backendCommand();
    if (!fs.existsSync(cmd)) {
      reject(new Error(`Python backend not found at ${cmd}.\nRun \`npm run setup\` in the repo root (see README.md).`));
      return;
    }
    const env = { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' };
    if (app.isPackaged) {
      env.KLARO_DATA_DIR = path.join(app.getPath('userData'), 'data');
      env.KLARO_MODELS_DIR ??= path.join(app.getPath('userData'), 'models');
    }
    log(`Starting backend: ${cmd} ${args.join(' ')}\n`);

    backend = spawn(cmd, args, { cwd, env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    let out = '';
    let err = '';
    backend.stdout.on('data', (d) => {
      process.stdout.write(d);
      log(d);
      out += d;
      const m = out.match(/KLARO_PORT=(\d+)/);
      if (m) resolve(`http://127.0.0.1:${m[1]}`);
    });
    backend.stderr.on('data', (d) => {
      process.stderr.write(d);
      log(d);
      err = (err + d).slice(-4000);
    });
    backend.on('error', reject);
    backend.on('exit', (code) => {
      backend = null;
      log(`Backend exited with code ${code}\n`);
      reject(new Error(`The Python backend exited (code ${code}) before it was ready.\n\n${err}\n\nLog: ${path.join(app.getPath('userData'), 'logs', 'backend.log')}`));
    });
  });
}

async function waitForHealth(base) {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${base}/health`);
      if (res.ok) {
        dataDir = (await res.json()).data_dir;
        return;
      }
      lastError = new Error(`/health returned ${res.status}`);
    } catch (e) {
      lastError = e;
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`The Python backend did not answer /health within ${HEALTH_TIMEOUT_MS / 1000}s: ${lastError?.message}`);
}

function stopBackend() {
  if (!backend) return;
  if (process.platform === 'win32') {
    // /T takes uvicorn's children (the running pipeline) down too.
    spawnSync('taskkill', ['/pid', String(backend.pid), '/T', '/F'], { windowsHide: true });
  } else {
    backend.kill('SIGTERM'); // uvicorn shuts down gracefully and kills the running pipeline
  }
  backend = null;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 820,
    minWidth: 820,
    minHeight: 560,
    show: false,
    title: 'Klaro',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  // The renderer never navigates or opens windows; a dropped file or a stray link must not either.
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  win.once('ready-to-show', () => win.show());

  if (process.env.KLARO_RENDERER_URL) win.loadURL(process.env.KLARO_RENDERER_URL);
  else win.loadFile(path.join(__dirname, 'dist', 'index.html'));
}

// A run's file, only ever inside <data>/runs/<runId>/. Throws for anything that resolves elsewhere.
function runFile(runId, ...rel) {
  if (typeof runId !== 'string' || !/^[\w.-]+$/.test(runId) || !dataDir) throw new Error('Invalid run id.');
  const runsDir = path.resolve(dataDir, 'runs');
  const dir = path.resolve(runsDir, runId);
  const file = path.resolve(dir, ...rel);
  if (path.dirname(dir) !== runsDir || (file !== dir && !file.startsWith(dir + path.sep))) {
    throw new Error('Path is outside the run folder.');
  }
  return file;
}

// Runs a backend CLI helper (dev: the venv's python). Resolves with the last stdout line parsed as JSON.
function runPythonModule(args) {
  const { cmd, cwd } = backendCommand();
  // ponytail: the packaged PyInstaller backend has no helper entry points yet; add them when it is built.
  if (app.isPackaged) return Promise.reject(new Error('Language tools are not available in the packaged build yet.'));
  return new Promise((resolve, reject) => {
    execFile(cmd, ['-m', ...args], { cwd, env: { ...process.env, PYTHONUTF8: '1' }, timeout: 60000, windowsHide: true },
      (err, stdout, stderr) => {
        const line = String(stdout).trim().split('\n').pop();
        try {
          resolve(JSON.parse(line));
        } catch {
          reject(new Error(String(stderr).trim().split('\n').pop() || err?.message || 'The language tool failed.'));
        }
      });
  });
}

ipcMain.handle('api-base', () => apiBase);

ipcMain.handle('detect-language', async (_e, file) => {
  if (typeof file !== 'string' || !file.toLowerCase().endsWith('.pdf') || !fs.statSync(file, { throwIfNoEntry: false })?.isFile()) {
    throw new Error('Not a PDF file.');
  }
  return runPythonModule(['backend.translation.detect', file]); // {language: de|en|unknown, confidence}
});

ipcMain.handle('check-translator', () => runPythonModule(['backend.translation.translator', '--check', 'de', 'en'])); // {ok, error}

ipcMain.handle('get-source', async (_e, runId) => {
  const file = runFile(runId, 'source.pdf');
  if (fs.existsSync(file)) return fs.promises.readFile(file);
  // Runs from before language support only have the copy in input/.
  const input = runFile(runId, 'input');
  const pdf = (await fs.promises.readdir(input).catch(() => [])).find((n) => n.toLowerCase().endsWith('.pdf'));
  if (!pdf) throw new Error('The source PDF for this run is missing.');
  return fs.promises.readFile(runFile(runId, 'input', pdf));
});

ipcMain.handle('get-evidence', async (_e, runId) => {
  try {
    return JSON.parse(await fs.promises.readFile(runFile(runId, 'evidence.json'), 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return null; // old runs have none
    throw err;
  }
});

ipcMain.handle('get-translation', async (_e, runId) => {
  try {
    return JSON.parse(await fs.promises.readFile(runFile(runId, 'translation', 'segments.json'), 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return null; // English runs and old runs have none
    throw err;
  }
});

// Saves the English view: the renderer sends each page as a JPEG, main prints them as a PDF with Chromium's
// printer from a script-free local page (one named @page per page so sizes can differ).
ipcMain.handle('save-english-pdf', async (e, name, pages) => {
  const ok = typeof name === 'string' && Array.isArray(pages) && pages.length > 0 && pages.length <= 2000
    && pages.every((p) => p.jpeg?.length > 4 && p.jpeg[0] === 0xff && p.jpeg[1] === 0xd8 && p.w > 0 && p.h > 0);
  if (!ok) throw new Error('Invalid pages.');
  const { canceled, filePath } = await dialog.showSaveDialog(BrowserWindow.fromWebContents(e.sender), {
    defaultPath: path.basename(name),
    filters: [{ name: 'PDF documents', extensions: ['pdf'] }],
  });
  if (canceled || !filePath) return null;

  const dir = await fs.promises.mkdtemp(path.join(app.getPath('temp'), 'klaro-export-'));
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, javascript: false } });
  try {
    const css = pages.map((p, i) => `@page p${i}{size:${p.w}pt ${p.h}pt;margin:0}.p${i}{page:p${i}}`).join('');
    const body = pages.map((p, i) => `<img class="p${i}" src="page-${i}.jpg" style="display:block;width:${p.w}pt;height:${p.h}pt;break-after:page">`).join('');
    await Promise.all(pages.map((p, i) => fs.promises.writeFile(path.join(dir, `page-${i}.jpg`), Buffer.from(p.jpeg))));
    await fs.promises.writeFile(path.join(dir, 'index.html'), `<!doctype html><meta charset="utf-8"><style>body{margin:0}${css}</style>${body}`);
    await win.loadFile(path.join(dir, 'index.html'));
    await fs.promises.writeFile(filePath, await win.webContents.printToPDF({ preferCSSPageSize: true }));
  } finally {
    win.destroy();
    fs.promises.rm(dir, { recursive: true, force: true }).catch(() => {});
  }
  return filePath;
});

ipcMain.handle('open-file', async (e) => {
  const { canceled, filePaths } = await dialog.showOpenDialog(BrowserWindow.fromWebContents(e.sender), {
    properties: ['openFile'],
    filters: [{ name: 'PDF documents', extensions: ['pdf'] }],
  });
  if (canceled || filePaths.length === 0) return null;
  return { name: path.basename(filePaths[0]), path: filePaths[0], data: await fs.promises.readFile(filePaths[0]) };
});

ipcMain.handle('open-external', (_e, url) => {
  if (typeof url !== 'string' || !url.startsWith('https://')) throw new Error('Only https links can be opened.');
  return shell.openExternal(url);
});

app.whenReady().then(async () => {
  try {
    openLog();
    apiBase = await startBackend();
    await waitForHealth(apiBase);
  } catch (e) {
    stopBackend();
    dialog.showErrorBox('Klaro could not start', String(e?.message ?? e));
    app.quit();
    return;
  }
  createWindow();
});

app.on('window-all-closed', () => {
  stopBackend();
  app.quit();
});
app.on('before-quit', stopBackend);
process.on('SIGINT', () => app.quit());
process.on('SIGTERM', () => app.quit());
