"""Dashboard routes — serves a multi-page HTML dashboard (Phase 15 redesign)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])


# ---------------------------------------------------------------------------
# Design system
# ---------------------------------------------------------------------------

_BASE_STYLES = """
:root {
  --bg: #0a0e17;
  --bg-elev-1: #0f1623;
  --bg-elev-2: #111827;
  --bg-elev-3: #0f172a;
  --border: #1e293b;
  --border-strong: #2a3a52;
  --text: #e2e8f0;
  --text-dim: #94a3b8;
  --text-muted: #64748b;
  --accent: #00d4ff;
  --accent-dim: #0891b2;
  --accent-glow: rgba(0, 212, 255, 0.18);
  --green: #22c55e;
  --green-dim: rgba(34, 197, 94, 0.16);
  --red: #ef4444;
  --red-dim: rgba(239, 68, 68, 0.16);
  --amber: #f59e0b;
  --amber-dim: rgba(245, 158, 11, 0.16);
  --font-sans: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Monaco, Consolas, monospace;
  --radius: 8px;
  --radius-sm: 4px;
  --shadow-card: 0 1px 0 rgba(255, 255, 255, 0.02) inset, 0 1px 2px rgba(0, 0, 0, 0.3);
  --shadow-hover: 0 0 0 1px var(--accent), 0 8px 24px rgba(0, 212, 255, 0.08);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

html, body { height: 100%; }

body {
  font-family: var(--font-sans);
  background:
    radial-gradient(1200px 600px at 50% -200px, rgba(0, 212, 255, 0.04), transparent 60%),
    var(--bg);
  color: var(--text);
  font-size: 14px;
  line-height: 1.5;
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

a { color: var(--accent); text-decoration: none; }
a:hover { color: #67e8f9; }

code, pre, .mono { font-family: var(--font-mono); }

/* App shell ---------------------------------------------------------------- */

.app-header {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(15, 22, 35, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
}

.app-header__inner {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0.875rem 1.5rem;
  display: flex;
  align-items: center;
  gap: 1rem;
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  font-weight: 600;
  font-size: 0.95rem;
  letter-spacing: -0.01em;
  color: var(--text);
}

.brand__mark {
  width: 22px; height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 5px;
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent-dim) 100%);
  color: var(--bg);
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 11px;
}

.brand__sub {
  color: var(--text-dim);
  font-weight: 400;
  font-size: 0.8rem;
  margin-left: 0.5rem;
  padding-left: 0.75rem;
  border-left: 1px solid var(--border);
}

.header-meta {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--text-dim);
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border: 1px solid var(--border-strong);
  background: var(--bg-elev-2);
  color: var(--text-dim);
}

.pill--accent { color: var(--accent); border-color: rgba(0, 212, 255, 0.35); background: rgba(0, 212, 255, 0.06); }
.pill--green { color: var(--green); border-color: rgba(34, 197, 94, 0.35); background: var(--green-dim); }
.pill--amber { color: var(--amber); border-color: rgba(245, 158, 11, 0.35); background: var(--amber-dim); }
.pill--red   { color: var(--red);   border-color: rgba(239, 68, 68, 0.35);  background: var(--red-dim);   }

/* Nav ---------------------------------------------------------------------- */

.app-nav {
  border-bottom: 1px solid var(--border);
  background: rgba(10, 14, 23, 0.7);
}

.app-nav__inner {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 1.5rem;
  display: flex;
  gap: 0.25rem;
  overflow-x: auto;
  scrollbar-width: none;
}

.app-nav__inner::-webkit-scrollbar { display: none; }

.nav-link {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.75rem 0.875rem;
  color: var(--text-dim);
  font-size: 0.825rem;
  font-weight: 500;
  letter-spacing: 0.01em;
  white-space: nowrap;
  transition: color 0.15s var(--ease);
}

.nav-link:hover { color: var(--text); }

.nav-link::after {
  content: "";
  position: absolute;
  left: 0.875rem; right: 0.875rem;
  bottom: -1px;
  height: 2px;
  background: var(--accent);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 0.2s var(--ease);
}

.nav-link.active {
  color: var(--accent);
}

.nav-link.active::after { transform: scaleX(1); }

.nav-link__dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.6;
}

/* Main --------------------------------------------------------------------- */

main {
  max-width: 1280px;
  margin: 0 auto;
  padding: 1.5rem 1.5rem 4rem;
}

.page-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.page-head h1 {
  font-size: 1.25rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text);
}

.page-head p {
  font-size: 0.8rem;
  color: var(--text-dim);
  margin-top: 0.25rem;
}

.page-head__meta {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

/* Grid + cards ------------------------------------------------------------- */

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 1rem;
}

.grid--3 { grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }

.card {
  position: relative;
  background: linear-gradient(180deg, var(--bg-elev-2) 0%, var(--bg-elev-1) 100%);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.125rem 1.25rem;
  box-shadow: var(--shadow-card);
  transition: transform 0.18s var(--ease), border-color 0.18s var(--ease), box-shadow 0.18s var(--ease);
}

.card:hover {
  transform: translateY(-2px);
  border-color: var(--border-strong);
  box-shadow: var(--shadow-hover);
}

.card--full { grid-column: 1 / -1; }

.card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.875rem;
}

.card__title {
  font-size: 0.7rem;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 600;
}

.card__hint {
  font-size: 0.7rem;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.card__value {
  font-family: var(--font-mono);
  font-size: 1.75rem;
  font-weight: 600;
  color: var(--text);
  line-height: 1.15;
  letter-spacing: -0.01em;
  word-break: break-word;
}

.card__value--small { font-size: 1rem; font-weight: 500; }

.card__value--green { color: var(--green); }
.card__value--red   { color: var(--red); }

.card__label {
  font-size: 0.75rem;
  color: var(--text-dim);
  margin-top: 0.5rem;
  font-family: var(--font-mono);
}

.card__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--border);
  font-size: 0.825rem;
}

.card__row:last-child { border-bottom: none; }

.card__row-key { color: var(--text-dim); }
.card__row-val {
  font-family: var(--font-mono);
  color: var(--text);
}

.card__advisory {
  margin-top: 0.75rem;
  padding: 0.625rem 0.75rem;
  border-left: 2px solid var(--amber);
  background: rgba(245, 158, 11, 0.04);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  font-size: 0.75rem;
  color: var(--text-dim);
  line-height: 1.5;
}

.card__advisory code {
  font-size: 0.75rem;
  color: var(--text);
  background: var(--bg-elev-3);
  padding: 0.05rem 0.3rem;
  border-radius: 3px;
}

/* Status dot -------------------------------------------------------------- */

.status {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.825rem;
  color: var(--text);
}

.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  position: relative;
}

.status-dot.ok   { background: var(--green); box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.5); animation: pulse-ok 2.4s var(--ease) infinite; }
.status-dot.warn { background: var(--amber); box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.5); animation: pulse-warn 2.4s var(--ease) infinite; }
.status-dot.err  { background: var(--red);   box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.5);  animation: pulse-err 2.4s var(--ease) infinite;  }

@keyframes pulse-ok   { 0%, 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.45);  } 70% { box-shadow: 0 0 0 6px rgba(34, 197, 94, 0); } }
@keyframes pulse-warn { 0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.45); } 70% { box-shadow: 0 0 0 6px rgba(245, 158, 11, 0); } }
@keyframes pulse-err  { 0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.45);  } 70% { box-shadow: 0 0 0 6px rgba(239, 68, 68, 0);  } }

/* Tables ------------------------------------------------------------------- */

.table-wrap {
  overflow-x: auto;
  margin: -0.25rem;
  padding: 0.25rem;
}

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 0.825rem;
}

thead th {
  position: sticky;
  top: 0;
  background: var(--bg-elev-1);
  color: var(--text-dim);
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  text-align: left;
  padding: 0.625rem 0.75rem;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

tbody td {
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  vertical-align: middle;
}

tbody tr {
  transition: background 0.12s var(--ease);
}

tbody tr:hover { background: rgba(0, 212, 255, 0.04); }
tbody tr:last-child td { border-bottom: none; }

td.mono, td.num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

td.num--pos { color: var(--green); }
td.num--neg { color: var(--red); }

td.dim { color: var(--text-dim); }

td.title { max-width: 28rem; }
td.title-inner { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

td .pill { font-size: 0.65rem; padding: 0.1rem 0.4rem; }

.row-action {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--accent);
}

.row-action:hover { text-decoration: underline; }

/* Badges ------------------------------------------------------------------ */

.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.15rem 0.5rem;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border: 1px solid transparent;
}

.badge--on  { color: var(--green); background: var(--green-dim); border-color: rgba(34, 197, 94, 0.25); }
.badge--off { color: var(--text-dim); background: rgba(148, 163, 184, 0.08); border-color: rgba(148, 163, 184, 0.18); }

/* Chart ------------------------------------------------------------------- */

.chart-wrap {
  position: relative;
  height: 200px;
  margin: 0.25rem 0;
}

canvas { display: block; width: 100%; height: 100%; }

.chart-meta {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.chart-meta__value {
  font-family: var(--font-mono);
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text);
}

.chart-meta__delta {
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: var(--green);
}

.chart-meta__hint {
  font-size: 0.7rem;
  color: var(--text-muted);
  font-family: var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

/* Detail blocks (brief / debate JSON) ------------------------------------ */

.detail-pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--text-dim);
  background: var(--bg-elev-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 1rem;
  max-height: 480px;
  overflow: auto;
  line-height: 1.55;
}

/* States ----------------------------------------------------------------- */

.loading, .empty {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--text-muted);
  font-size: 0.825rem;
  font-style: italic;
  padding: 0.5rem 0;
}

.error { color: var(--red); font-size: 0.825rem; }

.skeleton {
  display: block;
  background: linear-gradient(
    90deg,
    var(--bg-elev-3) 0%,
    var(--border) 50%,
    var(--bg-elev-3) 100%
  );
  background-size: 200% 100%;
  border-radius: 4px;
  animation: skeleton-shimmer 1.4s linear infinite;
  height: 0.85rem;
  margin: 0.35rem 0;
}
.skeleton--value { height: 1.75rem; width: 60%; }
.skeleton--short { width: 40%; }
.skeleton--line  { width: 100%; }

@keyframes skeleton-shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  vertical-align: middle;
}
@keyframes spin { to { transform: rotate(360deg); } }

.refresh-indicator {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-left: 0.75rem;
}
.refresh-indicator.is-spinning .spinner { animation-play-state: running; }
.refresh-indicator:not(.is-spinning) .spinner {
  animation-play-state: paused;
  border-top-color: var(--accent-dim);
}

/* Footer ------------------------------------------------------------------ */

.app-footer {
  border-top: 1px solid var(--border);
  background: rgba(10, 14, 23, 0.7);
  margin-top: 3rem;
}

.app-footer__inner {
  max-width: 1280px;
  margin: 0 auto;
  padding: 1rem 1.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--text-muted);
}

.app-footer__inner a { color: var(--text-dim); }
.app-footer__inner a:hover { color: var(--accent); }

.app-footer__left, .app-footer__right { display: flex; align-items: center; gap: 0.875rem; }

