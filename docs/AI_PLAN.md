# AlphaBrief AI Plan — Phase 15

> Historical planning snapshot for Phase 15. For current status and quality
> gates, use `docs/roadmap.md` and `docs/development_log.md`.

## Current State Assessment

After 14 phases, AlphaBrief has solid foundations:

- **Data Layer**: CSV/Parquet loaders, Yahoo/Binance/AlphaVantage providers,
  NewsHeadline (RSS/SEC/Sentiment), MacroIndicator (FRED), DuckDB persistence.
- **AI Research Layer**: ModelGateway, provider adapters, prompt templates,
  MarketBrief/SymbolBrief/DailyAlphaBrief, multi-model debate orchestrator.
- **Strategy Layer**: StrategySpec schema, StrategyInterface, MovingAverageTrendStrategy.
- **Backtest Layer**: Vectorized backtester, metrics, env v2 (multi-asset).
- **Risk Layer**: RiskGate with RiskContextDecision tightening, KillSwitch.
- **Execution Layer**: PaperBroker with audit log.
- **Observability**: ModelEvaluator, ModelRouter, ReviewCenterSnapshot.

782 tests pass. ruff and strict mypy clean.

## Critical Gap Identified

**The Strategy Layer has no persistence, no registry, no lifecycle.**

Looking at blueprint section 7.3 (Strategy Layer) and 22 (Dashboard / Strategies):

```text
Strategy Layer
├── StrategySpec                  ✓ exists (Pydantic only)
├── Strategy Interface            ✓ exists
├── Signal Engine                 ✓ exists (in builtins.py)
├── Strategy Registry             ✗ MISSING — no concept of named, persisted strategies
├── Strategy Evaluation           ✗ MISSING — no save/load/compare
└── Parameter Management          ✗ MISSING — no versioning
```

There is no `strategies` table in DuckDB. Every API call that touches a
strategy is stateless. The user cannot:

1. Save a strategy and reload it later.
2. List all their saved strategies.
3. Activate or deactivate a strategy.
4. Track signals emitted by a specific strategy over time.
5. See which strategies are currently registered as paper-trading candidates.

The dashboard's `/dashboard` shows "Last Backtest" but no strategy list
because strategies cannot be persisted.

## Proposed Phase 15 Goal

**Make strategies first-class persisted artifacts in the system.**

Add the missing Strategy Registry + Lifecycle layer:
`strategy_specs` and `strategy_signals` DuckDB tables, a full CRUD
`StrategyStore`, an activation flag, full API + CLI surface, and a
dashboard page that lists saved strategies with their latest signal.

This unlocks all downstream work (real paper trading loop, daily automation,
P&L attribution by strategy) without touching risk or execution core.

## Why This Is The Most Valuable Next Thing

1. **Foundation**: Every future feature (paper trading loop, automation,
   attribution) depends on having identified, persisted strategies.
2. **Smallest scope**: Pure additive — no changes to RiskGate, PaperBroker,
   or strategy logic. New tables, new store, new endpoints, new CLI.
3. **Lowest risk**: No live trading implications, no risk semantics change.
4. **Highest leverage**: One round of 6-8 sub-rounds enables multiple new
   future phases.

## Round-by-Round Breakdown

### R15.1 — DuckDB strategy_specs table + StrategySpecStore

- **Model**: kimi-k2.7-code (Plan)
- **Model**: glm-5.2 (Execute)
- **Model**: deepseek-v4-flash (Commit)
- **Files**:
  - `apps/api/src/alphabrief_api/db/schema.py` — add `strategy_specs` DDL
  - `apps/api/src/alphabrief_api/db/strategies.py` — new StrategySpecStore
  - `apps/api/src/alphabrief_api/db/__init__.py` — export StrategySpecStore
  - `tests/test_strategy_store.py` — new
- **Tests**: 12-15 unit tests (save, get, list, update, delete, activation flag, clear/reopen)
- **Untouched**: risk/, execution/, strategy interface, models

### R15.2 — API endpoints for strategies

- **Model**: kimi-k2.7-code (Plan)
- **Files**:
  - `apps/api/src/alphabrief_api/routes/strategies.py` — new router
  - `apps/api/src/alphabrief_api/main.py` — register router
  - `tests/test_api_server.py` — new endpoint tests
- **Endpoints**:
  - `POST /api/v1/strategies/specs` — create
  - `GET /api/v1/strategies/specs` — list (with optional `?enabled=true`)
  - `GET /api/v1/strategies/specs/{strategy_id}` — read
  - `PATCH /api/v1/strategies/specs/{strategy_id}` — update activation
  - `DELETE /api/v1/strategies/specs/{strategy_id}` — delete
- **Tests**: 10-15 endpoint tests

### R15.3 — CLI `strategy` commands

- **Model**: kimi-k2.7-code (Plan)
- **Files**:
  - `apps/cli/src/alphabrief_cli/strategy_commands.py` — new
  - `apps/cli/src/alphabrief_cli/main.py` — register subapp
  - `tests/test_strategy_commands.py` — new
- **Commands**:
  - `alphabrief strategy save --from-yaml file.yaml`
  - `alphabrief strategy list [--enabled-only]`
  - `alphabrief strategy show <strategy_id>`
  - `alphabrief strategy enable <strategy_id>`
  - `alphabrief strategy disable <strategy_id>`
  - `alphabrief strategy delete <strategy_id>`
