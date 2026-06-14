"""Dashboard route — serves a simple HTML status dashboard."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AlphaBrief Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
header { background: #1e293b; padding: 1.5rem 2rem; border-bottom: 1px solid #334155; }
header h1 { font-size: 1.5rem; color: #38bdf8; }
header p { color: #94a3b8; font-size: 0.875rem; margin-top: 0.25rem; }
main { max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1.5rem; }
.card h2 { font-size: 0.875rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.75rem; }
.card .value { font-size: 2rem; font-weight: 700; color: #f8fafc; }
.card .label { font-size: 0.75rem; color: #64748b; margin-top: 0.5rem; }
.status { display: inline-flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.ok { background: #22c55e; }
.status-dot.warn { background: #f59e0b; }
.loading { color: #64748b; font-style: italic; }
.error { color: #f87171; }
footer { text-align: center; padding: 2rem; color: #475569; font-size: 0.75rem; }
</style>
</head>
<body>
<header>
  <h1>AlphaBrief Dashboard</h1>
  <p>Local-first AI quant research and paper-trading workbench</p>
</header>
<main>
  <div class="grid">
    <div class="card">
      <h2>Project Status</h2>
      <div id="project-status" class="loading">Loading...</div>
    </div>
    <div class="card">
      <h2>Data Symbols</h2>
      <div id="data-symbols" class="loading">Loading...</div>
    </div>
    <div class="card">
      <h2>Last Backtest</h2>
      <div id="last-backtest" class="loading">Loading...</div>
    </div>
    <div class="card">
      <h2>Last Brief</h2>
      <div id="last-brief" class="loading">Loading...</div>
    </div>
    <div class="card">
      <h2>Paper Portfolio</h2>
      <div id="portfolio" class="loading">Loading...</div>
    </div>
    <div class="card">
      <h2>Risk Status</h2>
      <div id="risk-status" class="loading">Loading...</div>
    </div>
  </div>
</main>
<footer>AlphaBrief v0.0.0 &mdash; <a href="/docs" style="color: #38bdf8;">API Docs</a> &middot; <a href="/redoc" style="color: #38bdf8;">ReDoc</a></footer>
<script>
async function fetchJSON(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(res.status);
    return await res.json();
  } catch (err) {
    return null;
  }
}

async function loadDashboard() {
  const [status, symbols, reports, briefs, portfolio, risk] = await Promise.all([
    fetchJSON('/api/status'),
    fetchJSON('/api/v1/data/symbols'),
    fetchJSON('/api/v1/backtest/reports'),
    fetchJSON('/api/v1/brief/history'),
    fetchJSON('/api/v1/paper/portfolio'),
    fetchJSON('/api/v1/risk/dashboard'),
  ]);

  document.getElementById('project-status').innerHTML = status
    ? `<div class="value">${status.environment}</div><div class="label">Live trading: ${status.live_trading_enabled ? 'ON' : 'OFF'}</div>`
    : '<div class="error">Failed to load</div>';

  document.getElementById('data-symbols').innerHTML = symbols
    ? `<div class="value">${symbols.symbols.length}</div><div class="label">Loaded symbols</div>`
    : '<div class="error">Failed to load</div>';

  const lastReport = reports?.reports?.[reports.reports.length - 1];
  document.getElementById('last-backtest').innerHTML = lastReport
    ? `<div class="value">${(lastReport.total_return * 100).toFixed(2)}%</div><div class="label">${lastReport.symbol} — ${lastReport.trade_count} trades</div>`
    : '<div class="value">—</div><div class="label">No backtests yet</div>';

  const lastBrief = briefs?.briefs?.[briefs.briefs.length - 1];
  document.getElementById('last-brief').innerHTML = lastBrief
    ? `<div class="value" style="font-size:1rem;">${escapeHtml(lastBrief.headline)}</div><div class="label">${lastBrief.trading_day}</div>`
    : '<div class="value">—</div><div class="label">No briefs yet</div>';

  document.getElementById('portfolio').innerHTML = portfolio
    ? `<div class="value">$${Number(portfolio.cash).toLocaleString()}</div><div class="label">Cash &middot; ${portfolio.positions?.length || 0} positions</div>`
    : '<div class="error">Failed to load</div>';

  document.getElementById('risk-status').innerHTML = risk
    ? `<div class="status"><span class="status-dot ${risk.kill_switch_active ? 'warn' : 'ok'}"></span>${risk.kill_switch_active ? 'Kill switch ACTIVE' : 'Risk gate OK'}</div><div class="label">Trading: ${risk.config.trading_enabled ? 'Enabled' : 'Disabled'}</div>`
    : '<div class="error">Failed to load</div>';
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

loadDashboard();
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse)
def get_dashboard() -> HTMLResponse:
    """Serve the AlphaBrief web dashboard."""
    return HTMLResponse(content=_DASHBOARD_HTML)


__all__ = ["router"]
