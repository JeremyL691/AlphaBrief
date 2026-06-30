# AlphaBrief Desktop (Electron wrapper)

A native macOS wrapper around the AlphaBrief FastAPI dashboard. Spawns the
project's `alphabrief serve serve` backend as a child process, waits for
`/health` to return 200, then opens a `BrowserWindow` pointed at
`/dashboard`.

## Run

```bash
cd electron
npm install
npm start
```

## What it does

1. Resolves the venv's `alphabrief` console script (falls back to
   `uv run alphabrief` if the venv is missing).
2. Spawns the FastAPI server on `127.0.0.1:8765` (default — see below).
3. Polls `/health` until it returns 200 (30 s timeout).
4. Opens a `BrowserWindow` at `http://127.0.0.1:8765/dashboard`.
5. Streams the child's stdout/stderr to `electron/backend.log`.
6. Adds a tray menu with **Open Dashboard**, **Open Backend Log**, and
   **Quit AlphaBrief**.
7. Kills the child on app quit (SIGTERM, then SIGKILL after 3 s).
8. Single-instance: a second launch focuses the existing window.

## Port choice

The default port is **8765** (not 8000) so the desktop backend never
collides with the launchd-managed `com.alphabrief.api` service that
operator setups keep on `127.0.0.1:8000`. Override with:

```bash
ALPHABRIEF_ELECTRON_PORT=9000 npm start
```

## Constraints respected

- No Python / CLI / API code in this repo was modified.
- No launchd plist was touched.
- The desktop backend is a second, isolated instance; it does not
  proxy or interfere with the operator's launchd-managed service.

## Files

- `main.js` — Electron main process: child spawn, health check,
  window, tray, shutdown.
- `preload.js` — context-isolated bridge exposing the dashboard URL.
- `package.json` — `electron` only; no extra runtime deps.
- `backend.log` — child stdout/stderr (created at runtime, gitignored).