/* Responsive -------------------------------------------------------------- */

@media (max-width: 720px) {
  .app-header__inner { padding: 0.75rem 1rem; flex-wrap: wrap; }
  .header-meta { width: 100%; margin-left: 0; }
  main { padding: 1rem 1rem 3rem; }
  .grid { grid-template-columns: 1fr; }
  .card__value { font-size: 1.5rem; }
  .app-footer__inner { flex-direction: column; align-items: flex-start; gap: 0.5rem; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
}
""".strip()


# ---------------------------------------------------------------------------
# Nav definition
# ---------------------------------------------------------------------------

_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("/dashboard", "Main", "main"),
    ("/dashboard/news", "News", "news"),
    ("/dashboard/macro", "Macro", "macro"),
    ("/dashboard/brief", "Briefs", "brief"),
    ("/dashboard/debate", "Debate", "debate"),
    ("/dashboard/models", "Models", "models"),
    ("/dashboard/strategies", "Strategies", "strategies"),
    ("/dashboard/ai-trading", "AI Trading", "ai-trading"),
]


def _nav(active: str) -> str:
    parts: list[str] = []
    for href, label, key in _NAV_ITEMS:
        cls = "nav-link active" if key == active else "nav-link"
        parts.append(
            f'<a href="{href}" class="{cls}" data-nav="{key}">'
            f'<span class="nav-link__dot" aria-hidden="true"></span>'
            f"{label}</a>"
        )
    return (
        '<nav class="app-nav" aria-label="Primary">'
        f'<div class="app-nav__inner">{"".join(parts)}</div>'
        "</nav>"
    )


# ---------------------------------------------------------------------------
# Common scripts
# ---------------------------------------------------------------------------

_COMMON_SCRIPTS = r"""
async function fetchJSON(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(res.status);
    return await res.json();
  } catch (err) {
    return null;
  }
}

function escapeHtml(text) {
  if (text === null || text === undefined) return "";
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

function fmtNumber(v, opts) {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(opts && opts.locale ? opts.locale : "en-US", opts || {});
}

function fmtPct(v, digits) {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return (n * 100).toFixed(digits === undefined ? 2 : digits) + "%";
}

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toISOString().replace("T", " ").replace(/\..*$/, "Z");
  } catch (e) {
    return String(iso);
  }
}

function headerClock() {
  const el = document.getElementById("header-time");
  if (!el) return;
  const tick = () => {
    const d = new Date();
    el.textContent = d.toISOString().replace("T", " ").replace(/\..*$/, "Z");
  };
  tick();
  setInterval(tick, 1000);
}

document.addEventListener("DOMContentLoaded", headerClock);

// ---------------------------------------------------------------------------
// Canvas chart helpers (Phase 32: shared by main + AI trading dashboards)
// ---------------------------------------------------------------------------

// Resize a canvas to its CSS box for HiDPI rendering. Returns {ctx, w, h}.
function setupChartCanvas(canvas) {
  if (!canvas) return null;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(1, Math.floor(rect.width));
  const h = Math.max(1, Math.floor(rect.height));
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx: ctx, w: w, h: h };
}

// Draw a line chart of {t, v} points. Auto-scales; renders axes + grid.
function drawLineChart(canvasId, points, opts) {
  const canvas = document.getElementById(canvasId);
  const setup = setupChartCanvas(canvas);
  if (!setup) return;
  const { ctx, w, h } = setup;
  const padL = 44, padR = 12, padT = 14, padB = 22;
  ctx.clearRect(0, 0, w, h);
  if (!points || points.length === 0) {
    ctx.fillStyle = "#64748b";
    ctx.font = "12px var(--font-sans, sans-serif)";
    ctx.textAlign = "center";
    ctx.fillText("no data", w / 2, h / 2);
    return;
  }
  // ponytail: O(n) single-pass for min/max; stdlib Math.min/max covers it.
  let vMin = Infinity, vMax = -Infinity, tMin = Infinity, tMax = -Infinity;
  for (const p of points) {
    if (p.v < vMin) vMin = p.v;
    if (p.v > vMax) vMax = p.v;
    if (p.t < tMin) tMin = p.t;
    if (p.t > tMax) tMax = p.t;
  }
  if (vMin === vMax) { vMin -= 1; vMax += 1; }
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const sx = (t) => tMin === tMax ? padL + innerW / 2 : padL + ((t - tMin) / (tMax - tMin)) * innerW;
  const sy = (v) => padT + (1 - (v - vMin) / (vMax - vMin)) * innerH;
  // Grid + Y axis labels (4 ticks).
  ctx.strokeStyle = "rgba(148, 163, 184, 0.12)";
  ctx.fillStyle = "#64748b";
  ctx.font = "10px var(--font-mono, monospace)";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 3; i++) {
    const v = vMin + (vMax - vMin) * (i / 3);
    const y = sy(v);
    ctx.beginPath();
    ctx.moveTo(padL, y); ctx.lineTo(w - padR, y);
    ctx.stroke();
    ctx.fillText(v.toLocaleString("en-US", { maximumFractionDigits: 0 }), padL - 6, y);
  }
  // X axis labels (start / mid / end).
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const fmtX = (opts && opts.fmtX) || ((t) => new Date(t).toISOString().slice(5, 10));
  const xTicks = points.length === 1 ? [tMin] : [tMin, (tMin + tMax) / 2, tMax];
  xTicks.forEach((t) => ctx.fillText(fmtX(t), sx(t), h - padB + 4));
  // Line + fill.
  const lineColor = (opts && opts.color) || "#00d4ff";
  const fillColor = (opts && opts.fillColor) || "rgba(0, 212, 255, 0.12)";
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = sx(p.t), y = sy(p.v);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = lineColor;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.stroke();
  // Area fill.
  ctx.lineTo(sx(points[points.length - 1].t), padT + innerH);
  ctx.lineTo(sx(points[0].t), padT + innerH);
  ctx.closePath();
  ctx.fillStyle = fillColor;
  ctx.fill();
  // Latest-point dot.
  const last = points[points.length - 1];
  ctx.beginPath();
  ctx.arc(sx(last.t), sy(last.v), 3.5, 0, Math.PI * 2);
  ctx.fillStyle = lineColor;
  ctx.fill();
}

// Draw a donut chart. segments = [{label, value, color}]. Renders a centered
// legend on the right when wider than 220px.
function drawDonut(canvasId, segments) {
  const canvas = document.getElementById(canvasId);
  const setup = setupChartCanvas(canvas);
  if (!setup) return;
  const { ctx, w, h } = setup;
  ctx.clearRect(0, 0, w, h);
  const total = segments.reduce((s, x) => s + Math.max(0, x.value || 0), 0);
  if (total <= 0) {
    ctx.fillStyle = "#64748b";
    ctx.font = "12px var(--font-sans, sans-serif)";
    ctx.textAlign = "center";
    ctx.fillText("no votes", w / 2, h / 2);
    return;
  }
  const cx = w / 2, cy = h / 2;
  const radius = Math.min(w, h) * 0.36;
  const innerR = radius * 0.62;
  let start = -Math.PI / 2;
  for (const seg of segments) {
    const v = Math.max(0, seg.value || 0);
    if (v === 0) continue;
    const sweep = (v / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, start, start + sweep);
    ctx.closePath();
    ctx.fillStyle = seg.color;
    ctx.fill();
    start += sweep;
  }
  // Donut hole.
  ctx.beginPath();
  ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
  ctx.fillStyle = "#0f1623";
  ctx.fill();
  // Center label = total.
  ctx.fillStyle = "#e2e8f0";
  ctx.font = "600 16px var(--font-mono, monospace)";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(String(total), cx, cy - 6);
  ctx.fillStyle = "#64748b";
  ctx.font = "10px var(--font-sans, sans-serif)";
  ctx.fillText("votes", cx, cy + 10);
}
""".strip()


# ---------------------------------------------------------------------------
# Shell builder
# ---------------------------------------------------------------------------

_APP_VERSION = "v0.0.0"


def _shell(
    active: str,
    title: str,
    subtitle: str,
    body: str,
    scripts: str = "",
    meta: str = "",
) -> str:
    nav = _nav(active)
    extra = f"<script>\n{scripts}\n</script>" if scripts else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{title} - AlphaBrief</title>\n"
        "<style>\n"
        f"{_BASE_STYLES}\n"
        "</style>\n"
        "</head>\n"
        f'<body data-active="{active}">\n'
        '<header class="app-header">\n'
        '<div class="app-header__inner">\n'
        '<div class="brand">\n'
        '<span class="brand__mark" aria-hidden="true">A</span>\n'
        "AlphaBrief\n"
        '<span class="brand__sub">Local-first AI quant research</span>\n'
        "</div>\n"
        '<div class="header-meta">\n'
        f'<span id="header-time" class="mono" aria-label="UTC time">—</span>\n'
        f"{meta}\n"
        "</div>\n"
        "</div>\n"
        "</header>\n"
        f"{nav}\n"
        "<main>\n"
        '<div class="page-head">\n'
        f"<div><h1>{title}</h1><p>{subtitle}</p></div>\n"
        f"{('<div class="page-head__meta">' + meta + '</div>') if meta else ''}"
        "</div>\n"
        f"{body}\n"
        "</main>\n"
        '<footer class="app-footer">\n'
        '<div class="app-footer__inner">\n'
        '<div class="app-footer__left">\n'
        f"<span>AlphaBrief {_APP_VERSION}</span>\n"
        '<span aria-hidden="true">·</span>\n'
        '<a href="/docs">API Docs</a>\n'
        '<span aria-hidden="true">·</span>\n'
        '<a href="/redoc">ReDoc</a>\n'
        "</div>\n"
        '<div class="app-footer__right">\n'
        '<span class="status"><span class="status-dot ok" aria-hidden="true"></span>API ready</span>\n'
        "</div>\n"
        "</div>\n"
        "</footer>\n"
        "<script>\n"
        f"{_COMMON_SCRIPTS}\n"
        "</script>\n"
        f"{extra}\n"
        "</body>\n"
        "</html>"
    )


# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------

_DASHBOARD_BODY = """
<section class="grid grid--3">
  <article class="card">
    <div class="card__head"><span class="card__title">Project Status</span><span id="project-status-pill"></span></div>
    <div id="project-status" class="loading">
      <div class="skeleton skeleton--line"></div>
      <div class="skeleton skeleton--line skeleton--short"></div>
    </div>
  </article>

  <article class="card">
    <div class="card__head"><span class="card__title">Data Symbols</span><span class="card__hint" id="data-symbols-hint">—</span></div>
    <div id="data-symbols" class="loading">
      <div class="skeleton skeleton--value"></div>
    </div>
  </article>

  <article class="card">
    <div class="card__head"><span class="card__title">Risk Status</span><span id="risk-status-pill"></span></div>
    <div id="risk-status" class="loading">
      <div class="skeleton skeleton--line"></div>
      <div class="skeleton skeleton--line skeleton--short"></div>
    </div>
  </article>

  <article class="card">
    <div class="card__head"><span class="card__title">Scheduler</span><span id="scheduler-status-pill"></span></div>
    <div id="scheduler-status" class="loading">
      <div class="skeleton skeleton--line"></div>
      <div class="skeleton skeleton--line skeleton--short"></div>
    </div>
  </article>

  <article class="card">
    <div class="card__head"><span class="card__title">Last Backtest</span><span class="card__hint" id="last-backtest-hint">—</span></div>
    <div id="last-backtest" class="loading">
      <div class="skeleton skeleton--value"></div>
    </div>
  </article>

  <article class="card">
    <div class="card__head"><span class="card__title">Last Brief</span><span class="card__hint" id="last-brief-hint">—</span></div>
    <div id="last-brief" class="loading">
      <div class="skeleton skeleton--value"></div>
    </div>
  </article>

  <article class="card">
    <div class="card__head"><span class="card__title">Paper Portfolio</span><span class="card__hint" id="portfolio-hint">—</span></div>
    <div id="portfolio" class="loading">
      <div class="skeleton skeleton--value"></div>
    </div>
  </article>

  <article class="card card--full">
    <div class="card__head"><span class="card__title">Positions</span><span class="card__hint" id="positions-hint">—</span></div>
    <div id="positions" class="loading">
      <div class="skeleton skeleton--line"></div>
      <div class="skeleton skeleton--line"></div>
      <div class="skeleton skeleton--line skeleton--short"></div>
    </div>
  </article>

  <article class="card card--full">
    <div class="card__head"><span class="card__title">Equity Curve</span><span class="card__hint">Simulated sample</span></div>
    <div class="chart-meta">
      <div>
        <div class="chart-meta__value" id="equity-latest">—</div>
        <div class="chart-meta__delta" id="equity-delta">—</div>
      </div>
      <div class="chart-meta__hint">20 sample points · USD</div>
    </div>
    <div class="chart-wrap"><canvas id="equity-canvas"></canvas></div>
  </article>

  <article class="card card--full">
    <div class="card__head"><span class="card__title">Recent Fills</span><span class="card__hint">order_created · latest 5</span></div>
    <div id="recent-fills" class="loading">
      <div class="skeleton skeleton--line"></div>
      <div class="skeleton skeleton--line"></div>
    </div>
  </article>

  <article class="card card--full">
    <div class="card__head"><span class="card__title">Model Performance</span><span class="card__hint">latest schema pass rate</span></div>
    <div id="model-performance" class="loading">
      <div class="skeleton skeleton--line"></div>
      <div class="skeleton skeleton--line"></div>
      <div class="skeleton skeleton--line skeleton--short"></div>
    </div>
  </article>
