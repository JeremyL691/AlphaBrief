// Preload runs in an isolated context; expose a tiny surface to the renderer.
// The renderer only needs to know the dashboard URL and the backend port.
const { contextBridge } = require('electron');

const port = Number(process.env.ALPHABRIEF_ELECTRON_PORT || 8765);

contextBridge.exposeInMainWorld('alphabrief', {
  dashboardUrl: `http://127.0.0.1:${port}/dashboard`,
  backendPort: port,
});