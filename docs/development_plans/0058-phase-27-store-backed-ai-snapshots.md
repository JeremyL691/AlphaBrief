# 0058 Phase 27 Store-backed AI Trading Snapshots

## Goal

Replace the AI trading scheduler/API placeholder market snapshots with
local-store snapshots built from AlphaBrief's existing DuckDB market data
and news stores.

## Files Changed

1. `packages/alphabrief-trader/src/alphabrief_trader/snapshot_builder.py`
2. `packages/alphabrief-trader/src/alphabrief_trader/__init__.py`
3. `apps/cli/src/alphabrief_cli/scheduler_commands.py`
4. `apps/api/src/alphabrief_api/routes/ai_trading.py`
5. `tests/test_ai_trader_snapshot_builder.py`
6. `tests/test_ai_trader_scheduler.py`
7. `docs/architecture.md`
8. `docs/roadmap.md`
9. `docs/development_log.md`

## Modules Not Touched

1. Dashboard/UI files, because frontend edits require explicit design
   preference dials first.
2. Broker adapter credential handling.
3. Live-trading locks.
4. Reference sources.

## Implementation

1. Added `StoredMarketSnapshotBuilder`, a provider-neutral builder that
   accepts injected bar and headline loader functions.
2. The builder now derives:
   - reference price from the latest local bar, unless explicitly
     overridden by the API request;
   - recent return from the last two stored closes;
   - recent volume from the latest bar;
   - news context from the last 24 hours of local headlines;
   - missing headline sentiment via `RuleBasedSentimentAnalyzer`.
3. Wired scheduler `ai_daily_cycle` to open `MarketDataStore` and
   `NewsStore` against the same `alphabrief.db` as the AI cycle store.
4. Wired API `/api/v1/ai/run` to use the same builder while preserving
   `reference_prices` as an explicit manual override.
5. Symbols without any local price source are skipped instead of being
   assigned a fake `$100` reference price.

## Tests

1. `tests/test_ai_trader_snapshot_builder.py` covers latest-price
   selection, return/volume derivation, sentiment annotation, and the
   no-price skip path.
2. `tests/test_ai_trader_scheduler.py` now asserts the scheduler AI
   factory skips symbols with no local bars rather than running the
   committee on placeholder prices.

## Remaining Production-readiness Work

1. Replace the default `FakeProviderAdapter` committee with configured
   real `ModelGateway` providers while preserving structured-output
   validation.
2. Bridge approved AI order attempts from the local `PaperBroker` path
   to the configured external paper `BrokerAdapter` when policy allows.
3. Reconcile `config/paper_execution_policy.yaml` with the operator's
   selected paper provider. It is still locked to `alpaca_paper` /
   `us_equity`.
4. Add a daily data-ingestion task that fetches market data and news
   before `ai_daily_cycle` runs.
5. Run the full suite outside the restricted sandbox to clear the
   known localhost mock-broker socket failures.
