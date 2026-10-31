// The renderer's only bridge to the main process. All data goes over HTTP to the backend.
const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('klaro', {
  getApiBase: () => ipcRenderer.invoke('api-base'),
  openFile: () => ipcRenderer.invoke('open-file'), // -> { name, path, data: Uint8Array } | null
  // Takes a path string or a dropped File. -> { language: 'de' | 'en' | 'unknown', confidence }
  detectLanguage: (fileOrPath) =>
    ipcRenderer.invoke('detect-language', typeof fileOrPath === 'string' ? fileOrPath : webUtils.getPathForFile(fileOrPath)),
  checkTranslator: () => ipcRenderer.invoke('check-translator'), // -> { ok, error }
  getSource: (runId) => ipcRenderer.invoke('get-source', runId), // -> Uint8Array of the run's PDF
  getTranslation: (runId) => ipcRenderer.invoke('get-translation', runId), // -> segments.json | null
  // Save dialog, then prints the pages ([{ jpeg: Uint8Array, w, h }]) as a PDF. -> path | null
  saveEnglishPdf: (name, pages) => ipcRenderer.invoke('save-english-pdf', name, pages),
  getEvidence: (runId) => ipcRenderer.invoke('get-evidence', runId), // -> evidence.json | null
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
});
