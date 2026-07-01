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

// Backend log rotation: cap the file at 1 MiB. When the file is
// approaching the cap (>= 768 KiB written this session), rotate to a
// single `.1` backup before opening a fresh append handle. ponytail:
// single backup rotation — a real app would use logrotate or a
// rotating-stream module, but the desktop wrapper only writes
// stdout/stderr and one backup keeps the file from growing
// unbounded across daily restarts.
const LOG_ROTATE_AT = 1024 * 1024;
const LOG_ROTATE_TRIGGER = 768 * 1024;

// Lazy single-instance check — second launch focuses the existing window.
if (!app.requestSingleInstanceLock()) {
  app.quit();
  return;
}

let backendProcess = null;
let backendLogStream = null;
let backendLogBytesThisSession = 0;
let mainWindow = null;
let tray = null;
let isQuitting = false;
let lastBackendStartFailedReason = null;

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

function rotateBackendLogIfNeeded() {
  try {
    const stat = fs.statSync(LOG_FILE);
    if (stat.size + backendLogBytesThisSession < LOG_ROTATE_AT) {
      return;
    }
    const backup = LOG_FILE + '.1';
    if (fs.existsSync(backup)) fs.unlinkSync(backup);
    fs.renameSync(LOG_FILE, backup);
  } catch (err) {
    // Best-effort rotation — fall through and continue writing.
    console.error('[electron] log rotation failed:', err.message);
  }
  backendLogBytesThisSession = 0;
}

function writeBackendLog(chunk) {
  if (!backendLogStream) return;
  // 4-byte prefix per chunk + chunk length in bytes — close enough to
  // bound the on-disk size without counting UTF-8 multibyte widths.
  const overhead = 12; // "[stdout] " / "[stderr] " prefix
  backendLogBytesThisSession += chunk.length + overhead;
  if (backendLogBytesThisSession >= LOG_ROTATE_TRIGGER) {
    rotateBackendLogIfNeeded();
  }
  backendLogStream.write(chunk);
}

function openBackendLogStream() {
  // Append mode, same as before — only rotate when the on-disk file is
  // large enough that a new session's writes would push it past the cap.
  return fs.createWriteStream(LOG_FILE, { flags: 'a' });
}

function startBackend() {
  const { command, args, label } = resolveBackendCommand();
  backendLogStream = openBackendLogStream();
  const banner = `\n--- backend start (${new Date().toISOString()}) via ${label} ---\n`;
  backendLogBytesThisSession += banner.length;
  backendLogStream.write(banner);
  lastBackendStartFailedReason = null;

  backendProcess = spawn(command, args, {
    cwd: REPO_ROOT,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  backendProcess.stdout.on('data', (chunk) => {
    writeBackendLog(`[stdout] ${chunk}`);
  });
  backendProcess.stderr.on('data', (chunk) => {
    writeBackendLog(`[stderr] ${chunk}`);
  });
  backendProcess.on('exit', (code, signal) => {
    if (backendLogStream) {
      backendLogStream.write(
        `--- backend exit code=${code} signal=${signal} ---\n`
      );
    }
    if (!isQuitting) {
      lastBackendStartFailedReason =
        `backend exited (code=${code}, signal=${signal}) before becoming healthy`;
      showErrorOverlay(lastBackendStartFailedReason);
    }
  });
  backendProcess.on('error', (err) => {
    lastBackendStartFailedReason = `failed to spawn backend: ${err.message}`;
    showErrorOverlay(lastBackendStartFailedReason);
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

const ERROR_OVERLAY = path.join(__dirname, 'error-overlay.html');

function buildErrorOverlayUrl(message) {
  const params = new URLSearchParams({ message: message || 'Unknown error.' });
  return `file://${ERROR_OVERLAY}?${params.toString()}`;
}

function showErrorOverlay(message) {
  if (!mainWindow) {
    createWindow({ initialError: message });
    return;
  }
  mainWindow.loadURL(buildErrorOverlayUrl(message)).catch((err) => {
    console.error('[electron] failed to load error overlay:', err);
  });
}

function createWindow({ initialError } = {}) {
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

  if (initialError) {
    mainWindow.loadURL(buildErrorOverlayUrl(initialError)).catch((err) => {
      console.error('[electron] failed to load error overlay:', err);
    });
    return;
  }

  mainWindow.loadURL(DASHBOARD_URL).catch((err) => {
    console.error('[electron] failed to load dashboard:', err);
    if (lastBackendStartFailedReason) {
      mainWindow.loadURL(buildErrorOverlayUrl(lastBackendStartFailedReason)).catch(() => {});
    }
  });
}

function restartBackend() {
  if (backendProcess && !backendProcess.killed) {
    try {
      backendProcess.kill('SIGTERM');
    } catch (e) {
      console.error('[electron] kill failed:', e);
    }
    // Wait briefly for graceful exit, then force.
    setTimeout(() => {
      if (backendProcess && !backendProcess.killed) {
        try { backendProcess.kill('SIGKILL'); } catch (_) {}
      }
      backendProcess = null;
      if (backendLogStream) {
        backendLogStream.end();
        backendLogStream = null;
      }
      startBackend();
      waitForHealth().catch((err) => {
        showErrorOverlay(`backend restart failed: ${err.message}`);
      });
    }, 1500);
  } else {
    backendProcess = null;
    startBackend();
    waitForHealth().catch((err) => {
      showErrorOverlay(`backend start failed: ${err.message}`);
    });
  }
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
        if (!mainWindow) createWindow();
        else {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.show();
          mainWindow.focus();
        }
      } },
    { label: 'Restart Backend', click: () => restartBackend() },
    { label: 'Open Backend Log', click: () => shell.openPath(LOG_FILE) },
    { type: 'separator' },
    { label: 'Quit AlphaBrief', click: () => { isQuitting = true; app.quit(); } },
  ]);
  tray.setToolTip('AlphaBrief');
  tray.setContextMenu(menu);
  tray.on('click', () => {
    if (!mainWindow) createWindow();
    else {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

function focusMainWindow() {
  if (!mainWindow) {
    createWindow();
    return;
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  if (!mainWindow.isVisible()) mainWindow.show();
  mainWindow.focus();
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
  // Bring the existing window to front instead of silently discarding
  // the second launch — the previous behaviour did this on most
  // platforms but could leave the window hidden on macOS, so we
  // always call focusMainWindow() now.
  focusMainWindow();
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
  let backendHealthy = false;
  try {
    await waitForHealth();
    console.log('[electron] backend healthy, opening dashboard');
    backendHealthy = true;
  } catch (err) {
    console.error('[electron] backend failed to become healthy:', err.message);
    console.error(`[electron] see ${LOG_FILE} for details`);
    lastBackendStartFailedReason = err.message;
  }
  createWindow(backendHealthy ? {} : { initialError: lastBackendStartFailedReason || 'backend health check failed' });
  createTray();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});