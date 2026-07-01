// Preload runs in an isolated context; expose a tiny surface to the renderer.
// The renderer only needs to know the dashboard URL, the backend port, and
// how to subscribe to backend-error events from the main process.
const { contextBridge, ipcRenderer } = require('electron');

const port = Number(process.env.ALPHABRIEF_ELECTRON_PORT || 8765);

contextBridge.exposeInMainWorld('alphabrief', {
  dashboardUrl: `http://127.0.0.1:${port}/dashboard`,
  backendPort: port,
  onBackendError: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on('alphabrief:backend-error', listener);
    return () => ipcRenderer.removeListener('alphabrief:backend-error', listener);
  },
});