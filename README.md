# AlphaBrief

AlphaBrief is a local-first, model-agnostic research workbench for
quantitative market research, backtesting, simulation, paper trading, risk
review, audit, and post-trade review.

```
market data -> research -> hypothesis -> StrategySpec -> backtest
-> simulation -> paper trading -> risk audit -> review
```

## Status

Phases 1–23 are implemented and locally verified. The project remains
paper-only: external broker credentials and a long-running external-paper
observation period are separate acceptance gates, and live trading stays
locked.

- **Phase 1 — Core.** Domain models, CSV/Parquet OHLCV loaders, in-memory
  data quality checks, no-lookahead features, StrategySpec schema, and a
  vectorized backtester with fees, slippage, equity curve, trades, and
  metrics.
- **Phase 2 — ModelGateway and research briefs.** Gateway contracts, a
  fake provider for tests, a local Ollama provider adapter, model
  registry and profile selection, prompt template versioning, structured
  output parser, MarketBrief, SymbolBrief, and DailyAlphaBrief
  generation.
- **Phase 3 — Risk and paper trading.** OrderIntent, RiskDecision,
  RiskGate, KillSwitch, OrderRouter, FillSimulator, PortfolioState,
  PaperBroker, and ExecutionAuditLog. Every OrderIntent passes RiskGate
  before reaching the paper broker.
- **Phase 4 — Trading environment.** Gymnasium-style `reset`/`step`
  interface with discrete actions, observations, transition rewards,
  transaction costs, slippage, a random-policy baseline, a buy-and-hold
  baseline, and a strategy comparison report.
- **Phase 5 — Review center.** Snapshot aggregation across strategies,
  backtests, briefs, model calls, paper portfolio, audit log, and risk
  data, plus plain-text viewers and deterministic daily/weekly journal
  generation.
- **Phase 6 — Web API surface.** FastAPI server exposing health, data,
  backtest, research, paper, risk, review, and dashboard endpoints,
  launched from the CLI.
- **Phase 7 — Persistent storage.** DuckDB-backed stores for market
  data, backtest reports, briefs, paper portfolio, audit logs, and
  review snapshots, so all API state survives restarts.
- **Phase 8 — Multi-model research committee.** Debate schemas,
  `DebateOrchestrator` that routes a question to multiple model
  perspectives and aggregates a consensus, DuckDB persistence, the
  `alphabrief research debate` CLI command, and
  `POST /api/v1/research/debate`.
- **Phase 9 — Real market data providers.** Key-less HTTP adapters for
  Yahoo Finance and Binance with a shared retry policy and an expanded
  interval set, plus the `alphabrief data fetch` CLI command and
  `POST /api/v1/data/fetch` endpoint that persist bars to the existing
  DuckDB store.
- **Phase 10 — News & Macro Data Layer.** Structured news headline
  and macro-economic indicator schemas, provider protocols, mock
  providers, RSS/Atom reader with free feed allowlist, DuckDB
  persistence, and full CLI/API surface. 58 new tests.
- **Phase 11 — Research integration, more data sources, trading
  env V2, multi-page dashboard.** News/macro context injection into
  research briefs and debate prompts, FRED/SEC/Sentiment/AlphaVantage
  providers, multi-asset continuous-action trading environment with
  short/leverage/liquidity/market-impact support, and five-page
  vanilla HTML dashboard. 108 new tests.
- **Phase 12 — External evidence + risk context.** Deterministic
  news/macro → risk tightening layer, strategy external evidence
  declaration and per-signal `SignalEvidence`, structured research
  context summary, and gymnasium EnvV2 episode reports with cost
  breakdowns. 62 new tests.
- **Phase 13 — RiskContext → RiskGate wiring.** `RiskGate` accepts an
  optional `RiskContextDecision` and applies it in a tighten-only
  manner. `PaperBroker` blocks auto-execution when the merged
  decision requires human review. The audit log records the
  risk-context metadata.
- **Phase 14 — Model evaluation & performance intelligence.**
  `ModelEvaluator` runs automated JSON/schema/hallucination
  evaluations against bundled local datasets through `ModelGateway`.
  `ModelRouter` adds cost/latency/performance-aware routing on top
  of the existing capability-based registry. The
  `model_evaluations` DuckDB table plus `ModelEvalStore` persist
  every record, and the new `/api/v1/models/*` endpoints and
  `alphabrief model {evaluate,performance,route,compare}` commands
  expose the full surface. The dashboard gains a Model Performance
  card grid and a dedicated `/dashboard/models` page. 87 new tests.
- **Phases 15–19 — Strategy lifecycle and paper-broker operations.**
  Strategy specifications and signals are persistent, versioned artifacts;
  the reviewed paper-only execution policy, Alpaca paper adapter,
  reconciliation store, scheduler operations surface, and account-level
  exposure guard are implemented. The exposure guard is fail-closed and
  tighten-only: it cannot relax an existing RiskGate decision.
- **Phase 20 — API-side broker observability.** The API process can
  expose read-only paper-broker positions and account snapshots through
  the broker adapter singleton. The surface never submits orders.
- **Phase 21 — Account-level risk hardening.** Runtime risk checks now
  cover per-symbol exposure, concentration, leverage, price deviation,
  market-open state, signal age, duplicate orders, daily loss, and
  drawdown floor. These checks are fail-closed and tighten-only.
- **Phase 22 — Kronos forecast integration.** Kronos is available as
  an optional market-forecasting provider through `ModelGateway` via
  `market_forecast` and `time_series_forecasting`. Forecasts are
  structured and advisory only; they never create signals, order
  intents, risk decisions, orders, or broker activity.
