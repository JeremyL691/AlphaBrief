"""Dashboard routes — serves a multi-page HTML dashboard (Phase 11+)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])


_BASE_STYLES = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
header { background: #1e293b; padding: 1.5rem 2rem; border-bottom: 1px solid #334155; }
header h1 { font-size: 1.5rem; color: #38bdf8; }
header p { color: #94a3b8; font-size: 0.875rem; margin-top: 0.25rem; }
nav { background: #1e293b; padding: 0.5rem 2rem; border-bottom: 1px solid #334155; display: flex; gap: 1rem; flex-wrap: wrap; }
nav a { color: #94a3b8; text-decoration: none; font-size: 0.875rem; padding: 0.25rem 0.5rem; border-radius: 4px; }
nav a:hover { background: #334155; color: #f8fafc; }
main { max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1.5rem; }
.card h2 { font-size: 0.875rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.75rem; }
.card .value { font-size: 2rem; font-weight: 700; color: #f8fafc; }
.card .label { font-size: 0.75rem; color: #64748b; margin-top: 0.5rem; }
.card .list { list-style: none; padding: 0; }
.card .list li { padding: 0.5rem 0; border-bottom: 1px solid #334155; font-size: 0.875rem; }
.card .list li:last-child { border-bottom: none; }
.status { display: inline-flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.ok { background: #22c55e; }
.status-dot.warn { background: #f59e0b; }
.loading { color: #64748b; font-style: italic; }
.error { color: #f87171; }
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
th, td { padding: 0.5rem; text-align: left; border-bottom: 1px solid #334155; }
th { color: #94a3b8; text-transform: uppercase; font-size: 0.75rem; }
canvas { background: #0f172a; border: 1px solid #334155; border-radius: 4px; }
footer { text-align: center; padding: 2rem; color: #475569; font-size: 0.75rem; }
""".strip()


_NAV_LINKS = """
<nav>
  <a href="/dashboard">Main</a>
  <a href="/dashboard/news">News</a>
  <a href="/dashboard/macro">Macro</a>
  <a href="/dashboard/brief">Briefs</a>
  <a href="/dashboard/debate">Debate</a>
  <a href="/dashboard/models">Models</a>
  <a href="/dashboard/strategies">Strategies</a>
</nav>
""".strip()


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
  if (text === null || text === undefined) return '';
  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}
