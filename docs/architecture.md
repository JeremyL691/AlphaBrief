# AlphaBrief Architecture

This document records AlphaBrief's high-level architecture. Detailed behavior
will be added as each module is implemented.

## Layers

AlphaBrief is organized around these boundaries:

1. Product Layer: CLI, API, web dashboard, and report viewer.
2. AI Research Layer: ModelGateway, providers, structured outputs, research
   agents, debate flows, and brief generation.
3. Strategy Layer: StrategySpec, signal generation, strategy registry, and
   evaluation contracts.
4. Simulation Layer: backtesting, trading environments, rewards, and
   walk-forward evaluation.
5. Risk Layer: RiskGate, limits, order checks, exposure rules, drawdown guards,
   and kill switch.
6. Execution Layer: PaperBroker, broker adapter interface, order router, fill
   simulation, and execution audit logs.
7. Data Layer: market data, news and macro inputs, feature store, data quality,
   and storage.
8. Observability Layer: logs, metrics, model cost tracking, and decision
   archive.

## Hard Boundaries

1. Research may produce briefs, hypotheses, StrategySpec drafts, or
   OrderIntent candidates; it must not produce broker orders.
2. Strategies may produce signals or OrderIntent objects; they must not access
   broker adapters directly.
3. Execution requires a RiskDecision.
4. Model calls must go through ModelGateway.
5. Reference sources are never imported by AlphaBrief runtime code.

## Core Domain Models

The first runtime package is `alphabrief_core`. It defines schema-only domain
objects used as boundaries between future modules:

1. `Bar`
2. `Signal`
3. `OrderIntent`
4. `RiskDecision`
5. `Order`

These models validate required fields, timezone-aware timestamps, Decimal
money/quantity values, confidence ranges, basic OHLCV consistency, and the
minimum relationship between order intents, risk decisions, and orders.

They do not implement RiskGate, PaperBroker, broker adapters, strategy logic,
model calls, or execution behavior.

## Core Configuration

`alphabrief_core.config` defines the minimal application settings boundary for
future modules:

1. `env`
2. `log_level`
3. `live_trading_enabled`
4. `data_dir`
5. `reports_dir`
6. `audit_log_dir`

Settings are loaded from explicit `ALPHABRIEF_` environment variables via
`load_settings`. Tests may pass a mapping directly to avoid mutating the real
process environment.

The configuration module does not read `.env` files, does not include secret
fields, and does not unlock live trading behavior. A parsed
`live_trading_enabled=True` value is only a configuration value; real trading
will still require future independent locks, RiskGate, broker adapters, and
audit controls.

## Market Data Loader

`alphabrief_data` starts the Data Layer with local CSV and Parquet OHLCV
loaders. The MVP loaders read one asset at a time and return in-memory `Bar`
objects from `alphabrief_core`.

Current behavior:

1. Required columns are `timestamp`, `open`, `high`, `low`, `close`, and
   `volume`.
2. `symbol`, `source`, and `data_version` are explicit loader inputs.
3. Numeric fields are parsed as `Decimal` from strings.
4. Naive timestamps are assigned the configured timezone; timezone-aware
   timestamps keep their original offset.
5. CSV uses only the standard library.
6. Parquet uses an optional local pandas parquet engine and fails clearly when
   pandas, pyarrow, or fastparquet support is unavailable.
7. Row-level parsing and `Bar` validation failures are wrapped in
   `MarketDataLoadError` with the input row number.

The loaders do not implement data quality reports, feature generation, storage
snapshots, or backtesting.

## Market Data Quality

`alphabrief_data.quality` provides explicit in-memory checks for `Bar`
sequences before future modules use them for backtesting or risk decisions.

Current checks:

1. Empty datasets are errors.
2. Mixed symbols are errors.
3. Mixed sources or data versions are warnings.
4. Duplicate or non-increasing timestamps are errors.
5. Gaps larger than a caller-provided `expected_interval` are errors.
6. Zero-volume bars are warnings.

The quality report exposes `passed`, `issues`, `bar_count`, `symbol`,
`start_timestamp`, and `end_timestamp`. CSV loading does not automatically run
these checks; callers must explicitly call `check_bar_quality`.