- **Tests**: 8-12 CLI integration tests

### R15.4 — Activation flag + risk gate integration

- **Model**: kimi-k2.7-code (Plan)
- **Files**:
  - `apps/api/src/alphabrief_api/routes/strategies.py` — activation logic
  - `tests/test_strategy_activation.py` — new
- **Behavior**:
  - Save defaults to `enabled=False`.
  - Enable flips the flag and registers the strategy_id as enabled in
    the module-level RiskLimitConfig via a helper (does not change the
    core RiskGate semantics — only adds the strategy_id to the
    `enabled_strategies` allowlist when activated).
  - Disable removes it.
  - The flag is purely advisory at this round: it does NOT block
    orders — it surfaces in the risk context as informational metadata.
- **Tests**: 6-10 tests covering enable/disable + state propagation

### R15.5 — Strategy signal history persistence

- **Model**: kimi-k2.7-code (Plan)
- **Files**:
  - `apps/api/src/alphabrief_api/db/schema.py` — add `strategy_signals` DDL
  - `apps/api/src/alphabrief_api/db/strategies.py` — extend store
  - `apps/api/src/alphabrief_api/routes/backtest.py` — optional
    `?persist_signals=true` to record emitted signals to the store
  - `tests/test_strategy_signal_history.py` — new
- **Schema**: `strategy_signals(strategy_id, signal_id PK, timestamp,
  symbol, direction, confidence, horizon, rationale, recorded_at,
  source_backtest_id)`.
- **Behavior**: Backtests may optionally record the signals they emit
  keyed by strategy_id. This is the data foundation for future
  attribution work.
- **Tests**: 8-12 tests covering insert, query, latest, by_symbol, clear

### R15.6 — Dashboard `/dashboard/strategies` page

- **Model**: kimi-k2.7-code (Plan)
- **Files**:
  - `apps/api/src/alphabrief_api/routes/dashboard.py` — add page
  - `tests/test_dashboard_strategies.py` — new
- **Page**: lists saved strategies with strategy_id, name, version,
  enabled/disabled badge, last-signal timestamp, signal count.
- **No new dependencies**.

### R15.7 — Final validation + development log

- All 6 prior rounds merged.
- Full test suite passes (target 850+ tests).
- ruff clean, mypy clean.
- `docs/roadmap.md` Phase 15 status block added.
- `docs/development_log.md` entry per round.
- `docs/architecture.md` Strategy Registry chapter added.

## Files That Will Be Changed

- `apps/api/src/alphabrief_api/db/schema.py` (add 2 tables)
- `apps/api/src/alphabrief_api/db/strategies.py` (new file)
- `apps/api/src/alphabrief_api/db/__init__.py` (export new store)
- `apps/api/src/alphabrief_api/routes/strategies.py` (new file)
- `apps/api/src/alphabrief_api/routes/backtest.py` (extend)
- `apps/api/src/alphabrief_api/routes/dashboard.py` (add page)
- `apps/api/src/alphabrief_api/main.py` (register router)
- `apps/cli/src/alphabrief_cli/strategy_commands.py` (new file)
- `apps/cli/src/alphabrief_cli/main.py` (register subapp)
- `tests/test_strategy_store.py` (new)
- `tests/test_api_server.py` (extend)
- `tests/test_strategy_commands.py` (new)
- `tests/test_strategy_activation.py` (new)
- `tests/test_strategy_signal_history.py` (new)
- `tests/test_dashboard_strategies.py` (new)
- `docs/roadmap.md` (Phase 15 block)
- `docs/development_log.md` (per-round entries)
- `docs/architecture.md` (Strategy Registry chapter)

## Files That Will NOT Be Touched

- `packages/alphabrief-core/**` — domain models unchanged
- `packages/alphabrief-strategy/src/alphabrief_strategy/spec.py` — schema unchanged
- `packages/alphabrief-strategy/src/alphabrief_strategy/interface.py` — interface unchanged
- `packages/alphabrief-strategy/src/alphabrief_strategy/builtins.py` — builtins unchanged
- `packages/alphabrief-risk/**` — RiskGate semantics unchanged
- `packages/alphabrief-execution/**` — PaperBroker unchanged
- `packages/alphabrief-models/**` — ModelGateway unchanged
- `packages/alphabrief-research/**` — research layer unchanged
- `packages/alphabrief-backtest/**` — backtester core unchanged
- `_reference_sources/**` — never imported
- `tests/test_risk_gate.py`, `tests/test_paper_execution.py` — risk/execution tests unchanged

## Safety Boundaries

- No live trading implications.
- No RiskGate semantic change.
- Activation flag is purely advisory at this round.
- No new model calls, no provider SDK imports outside ModelGateway.
- No imports from `_reference_sources/`.
- No defaults that enable live behavior.

## Done When

- 850+ tests pass.
- `ruff check .` clean.
- `mypy packages apps tests` clean.
- `/api/v1/strategies/specs` CRUD endpoints work end-to-end.
- `alphabrief strategy save/list/show/enable/disable/delete` work.
- `/dashboard/strategies` renders saved strategies.
- Phase 15 marked complete in `docs/roadmap.md`.
