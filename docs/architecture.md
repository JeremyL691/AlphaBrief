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
5. `OllamaProviderAdapter` provides the first real provider adapter through
   Ollama's local HTTP API.
6. `ModelCallRecord` records provider, model, task, prompt version, input hash,
   output hash, latency, status, and error type.
7. `ModelRegistry` stores provider configs and model profiles so future modules
   can select enabled models by capability and priority.
8. `parse_structured_output` validates `ModelResponse.structured_output` or
   JSON-decoded `output_text` against a Pydantic target model and returns a
   structured result with stable error codes.
9. Research brief schemas (`MarketBrief`, `SymbolBrief`, `DailyAlphaBrief`)
   provide structured target types for brief generation and serve as the
   integration surface between the structured output parser and the research
   layer.
10. `generate_daily_alpha_brief` calls `ModelGateway`, validates the model
   response as `DailyAlphaBrief`, and returns structured success or failure
   results.
11. Prompt templates are versioned with `PromptTemplate` and rendered into
   explicit `prompt_version` plus `input_text` values for `ModelRequest`.

The gateway does not implement cloud provider SDKs, retries, fallback,
persistent prompt storage, order generation, RiskGate, or execution behavior.

The registry stores environment variable names only for future provider
configuration; it does not read environment variables or store secret values.

The structured output parser is a pure validation utility. It does not call
providers, does not read environment variables, and does not persist raw output.

Research brief schemas are pure Pydantic validation boundaries. They do not
call providers, do not read environment variables, and do not generate
content themselves. They are designed to be the target model for
``parse_structured_output`` and future research layer generators.

The DailyAlphaBrief generator is a thin orchestration boundary. It does not
build prompt templates, instantiate providers, retry failed calls, or persist
briefs; callers provide the input text and prompt version explicitly.

Prompt template versioning is local and in-memory in the MVP. It does not load
templates from disk, allow secret variables, or call providers.

The Ollama adapter performs a real local HTTP request when used at runtime, but
tests inject the HTTP boundary. It does not store API keys or provider secrets.

## Risk and Paper Trading

`alphabrief_risk` and `alphabrief_execution` implement the Phase 3 paper
trading safety loop.

Current behavior:

1. `RiskGate` evaluates `OrderIntent` objects and always returns a
   `RiskDecision`.
2. `RiskLimitConfig` supports trading enabled status, live trading lock,
   enabled strategies, symbol allowlist, max order quantity, max order value,
   data quality requirement, and human-review flag.
3. `KillSwitch` can block all orders.
4. `OrderRouter` creates `Order` objects only when a matching approved
   `RiskDecision` is present.
5. `FillSimulator` creates deterministic paper fills with fee and slippage.
6. `PortfolioState` updates cash, positions, and realized PnL from fills.
7. `PaperBroker` coordinates routing, fill simulation, portfolio updates, and
   audit entries.
8. `ExecutionAuditLog` records risk decisions, order rejections, orders, fills,
   and portfolio updates.

This layer is paper-only. It does not implement live broker adapters, live
order routing, margin, leverage, partial fills, or external persistence.

## Trading Environment

`alphabrief_gym` implements the Phase 4 Gymnasium-style simulation boundary.

Current behavior:

1. `AlphaBriefTradingEnv` exposes `reset()` and `step(action)` methods.
2. Actions are `hold`, `buy`, and `sell`.
3. Observations include current bar identity, close price, cash, position
   quantity, portfolio value, and step index.
4. Rewards are computed from the portfolio value transition from the current
   bar to the next bar after applying the current action.
5. Transaction costs and slippage are explicit basis-point inputs.
6. Episode metrics include initial value, final value, total return, max
   drawdown, step count, and trade count.
7. Random policy and buy-and-hold baselines can be evaluated.
8. `StrategyComparisonReport` ranks evaluated policies by total return.

The environment is single-asset and long/flat in the MVP. It does not depend
on Gymnasium, implement vectorized spaces, train agents, short assets, use
leverage, or persist evaluation reports.

## Review Center

`alphabrief_review` implements the Phase 5 daily-use review boundary.

Current behavior:

1. `ReviewCenterSnapshot` aggregates strategies, backtest reports, daily
   AlphaBrief summaries, model calls, paper portfolio state, order audit log,
   risk dashboard data, and review journal entries.
2. Snapshot JSON can be written and loaded locally.
3. Plain-text viewers expose research reports, backtest summaries, model call
   history, paper portfolio, order audit log, risk dashboard, strategy list,
   and review journal entries.
4. Daily and weekly review journal entries can be generated deterministically
   from a snapshot.

The Review Center is read-only. It does not call models, run backtests, submit
orders, change portfolio state, bypass RiskGate, or implement a Web Dashboard.

## API Layer

`apps/api` starts the Product Layer with a FastAPI web server.

Current behavior:

1. Health check endpoint returns service status and API version.
2. Project status endpoint returns version, environment, live-trading lock state,
   configured data/report directories, and loaded AlphaBrief package surfaces.
3. Data status endpoint reports whether the configured data directory exists,
   whether it has files, and a CSV/Parquet file summary.

The API server is read-only. It is exposed through the CLI with
`alphabrief serve` and runs the FastAPI app via Uvicorn.

It does not call models, access brokers, bypass RiskGate, or enable live
trading.

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