""".strip()


_DASHBOARD_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AlphaBrief Dashboard</title>
<style>
{_BASE_STYLES}
</style>
</head>
<body>
<header>
  <h1>AlphaBrief Dashboard</h1>
  <p>Local-first AI quant research and paper-trading workbench</p>
</header>
{_NAV_LINKS}
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
    <div class="card" style="grid-column: 1 / -1;">
      <h2>Positions</h2>
      <div id="positions" class="loading">Loading...</div>
    </div>
    <div class="card" style="grid-column: 1 / -1;">
      <h2>Equity Curve</h2>
      <div id="equity-curve"><canvas id="equity-canvas" width="1100" height="160"></canvas></div>
    </div>
    <div class="card" style="grid-column: 1 / -1;">
      <h2>Recent Fills</h2>
      <div id="recent-fills" class="loading">Loading...</div>
    </div>
    <div class="card" style="grid-column: 1 / -1;">
      <h2>Model Performance</h2>
      <div id="model-performance" class="loading">Loading...</div>
    </div>
  </div>
</main>
<footer>AlphaBrief v0.0.0 &mdash; <a href="/docs" style="color: #38bdf8;">API Docs</a> &middot; <a href="/redoc" style="color: #38bdf8;">ReDoc</a></footer>
<script>
{_COMMON_SCRIPTS}

async function loadDashboard() {{
  const [status, symbols, reports, briefs, portfolio, risk, orders] = await Promise.all([
    fetchJSON('/api/status'),
    fetchJSON('/api/v1/data/symbols'),
    fetchJSON('/api/v1/backtest/reports'),
    fetchJSON('/api/v1/brief/history'),
    fetchJSON('/api/v1/paper/portfolio'),
    fetchJSON('/api/v1/risk/dashboard'),
    fetchJSON('/api/v1/paper/orders?status=order_created'),
  ]);

  document.getElementById('project-status').innerHTML = status
    ? `<div class="value">${{status.environment}}</div><div class="label">Live trading: ${{status.live_trading_enabled ? 'ON' : 'OFF'}}</div>`
    : '<div class="error">Failed to load</div>';

  document.getElementById('data-symbols').innerHTML = symbols
    ? `<div class="value">${{symbols.symbols.length}}</div><div class="label">Loaded symbols</div>`
    : '<div class="error">Failed to load</div>';

  const lastReport = reports?.reports?.[reports.reports.length - 1];
  document.getElementById('last-backtest').innerHTML = lastReport
    ? `<div class="value">${{(lastReport.total_return * 100).toFixed(2)}}%</div><div class="label">${{escapeHtml(lastReport.symbol)}} &mdash; ${{lastReport.trade_count}} trades</div>`
    : '<div class="value">&mdash;</div><div class="label">No backtests yet</div>';

  const lastBrief = briefs?.briefs?.[briefs.briefs.length - 1];
  document.getElementById('last-brief').innerHTML = lastBrief
    ? `<div class="value" style="font-size:1rem;">${{escapeHtml(lastBrief.headline)}}</div><div class="label">${{escapeHtml(lastBrief.trading_day)}}</div>`
    : '<div class="value">&mdash;</div><div class="label">No briefs yet</div>';

  const positions = portfolio?.positions || [];
  document.getElementById('portfolio').innerHTML = portfolio
    ? `<div class="value">$${{Number(portfolio.cash).toLocaleString()}}</div><div class="label">Cash &middot; ${{positions.length}} positions</div>`
    : '<div class="error">Failed to load</div>';

  const positionsHtml = positions.length === 0
    ? '<div class="label">No open positions</div>'
    : '<table><thead><tr><th>Symbol</th><th>Quantity</th><th>Avg Price</th></tr></thead><tbody>'
      + positions.map(p => `<tr><td>${{escapeHtml(p.symbol)}}</td><td>${{p.quantity}}</td><td>${{p.average_price}}</td></tr>`).join('')
      + '</tbody></table>';
  document.getElementById('positions').innerHTML = positionsHtml;

  drawEquityCurve(positions.length);

  const recentOrders = (orders?.entries || []).slice(0, 5);
  const fillsHtml = recentOrders.length === 0
    ? '<div class="label">No recent orders</div>'
    : '<table><thead><tr><th>Time</th><th>Symbol</th><th>Message</th></tr></thead><tbody>'
      + recentOrders.map(o => `<tr><td>${{escapeHtml(o.created_at)}}</td><td>${{escapeHtml(o.symbol || '')}}</td><td>${{escapeHtml(o.message || '')}}</td></tr>`).join('')
      + '</tbody></table>';
  document.getElementById('recent-fills').innerHTML = fillsHtml;

  document.getElementById('risk-status').innerHTML = risk
    ? `<div class="status"><span class="status-dot ${{risk.kill_switch_active ? 'warn' : 'ok'}}"></span>${{risk.kill_switch_active ? 'Kill switch ACTIVE' : 'Risk gate OK'}}</div><div class="label">Trading: ${{risk.config.trading_enabled ? 'Enabled' : 'Disabled'}}</div>`
    : '<div class="error">Failed to load</div>';

  const modelsData = await fetchJSON('/api/v1/models/evaluations?limit=20');
  const evaluations = modelsData?.entries || [];
  const modelIds = Array.from(new Set(evaluations.map(e => e.model_id))).slice(0, 6);
  const modelCards = await Promise.all(modelIds.map(id => fetchJSON('/api/v1/models/performance/' + encodeURIComponent(id))));
  const cardsHtml = modelCards
    .filter(c => c !== null)
    .map(card => {{
      const tasks = Object.values(card.evaluations_by_task || {{}});
      const latest = tasks[0];
      const rate = latest ? Math.round((latest.schema_pass_rate || 0) * 100) : null;
      const colorClass = rate === null ? 'warn' : rate >= 90 ? 'ok' : rate >= 70 ? 'warn' : 'warn';
      const rateStr = rate === null ? 'No data' : rate + '%';
      return `<div class="card" style="background: #0f172a; border: 1px solid #475569;">
        <h2>${{escapeHtml(card.model_id)}}</h2>
        <div class="value">${{rateStr}}</div>
        <div class="label">schema pass rate (latest)</div>
        <div class="status"><span class="status-dot ${{colorClass}}"></span>${{tasks.length}} task(s) evaluated</div>
      </div>`;
    }}).join('');
  document.getElementById('model-performance').innerHTML = modelCards.length === 0
    ? '<div class="label">No model evaluations yet. POST /api/v1/models/evaluate to run one.</div>'
    : '<div class="grid">' + cardsHtml + '</div>';
}}

function drawEquityCurve(hasPositions) {{
  const canvas = document.getElementById('equity-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const samples = 20;
  const base = 100000;
  const points = [];
  for (let i = 0; i < samples; i++) {{
    const noise = Math.sin(i * 0.5) * 200 + (hasPositions ? (i - samples / 2) * 100 : 0);
    points.push(base + i * 50 + noise);
  }}
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((value, idx) => {{
    const x = (idx / (samples - 1)) * (canvas.width - 20) + 10;
    const y = canvas.height - 10 - ((value - min) / span) * (canvas.height - 20);
    if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }});
  ctx.stroke();
}}

loadDashboard();
</script>
</body>
</html>"""