</section>
""".strip()


_DASHBOARD_JS = """
const REFRESH_INTERVAL_MS = 30000;

function setSkeleton(elementId, lines) {
  // lines: array of {modifier: "value"|"short"|""} or null to clear
  const el = document.getElementById(elementId);
  if (!el) return;
  if (!lines) {
    el.classList.remove("loading");
    return;
  }
  el.classList.add("loading");
  el.innerHTML = lines.map(function (l) {
    const mod = l && l.modifier ? " skeleton--" + l.modifier : "";
    return '<div class="skeleton' + mod + '"></div>';
  }).join("");
}

function setRefreshIndicator(spinning) {
  const el = document.getElementById("refresh-indicator");
  if (!el) return;
  if (spinning) el.classList.add("is-spinning");
  else el.classList.remove("is-spinning");
  const ts = document.getElementById("refresh-timestamp");
  if (ts) {
    const d = new Date();
    ts.textContent = "updated " + d.toISOString().replace("T", " ").replace(/\..*$/, "Z");
  }
}

function fmtInterval(ms) {
  if (ms === null || ms === undefined) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return s + "s ago";
  const m = Math.floor(s / 60);
  if (m < 60) return m + "m ago";
  const h = Math.floor(m / 60);
  return h + "h ago";
}

function lastRunAge(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return Date.now() - d.getTime();
}

async function loadScheduler() {
  const el = document.getElementById("scheduler-status");
  const pill = document.getElementById("scheduler-status-pill");
  if (!el) return;
  // 503 + scheduler_writer_locked is a graceful degradation, not an error.
  const data = await fetchJSON("/api/v1/scheduler/status");
  if (!data) {
    el.classList.remove("loading");
    el.innerHTML = '<div class="error">Failed to load</div>';
    if (pill) pill.innerHTML = '<span class="pill pill--red">UNREACHABLE</span>';
    return;
  }
  if (data && data.kind === "scheduler_writer_locked") {
    el.classList.remove("loading");
    el.innerHTML =
      '<div class="status">'
      + '<span class="status-dot warn" aria-hidden="true"></span>'
      + 'Scheduler writer active — data unavailable'
      + '</div>'
      + '<div class="card__label">The launchd-managed scheduler process holds the DuckDB writer lock.</div>';
    if (pill) pill.innerHTML = '<span class="pill pill--amber">WRITER ACTIVE</span>';
    return;
  }
  el.classList.remove("loading");
  const beats = Number(data.heartbeat_count || 0);
  const freezes = Number(data.open_freeze_count || 0);
  const alerts = Number(data.alerts_total || 0);
  el.innerHTML =
    '<div class="status">'
    + '<span class="status-dot ' + (freezes > 0 ? "err" : (beats > 0 ? "ok" : "warn")) + '" aria-hidden="true"></span>'
    + beats + ' task' + (beats === 1 ? '' : 's') + ' · ' + freezes + ' freeze' + (freezes === 1 ? '' : 's') + ' · ' + alerts + ' alert' + (alerts === 1 ? '' : 's')
    + '</div>'
    + '<div class="card__label">read-only · writer may be in a separate process</div>';
  if (pill) {
    pill.innerHTML = freezes > 0
      ? '<span class="pill pill--red">FROZEN</span>'
      : '<span class="pill pill--green">READY</span>';
  }
}

async function loadHeartbeatsForLastRun() {
  const data = await fetchJSON("/api/v1/scheduler/heartbeats");
  if (!data) return null;
  return data.heartbeats || [];
}