- **Phase 23 — Project acceptance closeout.** A read-only
  `alphabrief_acceptance` package verifies the project-level safety and
  delivery invariants. The verifier is exposed through
  `alphabrief acceptance verify` and `GET /api/v1/acceptance/verify`,
  and it checks required docs, importable runtime packages, paper-only
  defaults, RiskGate's live lock, advisory-only Kronos forecasts,
  reference-source isolation, provider SDK boundaries, and quality
  tooling configuration. The same package ships a scoped paper-broker
  pre-flight check via `alphabrief acceptance preflight --paper`
  and `GET /api/v1/acceptance/preflight?scope=paper`; it confirms the
  30-day observation runbook (`docs/paper_broker_setup.md`) is in place
  and that the Alpaca env-var names, paper execution policy, and
  broker config files are wired up.

## Safety Boundary

AlphaBrief is research-first and paper-first. It is not a live-trading
bot, a high-frequency trading system, or a wrapper around one model
provider.

1. Model calls must go through `ModelGateway`.
2. Business modules must not call provider SDKs directly.
3. Models cannot place orders or override risk controls.
4. Research outputs may produce structured reports, hypotheses,
   StrategySpec drafts, or OrderIntent drafts only.
5. Every OrderIntent must pass RiskGate before paper execution.
6. Live trading is disabled by default and out of scope for the MVP.
7. API keys and broker keys must never be committed, logged, or embedded
   in prompts.

## Repository Layout

```
apps/        API, CLI, and worker surfaces.
packages/    AlphaBrief-owned Python packages.
strategies/  Strategy specs and experiments.
tests/       Unit and boundary tests.
docs/        Architecture, roadmap, risk model, and development log.
reports/     Local report output placeholders.
notebooks/   Local analysis workspace placeholders.
scripts/     Utility scripts.
```

Runtime packages under `packages/*/src`:

- `alphabrief_core`
- `alphabrief_data` (with the `providers` subpackage)
- `alphabrief_strategy`
- `alphabrief_backtest`
- `alphabrief_models`
- `alphabrief_research`
- `alphabrief_risk`
- `alphabrief_execution`
- `alphabrief_gym`
- `alphabrief_review`
- `alphabrief_acceptance`

## Local Setup

Requirements:

- Python 3.12+
- A virtual environment

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Quality Gates

Run all checks before committing:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy
alphabrief acceptance verify
```

Current result: Phase 23 targeted acceptance and CLI coverage passes;
the sandboxed full pytest run reaches 1204 passing tests, with 12
localhost mock-broker tests blocked by sandbox socket permissions. Ruff
is clean, strict Mypy is clean across 223 source files, and the project
acceptance verifier is green. The
development log records the latest verified run and its environment
constraints.

## Paper Broker Setup

The external paper-trading adapter (Alpaca) and the 30-day observation
runbook are wired and ready to use. To attach AlphaBrief to a paper
account:

1. Read the runbook: [`docs/paper_broker_setup.md`](docs/paper_broker_setup.md).
2. Sign up at <https://app.alpaca.markets/signup> (Paper mode).
3. Copy `.env.example` to `.env` and fill in `ALPHABRIEF_ALPACA_KEY`
   and `ALPHABRIEF_ALPACA_SECRET` (placeholders in `.env.example`).
4. Run the pre-flight:

   ```bash
   .venv/bin/alphabrief acceptance preflight --paper
   .venv/bin/alphabrief broker status
   .venv/bin/alphabrief scheduler status
   ```

5. Start the 30-day run:

   ```bash
   .venv/bin/alphabrief scheduler run --reconcile-interval 60
   ```

The runbook covers daily and weekly observation checkpoints, freeze
handling, and end-of-run reporting. Live trading remains disabled by
default and locked by `RiskGate`; the scheduler refuses to start with
`ALPHABRIEF_LIVE_TRADING_ENABLED=true`.

## Reference Source Policy

Reference projects under `_reference_sources/` are local-only research
material. They are intentionally ignored by Git and must not be pushed to
this repository.

Allowed use:

- Read reference projects to understand behavior, product flows, and
  module boundaries.
- Convert observations into natural-language notes under
  `docs/reference_notes/`.
- Implement AlphaBrief-owned behavior from those notes using original
  names, interfaces, tests, and structure.

Forbidden use:

- Importing from `_reference_sources/`.
- Copying, translating, or lightly rewriting reference source files.
- Copying prompts, comments, test cases, class names, function names, or
  file structure.

## Configuration

Use `.env.example` as the local template. Do not commit real secrets.

```
ALPHABRIEF_ENV=local
ALPHABRIEF_LOG_LEVEL=INFO
ALPHABRIEF_LIVE_TRADING_ENABLED=false
ALPHABRIEF_DATA_DIR=data/local
ALPHABRIEF_REPORTS_DIR=reports/generated
ALPHABRIEF_AUDIT_LOG_DIR=reports/audit
```

## Documentation

- `ALPHABRIEF_PRODUCT_BLUEPRINT.md`
- `ALPHABRIEF_DEVELOPMENT_CADENCE.md`
- `PROJECT_RULES.md`
- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/model_gateway.md`
- `docs/risk_model.md`
- `docs/paper_broker_setup.md`
- `docs/development_log.md`

## Availability

This project is private and not open source. No public license is granted
at this stage. All rights are reserved unless a license is added later.
