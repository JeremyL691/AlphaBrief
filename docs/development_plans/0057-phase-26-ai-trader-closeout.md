# 0057 Phase 26 AI Trader Closeout

## Goal

Make the newly introduced AI Trading Committee runtime importable,
persistable, and verifiable without changing AlphaBrief's paper-first safety
boundary.

## Files Changed

- `packages/alphabrief-trader/src/alphabrief_trader/db_schema.py`
- `packages/alphabrief-trader/src/alphabrief_trader/db_store.py`
- `apps/api/src/alphabrief_api/db/schema.py`
- `apps/api/src/alphabrief_api/routes/ai_trading.py`
- `apps/cli/src/alphabrief_cli/scheduler_commands.py`
- `alphabrief.egg-info/SOURCES.txt`
- `alphabrief.egg-info/top_level.txt`
- `tests/test_api_server.py`
- Documentation files for this phase

## Modules Not Touched

- `alphabrief_risk` RiskGate semantics
- `alphabrief_execution` PaperBroker / BrokerAdapter execution semantics
- Model provider adapters
- Live-trading configuration or broker credentials
- `_reference_sources/`

## Plan Review

The current uncommitted AI trader work introduced a new runtime package,
CLI/API routes, scheduler task wiring, and tests. The first targeted test run
failed during collection because `alphabrief_trader.db_store` imported
`alphabrief_api.db.schema`, which imported the API app and routes, which
re-imported `alphabrief_trader`.

This round stays scoped to restoring the intended Phase 26 surface:

1. Break the package-to-API circular import.
2. Make AI trading store keys support multi-symbol daily cycles.
3. Ensure the installed local entrypoint can import `alphabrief_trader`.
4. Update docs and tests to include the new runtime package surface.
5. Run targeted AI trader tests and project quality gates.

## Implementation Notes

- Added a package-owned AI-only DuckDB schema helper so
  `alphabrief_trader` can create its tables without importing
  `alphabrief_api`.
- Changed `ai_committee_votes` from `(cycle_id, role)` uniqueness to
  `(cycle_id, vote_index)`, because a multi-symbol daily cycle has the same
  four committee roles per symbol.
- Changed `ai_order_attempts` to use `(cycle_id, intent_id)`, preserving
  cycle-local replay while avoiding cross-cycle collisions.
- Added `alphabrief_trader` to tracked egg-info metadata and refreshed the
  local editable finder so the current workspace `alphabrief` command can
  import the new package.
- Kept the AI cycle paper-only, feature-flag gated, ModelGateway-only, and
  RiskGate-before-broker.

## Test Plan

- Targeted AI trader cluster:
  `tests/test_ai_trader_schemas.py tests/test_ai_trader_rules.py
  tests/test_ai_trader_committee.py tests/test_ai_trader_daily_cycle.py
  tests/test_ai_trader_store.py tests/test_ai_trader_cli.py
  tests/test_ai_trading_api.py tests/test_ai_trader_scheduler.py`
- CLI/API regression subset:
  `tests/test_broker_cli.py tests/test_scheduler_cli.py
  tests/test_api_server.py::test_api_status_body`
- Full quality gates:
  `pytest`, `ruff check .`, `mypy packages apps tests`,
  `alphabrief acceptance verify --compact`

## Completion Criteria

- Targeted AI trader tests pass.
- Broker/scheduler CLI subprocess tests can import the new package.
- Ruff, Mypy, and acceptance verifier pass.
- Any remaining full-test failures are attributable to the known sandbox
  restriction on binding localhost mock broker servers.