async function loadDashboard() {
  setRefreshIndicator(true);
  const [status, symbols, reports, briefs, portfolio, risk, orders, schedulerData, heartbeats] = await Promise.all([
    fetchJSON("/api/status"),
    fetchJSON("/api/v1/data/symbols"),
    fetchJSON("/api/v1/backtest/reports"),
    fetchJSON("/api/v1/brief/history"),
    fetchJSON("/api/v1/paper/portfolio"),
    fetchJSON("/api/v1/risk/dashboard"),
    fetchJSON("/api/v1/paper/orders?status=order_created"),
    fetchJSON("/api/v1/scheduler/status"),
    fetchJSON("/api/v1/scheduler/heartbeats"),
  ]);

  // Project status
  if (status) {
    const envPill = status.environment === "production"
      ? '<span class="pill pill--accent">PROD</span>'
      : '<span class="pill">DEV</span>';
    const livePill = status.live_trading_enabled
      ? '<span class="pill pill--red">LIVE ON</span>'
      : '<span class="pill pill--green">LIVE OFF</span>';
    document.getElementById("project-status-pill").innerHTML = envPill + " " + livePill;
    document.getElementById("project-status").classList.remove("loading");
    document.getElementById("project-status").innerHTML =
      '<div class="card__value">' + escapeHtml(status.environment) + '</div>'
      + '<div class="card__label">'
      + (status.live_trading_enabled ? "Live trading enabled" : "Paper trading only")
      + '</div>';
  } else {
    document.getElementById("project-status-pill").innerHTML = "";
    document.getElementById("project-status").classList.remove("loading");
    document.getElementById("project-status").innerHTML = '<div class="error">Failed to load</div>';
  }

  // Data symbols
  if (symbols) {
    const n = (symbols.symbols || []).length;
    document.getElementById("data-symbols-hint").textContent = "universe";
    document.getElementById("data-symbols").classList.remove("loading");
    document.getElementById("data-symbols").innerHTML =
      '<div class="card__value">' + n + '</div>'
      + '<div class="card__label">loaded symbols</div>';
  } else {
    document.getElementById("data-symbols").classList.remove("loading");
    document.getElementById("data-symbols").innerHTML = '<div class="error">Failed to load</div>';
  }

  // Risk status
  if (risk) {
    const ks = !!risk.kill_switch_active;
    const te = !!risk.config && risk.config.trading_enabled;
    document.getElementById("risk-status-pill").innerHTML = te
      ? '<span class="pill pill--green">TRADING ON</span>'
      : '<span class="pill pill--amber">TRADING OFF</span>';
    document.getElementById("risk-status").classList.remove("loading");
    document.getElementById("risk-status").innerHTML =
      '<div class="status">'
      + '<span class="status-dot ' + (ks ? "err" : "ok") + '" aria-hidden="true"></span>'
      + (ks ? "Kill switch active" : "Risk gate ok")
      + '</div>'
      + '<div class="card__label">' + (te ? "Orders accepted" : "Orders blocked") + '</div>';
  } else {
    document.getElementById("risk-status").classList.remove("loading");
    document.getElementById("risk-status").innerHTML = '<div class="error">Failed to load</div>';
  }

  // Scheduler status (graceful degradation for writer-lock 503)
  const elSched = document.getElementById("scheduler-status");
  const pillSched = document.getElementById("scheduler-status-pill");
  if (schedulerData && schedulerData.kind === "scheduler_writer_locked") {
    elSched.classList.remove("loading");
    elSched.innerHTML =
      '<div class="status">'
      + '<span class="status-dot warn" aria-hidden="true"></span>'
      + 'Scheduler writer active — data unavailable'
      + '</div>'
      + '<div class="card__label">The launchd-managed scheduler process holds the DuckDB writer lock.</div>';
    if (pillSched) pillSched.innerHTML = '<span class="pill pill--amber">WRITER ACTIVE</span>';
  } else if (schedulerData) {
    const beats = Number(schedulerData.heartbeat_count || 0);
    const freezes = Number(schedulerData.open_freeze_count || 0);
    const alerts = Number(schedulerData.alerts_total || 0);
    elSched.classList.remove("loading");
    elSched.innerHTML =
      '<div class="status">'
      + '<span class="status-dot ' + (freezes > 0 ? "err" : (beats > 0 ? "ok" : "warn")) + '" aria-hidden="true"></span>'
      + beats + ' task' + (beats === 1 ? '' : 's') + ' · ' + freezes + ' freeze' + (freezes === 1 ? '' : 's') + ' · ' + alerts + ' alert' + (alerts === 1 ? '' : 's')
      + '</div>'
      + '<div class="card__label">read-only · writer may be in a separate process</div>';
    if (pillSched) {
      pillSched.innerHTML = freezes > 0
        ? '<span class="pill pill--red">FROZEN</span>'
        : '<span class="pill pill--green">READY</span>';
    }
  } else {
    elSched.classList.remove("loading");
    elSched.innerHTML = '<div class="error">Failed to load</div>';
    if (pillSched) pillSched.innerHTML = '<span class="pill pill--red">UNREACHABLE</span>';
  }

  // Last backtest
  const lastReport = reports && reports.reports && reports.reports[reports.reports.length - 1];
  const lbEl = document.getElementById("last-backtest");
  lbEl.classList.remove("loading");
  if (lastReport) {
    const r = Number(lastReport.total_return || 0);
    const cls = r >= 0 ? "card__value--green" : "card__value--red";
    document.getElementById("last-backtest-hint").textContent = escapeHtml(lastReport.symbol || "");
    lbEl.innerHTML =
      '<div class="card__value ' + cls + '">' + fmtPct(r, 2) + '</div>'
      + '<div class="card__label">' + Number(lastReport.trade_count || 0) + ' trades · last run</div>';
  } else {
    lbEl.innerHTML =
      '<div class="card__value">—</div><div class="card__label">No backtests yet</div>';
  }

  // Last brief
  const lastBrief = briefs && briefs.briefs && briefs.briefs[briefs.briefs.length - 1];
  const lbBriefEl = document.getElementById("last-brief");
  lbBriefEl.classList.remove("loading");
  if (lastBrief) {
    document.getElementById("last-brief-hint").textContent = escapeHtml(lastBrief.trading_day || "");
    lbBriefEl.innerHTML =
      '<div class="card__value card__value--small">' + escapeHtml(lastBrief.headline || "") + '</div>'
      + '<div class="card__label">' + fmtTime(lastBrief.generated_at) + '</div>';
  } else {
    lbBriefEl.innerHTML =
      '<div class="card__value">—</div><div class="card__label">No briefs yet</div>';
  }

  // Paper portfolio
  const positions = (portfolio && portfolio.positions) || [];
  const portEl = document.getElementById("portfolio");
  portEl.classList.remove("loading");
  if (portfolio) {
    const cash = Number(portfolio.cash || 0);
    document.getElementById("portfolio-hint").textContent = positions.length + " positions";
    portEl.innerHTML =
      '<div class="card__value">$' + fmtNumber(cash) + '</div>'
      + '<div class="card__label">cash · ' + positions.length + ' open</div>';
  } else {
    portEl.innerHTML = '<div class="error">Failed to load</div>';
  }

  // Positions table
  document.getElementById("positions-hint").textContent = positions.length + " open";
  const positionsEl = document.getElementById("positions");
  positionsEl.classList.remove("loading");
  const positionsHtml = positions.length === 0
    ? '<div class="empty">No open positions</div>'
    : '<div class="table-wrap"><table>'
      + '<thead><tr><th>Symbol</th><th class="num">Quantity</th><th class="num">Avg Price</th></tr></thead><tbody>'
      + positions.map(function (p) {
          return '<tr>'
            + '<td class="mono">' + escapeHtml(p.symbol) + '</td>'
            + '<td class="num">' + fmtNumber(p.quantity) + '</td>'
            + '<td class="num">' + fmtNumber(p.average_price) + '</td>'
            + '</tr>';
        }).join('')
      + '</tbody></table></div>';
  positionsEl.innerHTML = positionsHtml;

  drawEquityCurve(positions.length);

  // Recent fills
  const recentOrders = ((orders && orders.entries) || []).slice(0, 5);
  const fillsEl = document.getElementById("recent-fills");
  fillsEl.classList.remove("loading");
  const fillsHtml = recentOrders.length === 0
    ? '<div class="empty">No recent orders</div>'
    : '<div class="table-wrap"><table>'
      + '<thead><tr><th>Time</th><th>Symbol</th><th>Message</th></tr></thead><tbody>'
      + recentOrders.map(function (o) {
          return '<tr>'
            + '<td class="dim mono">' + fmtTime(o.created_at) + '</td>'
            + '<td class="mono">' + escapeHtml(o.symbol || "—") + '</td>'
            + '<td>' + escapeHtml(o.message || "—") + '</td>'
            + '</tr>';
        }).join('')
      + '</tbody></table></div>';
  fillsEl.innerHTML = fillsHtml;

  // Model performance
  const modelsData = await fetchJSON("/api/v1/models/evaluations?limit=20");
  const evaluations = (modelsData && modelsData.entries) || [];
  const modelIds = Array.from(new Set(evaluations.map(function (e) { return e.model_id; }))).slice(0, 6);
  const modelCards = await Promise.all(
    modelIds.map(function (id) {
      return fetchJSON("/api/v1/models/performance/" + encodeURIComponent(id));
    })
  );
  const cardsHtml = modelCards
    .filter(function (c) { return c !== null; })
    .map(function (card) {
      const tasks = Object.values(card.evaluations_by_task || {});
      const latest = tasks[0];
      const rate = latest ? Math.round((latest.schema_pass_rate || 0) * 100) : null;
      const rateStr = rate === null ? "—" : rate + "%";
      const valueCls = rate === null ? "" : (rate >= 90 ? "card__value--green" : (rate >= 70 ? "" : "card__value--red"));
      const dotCls = rate === null ? "warn" : (rate >= 70 ? "ok" : "err");
      return '<div class="card">'
        + '<div class="card__head"><span class="card__title">' + escapeHtml(card.model_id) + '</span><span class="card__hint">'
        + tasks.length + ' task' + (tasks.length === 1 ? "" : "s") + '</span></div>'
        + '<div class="card__value ' + valueCls + '">' + rateStr + '</div>'
        + '<div class="card__label"><span class="status"><span class="status-dot ' + dotCls + '" aria-hidden="true"></span>schema pass · latest</span></div>'
        + '</div>';
    }).join('');
  const mpEl = document.getElementById("model-performance");
  mpEl.classList.remove("loading");
  mpEl.innerHTML = cardsHtml.length === 0
    ? '<div class="empty">No model evaluations yet. POST /api/v1/models/evaluate to run one.</div>'
    : '<div class="grid">' + cardsHtml + '</div>';

  setRefreshIndicator(false);
}

window.addEventListener("resize", function () {
  drawEquityCurve(true);
});

loadDashboard();
setInterval(loadDashboard, REFRESH_INTERVAL_MS);
""".strip()


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

_NEWS_BODY = """
<section class="card">
  <div class="card__head">
    <span class="card__title">Headlines</span>
    <span class="card__hint" id="news-hint">—</span>
  </div>
  <div id="headlines" class="loading">Loading...</div>
</section>
""".strip()


_NEWS_JS = """
async function loadNews() {
  const data = await fetchJSON("/api/v1/news/headlines?limit=50");
  const list = (data && data.headlines) || [];
  document.getElementById("news-hint").textContent = list.length + " headlines";
  const html = list.length === 0
    ? '<div class="empty">No headlines yet. POST /api/v1/news/fetch to ingest some.</div>'
    : '<div class="table-wrap"><table>'
      + '<thead><tr><th>Published</th><th>Source</th><th>Symbols</th><th>Title</th><th>Category</th></tr></thead><tbody>'
      + list.map(function (h) {
          const syms = (h.symbols || []).map(escapeHtml).join(", ") || "—";
          return '<tr>'
            + '<td class="dim mono">' + fmtTime(h.published_at) + '</td>'
            + '<td class="mono">' + escapeHtml(h.source || "—") + '</td>'
            + '<td class="mono">' + syms + '</td>'
            + '<td class="title"><div class="title-inner">' + escapeHtml(h.title || "—") + '</div></td>'
            + '<td class="mono">' + escapeHtml(h.category || "—") + '</td>'
            + '</tr>';
        }).join('')
      + '</tbody></table></div>';
  document.getElementById("headlines").innerHTML = html;
}

loadNews();
""".strip()


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------

_MACRO_BODY = """
<section class="card">
  <div class="card__head">
    <span class="card__title">Indicators</span>
    <span class="card__hint" id="macro-hint">—</span>
  </div>
  <div id="indicators" class="loading">Loading...</div>
</section>
""".strip()


_MACRO_JS = """
async function loadMacro() {
  const data = await fetchJSON("/api/v1/macro/indicators?limit=50");
  const list = (data && data.indicators) || [];
  document.getElementById("macro-hint").textContent = list.length + " indicators";
  const html = list.length === 0
    ? '<div class="empty">No indicators yet. POST /api/v1/macro/fetch to ingest some.</div>'
    : '<div class="table-wrap"><table>'
      + '<thead><tr><th>Released</th><th>ID</th><th>Name</th><th>Value</th><th>Unit</th></tr></thead><tbody>'
      + list.map(function (i) {
          return '<tr>'
            + '<td class="dim mono">' + fmtTime(i.released_at) + '</td>'
            + '<td class="mono">' + escapeHtml(i.indicator_id || "—") + '</td>'
            + '<td>' + escapeHtml(i.name || "—") + '</td>'
            + '<td class="num">' + escapeHtml(i.value == null ? "—" : String(i.value)) + '</td>'
            + '<td class="mono dim">' + escapeHtml(i.unit || "") + '</td>'
            + '</tr>';
        }).join('')
      + '</tbody></table></div>';
  document.getElementById("indicators").innerHTML = html;
}

loadMacro();
""".strip()


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------

_BRIEF_BODY = """
<section class="card card--full">
  <div class="card__head">
    <span class="card__title">Briefs</span>
    <span class="card__hint" id="brief-hint">—</span>
  </div>
  <div id="briefs" class="loading">Loading...</div>
</section>
<section class="card card--full" id="brief-detail" style="display:none;">
  <div class="card__head">
    <span class="card__title">Detail</span>
    <a href="#" id="brief-detail-close" class="card__hint">close</a>
  </div>
  <div id="brief-detail-content"></div>