This module does not repair data, resample bars, infer market calendars,
detect statistical outliers, or decide how future backtests reject data.

## Feature Generation

`alphabrief_data.features` provides the first no-lookahead feature generation
boundary for in-memory `Bar` sequences.

Current features:

1. Trailing close returns such as `return_1`.
2. Trailing close moving averages such as `close_sma_3`.
3. Trailing volume moving averages such as `volume_sma_3`.

Feature generation first runs `check_bar_quality`. Reports with errors block
feature generation; warning-only reports do not. All generated values use
`Decimal | None`, and trailing windows use only the current and past bars.

This module does not generate signals, StrategySpec objects, orders, feature
store snapshots, dataframe outputs, or backtest inputs.

## StrategySpec Schema

`alphabrief_strategy` defines the first Strategy Layer boundary with a
schema-only `StrategySpec`.

Current schema areas:

1. Strategy identity: `strategy_id`, `name`, and `version`.
2. Universe: stable de-duplicated symbols.
3. Rules: entry and exit condition text.
4. Risk: maximum position percentage and optional stop-loss text.
5. Costs: fee and slippage in basis points.
6. Evaluation: non-overlapping train and test date periods.

StrategySpec condition strings are auditable text in this round. They are not
parsed, executed, converted into signals, or allowed to access brokers. Future
strategy interfaces and backtests will consume this schema explicitly.

## Strategy Interface

`alphabrief_strategy.interface` defines the first strategy execution contract.
Strategies are called through `run_strategy(strategy, strategy_input)` and must
implement `generate(input) -> StrategyOutput`.

Current interface behavior:

1. `StrategyInput` carries a `StrategySpec`, bars, and feature rows.
2. `StrategyOutput` may contain `Signal` objects only.
3. Bars must be non-empty and pass data quality checks.
4. Feature rows must have the same length as bars.
5. Signals must match the StrategySpec strategy ID, universe, and input bar
   timestamps.

The interface does not parse conditions, implement built-in strategies, create
OrderIntent objects, run backtests, access brokers, or bypass future RiskGate
checks.

## Built-In MVP Strategy

`MovingAverageTrendStrategy` is the first built-in strategy implementation. It
uses trailing close SMA feature rows and emits long/flat `Signal` objects only.

The strategy exists to prove the Phase 1 data -> feature -> strategy ->
backtest loop. It does not parse StrategySpec conditions, generate
OrderIntent, size positions, or access brokers.

## ModelGateway Contract

`alphabrief_models` starts the AI Research Layer with a model-call boundary.
All future model-backed modules must use `ModelGateway` instead of calling
provider SDKs directly.

Current behavior:

1. `ModelRequest` declares a task type, prompt version, input text, and required
   model capabilities.
2. `ProviderAdapter` defines the provider boundary used by the gateway.
3. `ModelGateway` selects the first provider that satisfies the requested
   capabilities.
4. `FakeProviderAdapter` provides deterministic local success and failure paths
   for tests.
5. `ModelCallRecord` records provider, model, task, prompt version, input hash,
   output hash, latency, status, and error type.
6. `ModelRegistry` stores provider configs and model profiles so future modules
   can select enabled models by capability and priority.

The gateway does not implement real provider SDKs, network calls, retries,
fallback, prompt storage, structured output parsing, research briefs, order
generation, RiskGate, or execution behavior.

The registry stores environment variable names only for future provider
configuration; it does not read environment variables or store secret values.

## Vectorized Backtester

`alphabrief_backtest` provides the first long/flat backtesting loop.

Current behavior:

1. Calls strategies through `run_strategy`.
2. Uses `StrategySpec.costs` for fee and slippage assumptions.
3. Uses `StrategySpec.risk.max_position_pct` as the maximum long allocation.
4. Supports long entries and flat exits only.
5. Produces `BacktestReport` with metrics, equity curve, trades, costs, and
   data version.
6. Can write `backtest_report.json`.

The backtester does not route orders, touch brokers, model margin, shorting,
leverage, liquidity, or portfolio-level allocation.
