# AlphaBrief

AlphaBrief is a local-first, model-agnostic research workbench for quantitative
market research, backtesting, simulation, paper trading, risk review, audit, and
post-trade review.

The project is built around a simple principle: AI can help produce structured
research, but deterministic systems must own validation, risk controls, audit
records, and execution boundaries.

```text
market data -> research -> hypothesis -> StrategySpec -> backtest
-> simulation -> paper trading -> risk audit -> review
```

## Status

AlphaBrief is in private MVP development.

Current implemented kernel:

1. Core domain models for bars, signals, order intents, risk decisions, and
   orders.
2. Local CSV and Parquet OHLCV loaders.
3. In-memory market data quality checks.
4. No-lookahead feature generation for trailing returns and moving averages.
5. StrategySpec schema and a simple strategy interface.
6. A long/flat moving-average strategy for MVP validation.
7. A vectorized backtester with fees, slippage, equity curve, trades, and basic
   metrics.
8. ModelGateway contracts, fake provider, model call records, model
   registry/profile selection, structured output parser, research brief
   schemas, DailyAlphaBrief generation, prompt template versioning, and a
   local Ollama provider adapter.
9. RiskGate, KillSwitch, PaperBroker, OrderRouter, FillSimulator,
   PortfolioState, and ExecutionAuditLog for a safe paper-trading loop.
10. A Gymnasium-style trading environment with rewards, costs, random policy,
   buy-and-hold baseline, and strategy comparison report.
11. Review Center snapshots, text viewers, paper/risk/audit summaries, and
   daily/weekly review journal generation.
12. Passing pytest, Ruff, and strict mypy quality gates.

In progress:

1. FastAPI web API surface (Phase 6 Round 1 complete — health, status, data
   endpoints with CLI `alphabrief serve`).

Not implemented yet:

1. Full web dashboard.
2. Live trading.
3. Additional cloud model provider adapters.

## Safety Boundary

AlphaBrief is research-first and paper-first. It is not a live-trading bot, a
high-frequency trading system, or a wrapper around one model provider.

Hard rules:

1. Model calls must go through `ModelGateway`.
2. Business modules must not call provider SDKs directly.
3. Models cannot place orders or override risk controls.
4. Research outputs may produce structured reports, hypotheses, StrategySpec
   drafts, or OrderIntent drafts only.
5. Every OrderIntent must pass RiskGate before paper execution.
6. Live trading is disabled by default and out of scope for the MVP.
7. API keys and broker keys must never be committed, logged, or embedded in
   prompts.

## Repository Layout

```text
apps/                 Future API, web, and worker surfaces.
packages/             AlphaBrief-owned Python packages.
strategies/           Future strategy specs and experiments.
tests/                Unit and boundary tests.
docs/                 Architecture, roadmap, risk model, and development log.
reports/              Local report output placeholders.
notebooks/            Local analysis workspace placeholders.
scripts/              Future utility scripts.
```

Runtime packages currently live under `packages/*/src`:

1. `alphabrief_core`
2. `alphabrief_data`
3. `alphabrief_strategy`
4. `alphabrief_backtest`
5. `alphabrief_models`
6. `alphabrief_risk`
7. `alphabrief_execution`
8. `alphabrief_gym`
9. `alphabrief_review`

## Local Setup

Requirements:

1. Python 3.12+
2. A virtual environment

Install for local development:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Optional local Parquet tests require a pandas-compatible Parquet engine such as
`pyarrow` or `fastparquet`. The current test suite uses monkeypatched Parquet
rows and does not require a real Parquet engine.

## Quality Gates

Run all checks before committing:

```bash
python3 -m pytest
.venv/bin/ruff check .
.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests
```

Current expected result:

```text
pytest: 134 passed
ruff: all checks passed
mypy: success
```

## Reference Source Policy

Reference projects are local-only research material. They are intentionally
ignored by Git and should not be pushed to this repository.

Allowed use:

1. Read reference projects to understand behavior, product flows, and module
   boundaries.
2. Convert observations into natural-language notes under `docs/reference_notes/`.
3. Implement AlphaBrief-owned behavior from those notes using original names,
   interfaces, tests, and structure.

Forbidden use:

1. Importing from `_reference_sources/`.
2. Copying, translating, or lightly rewriting reference source files.
3. Copying prompts, comments, test cases, class names, function names, or file
   structure.

## Configuration

Use `.env.example` as the local template. Do not commit real secrets.

Current environment variables:

```text
ALPHABRIEF_ENV=local
ALPHABRIEF_LOG_LEVEL=INFO
ALPHABRIEF_LIVE_TRADING_ENABLED=false
ALPHABRIEF_DATA_DIR=data/local
ALPHABRIEF_REPORTS_DIR=reports/generated
ALPHABRIEF_AUDIT_LOG_DIR=reports/audit
```

## Documentation

Core project documents:

1. `ALPHABRIEF_PRODUCT_BLUEPRINT.md`
2. `ALPHABRIEF_DEVELOPMENT_CADENCE.md`
3. `PROJECT_RULES.md`
4. `docs/architecture.md`
5. `docs/roadmap.md`
6. `docs/model_gateway.md`
7. `docs/risk_model.md`
8. `docs/development_log.md`

## Availability

This version is private and not open source. No public license is granted at
this stage. All rights are reserved unless a license is added later.