## Storage Layer

`apps/api/src/alphabrief_api/db` starts the Data Layer persistent storage
boundary with DuckDB-backed data access.

Current behavior:

1. `db/schema.py` defines the `symbols` and `bars` tables with
   ``CREATE TABLE IF NOT EXISTS`` DDL, plus ``apply_schema`` and
   ``drop_schema`` helpers.
2. `db/market_data.py` provides ``MarketDataStore`` — a DuckDB-backed
   persistent store for OHLCV bars and symbol metadata.
3. ``MarketDataStore.insert_bars(bars, source, data_version)`` batch-inserts
   bars and upserts symbol metadata in a single transaction.
4. ``MarketDataStore.get_symbols()`` returns all loaded symbols with bar
   counts.
5. ``MarketDataStore.get_bars(symbol, limit, offset)`` returns paginated
   OHLCV rows as JSON-safe dicts.
6. ``MarketDataStore.get_symbol_info(symbol)`` returns symbol metadata
   including time range.
7. ``MarketDataStore.get_bar_models(symbol)`` returns ``Bar`` domain objects
   for backtesting and feature generation.
8. ``MarketDataStore.clear()`` drops and recreates tables for test isolation.
9. Data directory defaults to ``~/.alphabrief/data/``, overridable via
   ``ALPHABRIEF_DATA_DIR`` environment variable.

The storage layer is currently used by the market data API routes.
Backtest reports, briefs, paper portfolio, audit logs, and review
snapshots remain in-memory pending future Phase 7 rounds.

This layer does not implement connection pooling, migrations, backup,
or multi-process locking.

## Market Data Providers

`alphabrief_data.providers` adds the first external market data
provider boundary to the Data Layer. The package is intentionally
small and ships with two free, key-less HTTP adapters that store
their bars through the existing ``MarketDataStore``.

Current behavior:

1. ``MarketDataProvider`` is a runtime-checkable ``Protocol`` that
   every external provider must satisfy. It declares a single
   ``fetch_ohlcv`` method returning ``list[Bar]`` for a half-open
   ``[start, end)`` range at a given interval.
2. ``MarketDataProviderError`` is the single error class used by all
   providers. It carries a stable ``code`` attribute (drawn from
   ``MarketDataProviderErrorCode``) so CLI and API layers can
   branch on the failure mode without parsing free-form messages.
3. ``YahooFinanceProvider`` downloads OHLCV bars from Yahoo
   Finance's unofficial chart endpoint
   (``query1.finance.yahoo.com``). It uses ``urllib`` only — no
   ``yfinance`` SDK is imported. Timestamps are converted from
   UNIX seconds to timezone-aware UTC ``datetime`` objects.
   Supported intervals are ``1m``, ``5m``, ``15m``, ``30m``, ``1h``,
   ``1d``, ``1wk``, and ``1mo``; the ``data_version`` of every bar
   embeds the interval so the same symbol can be re-fetched at
   different granularities without collision.
4. ``BinanceProvider`` downloads OHLCV klines from Binance's
   public klines endpoint (``api.binance.com/api/v3/klines``). It
   uses ``urllib`` only — no ``python-binance`` SDK is imported.
   Timestamps are converted from UNIX milliseconds to
   timezone-aware UTC ``datetime`` objects and prices are parsed as
   ``Decimal`` from strings. Supported intervals are ``1m``,
   ``3m``, ``5m``, ``15m``, ``30m``, ``1h``, ``1d``, ``1w``, and
   ``1M`` (the capital-M monthly interval is Binance-specific and
   is mapped to a 30-day month for pagination). Multi-day ranges
   are fetched in 1 000-row pages using the
   ``_interval_to_seconds()`` cursor.
5. Both providers expose an injectable ``http_get`` callable so
   tests can inject deterministic responses without monkeypatching
   ``urllib``. The default callable performs a real HTTP request.
6. Both providers wrap their HTTP call with ``call_with_retry``
   using a shared ``RetryPolicy`` (exponential backoff with
   uniform jitter, hard cap at ``max_backoff_seconds``). Only
   recoverable failures are retried: HTTP 429/418/5xx and
   ``URLError``/``OSError``/``TimeoutError``/``ConnectionError``.
   Non-rate-limit 4xx errors are re-raised immediately so the
   caller learns about caller-side mistakes without delay. After
   the retry budget is exhausted the **last** exception is
   surfaced.
7. The CLI exposes ``alphabrief data fetch`` and the API exposes
   ``POST /api/v1/data/fetch``. Both accept ``source``
   (``yahoo`` or ``binance``), ``symbol``, ``start``, ``end``,
   ``interval`` (any of the supported values above), and an
   optional ``data_version`` tag, and persist the resulting bars
   to the DuckDB ``bars`` table.
8. Rate-limited (HTTP 429/418/5xx) and generic HTTP / network
   failures are surfaced as structured ``MarketDataProviderError``
   instances, never as raw ``urllib`` exceptions.
9. The package never logs, stores, or transmits API keys. Both
   providers are key-less by design.

The provider package does not implement tick data, options,
futures, fundamentals, news, or social sentiment. It does not
implement cross-provider fallbacks or persistent rate-limit
queues — callers can disable retries by setting
``retry_policy.max_retries=0`` if they need strict at-most-once
semantics.