_NEWS_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>News Dashboard</title>
<style>
{_BASE_STYLES}
</style>
</head>
<body>
<header>
  <h1>News</h1>
  <p>Latest news headlines stored in DuckDB</p>
</header>
{_NAV_LINKS}
<main>
  <div class="card">
    <h2>Headlines</h2>
    <div id="headlines" class="loading">Loading...</div>
  </div>
</main>
<footer><a href="/dashboard" style="color: #38bdf8;">Back to dashboard</a></footer>
<script>
{_COMMON_SCRIPTS}

async function loadNews() {{
  const data = await fetchJSON('/api/v1/news/headlines?limit=50');
  const list = data?.headlines || [];
  const html = list.length === 0
    ? '<div class="label">No headlines yet. POST /api/v1/news/fetch to ingest some.</div>'
    : '<table><thead><tr><th>Published</th><th>Source</th><th>Symbols</th><th>Title</th><th>Category</th></tr></thead><tbody>'
      + list.map(h => `<tr><td>${{escapeHtml(h.published_at)}}</td><td>${{escapeHtml(h.source)}}</td><td>${{(h.symbols || []).map(escapeHtml).join(', ')}}</td><td>${{escapeHtml(h.title)}}</td><td>${{escapeHtml(h.category)}}</td></tr>`).join('')
      + '</tbody></table>';
  document.getElementById('headlines').innerHTML = html;
}}

loadNews();
</script>
</body>
</html>"""


_MACRO_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Macro Dashboard</title>
<style>
{_BASE_STYLES}
</style>
</head>
<body>
<header>
  <h1>Macro Indicators</h1>
  <p>Latest macro indicators stored in DuckDB</p>
</header>
{_NAV_LINKS}
<main>
  <div class="card">
    <h2>Indicators</h2>
    <div id="indicators" class="loading">Loading...</div>
  </div>
</main>
<footer><a href="/dashboard" style="color: #38bdf8;">Back to dashboard</a></footer>
<script>
{_COMMON_SCRIPTS}

async function loadMacro() {{
  const data = await fetchJSON('/api/v1/macro/indicators?limit=50');
  const list = data?.indicators || [];
  const html = list.length === 0
    ? '<div class="label">No indicators yet. POST /api/v1/macro/fetch to ingest some.</div>'
    : '<table><thead><tr><th>Released</th><th>ID</th><th>Name</th><th>Value</th><th>Unit</th></tr></thead><tbody>'
      + list.map(i => `<tr><td>${{escapeHtml(i.released_at)}}</td><td>${{escapeHtml(i.indicator_id)}}</td><td>${{escapeHtml(i.name)}}</td><td>${{escapeHtml(i.value)}}</td><td>${{escapeHtml(i.unit || '')}}</td></tr>`).join('')
      + '</tbody></table>';
  document.getElementById('indicators').innerHTML = html;
}}

loadMacro();
</script>
</body>
</html>"""


_BRIEF_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Brief Dashboard</title>
<style>
{_BASE_STYLES}
</style>
</head>
<body>
<header>
  <h1>Daily Briefs</h1>
  <p>Generated daily AlphaBrief history</p>
</header>
{_NAV_LINKS}
<main>
  <div class="card">
    <h2>Briefs</h2>
    <div id="briefs" class="loading">Loading...</div>
  </div>
  <div class="card" id="brief-detail" style="display:none;">
    <h2>Detail</h2>
    <div id="brief-detail-content"></div>
  </div>
</main>
<footer><a href="/dashboard" style="color: #38bdf8;">Back to dashboard</a></footer>
<script>
{_COMMON_SCRIPTS}

