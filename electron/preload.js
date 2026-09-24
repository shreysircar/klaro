// The renderer's only bridge to the main process. All data goes over HTTP to the backend.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('klaro', {
  getApiBase: () => ipcRenderer.invoke('api-base'),
  openFile: () => ipcRenderer.invoke('open-file'), // -> { name, data: Uint8Array } | null
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
});
