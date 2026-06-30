// Electron main process for AlphaBrief.
//
// Spawns the project's FastAPI backend (`alphabrief serve serve`) as a child
// process using the project's .venv, waits for /health to return 200, then
// opens a BrowserWindow pointed at /dashboard. Streams child stderr to
// electron/backend.log. On quit the child is killed.
//
// One Python entry point is intentionally not modified — the `alphabrief`
// CLI already does everything the desktop app needs.

const { app, BrowserWindow, Tray, Menu, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

const HOST = '127.0.0.1';
// Default port differs from the launchd-managed API (8000) so we never
// collide with the operator's existing service. Override via
// ALPHABRIEF_ELECTRON_PORT env var.
const PORT = Number(process.env.ALPHABRIEF_ELECTRON_PORT || 8765);
const HEALTH_URL = `http://${HOST}:${PORT}/health`;
const DASHBOARD_URL = `http://${HOST}:${PORT}/dashboard`;

// Repo root is the parent of the electron/ directory.
const REPO_ROOT = path.resolve(__dirname, '..');
const VENV_BIN = path.join(REPO_ROOT, '.venv', 'bin');
const VENTRY_ALPHABRIEF = path.join(VENV_BIN, 'alphabrief');
const LOG_FILE = path.join(__dirname, 'backend.log');

// Lazy single-instance check — second launch focuses the existing window.
if (!app.requestSingleInstanceLock()) {
  app.quit();
  return;
}

let backendProcess = null;
let backendLogStream = null;
let mainWindow = null;
let tray = null;
let isQuitting = false;

function resolveBackendCommand() {
  // Prefer the venv's installed `alphabrief` console script — it's the
  // same one `alphabrief serve serve` invokes. Falls back to `uv run` if
  // the venv is missing (CI / cold clone).
  if (fs.existsSync(VENTRY_ALPHABRIEF)) {
    return {
      command: VENTRY_ALPHABRIEF,
      args: ['serve', 'serve', '--host', HOST, '--port', String(PORT)],
      label: 'venv alphabrief',
    };
  }
  return {
    command: 'uv',
    args: ['run', 'alphabrief', 'serve', 'serve', '--host', HOST, '--port', String(PORT)],
    label: 'uv run',
  };
}

function startBackend() {
  const { command, args, label } = resolveBackendCommand();
  backendLogStream = fs.createWriteStream(LOG_FILE, { flags: 'a' });
  backendLogStream.write(`\n--- backend start (${new Date().toISOString()}) via ${label} ---\n`);

  backendProcess = spawn(command, args, {
    cwd: REPO_ROOT,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  backendProcess.stdout.on('data', (chunk) => {
    backendLogStream.write(`[stdout] ${chunk}`);
  });
  backendProcess.stderr.on('data', (chunk) => {
    backendLogStream.write(`[stderr] ${chunk}`);
  });
  backendProcess.on('exit', (code, signal) => {
    backendLogStream.write(`--- backend exit code=${code} signal=${signal} ---\n`);
    if (!isQuitting && mainWindow) {
      mainWindow.webContents.executeJavaScript(
        `alert("AlphaBrief backend stopped (code=${code}, signal=${signal}). See electron/backend.log.");`
      ).catch(() => {});
    }
  });

  console.log(`[electron] backend spawned via ${label}, pid=${backendProcess.pid}`);
}

function waitForHealth(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  const tick = () => new Promise((resolve, reject) => {
    const req = http.get(HEALTH_URL, { timeout: 1000 }, (res) => {
      res.resume();
      if (res.statusCode === 200) resolve();
      else if (Date.now() > deadline) reject(new Error(`health ${res.statusCode}`));
      else setTimeout(tick, 250);
    });
    req.on('error', () => {
      if (Date.now() > deadline) reject(new Error('health timeout'));
      else setTimeout(tick, 250);
    });
  });
  return tick();
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    title: 'AlphaBrief Dashboard',
    backgroundColor: '#0a0e17',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => { mainWindow = null; });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.loadURL(DASHBOARD_URL).catch((err) => {
    console.error('[electron] failed to load dashboard:', err);
  });
}

function createTray() {
  // Use a built-in template image — no bundled asset needed.
  const iconPath = process.platform === 'darwin'
    ? path.join(__dirname, 'icon.png')
    : undefined;
  // On macOS, a missing icon is fine; the tray still works with a fallback.
  tray = iconPath && fs.existsSync(iconPath)
    ? new Tray(iconPath)
    : new Tray(require('electron').nativeImage.createEmpty());

  const menu = Menu.buildFromTemplate([
    { label: 'Open Dashboard', click: () => {
        if (mainWindow) mainWindow.show();
        else createWindow();
      } },
    { label: 'Open Backend Log', click: () => shell.openPath(LOG_FILE) },
    { type: 'separator' },
    { label: 'Quit AlphaBrief', click: () => { isQuitting = true; app.quit(); } },
  ]);
  tray.setToolTip('AlphaBrief');
  tray.setContextMenu(menu);
  tray.on('click', () => {
    if (mainWindow) mainWindow.show();
    else createWindow();
  });
}

function killBackend() {
  if (!backendProcess) return;
  try {
    backendProcess.kill('SIGTERM');
  } catch (e) {
    console.error('[electron] kill failed:', e);
  }
  // Hard-kill after 3s if it refuses to exit.
  setTimeout(() => {
    if (backendProcess && !backendProcess.killed) {
      try { backendProcess.kill('SIGKILL'); } catch (_) {}
    }
  }, 3000);
}

app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
});

app.on('window-all-closed', (e) => {
  // Stay alive on macOS so the tray keeps working.
  if (process.platform !== 'darwin') app.quit();
  else e?.preventDefault?.();
});

app.on('before-quit', () => { isQuitting = true; });

app.on('will-quit', () => {
  killBackend();
  if (backendLogStream) backendLogStream.end();
});

app.whenReady().then(async () => {
  startBackend();
  try {
    await waitForHealth();
    console.log('[electron] backend healthy, opening dashboard');
  } catch (err) {
    console.error('[electron] backend failed to become healthy:', err.message);
    console.error(`[electron] see ${LOG_FILE} for details`);
  }
  createWindow();
  createTray();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});