async function loadBriefs() {{
  const data = await fetchJSON('/api/v1/brief/history');
  const list = data?.briefs || [];
  const html = list.length === 0
    ? '<div class="label">No briefs yet. POST /api/v1/brief/generate to create one.</div>'
    : '<table><thead><tr><th>Trading Day</th><th>Generated At</th><th>Headline</th><th></th></tr></thead><tbody>'
      + list.map(b => `<tr><td>${{escapeHtml(b.trading_day)}}</td><td>${{escapeHtml(b.generated_at)}}</td><td>${{escapeHtml(b.headline)}}</td><td><a href="#" data-id="${{escapeHtml(b.brief_id)}}" class="brief-link">View</a></td></tr>`).join('')
      + '</tbody></table>';
  document.getElementById('briefs').innerHTML = html;
  document.querySelectorAll('.brief-link').forEach(el => {{
    el.addEventListener('click', async (e) => {{
      e.preventDefault();
      const id = e.target.dataset.id;
      const detail = await fetchJSON('/api/v1/brief/' + encodeURIComponent(id));
      const card = document.getElementById('brief-detail');
      const content = document.getElementById('brief-detail-content');
      if (detail) {{
        content.innerHTML = `<pre style="white-space: pre-wrap; color: #cbd5e1; font-size: 0.8rem;">${{escapeHtml(JSON.stringify(detail, null, 2))}}</pre>`;
        card.style.display = 'block';
      }}
    }});
  }});
}}

loadBriefs();
</script>
</body>
</html>"""


_DEBATE_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Debate Dashboard</title>
<style>
{_BASE_STYLES}
</style>
</head>
<body>
<header>
  <h1>Research Debates</h1>
  <p>Multi-model research debate history</p>
</header>
{_NAV_LINKS}
<main>
  <div class="card">
    <h2>Debates</h2>
    <div id="debates" class="loading">Loading...</div>
  </div>
  <div class="card" id="debate-detail" style="display:none;">
    <h2>Detail</h2>
    <div id="debate-detail-content"></div>
  </div>
</main>
<footer><a href="/dashboard" style="color: #38bdf8;">Back to dashboard</a></footer>
<script>
{_COMMON_SCRIPTS}

async function loadDebates() {{
  const data = await fetchJSON('/api/v1/research/debate');
  const list = data?.debates || [];
  const html = list.length === 0
    ? '<div class="label">No debates yet. POST /api/v1/research/debate to start one.</div>'
    : '<table><thead><tr><th>Created</th><th>Question</th><th></th></tr></thead><tbody>'
      + list.map(d => `<tr><td>${{escapeHtml(d.created_at)}}</td><td>${{escapeHtml(d.question)}}</td><td><a href="#" data-id="${{escapeHtml(d.debate_id)}}" class="debate-link">View</a></td></tr>`).join('')
      + '</tbody></table>';
  document.getElementById('debates').innerHTML = html;
  document.querySelectorAll('.debate-link').forEach(el => {{
    el.addEventListener('click', async (e) => {{
      e.preventDefault();
      const id = e.target.dataset.id;
      const detail = await fetchJSON('/api/v1/research/debate/' + encodeURIComponent(id));
      const card = document.getElementById('debate-detail');
      const content = document.getElementById('debate-detail-content');
      if (detail) {{
        content.innerHTML = `<pre style="white-space: pre-wrap; color: #cbd5e1; font-size: 0.8rem;">${{escapeHtml(JSON.stringify(detail, null, 2))}}</pre>`;
        card.style.display = 'block';
      }}
    }});
  }});
}}

loadDebates();
</script>
</body>
</html>"""


_MODELS_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Models Dashboard</title>
<style>
{_BASE_STYLES}
</style>
</head>
<body>
<header>
  <h1>Model Performance</h1>
  <p>Evaluation history across providers and task types</p>
</header>
{_NAV_LINKS}
<main>
  <div class="card" style="grid-column: 1 / -1;">
    <h2>Recent Evaluations</h2>
    <div id="evaluations" class="loading">Loading...</div>
  </div>
  <div class="card" style="grid-column: 1 / -1;">
    <h2>Performance by Model</h2>
    <div id="by-model" class="loading">Loading...</div>
  </div>
</main>
<footer><a href="/dashboard" style="color: #38bdf8;">Back to dashboard</a></footer>
<script>
{_COMMON_SCRIPTS}

function rateColor(rate) {{
  if (rate === null || rate === undefined) return 'warn';
  if (rate >= 0.9) return 'ok';
  if (rate >= 0.7) return 'warn';
  return 'warn';
}}

