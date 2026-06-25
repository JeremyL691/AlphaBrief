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

_COMMON_SCRIPTS = """
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
    <div id="project-status" class="loading">Loading...</div>
  </article>

  <article class="card">
    <div class="card__head"><span class="card__title">Data Symbols</span><span class="card__hint" id="data-symbols-hint">—</span></div>
    <div id="data-symbols" class="loading">Loading...</div>
  </article>

  <article class="card">
    <div class="card__head"><span class="card__title">Risk Status</span><span id="risk-status-pill"></span></div>
    <div id="risk-status" class="loading">Loading...</div>
  </article>

  <article class="card">
    <div class="card__head"><span class="card__title">Last Backtest</span><span class="card__hint" id="last-backtest-hint">—</span></div>
    <div id="last-backtest" class="loading">Loading...</div>
  </article>

  <article class="card">
    <div class="card__head"><span class="card__title">Last Brief</span><span class="card__hint" id="last-brief-hint">—</span></div>
    <div id="last-brief" class="loading">Loading...</div>
  </article>

  <article class="card">
    <div class="card__head"><span class="card__title">Paper Portfolio</span><span class="card__hint" id="portfolio-hint">—</span></div>
    <div id="portfolio" class="loading">Loading...</div>
  </article>

  <article class="card card--full">
    <div class="card__head"><span class="card__title">Positions</span><span class="card__hint" id="positions-hint">—</span></div>
    <div id="positions" class="loading">Loading...</div>
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
    <div id="recent-fills" class="loading">Loading...</div>
  </article>

  <article class="card card--full">
    <div class="card__head"><span class="card__title">Model Performance</span><span class="card__hint">latest schema pass rate</span></div>
    <div id="model-performance" class="loading">Loading...</div>
  </article>
</section>
""".strip()


