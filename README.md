# AlphaBrief

A local-first data pipeline for market, news, and macro research. It ingests from multiple providers, versions immutable facts in DuckDB, and runs a durable daily cycle with restart-resume and at-most-once OANDA practice execution.

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![Tests: ~3k collected](https://img.shields.io/badge/tests-%7E3k%20collected-blue.svg)](#current-verified-baseline)

```mermaid
flowchart LR
    E[electron desktop] --> API[apps/api<br/>FastAPI + dashboard]
    CLI[apps/cli<br/>CLI + scheduler] --> API
    API --> DATA[packages/alphabrief-data<br/>providers + bars + quality]
    API --> NEWS[packages/alphabrief-news<br/>news + sentiment]
    DATA --> DB[(DuckDB<br/>versioned immutable facts)]
    NEWS --> DB
    API --> TRADER[packages/alphabrief-trader<br/>AI committee + daily cycle]
    TRADER --> STRAT[alphabrief-strategy<br/>signals]
    TRADER --> BT[alphabrief-backtest<br/>IS/OOS walk-forward]
    TRADER --> RISK[alphabrief-risk<br/>deterministic risk gates]
    RISK --> EXEC[alphabrief-execution<br/>OANDA practice only]
    EXEC --> DB
```

## Why I built this

Market-data scripts kept annoying me in the same way: every provider had its own quirks, failures were silent, and killing a run mid-day either skipped work or duplicated orders. I wanted one place where ingestion is explicit, failures are classified, storage is immutable, and a scheduler can be killed and resumed without losing track. The committee and LLM parts are secondary. The data platform is the point.

## What it does

- Discovers tradable instruments from the configured OANDA practice account (`GET /v3/accounts/{id}/instruments`) instead of hard-coding a catalog.
- Ingests bars through `alphabrief-data` providers (CSV/Parquet loaders plus Yahoo, Binance, Alpha Vantage), with `check_bar_quality` covering duplicate timestamps, non-increasing sequences, mixed symbols, zero volume, and gap detection.
- Ingests news through `alphabrief-news` (`fetch_and_ingest`): canonical URL, published/fetched UTC, content hash, bounded summary, and a `fetch_outcome` in `success/empty/timeout/rate_limit/malformed/source_failure`.
- Runs a persisted compare-and-set daily cycle: preflight, ingest, snapshot, discuss, propose, risk, execute or no-trade, reconcile, report. A renewable leader lease and restart-resume at every phase boundary keep a crashed run recoverable, and external OANDA calls are at-most-once with correlation chains.
- Records evidence end to end: model calls, proposals, risk decisions, orders, transactions, reconciliation. Missing credentials surface as `BLOCKED_EXTERNAL`; no observation day is ever fabricated.
- Appends bars, news items, and order facts immutably in DuckDB (`db/schema.py` plus `db/migrations.py`, transactional and idempotent), under versioned migrations in `apps/api/src/alphabrief_api/db/`. Nothing is mutated in place, so research and reconciliation can be replayed.
- Runs a persisted daily cycle (`alphabrief-trader/cycle_state.py`, `cycle_execution.py`, `scheduler_leader.py`); killing the process and restarting resumes the same phase.
- Applies a deterministic `RiskGate` before any `OrderIntent` reaches OANDA practice. Reconciliation freezes execution on unexplained differences.
- Keeps live trading permanently unreachable. Only `api-fxpractice.oanda.com` and `stream-fxpractice.oanda.com` are allowlisted.

## Engineering notes

- **Provider boundaries.** `providers/base.py` defines `RetryPolicy` (`max_retries`, `initial_backoff`, `factor`, `jitter`) and `call_with_retry`, which only retries 429/418/5xx plus transient network errors. Providers return `Bar` lists and never call a third-party SDK directly; tests inject a fake `http_get` callable, so no real network is involved.
- **Data quality.** `quality.py` checks identity consistency (mixed symbols/sources/versions), timestamp ordering (duplicates, non-increasing), expected interval gaps, and zero volume. `phases` are `error` vs `warning`, so pipelines can decide to block or just warn.
- **News provenance.** `news/ingestion.py` persists `item_id, source, canonical_url, published_at, fetched_at, content_hash, summary, fetch_outcome, correlation_id, metadata_only` with `INSERT OR IGNORE`, keeps copyright-safe retention (metadata-only sources never store full text), and sanitizes content before research or risk sees it. Daily regime and sentiment snapshots are immutable and shared by research and risk.
- **Durable cycle.** `cycle_state.py` stores `phase, phase_order, output_ids` with `ON CONFLICT DO UPDATE`; `scheduler_leader.py` uses a renewable lease so only one scheduler runs. At-most-once is enforced with idempotency keys and immediate reconciliation after every OANDA call.

### Not done yet

- The daily cycle is wired end to end, but T7 practice runtime evidence for M15/M16 (30-day observation, weekly zero-difference invariants, fault drills) is still pending real credentials. Commands report `BLOCKED_EXTERNAL` or `WAITING_EXTERNAL` honestly.
- The strategy DSL is a typed AST allowlist, so no arbitrary code runs; backtests reproduce with frozen params. The IS/OOS and strategy read surfaces landed in M13 and still need T7 evidence.
- Execution is OANDA practice only. Alpaca and live paths were removed and stay removed; missing credentials fail closed, and an in-memory fill is never presented as an OANDA fill.
- OANDA account-wide discovery is not complete (M04); current providers are not OANDA-native, so production bars still come from Yahoo/Binance/Alpha Vantage.
- Model composition fails closed: without `OPENAI_API_KEY` or `OLLAMA_*`, `ModelGateway` refuses, and `FakeProvider` exists only in tests.

<details>
<summary>Milestone contract status (M09-M17) - contracts closed, T7 evidence pending</summary>

- M09 content pipeline (DONE): deterministic news ingestion with provenance, URL canonicalization + dedup + entity linking, revision-aware macro calendar, multi-scope sentiment, untrusted sanitization, immutable snapshots.
- M10 ModelGateway (DONE): exclusive gateway, fail-closed composition, durable call records/budgets, five-role committee, grounded proposals, bounded structured-output repair, cycle-key idempotency.
- M11 durable cycle (DONE): persisted CAS state machine with restart-resume every phase, leader lease, single runtime truth, research/execution separation, bounded candidate selection, catch-up windows, terminal no-trade.
- M12-M15 (DONE): read/write contracts, strategy backtest closure, dashboard redesign, engineering readiness. Frozen build is OANDA practice-only; network allowlist enforced.
- M16 observation (DONE, evidence PENDING): Day 0 manifest, 14-kind daily chains, weekly gates, fault drills, Day 30 close.
- M17 handoff (DONE, evidence PENDING): evidence-derived final acceptance report, fresh-install/runbook, deterministic Electron packaging, 11-gate final release (`COMPLETE_PAPER_ONLY`).

</details>

## Current Verified Baseline

Snapshot: 2026-08-14, commit `0a1016a` (all M01-M17 closed as contracts; 30-day observation pending T7 credentials; status `IN_PROGRESS`).

| Area | What exists now | Important limitation |
|---|---|---|
| Market data | CSV/Parquet loaders, Yahoo/Binance/Alpha Vantage providers, quality checks, features, DuckDB storage with versioned immutable bar facts | OANDA discovery not complete; providers not OANDA-native |
| News and macro | RSS, SEC, FRED, mock/social-sentiment providers, ingestion store with provenance | Production freshness and untrusted-content defenses incomplete |
| Models | ModelGateway, Fake/OpenAI/Ollama adapters, structured output, evaluation/router, durable call records | Production fails closed without real provider |
| Research | Briefs, evidence objects, debate, AI committee, daily cycle reports | Cycle wired end-to-end; runtime evidence pending |
| Strategy/backtest | Typed AST DSL, 5 strategy families with OANDA-category admission, spread/slippage/financing/margin simulation, IS/OOS walk-forward, leakage/overfitting gates | API surfaces in M13; T7 evidence pending |
| Risk | Symbol/order/exposure/loss/drawdown/news-aware primitives | Full account+news context not yet passed to every RiskGate call |
| Execution | In-memory paper broker (explicit local), OANDA practice adapter, reconciliation stores | OANDA lifecycle persistence and reconciliation incomplete |
| Operations | Scheduler, heartbeats, alerts, API/CLI, 9 dashboard pages, Electron; versioned migrations, writer lease, backups | 30-day evidence and control-plane truth incomplete |
| API/CLI contracts | 14 read domains, 7 idempotent operator writes with audit, 18 CLI groups / 57 subcommands / 86 OpenAPI endpoints / 9 dashboard routes, locked OpenAPI with CLI parity | Dashboard redesign in M14; T7 evidence pending |

Local quality at baseline: **1,389 passing tests + 12 local-HTTP failures from sandbox `127.0.0.1` bind refuse**; Ruff and Mypy passed. Current `main` collects **~3,025 tests** (21 collection errors without `httpx` - needs `pip install -e '.[dev]'`).

## Repository Layout

```text
apps/
  api/                     FastAPI and dashboard
  cli/                     Typer CLI and scheduler entry points
packages/
  alphabrief-core/         domain schemas and policy
  alphabrief-data/         bars, providers, quality, features
  alphabrief-news/         news and sentiment ingestion
  alphabrief-models/       ModelGateway and model adapters
  alphabrief-research/     briefs and debate
  alphabrief-strategy/     strategy specifications and signals
  alphabrief-backtest/     backtesting and metrics
  alphabrief-risk/         deterministic risk gate
  alphabrief-execution/    paper/OANDA execution and operations
  alphabrief-trader/       AI committee and daily cycle
  alphabrief-gym/          training environments
  alphabrief-review/       post-trade review
  alphabrief-acceptance/   deterministic project gates
electron/                  local desktop wrapper
config/                    non-secret policy and OANDA practice config
docs/                      authoritative development and operating documents
tests/                     unit, integration, contract, and acceptance tests
```

## Local Setup

Requirements: Python 3.12+, a virtual environment, and Node.js only for the Electron wrapper.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
```

Never put credentials in tracked YAML or source files. For an external practice account:

```bash
ALPHABRIEF_OANDA_TOKEN=...
ALPHABRIEF_OANDA_ACCOUNT_ID=...
```

Follow `docs/progress.yaml` for the current milestone; do not assume all surfaces are already OANDA-only until M01 is marked complete.

## Common Commands

```bash
.venv/bin/alphabrief --help
.venv/bin/alphabrief serve serve
.venv/bin/alphabrief scheduler status
.venv/bin/alphabrief acceptance verify --compact
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
```

Electron shell (optional):

```bash
cd electron
npm install
npm start
```

## Authoritative Documents

Read in this order when developing:

1. [Agent contract](AGENTS.md)
2. [Current progress](docs/progress.yaml)
3. [Final product blueprint](ALPHABRIEF_PRODUCT_BLUEPRINT.md)
4. [Machine work queue](docs/work_items.yaml)
5. [Autonomous loop protocol](docs/autonomous_loop.md)
6. [Current and target architecture](docs/architecture.md)
7. [Acceptance and traceability](docs/acceptance.md)
8. [OANDA 30-day runbook](docs/oanda_30_day_runbook.md)

Old phase plans and snapshot reports were intentionally removed; git history is the archive.

## Safety Notice

AlphaBrief is research software, not financial advice. The repository is designed for paper trading only. Do not connect it to a live endpoint or use practice results as evidence of future profitability.