</section>
""".strip()


_BRIEF_JS = """
async function loadBriefs() {
  const data = await fetchJSON("/api/v1/brief/history");
  const list = (data && data.briefs) || [];
  document.getElementById("brief-hint").textContent = list.length + " briefs";
  const html = list.length === 0
    ? '<div class="empty">No briefs yet. POST /api/v1/brief/generate to create one.</div>'
    : '<div class="table-wrap"><table>'
      + '<thead><tr><th>Trading Day</th><th>Generated</th><th>Headline</th><th></th></tr></thead><tbody>'
      + list.map(function (b) {
          return '<tr>'
            + '<td class="mono">' + escapeHtml(b.trading_day || "—") + '</td>'
            + '<td class="dim mono">' + fmtTime(b.generated_at) + '</td>'
            + '<td class="title"><div class="title-inner">' + escapeHtml(b.headline || "—") + '</div></td>'
            + '<td><a href="#" data-id="' + escapeHtml(b.brief_id) + '" class="row-action brief-link">view</a></td>'
            + '</tr>';
        }).join('')
      + '</tbody></table></div>';
  document.getElementById("briefs").innerHTML = html;
  document.querySelectorAll(".brief-link").forEach(function (el) {
    el.addEventListener("click", async function (e) {
      e.preventDefault();
      const id = e.currentTarget.dataset.id;
      const detail = await fetchJSON("/api/v1/brief/" + encodeURIComponent(id));
      const card = document.getElementById("brief-detail");
      const content = document.getElementById("brief-detail-content");
      if (detail) {
        content.innerHTML = '<pre class="detail-pre">' + escapeHtml(JSON.stringify(detail, null, 2)) + '</pre>';
        card.style.display = "block";
        card.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });
  const closeBtn = document.getElementById("brief-detail-close");
  if (closeBtn) {
    closeBtn.addEventListener("click", function (e) {
      e.preventDefault();
      document.getElementById("brief-detail").style.display = "none";
    });
  }
}

loadBriefs();
""".strip()


# ---------------------------------------------------------------------------
# Debates
# ---------------------------------------------------------------------------

_DEBATE_BODY = """
<section class="card card--full">
  <div class="card__head">
    <span class="card__title">Debates</span>
    <span class="card__hint" id="debate-hint">—</span>
  </div>
  <div id="debates" class="loading">Loading...</div>
</section>
<section class="card card--full" id="debate-detail" style="display:none;">
  <div class="card__head">
    <span class="card__title">Detail</span>
    <a href="#" id="debate-detail-close" class="card__hint">close</a>
  </div>
  <div id="debate-detail-content"></div>
</section>
""".strip()


_DEBATE_JS = """
async function loadDebates() {
  const data = await fetchJSON("/api/v1/research/debate");
  const list = (data && data.debates) || [];
  document.getElementById("debate-hint").textContent = list.length + " debates";
  const html = list.length === 0
    ? '<div class="empty">No debates yet. POST /api/v1/research/debate to start one.</div>'
    : '<div class="table-wrap"><table>'
      + '<thead><tr><th>Created</th><th>Question</th><th></th></tr></thead><tbody>'
      + list.map(function (d) {
          return '<tr>'
            + '<td class="dim mono">' + fmtTime(d.created_at) + '</td>'
            + '<td class="title"><div class="title-inner">' + escapeHtml(d.question || "—") + '</div></td>'
            + '<td><a href="#" data-id="' + escapeHtml(d.debate_id) + '" class="row-action debate-link">view</a></td>'
            + '</tr>';
        }).join('')
      + '</tbody></table></div>';
  document.getElementById("debates").innerHTML = html;
  document.querySelectorAll(".debate-link").forEach(function (el) {
    el.addEventListener("click", async function (e) {
      e.preventDefault();
      const id = e.currentTarget.dataset.id;
      const detail = await fetchJSON("/api/v1/research/debate/" + encodeURIComponent(id));
      const card = document.getElementById("debate-detail");
      const content = document.getElementById("debate-detail-content");
      if (detail) {
        content.innerHTML = '<pre class="detail-pre">' + escapeHtml(JSON.stringify(detail, null, 2)) + '</pre>';
        card.style.display = "block";
        card.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });
  const closeBtn = document.getElementById("debate-detail-close");
  if (closeBtn) {
    closeBtn.addEventListener("click", function (e) {
      e.preventDefault();
      document.getElementById("debate-detail").style.display = "none";
    });
  }
}

loadDebates();
""".strip()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

_MODELS_BODY = """
<section class="card card--full">
  <div class="card__head">
    <span class="card__title">Recent Evaluations</span>
    <span class="card__hint" id="evaluations-hint">—</span>
  </div>
  <div id="evaluations" class="loading">Loading...</div>
</section>
<section class="card card--full">
  <div class="card__head">
    <span class="card__title">Performance by Model</span>
    <span class="card__hint">latest per task</span>
  </div>
  <div id="by-model" class="loading">Loading...</div>
</section>
""".strip()


_MODELS_JS = """
function rateClass(rate) {
  if (rate === null || rate === undefined) return "warn";
  if (rate >= 0.9) return "ok";
  if (rate >= 0.7) return "warn";
  return "err";
}

async function loadModels() {
  const data = await fetchJSON("/api/v1/models/evaluations?limit=100");
  const list = (data && data.entries) || [];
  document.getElementById("evaluations-hint").textContent = list.length + " entries";
  const html = list.length === 0
    ? '<div class="empty">No evaluations yet. Run <code>alphabrief model evaluate</code> to create one.</div>'
    : '<div class="table-wrap"><table>'
      + '<thead><tr><th>Evaluated</th><th>Model</th><th>Task</th><th class="num">JSON%</th><th class="num">Schema%</th><th class="num">Latency (ms)</th><th class="num">Samples</th></tr></thead><tbody>'
      + list.map(function (e) {
          const json = e.json_valid_rate !== null ? Math.round(e.json_valid_rate * 100) + "%" : "—";
          const schema = e.schema_pass_rate !== null ? Math.round(e.schema_pass_rate * 100) + "%" : "—";
          const latency = e.avg_latency_ms !== null && e.avg_latency_ms !== undefined ? Math.round(e.avg_latency_ms) : "—";
          return '<tr>'
            + '<td class="dim mono">' + fmtTime(e.evaluated_at) + '</td>'
            + '<td class="mono">' + escapeHtml(e.model_id) + '</td>'
            + '<td class="mono dim">' + escapeHtml(e.task_type) + '</td>'
            + '<td class="num">' + escapeHtml(json) + '</td>'
            + '<td class="num">' + escapeHtml(schema) + '</td>'
            + '<td class="num">' + escapeHtml(String(latency)) + '</td>'
            + '<td class="num">' + Number(e.sample_count || 0) + '</td>'
            + '</tr>';
        }).join('')
      + '</tbody></table></div>';
  document.getElementById("evaluations").innerHTML = html;

  const modelIds = Array.from(new Set(list.map(function (e) { return e.model_id; })));
  const perfData = await Promise.all(
    modelIds.map(function (id) {
      return fetchJSON("/api/v1/models/performance/" + encodeURIComponent(id));
    })
  );
  const present = perfData.filter(function (p) { return p !== null; });
  const byModelHtml = present.length === 0
    ? '<div class="empty">No model performance data yet.</div>'
    : '<div class="grid">' + present.map(function (p) {
        const tasks = Object.entries(p.evaluations_by_task || {});
        const taskRows = tasks.map(function (kv) {
          const task = kv[0], ev = kv[1];
          const sp = ev.schema_pass_rate !== null && ev.schema_pass_rate !== undefined
            ? Math.round(ev.schema_pass_rate * 100) + "%" : "—";
          return '<tr>'
            + '<td class="mono dim">' + escapeHtml(task) + '</td>'
            + '<td class="num">' + escapeHtml(sp) + '</td>'
            + '<td class="num">' + Number(ev.sample_count || 0) + '</td>'
            + '<td class="num">' + (ev.avg_latency_ms !== null && ev.avg_latency_ms !== undefined ? Math.round(ev.avg_latency_ms) : "—") + '</td>'
            + '</tr>';
        }).join('');
        const rates = tasks.map(function (kv) { return kv[1].schema_pass_rate; }).filter(function (v) { return v !== null && v !== undefined; });
        const avg = rates.length ? Math.round((rates.reduce(function (a, b) { return a + b; }, 0) / rates.length) * 100) : null;
        const avgStr = avg === null ? "—" : avg + "%";
        const avgCls = avg === null ? "" : (avg >= 90 ? "card__value--green" : (avg >= 70 ? "" : "card__value--red"));
        return '<article class="card">'
          + '<div class="card__head"><span class="card__title">' + escapeHtml(p.model_id) + '</span><span class="card__hint mono">' + escapeHtml(p.latest_evaluated_at || "—") + '</span></div>'
          + '<div class="card__value ' + avgCls + '">' + avgStr + '</div>'
          + '<div class="card__label">avg schema pass across ' + tasks.length + ' task' + (tasks.length === 1 ? "" : "s") + '</div>'
          + '<div class="table-wrap" style="margin-top: 0.75rem;"><table>'
          + '<thead><tr><th>Task</th><th class="num">Schema</th><th class="num">Samples</th><th class="num">Latency</th></tr></thead>'
          + '<tbody>' + taskRows + '</tbody></table></div>'
          + '</article>';
      }).join('') + '</div>';
  document.getElementById("by-model").innerHTML = byModelHtml;
}

loadModels();
""".strip()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_STRATEGIES_BODY = """
<section class="card card--full">
  <div class="card__head">
    <span class="card__title">Strategies</span>
    <span class="card__hint" id="strategies-hint">—</span>
  </div>
  <div id="strategies" class="loading">Loading...</div>
  <p class="card__advisory">
    The <code>enabled</code> flag is advisory only. It does not block orders
    and is not consulted by the risk gate.
  </p>
</section>
<section class="card card--full" id="strategy-detail" style="display:none;">
  <div class="card__head">
    <span class="card__title">Detail</span>
    <a href="#" id="strategy-detail-close" class="card__hint">close</a>
  </div>
  <div id="strategy-detail-content"></div>
</section>
<section class="card card--full">
  <div class="card__head">
    <span class="card__title">Signal Counts</span>
    <span class="card__hint" id="signal-counts-hint">—</span>
  </div>
  <div id="signal-counts" class="loading">Loading...</div>
  <p class="card__advisory">
    Signal history is a write-only advisory log; it never modifies risk gate decisions.
  </p>
</section>
""".strip()


_STRATEGIES_JS = """
async function loadStrategies() {
  const data = await fetchJSON("/api/v1/strategies/specs");
  const list = (data && data.strategies) || [];
  document.getElementById("strategies-hint").textContent = list.length + " specs";
  const html = list.length === 0
    ? '<div class="empty">No strategies yet. POST /api/v1/strategies/specs or run <code>alphabrief strategy save</code> to create one.</div>'
    : '<div class="table-wrap"><table>'
      + '<thead><tr><th>Strategy ID</th><th>Name</th><th class="num">Version</th><th>Enabled</th><th>Updated</th><th></th></tr></thead><tbody>'
      + list.map(function (s) {
          const badge = s.enabled
            ? '<span class="badge badge--on">enabled</span>'
            : '<span class="badge badge--off">disabled</span>';
          return '<tr>'
            + '<td class="mono">' + escapeHtml(s.strategy_id) + '</td>'
            + '<td>' + escapeHtml(s.name) + '</td>'
            + '<td class="num">' + escapeHtml(s.version) + '</td>'
            + '<td>' + badge + '</td>'
            + '<td class="dim mono">' + fmtTime(s.updated_at) + '</td>'
            + '<td><a href="#" data-id="' + escapeHtml(s.strategy_id) + '" class="row-action strategy-link">view</a></td>'
            + '</tr>';
        }).join('')
      + '</tbody></table></div>';
  document.getElementById("strategies").innerHTML = html;
  document.querySelectorAll(".strategy-link").forEach(function (el) {
    el.addEventListener("click", async function (e) {
      e.preventDefault();
      const id = e.currentTarget.dataset.id;
      const detail = await fetchJSON("/api/v1/strategies/specs/" + encodeURIComponent(id));
      const card = document.getElementById("strategy-detail");
      const content = document.getElementById("strategy-detail-content");
      if (detail) {
        content.innerHTML = '<pre class="detail-pre">' + escapeHtml(JSON.stringify(detail, null, 2)) + '</pre>';
        card.style.display = "block";
        card.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });
  const closeBtn = document.getElementById("strategy-detail-close");
  if (closeBtn) {
    closeBtn.addEventListener("click", function (e) {
      e.preventDefault();
      document.getElementById("strategy-detail").style.display = "none";
    });
  }

  const enabled = await fetchJSON("/api/v1/strategies/enabled");
  const ids = list.map(function (s) { return s.strategy_id; });
  const counts = await Promise.all(
    ids.map(function (id) {
      return fetchJSON("/api/v1/strategies/" + encodeURIComponent(id) + "/signals/count");
    })
  );
  const rows = ids.map(function (id, i) {
    return {
      id: id,
      count: (counts[i] && counts[i].count) || 0,
      isEnabled: ((enabled && enabled.strategy_ids) || []).indexOf(id) !== -1,
    };
  });
  document.getElementById("signal-counts-hint").textContent = rows.length + " strategies";
  const countHtml = rows.length === 0
    ? '<div class="empty">No strategies to summarize.</div>'
    : '<div class="table-wrap"><table>'
      + '<thead><tr><th>Strategy ID</th><th class="num">Signals recorded</th><th>Advisory activation</th></tr></thead><tbody>'
      + rows.map(function (r) {
          const badge = r.isEnabled
            ? '<span class="badge badge--on">enabled</span>'
            : '<span class="badge badge--off">disabled</span>';
          return '<tr>'
            + '<td class="mono">' + escapeHtml(r.id) + '</td>'
            + '<td class="num">' + Number(r.count) + '</td>'
            + '<td>' + badge + '</td>'
            + '</tr>';
        }).join('')
      + '</tbody></table></div>';
  document.getElementById("signal-counts").innerHTML = countHtml;
}

loadStrategies();
""".strip()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_class=HTMLResponse)
def get_dashboard() -> HTMLResponse:
    """Serve the AlphaBrief web dashboard main page."""
    return HTMLResponse(
        content=_shell(
            active="main",
            title="Main",
            subtitle="Status, portfolio, recent activity and model health.",
            body=_DASHBOARD_BODY,
            scripts=_DASHBOARD_JS,
            meta=(
                '<span class="refresh-indicator" id="refresh-indicator" '
                'title="Auto-refresh every 30s">'
                '<span class="spinner" aria-hidden="true"></span>'
                '<span id="refresh-timestamp">—</span></span>'
                '<span class="pill pill--accent" id="env-pill">—</span>'
            ),
        )
    )


@router.get("/dashboard/news", response_class=HTMLResponse)
def get_dashboard_news() -> HTMLResponse:
    """Serve the news dashboard page."""
    return HTMLResponse(
        content=_shell(
            active="news",
            title="News",
            subtitle="Latest news headlines stored in DuckDB.",
            body=_NEWS_BODY,
            scripts=_NEWS_JS,
        )
    )


@router.get("/dashboard/macro", response_class=HTMLResponse)
def get_dashboard_macro() -> HTMLResponse:
    """Serve the macro dashboard page."""
    return HTMLResponse(
        content=_shell(
            active="macro",
            title="Macro Indicators",
            subtitle="Latest macro indicators stored in DuckDB.",
            body=_MACRO_BODY,
            scripts=_MACRO_JS,
        )
    )


@router.get("/dashboard/brief", response_class=HTMLResponse)
def get_dashboard_brief() -> HTMLResponse:
    """Serve the brief dashboard page."""
    return HTMLResponse(
        content=_shell(
            active="brief",
            title="Daily Briefs",
            subtitle="Generated daily AlphaBrief history.",
            body=_BRIEF_BODY,
            scripts=_BRIEF_JS,
        )
    )


@router.get("/dashboard/debate", response_class=HTMLResponse)
def get_dashboard_debate() -> HTMLResponse:
    """Serve the debate dashboard page."""
    return HTMLResponse(
        content=_shell(
            active="debate",
            title="Research Debates",
            subtitle="Multi-model research debate history.",
            body=_DEBATE_BODY,
            scripts=_DEBATE_JS,
        )
    )


@router.get("/dashboard/models", response_class=HTMLResponse)
def get_dashboard_models() -> HTMLResponse:
    """Serve the model evaluation dashboard page."""
    return HTMLResponse(
        content=_shell(
            active="models",
            title="Model Performance",
            subtitle="Evaluation history across providers and task types.",
            body=_MODELS_BODY,
            scripts=_MODELS_JS,
        )
    )


@router.get("/dashboard/strategies", response_class=HTMLResponse)
def get_dashboard_strategies() -> HTMLResponse:
    """Serve the strategy registry dashboard page."""
    return HTMLResponse(
        content=_shell(
            active="strategies",
            title="Strategy Registry",
            subtitle="Persisted StrategySpec objects and their advisory signal history.",
            body=_STRATEGIES_BODY,
            scripts=_STRATEGIES_JS,
        )
    )


# ---------------------------------------------------------------------------
# AI Trading page
# ---------------------------------------------------------------------------

_AI_TRADING_BODY = r"""
<style>
  /* Phase 32 — AI Trading dashboard deepening. Scoped to .ai-page so it
     can't leak into the main dashboard. ponytail: minimal additions; all
     values come from existing endpoints. */
  .ai-page { display: grid; gap: 1rem; }
  .ai-page .ai-row--2 { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
  .ai-page .donut-card { display: flex; align-items: center; gap: 1rem; }
  .ai-page .donut-wrap { width: 180px; height: 180px; flex-shrink: 0; position: relative; }
  .ai-page .donut-legend { display: grid; gap: 0.35rem; font-family: var(--font-mono); font-size: 0.78rem; flex: 1; min-width: 0; }
  .ai-page .donut-legend__row { display: flex; align-items: center; gap: 0.5rem; }
  .ai-page .donut-legend__sw { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }
  .ai-page .donut-legend__label { color: var(--text-dim); flex: 1; }
  .ai-page .donut-legend__value { color: var(--text); font-variant-numeric: tabular-nums; }
  .ai-page .role-trend { display: grid; gap: 0.45rem; }
  .ai-page .role-trend__row { display: grid; grid-template-columns: 6.5rem 1fr; align-items: center; gap: 0.75rem; }
  .ai-page .role-trend__role { font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; }
  .ai-page .role-trend__dots { display: flex; gap: 4px; flex-wrap: wrap; }
  .ai-page .role-trend__dot { width: 12px; height: 12px; border-radius: 50%; border: 1px solid rgba(148, 163, 184, 0.15); }
  .ai-page .role-trend__dot--buy { background: var(--green); }
  .ai-page .role-trend__dot--sell { background: var(--red); }
  .ai-page .role-trend__dot--hold { background: var(--amber); }
  .ai-page .role-trend__dot--watch { background: var(--accent); opacity: 0.7; }
  .ai-page .role-trend__dot--skip { background: #475569; }
  .ai-page .role-trend__dot--none { background: transparent; }
  .ai-page .role-trend__legend { display: flex; gap: 0.75rem; flex-wrap: wrap; font-family: var(--font-mono); font-size: 0.65rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px solid var(--border); }
  .ai-page .role-trend__legend span { display: inline-flex; align-items: center; gap: 0.3rem; }
  .ai-page .role-trend__legend i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .ai-page .plan-cards { display: grid; gap: 0.75rem; }
  .ai-page .plan-card { border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 0.875rem 1rem; background: var(--bg-elev-3); }
  .ai-page .plan-card__head { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; margin-bottom: 0.5rem; flex-wrap: wrap; }
  .ai-page .plan-card__symbol { font-family: var(--font-mono); font-size: 0.95rem; font-weight: 600; color: var(--text); }
  .ai-page .plan-card__side { font-family: var(--font-mono); font-size: 0.7rem; padding: 0.15rem 0.5rem; border-radius: 3px; text-transform: uppercase; letter-spacing: 0.05em; }
  .ai-page .plan-card__side--buy { color: var(--green); background: var(--green-dim); border: 1px solid rgba(34,197,94,0.25); }
  .ai-page .plan-card__side--sell { color: var(--red); background: var(--red-dim); border: 1px solid rgba(239,68,68,0.25); }
  .ai-page .plan-card__side--hold { color: var(--amber); background: var(--amber-dim); border: 1px solid rgba(245,158,11,0.25); }
  .ai-page .plan-card__meta { font-family: var(--font-mono); font-size: 0.7rem; color: var(--text-dim); margin-bottom: 0.5rem; }
  .ai-page .plan-card__meta b { color: var(--text); font-weight: 500; }
  .ai-page .plan-card__rationale { font-size: 0.8rem; color: var(--text-dim); margin-bottom: 0.75rem; line-height: 1.5; }
  .ai-page .plan-card__votes { display: grid; gap: 0.35rem; padding-top: 0.5rem; border-top: 1px solid var(--border); }
  .ai-page .plan-card__vote { display: grid; grid-template-columns: 6.5rem 4rem 1fr auto; gap: 0.5rem; align-items: center; font-family: var(--font-mono); font-size: 0.72rem; }
  .ai-page .plan-card__vote-role { color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; }
  .ai-page .plan-card__vote-action { color: var(--text); }
  .ai-page .plan-card__vote-conf { color: var(--text-muted); }
  .ai-page .plan-card__vote-model { color: var(--text-muted); font-size: 0.65rem; }
  .ai-page .plan-card__attempts { margin-top: 0.75rem; padding-top: 0.5rem; border-top: 1px solid var(--border); font-family: var(--font-mono); font-size: 0.7rem; color: var(--text-dim); }
  .ai-page .plan-card__attempts-row { display: flex; gap: 0.5rem; align-items: center; margin-top: 0.25rem; }
  .ai-page .outcome-pill { display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.15rem 0.45rem; border-radius: 3px; font-family: var(--font-mono); font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; border: 1px solid transparent; white-space: nowrap; }
  .ai-page .outcome-pill--executed { color: var(--green); background: var(--green-dim); border-color: rgba(34,197,94,0.25); }
  .ai-page .outcome-pill--blocked { color: var(--red); background: var(--red-dim); border-color: rgba(239,68,68,0.25); }
  .ai-page .outcome-pill--mixed { color: var(--amber); background: var(--amber-dim); border-color: rgba(245,158,11,0.25); }
  .ai-page .outcome-pill--none { color: var(--text-dim); background: rgba(148,163,184,0.08); border-color: rgba(148,163,184,0.18); }
  .ai-page .equity-meta { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; margin-bottom: 0.75rem; }
  .ai-page .equity-meta__value { font-family: var(--font-mono); font-size: 1.4rem; font-weight: 600; color: var(--text); }
  .ai-page .equity-meta__hint { font-size: 0.65rem; color: var(--text-muted); font-family: var(--font-mono); text-transform: uppercase; letter-spacing: 0.06em; }
  @media (max-width: 720px) {
    .ai-page .donut-card { flex-direction: column; align-items: stretch; }
    .ai-page .donut-wrap { margin: 0 auto; }
    .ai-page .plan-card__vote { grid-template-columns: 1fr; gap: 0.15rem; }
  }
</style>
<section class="page-grid page-grid--ai ai-page">
  <div class="card card--status">
    <div class="card__head">
      <h2 class="card__title">AI Trading — feature flags</h2>
      <p class="card__hint">AI trading is paper-only and requires both an explicit feature flag and the absence of the live-trading lock.</p>
    </div>
    <div class="card__body">
      <div class="stat-grid" id="ai-status-grid">
        <div class="stat"><span class="stat__label">AI trading</span><span class="stat__value" id="ai-flag-enabled">…</span></div>
        <div class="stat"><span class="stat__label">Live trading</span><span class="stat__value" id="ai-flag-live">…</span></div>
        <div class="stat"><span class="stat__label">Cycles recorded</span><span class="stat__value" id="ai-cycle-count">…</span></div>
      </div>
      <p class="card__hint" id="ai-status-hint"></p>
    </div>
  </div>

  <div class="ai-row--2">
    <div class="card card--donut">
      <div class="card__head">
        <h2 class="card__title">Vote distribution</h2>
        <span class="card__hint" id="ai-donut-hint">latest cycle</span>
      </div>
      <div class="card__body donut-card">
        <div class="donut-wrap"><canvas id="ai-donut-canvas"></canvas></div>
        <div class="donut-legend" id="ai-donut-legend">
          <div class="empty">Loading…</div>
        </div>
      </div>
    </div>

    <div class="card card--trend">
      <div class="card__head">
        <h2 class="card__title">Per-role vote trend</h2>
        <span class="card__hint" id="ai-trend-hint">last 10 cycles</span>
      </div>
      <div class="card__body">
        <div class="role-trend" id="ai-role-trend">
          <div class="empty">Loading…</div>
        </div>
      </div>
    </div>
  </div>

  <div class="card card--equity">
    <div class="card__head">
      <h2 class="card__title">Paper portfolio equity</h2>
      <span class="card__hint">cash + positions + realized pnl · 30-day observation</span>
    </div>
    <div class="card__body">
      <div class="equity-meta">
        <div class="equity-meta__value" id="ai-equity-value">—</div>
        <div class="equity-meta__hint" id="ai-equity-hint">current snapshot</div>
      </div>
      <div class="chart-wrap"><canvas id="ai-equity-canvas"></canvas></div>
    </div>
  </div>

  <div class="card card--form">
    <div class="card__head">
      <h2 class="card__title">Run a cycle</h2>
      <p class="card__hint">Comma-separated symbols. The cycle still respects the AI trading feature flag — the form submits only when both flags permit it.</p>
    </div>
    <div class="card__body">
      <form id="ai-run-form" class="form-grid">
        <label class="form-row">
          <span>Symbols</span>
          <input type="text" id="ai-run-symbols" value="SPY,QQQ,IVV" autocomplete="off" />
        </label>
        <label class="form-row">
          <span>Reference prices (JSON)</span>
          <input type="text" id="ai-run-prices" placeholder='{"SPY": 450}' autocomplete="off" />
        </label>
        <div class="form-row form-row--actions">
          <button type="submit" class="btn btn--primary">Run cycle</button>
        </div>
        <p class="card__hint" id="ai-run-result"></p>
      </form>
    </div>
  </div>

  <div class="card card--rules">
    <div class="card__head">
      <h2 class="card__title">Discipline rules</h2>
      <p class="card__hint">Deterministic guardrails applied after the committee synthesizes a plan, before the risk gate.</p>
    </div>
    <div class="card__body">
      <pre class="codeblock" id="ai-rules-body">…</pre>
    </div>
  </div>

  <div class="card card--history">
    <div class="card__head">
      <h2 class="card__title">Cycle history</h2>
      <p class="card__hint">Newest-first. Click a row to view structured plan cards.</p>
    </div>
    <div class="card__body">
      <table class="data-table" id="ai-history-table">
        <thead>
          <tr>
            <th>Day</th>
            <th>Symbols</th>
            <th>Outcome</th>
            <th>Action</th>
            <th>Plans</th>
            <th>Attempts</th>
            <th>Executed</th>
            <th>Blocked</th>
            <th>When</th>
            <th></th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <div class="card card--detail">
    <div class="card__head">
      <h2 class="card__title">Cycle detail</h2>
      <a href="#" id="ai-detail-close" class="card__hint">close</a>
    </div>
    <div class="card__body">
      <div id="ai-detail-body" class="plan-cards"><div class="empty">Select a cycle to inspect its committee plan cards.</div></div>
      <pre class="codeblock" id="ai-detail-raw" style="display:none; margin-top:1rem;"></pre>
      <p class="card__hint" style="margin-top:0.5rem;"><a href="#" id="ai-detail-toggle-raw">show raw JSON</a></p>
    </div>
  </div>
</section>
""".strip()

_AI_TRADING_JS = r"""
// ---------------------------------------------------------------------------
// Phase 32: vote distribution, per-role trend, equity curve, plan cards,
// outcome badge. Pure HTML/CSS/JS, no new endpoints.
// ---------------------------------------------------------------------------

// Colors keyed by vote action for the donut and dot grid.
const VOTE_COLORS = {
  buy:   "#22c55e",
  sell:  "#ef4444",
  hold:  "#f59e0b",
  watch: "#00d4ff",
  skip:  "#475569",
};

function fmtUsd(v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return "$" + v.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function outcomeBadgeForCycle(c) {
  // ponytail: the "win/loss" claim the spec asks for can't be computed from
  // a single cycle without a held-position cost basis. The honest proxy is
  // executed_count vs blocked_count — does the committee's plan clear risk
  // and reach the broker?
  if (!c) return { label: "—", cls: "outcome-pill--none" };
  const ex = Number(c.executed_count || 0);
  const bl = Number(c.blocked_count || 0);
  if (ex > 0 && bl > 0) return { label: "MIXED", cls: "outcome-pill--mixed" };
  if (ex > 0) return { label: "EXECUTED", cls: "outcome-pill--executed" };
  if (bl > 0) return { label: "BLOCKED", cls: "outcome-pill--blocked" };
  return { label: "NO ACTION", cls: "outcome-pill--none" };
}

function majorityActionFromVotes(votes) {
  // ponytail: simple plurality over suggested_action. Treat watch/skip
  // separately from buy/hold/sell so the donut tells a clear story.
  if (!votes || votes.length === 0) return "hold";
  const counts = {};
  for (const v of votes) {
    const a = (v.suggested_action || "skip").toLowerCase();
    counts[a] = (counts[a] || 0) + 1;
  }
  let best = "hold", bestN = -1;
  for (const k of Object.keys(counts)) {
    if (counts[k] > bestN) { best = k; bestN = counts[k]; }
  }
  return best;
}

async function loadAiStatus() {
  const data = await fetchJSON('/api/v1/ai/status');
  if (!data) return;
  document.getElementById('ai-flag-enabled').textContent = data.ai_trading_enabled ? 'ENABLED' : 'disabled';
  document.getElementById('ai-flag-live').textContent = data.live_trading_enabled ? 'UNLOCKED' : 'locked';
  document.getElementById('ai-cycle-count').textContent = String(data.cycle_count);
  document.getElementById('ai-status-hint').textContent = data.ai_trading_enabled
    ? 'AI trading is on; the committee will route plans through the risk gate and the paper broker.'
    : 'Set ALPHABRIEF_AI_TRADING_ENABLED=true in the environment to actually execute cycles.';
}

async function loadAiRules() {
  const data = await fetchJSON('/api/v1/ai/rules');
  if (!data) return;
  document.getElementById('ai-rules-body').textContent = JSON.stringify(data, null, 2);
}

async function loadAiHistory() {
  const data = await fetchJSON('/api/v1/ai/history?limit=20');
  const tbody = document.querySelector('#ai-history-table tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  if (!data || !Array.isArray(data.cycles)) return;
  // Lazy-load outcomes (badge) per row in parallel.
  const detailPromises = data.cycles.map((c) =>
    fetchJSON('/api/v1/ai/cycles/' + encodeURIComponent(c.cycle_id)).catch(() => null)
  );
  const details = await Promise.all(detailPromises);
  data.cycles.forEach((c, i) => {
    const detail = details[i];
    const majority = detail ? majorityActionFromVotes(detail.votes) : "—";
    const badge = outcomeBadgeForCycle(c);
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td>' + escapeHtml(c.trading_day) + '</td>'
      + '<td>' + escapeHtml((c.symbols || []).join(', ')) + '</td>'
      + '<td>' + escapeHtml(c.outcome) + '</td>'
      + '<td><span class="outcome-pill ' + badge.cls + '">' + badge.label + '</span></td>'
      + '<td>' + c.plan_count + '</td>'
      + '<td>' + c.attempt_count + '</td>'
      + '<td>' + c.executed_count + '</td>'
      + '<td>' + c.blocked_count + '</td>'
      + '<td>' + escapeHtml(c.created_at) + '</td>'
      + '<td><a href="#" data-id="' + escapeHtml(c.cycle_id) + '" class="row-action ai-cycle-link">view</a></td>';
    tbody.appendChild(tr);
  });
  document.querySelectorAll('.ai-cycle-link').forEach((a) => {
    a.addEventListener('click', async (ev) => {
      ev.preventDefault();
      const id = a.getAttribute('data-id');
      await renderCycleDetail(id);
    });
  });
  // Drive the other visuals from the most recent N cycles' details.
  const valid = data.cycles
    .map((c, i) => ({ summary: c, detail: details[i] }))
    .filter((x) => x.detail)
    .slice(0, 10);
  renderVoteDonut(valid[0] ? valid[0].detail : null);
  renderRoleTrend(valid);
  loadEquityCurve();
}

async function renderCycleDetail(cycleId) {
  const body = document.getElementById('ai-detail-body');
  const raw = document.getElementById('ai-detail-raw');
  const toggle = document.getElementById('ai-detail-toggle-raw');
  if (toggle) toggle.textContent = 'show raw JSON';
  if (raw) { raw.style.display = 'none'; raw.textContent = ''; }
  body.innerHTML = '<div class="empty">Loading…</div>';
  const data = await fetchJSON('/api/v1/ai/cycles/' + encodeURIComponent(cycleId));
  if (!data) {
    body.innerHTML = '<div class="empty">cycle not found</div>';
    return;
  }
  // Stash raw JSON for the toggle.
  if (raw) raw.textContent = JSON.stringify(data, null, 2);
  body.innerHTML = '';
  const plans = data.plans || [];
  if (plans.length === 0) {
    body.innerHTML = '<div class="empty">No plans in this cycle.</div>';
    return;
  }
  // Index votes by plan-relevant (symbol, side) and attempts by intent_id.
  const votesBySymbol = {};
  for (const v of (data.votes || [])) {
    const sym = v.symbol || (data.symbols && data.symbols[0]) || '?';
    if (!votesBySymbol[sym]) votesBySymbol[sym] = [];
    votesBySymbol[sym].push(v);
  }
  const attempts = data.attempts || [];
  for (const p of plans) {
    const side = (p.side || 'hold').toLowerCase();
    const cls = 'plan-card__side--' + (side === 'buy' || side === 'sell' || side === 'hold' ? side : 'hold');
    const conf = (Number(p.confidence) * 100).toFixed(0);
    const tgt = (Number(p.target_position_pct) * 100).toFixed(1);
    const planAttempts = attempts.filter((a) => {
      const o = a.order_intent_json || {};
      return o.symbol === p.symbol && o.side === p.side;
    });
    const planVotes = votesBySymbol[p.symbol] || [];
    const card = document.createElement('div');
    card.className = 'plan-card';
    card.innerHTML =
      '<div class="plan-card__head">'
        + '<span class="plan-card__symbol">' + escapeHtml(p.symbol) + '</span>'
        + '<span class="plan-card__side ' + cls + '">' + escapeHtml(side) + '</span>'
      + '</div>'
      + '<div class="plan-card__meta">'
        + 'consensus: <b>' + escapeHtml(p.consensus_level || '—') + '</b>'
        + ' · confidence: <b>' + conf + '%</b>'
        + ' · target: <b>' + tgt + '%</b>'
        + (p.needs_human_review ? ' · <b style="color:var(--amber)">human review</b>' : '')
        + (p.blocked_by_ethics ? ' · <b style="color:var(--red)">ethics block</b>' : '')
      + '</div>'
      + '<div class="plan-card__rationale">' + escapeHtml(p.rationale || '') + '</div>'
      + (planVotes.length > 0
          ? '<div class="plan-card__votes">'
            + planVotes.map((v) =>
                '<div class="plan-card__vote">'
                  + '<span class="plan-card__vote-role">' + escapeHtml(v.role) + '</span>'
                  + '<span class="plan-card__vote-action">' + escapeHtml(v.suggested_action) + '</span>'
                  + '<span class="plan-card__vote-conf">conf ' + (Number(v.confidence) * 100).toFixed(0) + '%</span>'
                  + '<span class="plan-card__vote-model">' + escapeHtml(v.model_name || '') + '</span>'
                + '</div>'
              ).join('')
            + '</div>'
          : '')
      + (planAttempts.length > 0
          ? '<div class="plan-card__attempts">'
            + planAttempts.map((a) =>
                '<div class="plan-card__attempts-row">'
                  + '<span class="outcome-pill outcome-pill--' + (a.outcome === 'executed' ? 'executed' : (String(a.outcome).startsWith('blocked') ? 'blocked' : 'none')) + '">'
                  + escapeHtml(a.outcome) + '</span>'
                  + '<span>' + (a.filled ? 'filled @ ' + (a.fill_price || '?') : 'not filled') + '</span>'
                  + '<span style="color:var(--text-muted)">' + escapeHtml(a.reason || '') + '</span>'
                + '</div>'
              ).join('')
            + '</div>'
          : '');
    body.appendChild(card);
  }
}

function renderVoteDonut(latestDetail) {
  const hint = document.getElementById('ai-donut-hint');
  const legend = document.getElementById('ai-donut-legend');
  const votes = (latestDetail && latestDetail.votes) || [];
  if (votes.length === 0) {
    if (hint) hint.textContent = 'latest cycle · no votes';
    legend.innerHTML = '<div class="empty">No committee votes yet.</div>';
    drawDonut('ai-donut-canvas', []);
    return;
  }
  if (hint) hint.textContent = 'latest cycle · ' + (latestDetail.trading_day || '');
  const counts = { buy: 0, hold: 0, sell: 0, watch: 0, skip: 0 };
  for (const v of votes) {
    const a = (v.suggested_action || 'skip').toLowerCase();
    if (counts[a] === undefined) counts.skip += 1;
    else counts[a] += 1;
  }
  const segments = [
    { label: 'buy',   value: counts.buy,   color: VOTE_COLORS.buy },
    { label: 'hold',  value: counts.hold,  color: VOTE_COLORS.hold },
    { label: 'sell',  value: counts.sell,  color: VOTE_COLORS.sell },
    { label: 'watch', value: counts.watch, color: VOTE_COLORS.watch },
    { label: 'skip',  value: counts.skip,  color: VOTE_COLORS.skip },
  ].filter((s) => s.value > 0);
  drawDonut('ai-donut-canvas', segments);
  legend.innerHTML = segments.map((s) =>
    '<div class="donut-legend__row">'
      + '<span class="donut-legend__sw" style="background:' + s.color + '"></span>'
      + '<span class="donut-legend__label">' + s.label + '</span>'
      + '<span class="donut-legend__value">' + s.value + '</span>'
    + '</div>'
  ).join('');
}

function renderRoleTrend(records) {
  const wrap = document.getElementById('ai-role-trend');
  const hint = document.getElementById('ai-trend-hint');
  if (!records || records.length === 0) {
    if (hint) hint.textContent = 'last 10 cycles · no data';
    wrap.innerHTML = '<div class="empty">Run a cycle to populate the per-role trend.</div>';
    return;
  }
  // Reverse so column 0 is the OLDEST cycle and the rightmost dot is newest.
  const ordered = records.slice().reverse();
  if (hint) hint.textContent = 'last ' + ordered.length + ' cycles · newest on the right';
  const ROLES = ['technical', 'fundamental', 'risk', 'manager'];
  // For each role, find the majority suggested_action per cycle.
  const rows = ROLES.map((role) => {
    const dots = ordered.map((rec) => {
      const votes = (rec.detail.votes || []).filter((v) => v.role === role);
      if (votes.length === 0) return { action: null };
      const counts = {};
      for (const v of votes) {
        const a = (v.suggested_action || 'skip').toLowerCase();
        counts[a] = (counts[a] || 0) + 1;
      }
      let best = 'skip', bestN = -1;
      for (const k of Object.keys(counts)) {
        if (counts[k] > bestN) { best = k; bestN = counts[k]; }
      }
      return { action: best };
    });
    return { role: role, dots: dots };
  });
  wrap.innerHTML =
    rows.map((r) =>
      '<div class="role-trend__row">'
        + '<span class="role-trend__role">' + r.role + '</span>'
        + '<span class="role-trend__dots">'
          + r.dots.map((d) =>
              '<span class="role-trend__dot role-trend__dot--' + (d.action || 'none') + '" title="' + (d.action || 'no vote') + '"></span>'
            ).join('')
        + '</span>'
      + '</div>'
    ).join('')
    + '<div class="role-trend__legend">'
      + '<span><i style="background:' + VOTE_COLORS.buy + '"></i>buy</span>'
      + '<span><i style="background:' + VOTE_COLORS.hold + '"></i>hold</span>'
      + '<span><i style="background:' + VOTE_COLORS.sell + '"></i>sell</span>'
      + '<span><i style="background:' + VOTE_COLORS.watch + '"></i>watch</span>'
      + '<span><i style="background:' + VOTE_COLORS.skip + '"></i>skip</span>'
      + '<span><i style="background:transparent;border:1px solid var(--border-strong)"></i>none</span>'
    + '</div>';
}

async function loadEquityCurve() {
  const portfolio = await fetchJSON('/api/v1/paper/portfolio');
  const orders = await fetchJSON('/api/v1/paper/orders?status=order_created');
  const hintEl = document.getElementById('ai-equity-hint');
  const valueLabel = document.getElementById('ai-equity-value');
  // ponytail: no /equity-history endpoint exists, so the chart is a single
  // current-snapshot point unless the audit log provides fill events with
  // timestamps. The honest fallback is to mark the chart "current snapshot".
  const cash = portfolio ? Number(portfolio.cash || 0) : 0;
  const realized = portfolio ? Number(portfolio.realized_pnl || 0) : 0;
  const positions = (portfolio && portfolio.positions) || [];
  // Mark-to-market current equity = cash + realized + sum(qty * avg_price).
  // (avg_price is a cost basis; without a mark price we just use cost.)
  let mtm = 0;
  for (const p of positions) {
    mtm += Number(p.quantity || 0) * Number(p.average_price || 0);
  }
  const equityNow = cash + mtm + realized;
  if (valueLabel) valueLabel.textContent = fmtUsd(equityNow);
  // Build a one-point series; if we have order events, project a step
  // timeline walking down to the present so the chart isn't a dot.
  const events = (orders && orders.entries) || [];
  const points = [];
  if (events.length === 0) {
    points.push({ t: Date.now(), v: equityNow });
    if (hintEl) hintEl.textContent = 'current snapshot · no order history yet';
  } else {
    // Use the earliest order as t0 with a baseline cash value, then plot
    // the current equity at "now". This keeps the line meaningful without
    // fabricating intermediate values.
    const earliestTs = new Date(events[events.length - 1].created_at).getTime();
    points.push({ t: earliestTs, v: 100000 });
    points.push({ t: Date.now(), v: equityNow });
    if (hintEl) hintEl.textContent = 'snapshot vs starting cash · ' + events.length + ' order' + (events.length === 1 ? '' : 's');
  }
  drawLineChart('ai-equity-canvas', points, { color: '#00d4ff', fillColor: 'rgba(0, 212, 255, 0.12)' });
}

document.getElementById('ai-detail-close')?.addEventListener('click', (ev) => {
  ev.preventDefault();
  document.getElementById('ai-detail-body').innerHTML = '<div class="empty">Select a cycle to inspect its committee plan cards.</div>';
  const raw = document.getElementById('ai-detail-raw');
  if (raw) { raw.style.display = 'none'; raw.textContent = ''; }
  const toggle = document.getElementById('ai-detail-toggle-raw');
  if (toggle) toggle.textContent = 'show raw JSON';
});

document.getElementById('ai-detail-toggle-raw')?.addEventListener('click', (ev) => {
  ev.preventDefault();
  const raw = document.getElementById('ai-detail-raw');
  if (!raw) return;
  const showing = raw.style.display !== 'none';
  raw.style.display = showing ? 'none' : 'block';
  ev.target.textContent = showing ? 'show raw JSON' : 'hide raw JSON';
});

document.getElementById('ai-run-form')?.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const symbolsRaw = document.getElementById('ai-run-symbols').value;
  const pricesRaw = document.getElementById('ai-run-prices').value.trim();
  const symbols = symbolsRaw.split(',').map(s => s.trim()).filter(Boolean);
  const body = { symbols: symbols };
  if (pricesRaw) {
    try {
      body.reference_prices = JSON.parse(pricesRaw);
    } catch (err) {
      document.getElementById('ai-run-result').textContent = 'Invalid reference-prices JSON: ' + err.message;
      return;
    }
  }
  try {
    const res = await fetch('/api/v1/ai/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    document.getElementById('ai-run-result').textContent = res.ok
      ? 'Cycle ' + data.cycle_id + ' — ' + data.outcome + ' (' + data.summary + ')'
      : 'Error: ' + (data.detail || res.status);
    loadAiHistory();
    loadAiStatus();
  } catch (err) {
    document.getElementById('ai-run-result').textContent = 'Network error: ' + err.message;
  }
});

// Re-render the equity curve on resize so the canvas stays crisp.
let _aiResizeTimer = null;
window.addEventListener('resize', () => {
  if (!document.getElementById('ai-equity-canvas')) return;
  clearTimeout(_aiResizeTimer);
  _aiResizeTimer = setTimeout(loadEquityCurve, 150);
});

loadAiStatus();
loadAiRules();
loadAiHistory();
""".strip()


@router.get("/dashboard/ai-trading", response_class=HTMLResponse)
def get_dashboard_ai_trading() -> HTMLResponse:
    """Serve the AI Trading Committee dashboard page."""
    return HTMLResponse(
        content=_shell(
            active="ai-trading",
            title="AI Trading",
            subtitle=(
                "Read-only view of the AI Trading Committee's daily cycles, "
                "discipline rules, and order attempts. The committee is "
                "paper-only and is gated by ALPHABRIEF_AI_TRADING_ENABLED."
            ),
            body=_AI_TRADING_BODY,
            scripts=_AI_TRADING_JS,
        )
    )


__all__ = ["router"]