_DASHBOARD_JS = """
async function loadDashboard() {
  const [status, symbols, reports, briefs, portfolio, risk, orders] = await Promise.all([
    fetchJSON("/api/status"),
    fetchJSON("/api/v1/data/symbols"),
    fetchJSON("/api/v1/backtest/reports"),
    fetchJSON("/api/v1/brief/history"),
    fetchJSON("/api/v1/paper/portfolio"),
    fetchJSON("/api/v1/risk/dashboard"),
    fetchJSON("/api/v1/paper/orders?status=order_created"),
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
    document.getElementById("project-status").innerHTML =
      '<div class="card__value">' + escapeHtml(status.environment) + '</div>'
      + '<div class="card__label">'
      + (status.live_trading_enabled ? "Live trading enabled" : "Paper trading only")
      + '</div>';
  } else {
    document.getElementById("project-status-pill").innerHTML = "";
    document.getElementById("project-status").innerHTML = '<div class="error">Failed to load</div>';
  }

  // Data symbols
  if (symbols) {
    const n = (symbols.symbols || []).length;
    document.getElementById("data-symbols-hint").textContent = "universe";
    document.getElementById("data-symbols").innerHTML =
      '<div class="card__value">' + n + '</div>'
      + '<div class="card__label">loaded symbols</div>';
  } else {
    document.getElementById("data-symbols").innerHTML = '<div class="error">Failed to load</div>';
  }

  // Risk status
  if (risk) {
    const ks = !!risk.kill_switch_active;
    const te = !!risk.config && risk.config.trading_enabled;
    document.getElementById("risk-status-pill").innerHTML = te
      ? '<span class="pill pill--green">TRADING ON</span>'
      : '<span class="pill pill--amber">TRADING OFF</span>';
    document.getElementById("risk-status").innerHTML =
      '<div class="status">'
      + '<span class="status-dot ' + (ks ? "err" : "ok") + '" aria-hidden="true"></span>'
      + (ks ? "Kill switch active" : "Risk gate ok")
      + '</div>'
      + '<div class="card__label">' + (te ? "Orders accepted" : "Orders blocked") + '</div>';
  } else {
    document.getElementById("risk-status").innerHTML = '<div class="error">Failed to load</div>';
  }

  // Last backtest
  const lastReport = reports && reports.reports && reports.reports[reports.reports.length - 1];
  if (lastReport) {
    const r = Number(lastReport.total_return || 0);
    const cls = r >= 0 ? "card__value--green" : "card__value--red";
    document.getElementById("last-backtest-hint").textContent = escapeHtml(lastReport.symbol || "");
    document.getElementById("last-backtest").innerHTML =
      '<div class="card__value ' + cls + '">' + fmtPct(r, 2) + '</div>'
      + '<div class="card__label">' + Number(lastReport.trade_count || 0) + ' trades · last run</div>';
  } else {
    document.getElementById("last-backtest").innerHTML =
      '<div class="card__value">—</div><div class="card__label">No backtests yet</div>';
  }

  // Last brief
  const lastBrief = briefs && briefs.briefs && briefs.briefs[briefs.briefs.length - 1];
  if (lastBrief) {
    document.getElementById("last-brief-hint").textContent = escapeHtml(lastBrief.trading_day || "");
    document.getElementById("last-brief").innerHTML =
      '<div class="card__value card__value--small">' + escapeHtml(lastBrief.headline || "") + '</div>'
      + '<div class="card__label">' + fmtTime(lastBrief.generated_at) + '</div>';
  } else {
    document.getElementById("last-brief").innerHTML =
      '<div class="card__value">—</div><div class="card__label">No briefs yet</div>';
  }

  // Paper portfolio
  const positions = (portfolio && portfolio.positions) || [];
  if (portfolio) {
    const cash = Number(portfolio.cash || 0);
    document.getElementById("portfolio-hint").textContent = positions.length + " positions";
    document.getElementById("portfolio").innerHTML =
      '<div class="card__value">$' + fmtNumber(cash) + '</div>'
      + '<div class="card__label">cash · ' + positions.length + ' open</div>';
  } else {
    document.getElementById("portfolio").innerHTML = '<div class="error">Failed to load</div>';
  }

  // Positions table
  document.getElementById("positions-hint").textContent = positions.length + " open";
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
  document.getElementById("positions").innerHTML = positionsHtml;

  drawEquityCurve(positions.length);

  // Recent fills
  const recentOrders = ((orders && orders.entries) || []).slice(0, 5);
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
  document.getElementById("recent-fills").innerHTML = fillsHtml;

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
  document.getElementById("model-performance").innerHTML = cardsHtml.length === 0
    ? '<div class="empty">No model evaluations yet. POST /api/v1/models/evaluate to run one.</div>'
    : '<div class="grid">' + cardsHtml + '</div>';
}

function drawEquityCurve(hasPositions) {
  const canvas = document.getElementById("equity-canvas");
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(rect.width, 320);
  const h = Math.max(rect.height, 160);
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const samples = 20;
  const base = 100000;
  const points = [];
  for (let i = 0; i < samples; i++) {
    const noise = Math.sin(i * 0.5) * 200 + (hasPositions ? (i - samples / 2) * 100 : 0);
    points.push(base + i * 50 + noise);
  }
  const min = Math.min.apply(null, points);
  const max = Math.max.apply(null, points);
  const span = (max - min) || 1;
  const padTop = 12, padBot = 12, padLeft = 12, padRight = 12;
  const innerW = w - padLeft - padRight;
  const innerH = h - padTop - padBot;

  // Grid
  ctx.strokeStyle = "rgba(148, 163, 184, 0.08)";
  ctx.lineWidth = 1;
  for (let g = 0; g <= 4; g++) {
    const y = padTop + (innerH * g) / 4;
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(w - padRight, y);
    ctx.stroke();
  }

  const xy = points.map(function (v, i) {
    const x = padLeft + (i / (samples - 1)) * innerW;
    const y = padTop + innerH - ((v - min) / span) * innerH;
    return [x, y];
  });

  // Fill
  const grad = ctx.createLinearGradient(0, padTop, 0, h - padBot);
  grad.addColorStop(0, "rgba(0, 212, 255, 0.28)");
  grad.addColorStop(1, "rgba(0, 212, 255, 0)");
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.moveTo(xy[0][0], h - padBot);
  xy.forEach(function (p) { ctx.lineTo(p[0], p[1]); });
  ctx.lineTo(xy[xy.length - 1][0], h - padBot);
  ctx.closePath();
  ctx.fill();

  // Line
  ctx.strokeStyle = "#00d4ff";
  ctx.lineWidth = 1.75;
  ctx.beginPath();
  xy.forEach(function (p, i) { if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]); });
  ctx.stroke();

  // End dot
  const last = xy[xy.length - 1];
  ctx.fillStyle = "#00d4ff";
  ctx.beginPath();
  ctx.arc(last[0], last[1], 3, 0, Math.PI * 2);
  ctx.fill();

  // Meta
  const latest = "$" + fmtNumber(Math.round(points[points.length - 1]));
  const first = points[0];
  const delta = points[points.length - 1] - first;
  const deltaPct = (delta / first) * 100;
  document.getElementById("equity-latest").textContent = latest;
  const deltaEl = document.getElementById("equity-delta");
  const sign = delta >= 0 ? "+" : "";
  deltaEl.textContent = sign + fmtNumber(Math.round(delta)) + " (" + sign + deltaPct.toFixed(2) + "%)";
  deltaEl.style.color = delta >= 0 ? "var(--green)" : "var(--red)";
}

window.addEventListener("resize", function () {
  drawEquityCurve(true);
});

loadDashboard();
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
            meta='<span class="pill pill--accent" id="env-pill">—</span>',
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


__all__ = ["router"]
