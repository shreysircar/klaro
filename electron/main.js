// Main process: spawn the Python API, wait for /health, then load the renderer.
const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const REPO_ROOT = path.join(__dirname, '..');
const HEALTH_TIMEOUT_MS = 30000;

let backend = null;
let apiBase = null;

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
      reject(new Error(`Python backend not found at ${cmd}.\nFollow the setup steps in electron/README.md.`));
      return;
    }
    const env = { ...process.env, PYTHONUTF8: '1', PYTHONUNBUFFERED: '1' };
    if (app.isPackaged) env.KLARO_DATA_DIR = path.join(app.getPath('userData'), 'data');

    backend = spawn(cmd, args, { cwd, env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    let out = '';
    let err = '';
    backend.stdout.on('data', (d) => {
      process.stdout.write(d);
      out += d;
      const m = out.match(/KLARO_PORT=(\d+)/);
      if (m) resolve(`http://127.0.0.1:${m[1]}`);
    });
    backend.stderr.on('data', (d) => {
      process.stderr.write(d);
      err = (err + d).slice(-4000);
    });
    backend.on('error', reject);
    backend.on('exit', (code) => {
      backend = null;
      reject(new Error(`The Python backend exited (code ${code}) before it was ready.\n\n${err}`));
    });
  });
}

async function waitForHealth(base) {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${base}/health`);
      if (res.ok) return;
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
      webviewTag: true, // for the source PDF viewer only; locked down in will-attach-webview
    },
  });
  // The renderer never navigates or opens windows; a dropped file or a stray link must not either.
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  // The only webview is the PDF viewer: a run's source.pdf from the local API, with plugins on for
  // Chromium's built-in PDF viewer, and no preload or Node.
  win.webContents.on('will-attach-webview', (e, webPreferences, params) => {
    if (!isSourcePdf(params.src)) {
      e.preventDefault();
      return;
    }
    delete webPreferences.preload;
    Object.assign(webPreferences, { nodeIntegration: false, contextIsolation: true, sandbox: true, plugins: true });
  });
  win.once('ready-to-show', () => win.show());

  if (process.env.KLARO_RENDERER_URL) win.loadURL(process.env.KLARO_RENDERER_URL);
  else win.loadFile(path.join(__dirname, 'dist', 'index.html'));
}

function isSourcePdf(url) {
  try {
    const u = new URL(url);
    return u.origin === new URL(apiBase).origin && /^\/runs\/[^/]+\/source\.pdf$/.test(u.pathname);
  } catch {
    return false;
  }
}

// The PDF viewer may jump within the PDF but never navigate elsewhere or open windows.
app.on('web-contents-created', (_e, contents) => {
  if (contents.getType() !== 'webview') return;
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  contents.on('will-navigate', (e, url) => {
    if (!isSourcePdf(url)) e.preventDefault();
  });
});

ipcMain.handle('api-base', () => apiBase);

ipcMain.handle('open-file', async (e) => {
  const { canceled, filePaths } = await dialog.showOpenDialog(BrowserWindow.fromWebContents(e.sender), {
    properties: ['openFile'],
    filters: [{ name: 'PDF documents', extensions: ['pdf'] }],
  });
  if (canceled || filePaths.length === 0) return null;
  return { name: path.basename(filePaths[0]), data: await fs.promises.readFile(filePaths[0]) };
});

ipcMain.handle('open-external', (_e, url) => {
  if (typeof url !== 'string' || !url.startsWith('https://')) throw new Error('Only https links can be opened.');
  return shell.openExternal(url);
});

app.whenReady().then(async () => {
  try {
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