async function loadModels() {{
  const data = await fetchJSON('/api/v1/models/evaluations?limit=100');
  const list = data?.entries || [];
  const html = list.length === 0
    ? '<div class="label">No evaluations yet. Run ``alphabrief model evaluate`` to create one.</div>'
    : '<table><thead><tr><th>Evaluated</th><th>Model</th><th>Task</th><th>JSON%</th><th>Schema%</th><th>Latency (ms)</th><th>Samples</th></tr></thead><tbody>'
      + list.map(e => {{
        const json = e.json_valid_rate !== null ? Math.round(e.json_valid_rate * 100) + '%' : '-';
        const schema = e.schema_pass_rate !== null ? Math.round(e.schema_pass_rate * 100) + '%' : '-';
        const latency = e.avg_latency_ms !== null ? e.avg_latency_ms : '-';
        return `<tr>
          <td>${{escapeHtml(e.evaluated_at)}}</td>
          <td>${{escapeHtml(e.model_id)}}</td>
          <td>${{escapeHtml(e.task_type)}}</td>
          <td>${{escapeHtml(json)}}</td>
          <td>${{escapeHtml(schema)}}</td>
          <td>${{escapeHtml(String(latency))}}</td>
          <td>${{e.sample_count}}</td>
        </tr>`;
      }}).join('')
      + '</tbody></table>';
  document.getElementById('evaluations').innerHTML = html;

  const modelIds = Array.from(new Set(list.map(e => e.model_id)));
  const perfData = await Promise.all(
    modelIds.map(id => fetchJSON('/api/v1/models/performance/' + encodeURIComponent(id)))
  );
  const byModelHtml = perfData
    .filter(p => p !== null)
    .map(p => {{
      const tasks = Object.entries(p.evaluations_by_task || {{}});
      const taskRows = tasks.map(([task, ev]) => {{
        const sp = ev.schema_pass_rate !== null ? Math.round(ev.schema_pass_rate * 100) + '%' : '-';
        return `<tr>
          <td>${{escapeHtml(task)}}</td>
          <td>${{escapeHtml(sp)}}</td>
          <td>${{escapeHtml(String(ev.sample_count))}}</td>
          <td>${{escapeHtml(String(ev.avg_latency_ms ?? '-'))}}</td>
        </tr>`;
      }}).join('');
      return `<div class="card" style="background: #0f172a; border: 1px solid #475569;">
        <h2>${{escapeHtml(p.model_id)}}</h2>
        <div class="label">Latest: ${{escapeHtml(p.latest_evaluated_at || '-')}}</div>
        <table style="margin-top: 0.5rem;">
          <thead><tr><th>Task</th><th>Schema pass</th><th>Samples</th><th>Latency</th></tr></thead>
          <tbody>${{taskRows}}</tbody>
        </table>
      </div>`;
    }}).join('');
  document.getElementById('by-model').innerHTML = perfData.filter(p => p !== null).length === 0
    ? '<div class="label">No model performance data yet.</div>'
    : '<div class="grid">' + byModelHtml + '</div>';
}}

loadModels();
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse)
def get_dashboard() -> HTMLResponse:
    """Serve the AlphaBrief web dashboard main page."""
    return HTMLResponse(content=_DASHBOARD_HTML)


@router.get("/dashboard/news", response_class=HTMLResponse)
def get_dashboard_news() -> HTMLResponse:
    """Serve the news dashboard page."""
    return HTMLResponse(content=_NEWS_HTML)


@router.get("/dashboard/macro", response_class=HTMLResponse)
def get_dashboard_macro() -> HTMLResponse:
    """Serve the macro dashboard page."""
    return HTMLResponse(content=_MACRO_HTML)


@router.get("/dashboard/brief", response_class=HTMLResponse)
def get_dashboard_brief() -> HTMLResponse:
    """Serve the brief dashboard page."""
    return HTMLResponse(content=_BRIEF_HTML)


@router.get("/dashboard/debate", response_class=HTMLResponse)
def get_dashboard_debate() -> HTMLResponse:
    """Serve the debate dashboard page."""
    return HTMLResponse(content=_DEBATE_HTML)


@router.get("/dashboard/models", response_class=HTMLResponse)
def get_dashboard_models() -> HTMLResponse:
    """Serve the model evaluation dashboard page."""
    return HTMLResponse(content=_MODELS_HTML)


_STRATEGIES_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Strategies Dashboard</title>
<style>
{_BASE_STYLES}
.badge {{
  display: inline-block;
  padding: 0.125rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}}
.badge.on {{ background: #14532d; color: #bbf7d0; }}
.badge.off {{ background: #1f2937; color: #9ca3af; }}
.advisory {{
  color: #94a3b8;
  font-size: 0.75rem;
  font-style: italic;
}}
</style>
</head>
<body>
<header>
  <h1>Strategy Registry</h1>
  <p>Persisted StrategySpec objects and their advisory signal history</p>
</header>
{_NAV_LINKS}
<main>
  <div class="card">
    <h2>Strategies</h2>
    <div id="strategies" class="loading">Loading...</div>
    <p class="advisory">The <code>enabled</code> flag is advisory only. It does not block orders and is not consulted by RiskGate or PaperBroker.</p>
  </div>
  <div class="card" id="strategy-detail" style="display:none;">
    <h2>Detail</h2>
    <div id="strategy-detail-content"></div>
  </div>
  <div class="card">
    <h2>Signal Counts</h2>
    <div id="signal-counts" class="loading">Loading...</div>
    <p class="advisory">Signal history is a write-only advisory log; it never modifies risk decisions.</p>
  </div>
</main>
<footer><a href="/dashboard" style="color: #38bdf8;">Back to dashboard</a></footer>
<script>
{_COMMON_SCRIPTS}

async function loadStrategies() {{
  const data = await fetchJSON('/api/v1/strategies/specs');
  const list = data?.strategies || [];
  const html = list.length === 0
    ? '<div class="label">No strategies yet. POST /api/v1/strategies/specs or run <code>alphabrief strategy save</code> to create one.</div>'
    : '<table><thead><tr><th>Strategy ID</th><th>Name</th><th>Version</th><th>Enabled</th><th>Updated</th><th></th></tr></thead><tbody>'
      + list.map(s => {{
          const badge = s.enabled
            ? '<span class="badge on">Enabled</span>'
            : '<span class="badge off">Disabled</span>';
          return `<tr>
            <td>${{escapeHtml(s.strategy_id)}}</td>
            <td>${{escapeHtml(s.name)}}</td>
            <td>${{escapeHtml(s.version)}}</td>
            <td>${{badge}}</td>
            <td>${{escapeHtml(s.updated_at)}}</td>
            <td><a href="#" data-id="${{escapeHtml(s.strategy_id)}}" class="strategy-link">View</a></td>
          </tr>`;
        }}).join('')
      + '</tbody></table>';
  document.getElementById('strategies').innerHTML = html;
  document.querySelectorAll('.strategy-link').forEach(el => {{
    el.addEventListener('click', async (e) => {{
      e.preventDefault();
      const id = e.target.dataset.id;
      const detail = await fetchJSON('/api/v1/strategies/specs/' + encodeURIComponent(id));
      const card = document.getElementById('strategy-detail');
      const content = document.getElementById('strategy-detail-content');
      if (detail) {{
        content.innerHTML = `<pre style="white-space: pre-wrap; color: #cbd5e1; font-size: 0.8rem;">${{escapeHtml(JSON.stringify(detail, null, 2))}}</pre>`;
        card.style.display = 'block';
      }}
    }});
  }});

  const enabled = await fetchJSON('/api/v1/strategies/enabled');
  const ids = list.map(s => s.strategy_id);
  const counts = await Promise.all(
    ids.map(id => fetchJSON('/api/v1/strategies/' + encodeURIComponent(id) + '/signals/count'))
  );
  const rows = ids.map((id, i) => ({{
    id,
    count: counts[i]?.count ?? 0,
    isEnabled: (enabled?.strategy_ids || []).includes(id),
  }}));
  const countHtml = rows.length === 0
    ? '<div class="label">No strategies to summarize.</div>'
    : '<table><thead><tr><th>Strategy ID</th><th>Signals recorded</th><th>Advisory activation</th></tr></thead><tbody>'
      + rows.map(r => `<tr>
          <td>${{escapeHtml(r.id)}}</td>
          <td>${{r.count}}</td>
          <td>${{r.isEnabled ? '<span class="badge on">Enabled</span>' : '<span class="badge off">Disabled</span>'}}</td>
        </tr>`).join('')
      + '</tbody></table>';
  document.getElementById('signal-counts').innerHTML = countHtml;
}}

loadStrategies();
</script>
</body>
</html>"""


@router.get("/dashboard/strategies", response_class=HTMLResponse)
def get_dashboard_strategies() -> HTMLResponse:
    """Serve the strategy registry dashboard page."""
    return HTMLResponse(content=_STRATEGIES_HTML)


__all__ = ["router"]
