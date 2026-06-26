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
9. `RiskGate.evaluate()` (Phase 13.1) accepts an optional
   `RiskContextDecision` and applies it in a **tighten-only** manner:
   `risk_tags` are merged (deduplicated), the `requires_human_review`
   flag is OR-merged with the static config flag, and `max_quantity`
   is reduced by `suggested_max_position_multiplier` when that
   multiplier is strictly below `1.0`. The risk context can never
   re-approve a rejected intent, override the kill switch, lift the
   live-trading lock, add symbols to the allowlist, or relax
   `max_quantity`. When no `risk_context` is supplied the behavior is
   byte-for-byte backward compatible with the Phase 12 contract.

This layer is paper-only. It does not implement live broker adapters, live
order routing, margin, leverage, partial fills, or external persistence.

### Account-Level Exposure Enforcement (Phase 19)

`RiskGate` enforces a per-account total-exposure cap at runtime, fed
by a plain `AccountExposureContext` value object owned by the risk
package. The cap is sourced from `PaperExecutionPolicy.max_total_exposure`
(`$300` in the reviewed policy) and is exposed as
`RiskLimitConfig.max_total_exposure`.

```
alphabrief-execution (broker.exposure)
    │   async build_account_exposure_context(adapter, *, mark_prices=)
    │   sync  build_account_exposure_context_from_portfolio(portfolio, ...)
    ▼
alphabrief-risk (account_context.AccountExposureContext)
    │   current_total_exposure, exposure_by_symbol, cash, account_id, captured_at
    ▼
RiskGate.evaluate(intent, ..., account_context=...) → RiskDecision
    │   no-op when cap unset; fail-closed (``account_context_required``)
    │   when cap set but context missing; sell exempt; buy over cap
    │   rejected with ``max_total_exposure``; max_quantity clamped
    │   down to ``headroom / price`` (tighten-only).
    ▼
RiskDecision.approved (False on breach), risk_tags, max_quantity
```

Key invariants:

- **Layer discipline**: `alphabrief-risk` imports only
  `alphabrief_core`, never `alphabrief-execution`. The execution-side
  projection helper is the *only* place that touches a
  `BrokerAdapter` to feed account-level state to `RiskGate`. The
  dependency arrow is one-way: execution → risk.
- **Tighten-only**: the account check can only reject, clamp
  `max_quantity` down, or no-op. It can never re-approve a rejected
  intent, relax the human-review flag, raise `max_quantity`, or
  override the live-trading lock.
- **Fail-closed**: when the cap is configured but no
  `account_context` is supplied, the intent is rejected with the
  `account_context_required` tag. Skipping would defeat runtime
  enforcement.
- **Sells** never increase gross exposure and bypass the
  new-exposure projection (the paper policy is long-only;
  `ponytail:sell-exposure-ceiling` names the ceiling and the upgrade
  path).
- **No new SDK dependencies** and no imports from
  `_reference_sources/`.

The execution-side helper falls back to `position.average_price` as
the mark when no live quote is supplied. The
`ponytail:mark_price_ceiling` comment names the ceiling
(cost-basis not current market; understates exposure in a rising
market and overstates it in a falling one) and the upgrade path
(pass `mark_prices` from a quote provider when one exists).

### API-side Broker Adapter Singleton (Phase 20)

The API process holds a single lazy `BrokerAdapter` singleton
(`apps/api/src/alphabrief_api/broker_adapter.py`) so the read-only
`GET /api/v1/broker/positions` and `GET /api/v1/broker/account`
endpoints return live reads from the Alpaca Paper account instead of the
Phase 19 stubs. Phase 19 delivered account-exposure *enforcement*
(`RiskGate`); this singleton closes the *observability* gap on the API
side.

```
broker_adapter.get_broker_adapter()  (lazy, built on first access)
    │   AlpacaPaperAdapter  when ALPHABRIEF_ALPACA_KEY / SECRET set
    │   _NullBrokerAdapter otherwise (empty positions, zero account)
    ▼
routes/broker.py  /positions, /account  (sync def; asyncio.run() bridge)
    │   stringified BrokerPositionResponse / BrokerAccountResponse
    │   adapter failure → HTTP 503 {error,kind,message} (never silent)
    ▼
JSON response (Decimal / captured_at as strings)
```

Key invariants:

- **Read-only**: the API never calls `submit` / `cancel` / `get_order`
  / `list_orders` / `list_fills` through the singleton; those raise
  `NotImplementedError` on the null adapter and are simply never
  invoked on the live one. Order placement stays inside the operations
  scheduler and behind a `RiskDecision`. Account-exposure enforcement
  is still owned by `RiskGate`, not by these read endpoints.
- **Lazy + resettable**: the singleton is built on first access so
  `create_app()` boots without credentials; `_reset_broker_adapter()`
  is the test-isolation hook (mirrors `_reset_broker()` in
  `routes/paper.py`). `has_live_broker()` distinguishes a real adapter
  from the null fallback without leaking the concrete type.
- **Credential safety**: credentials are env-only, never logged or
  echoed; Alpaca modules are imported locally so the module imports
  cleanly without them and the HTTP client (which reads creds) is never
  constructed at import time.
- **Failure surfaces, never silently stubs**: an unreachable / refused
  / auth-failing live adapter returns HTTP 503 with a structured
  `{"error":"broker_adapter_unavailable","kind":...}` detail, not the
  empty list / null that the no-credentials null adapter returns. The
  two are distinct: no credentials is a graceful zero; a live failure
  is an explicit error.
- **Factory duplication** (`ponytail:duplicated-adapter-factory`): the
  adapter-selection logic duplicates the CLI `scheduler run`
  `_build_adapter` rather than importing the CLI into the API (which
  would invert layering). The upgrade path is to promote the factory
  into `alphabrief_execution.broker` and have both call it; deferred
  until a second caller justifies the move.

## Trading Environment

`alphabrief_gym` implements the Phase 4 Gymnasium-style simulation boundary
plus the Phase 11 multi-asset, continuous-action extension.

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
9. `AlphaBriefTradingEnvV2` adds multi-asset continuous target-weight
   actions, optional short, configurable `max_leverage`, daily borrow
   cost accrual, per-step liquidity limits, pluggable market-impact
   models, and pluggable reward functions (PnL, return,
   Sharpe-style, regime-scaled).
10. `EpisodeMetricsV2` includes `slippage_cost`, `market_impact_cost`,
    and `borrow_cost` per episode.

The original environment is single-asset and long/flat in the MVP. The
Phase 11 `AlphaBriefTradingEnvV2` adds multi-asset support while the
legacy env remains available for backward compatibility. Both envs do
not depend on Gymnasium, do not implement vectorized spaces, do not
train agents, and do not persist evaluation reports. Short positions
and leverage are **off by default** and require explicit configuration.

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

The API server is read-only with respect to execution. It is exposed
through the CLI with `alphabrief serve` and runs the FastAPI app via
Uvicorn.

It does not place or cancel orders, bypass RiskGate, or enable live
trading. The `/api/v1/broker/positions` and `/account` endpoints
perform **read-only** probes against the API-side `BrokerAdapter`
singleton (Phase 20) — they never submit orders, and account-exposure
*enforcement* still lives in `RiskGate`, not in these read endpoints.

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

## News & Macro Data Layer

`alphabrief_news` extends the Data Layer with structured news
headline and macro-economic indicator schemas, provider protocols,
mock providers for offline tests, a minimal RSS/Atom reader, and a
FRED stub that clearly surfaces the missing-API-key boundary.

Current behavior:

1. ``NewsHeadline`` and ``MacroIndicator`` are pure Pydantic
   validation boundaries with timezone-aware timestamps,
   stable IDs, and explicit ``data_version`` fields.
2. ``NewsProvider`` and ``MacroProvider`` are runtime-checkable
   ``Protocol`` objects declaring ``fetch_headlines`` and
   ``fetch_indicators`` respectively.
3. ``NewsProviderError`` carries a stable ``code`` drawn from
   ``NewsProviderErrorCode`` so CLI and API layers can branch on
   the failure mode without parsing free-form messages.
4. ``MockNewsProvider`` and ``MockMacroProvider`` return
   deterministic canned data for tests and offline use.
5. ``RssNewsProvider`` reads a hard-coded allowlist of free
   RSS/Atom feeds using only ``urllib`` and the standard-library
   XML parser. It extracts title, summary, published_at, source,
   and url only. It accepts no arbitrary user URLs.
6. ``FredMacroProvider`` is a stub that raises
   ``NewsProviderError(NO_API_KEY)``. No secret is read or stored.
7. ``check_headline_quality`` and ``check_indicator_quality``
   provide explicit in-memory validation (empty input, mixed
   ``data_version``, blank titles, invalid values, duplicate IDs,
   non-increasing timestamps).
8. ``NewsStore`` and ``MacroStore`` persist data in DuckDB through
   the existing storage layer. ``GET`` endpoints support filtering
   by symbol/indicator and time window.
9. The API exposes ``/api/v1/news/*`` and ``/api/v1/macro/*``
   endpoints; the CLI exposes ``alphabrief news`` and
   ``alphabrief macro`` subcommands.
10. Retry behavior is reused from ``alphabrief_data.providers``.
    HTTP 429/418/5xx and transient network errors are retried;
    non-rate-limit 4xx errors are not.

This layer does not wire news or macro data into research briefs,
model debates, risk rules, or execution. Those integrations are
reserved for future rounds.

## Phase 11 — Research Brief and Debate Context

The research layer can now consume news and macro data via the
`ResearchContextBuilder` and prompt v2 templates. The integration is
purely additive: all new schema fields are `Optional` and existing
tests / fake provider paths still pass.

Current behavior:

1. `MarketBrief`, `SymbolBrief`, `DailyAlphaBrief`, and
   `DebateQuestion` carry optional `news_context` /
   `macro_context` / `sentiment_summary` / `news_and_macro_summary`
   fields. Existing call sites that omit them continue to validate
   unchanged.
2. `ResearchContextBuilder` (in
   `packages/alphabrief-research/src/alphabrief_research/context.py`)
   accepts injected `news_loader` and `macro_loader` callables, so
   the research package never imports from the API or DB layers.
3. The API and CLI wire the builder to the existing
   `NewsStore` / `MacroStore` on demand. Failures are swallowed and
   fall back to an empty context block so prompt rendering never
   blocks brief generation.
4. Every external-content block is prefixed with an explicit
   untrusted-data banner. Prompt template v2 (`daily_alpha_brief:v2`,
   `market_brief:v2`, `symbol_brief:v2`, `debate_context:v1`) renders
   the banner and tells the model to treat the data as background
   only.
5. The `_PERSPECTIVE_PROMPTS` for `fundamental`, `risk`, and `judge`
   perspectives were updated to acknowledge the external context
   while still requiring the model to be critical of it.
6. The `/api/v1/brief/generate` and `/api/v1/research/debate` routes
   accept new `include_news`, `include_macro`, `news_symbols`, and
   `macro_indicators` fields. The CLI commands `alphabrief brief
   daily` and `alphabrief research debate` mirror them.
7. `RuleBasedSentimentAnalyzer` (in
   `packages/alphabrief-news/src/alphabrief_news/sentiment.py`)
   produces a deterministic, keyword-driven `SentimentLabel` for
   each headline. The `RssNewsProvider` annotates fetched headlines
   with sentiment by default; downstream consumers may opt out by
   passing `auto_sentiment=False`.
8. All research outputs continue to pass through `RiskGate` and
   remain OrderIntent drafts only — external content is never
   allowed to override deterministic risk rules.

This layer does not turn the model into a broker. OrderIntent drafts
still require an approved `RiskDecision` before reaching the paper
broker.

## Phase 11 — Additional Data Sources

The News & Macro Data Layer and the Market Data Layer each received
new providers in Phase 11.

Current behavior:

1. `FredMacroProvider` now performs real HTTP calls to
   `api.stlouisfed.org` via `urllib`. The API key is read from the
   `FRED_API_KEY` environment variable (or supplied via constructor)
   and is never logged, stored, or echoed in error messages. A
   missing key surfaces as `NewsProviderError(NO_API_KEY)`.
2. `SecEdgarNewsProvider` reads SEC EDGAR's company filing RSS feed
   and converts filings into `NewsHeadline` objects with
   `category="earnings"`. The User-Agent is configurable so callers
   can set a real contact per SEC's fair-access policy.
3. `SocialSentimentNewsProvider` is a deterministic stub that emits
   a small sentiment-tagged headline set per requested symbol. The
   provider exposes the `NewsProvider` protocol and is wired into
   the CLI/API `source=sentiment` branch.
4. `AlphaVantageProvider` is a free, key-gated daily / weekly /
   monthly OHLCV provider. The API key is read from
   `ALPHAVANTAGE_API_KEY` (or supplied via constructor). A missing
   key surfaces as `MarketDataProviderError(missing_api_key)`.
5. The CLI accepts the new sources: `alphabrief news fetch
   --source {mock,rss,sec,sentiment}` and `alphabrief data fetch
   --source {yahoo,binance,alphavantage}`.
6. The API mirrors them: `/api/v1/news/fetch` accepts
   `source={mock,rss,sec,sentiment}` and `/api/v1/data/fetch`
   accepts `source={yahoo,binance,alphavantage}`.
7. `.env.example` documents the new optional variables
   (`FRED_API_KEY`, `ALPHAVANTAGE_API_KEY`) without any real values.

These providers never call third-party SDKs. They expose an
injectable `http_get` so tests run with deterministic responses.

## Phase 11 — Dashboard Pages

The HTML dashboard grew from a single status page to a five-page
navigation.

Current behavior:

1. `/dashboard` — main status page. Adds Positions table, Equity
   Curve (canvas), and Recent Fills table alongside the existing
   Project Status / Data Symbols / Last Backtest / Last Brief /
   Paper Portfolio / Risk Status cards.
2. `/dashboard/news` — lists headlines via `/api/v1/news/headlines`,
   showing published time, source, symbols, title, and category.
3. `/dashboard/macro` — lists indicators via
   `/api/v1/macro/indicators`, showing release time, id, name, value,
   and unit.
4. `/dashboard/brief` — lists daily briefs via
   `/api/v1/brief/history` and reveals a JSON detail panel on
   click that fetches `/api/v1/brief/{id}`.
5. `/dashboard/debate` — lists debates via
   `/api/v1/research/debate` and reveals a JSON detail panel on
   click that fetches `/api/v1/research/debate/{id}`.
6. All pages share a top navigation bar, a consistent dark theme,
   and the existing `escapeHtml` helper for all external strings.

No new frontend dependency was added. The dashboard uses vanilla
HTML, JavaScript, and CSS only.

## Phase 12 — External Evidence Infrastructure

The strategy and risk layers now carry a structured external-evidence
pathway so that news sentiment and macro conditions can tighten (never
relax) risk decisions deterministically.

### Strategy External Evidence

`SignalEvidence` (in `alphabrief_core.domain`) is a frozen Pydantic
model attached to every `Signal`. It carries an `evidence_type`
(`"news"`, `"macro"`, or `"composite"`), `source`, `sentiment_score`,
`data_version`, and optional `headline_ids` / `macro_indicator_ids`.

`ExternalEvidenceConfig` (in `alphabrief_strategy.spec`) is an
optional field on `StrategySpec` that declares whether a strategy
intends to consume external evidence and how it should be treated by
downstream risk consumers (e.g. flag for human review on negative
sentiment). It is declarative only — it does not load data or wire
to providers.

Current behavior:

1. Every `Signal` may carry a `SignalEvidence` payload. When absent
   (legacy signal), downstream consumers treat it as a no-evidence
   signal and skip risk tightening.
2. `ExternalEvidenceConfig.require_human_review_on_negative` (default
   `True`) tells risk consumers to flag signals with sentiment below
   `negative_sentiment_threshold`.
3. All new fields are `Optional` with safe defaults — existing
   call sites and fake-provider tests pass unchanged.

### Research Structured Summary

`ResearchContextSummary` (in `alphabrief_research.context`) provides
a deterministic, frozen aggregate of news headlines and macro
indicators. It computes `positive_count`, `negative_count`,
`neutral_count`, `aggregate_sentiment_score`, `worst_sentiment`,
and `macro_indicator_ids`.

Current behavior:

1. `build_context_summary()` accepts lists of `NewsHeadline` and
   `MacroIndicator` and returns a `ResearchContextSummary`.
2. Every output carries `untrusted=True` — the summary is flagged
   as external data that must not override risk controls.
3. All fields default to safe empty values so the schema can be
   populated incrementally.

### Risk Context Decision Layer

`alphabrief_risk.context` provides a deterministic, tighten-only
adapter from `ResearchContextSummary` (or `NewsMacroRiskContext`)
into a `RiskContextDecision`.

Current behavior:

1. `NewsMacroRiskContext` is a lighter input mirror that consumers
   can construct without importing the research package directly.
2. `evaluate_news_macro_risk()` applies fixed thresholds:
   - `aggregate_sentiment_score < -0.2` → `negative_news_context`
     tag + `requires_human_review=True`
   - `macro_indicator_count > 4` → `macro_high_risk` tag +
     `suggested_position_reduction` (0.5× multiplier)
3. The decision is **advisory metadata only**. It never relaxes
   existing `RiskGate` limits — it can only add risk tags, flip
   `requires_human_review`, or suggest a position multiplier that
   downstream consumers may optionally apply.
4. Positive or neutral inputs return a neutral decision identical
   to the no-input default.

This layer does not call `ModelGateway`, read from a database, or
invoke external providers. It is a pure function from structured
input to deterministic risk metadata.

### Gymnasium EnvV2 Episode Reports

`alphabrief_gym.schemas` defines `EnvV2Report`, `EnvV2CostBreakdown`,
and `EnvV2AssetMetrics` — frozen Pydantic models for the multi-asset
environment's episode-level output.

Current behavior:

1. `EnvV2CostBreakdown` itemizes `slippage_cost`,
   `market_impact_cost`, `borrow_cost`, and `total_cost`.
2. `EnvV2AssetMetrics` captures per-asset `final_position`,
   `realized_pnl`, and `trade_count`.
3. `EnvV2Report` aggregates episode-level metrics (steps,
   initial/final value, total return, max drawdown, final
   leverage), per-asset metrics, and a cost breakdown.
4. All Decimal fields reject float input — Decimal-first
   throughout.

The report schemas are pure validation boundaries. They do not
call the environment, compute metrics, or persist reports.

## Phase 14 — Model Evaluation and Performance Intelligence

Phase 14 adds the model evaluation system that makes AlphaBrief's
"model-agnostic" promise actionable. Until Phase 14, the system routed
models by **declared capability tags only** — it had no way to know
which model actually performed better at which task, which model was
cost-effective, or which model hallucinated. Phase 14 closes this
gap with read-only intelligence that never touches trading, risk, or
execution code.

### Model Evaluation Store

`alphabrief_api.db.model_eval.ModelEvalStore` is a DuckDB-backed
persistent store for `ModelEvaluation` records. Each record carries
`json_valid_rate`, `schema_pass_rate`, `hallucination_rate`,
`avg_latency_ms`, `avg_cost_estimate`, `sample_count`, and a JSON
`eval_config` snapshot. The store exposes `save_evaluation`,
`get_evaluations`, `get_latest_evaluation`,
`get_latest_per_task_for_model`, and pagination helpers.

The store is read-only advisory: it never affects RiskGate,
KillSwitch, or execution. It never stores provider credentials.

### ModelEvaluator

`alphabrief_models.evaluation.ModelEvaluator` runs automated
evaluations against gold-standard local datasets through the
existing `ModelGateway`. The evaluator never calls provider SDKs
directly — all model invocations go through the gateway so that
capability filtering, fallback, and `ModelCallRecord` are honored.

The bundled datasets (`market_summary_v1`, `daily_brief_v1`,
`debate_response_v1`, `knowledge_v1`) are hardcoded Python
definitions in `alphabrief_models.evaluation_datasets`. They contain
no secrets, no URLs, and no network resources.

`MAX_SAMPLE_COUNT = 50` is a hard upper bound. Exceeding it is
silently clamped to 50.

### ModelRouter

`alphabrief_models.router.ModelRouter` is a capability +
performance-aware router. When no performance data exists, the
router preserves the existing capability-only behavior (sorting
profiles by `priority`, then `profile_id`). When performance data is
available, profiles are scored by `schema_pass_rate` (descending)
with optional `prefer_low_latency` and `prefer_low_cost` flags.
Profiles with `schema_pass_rate < MIN_SCHEMA_PASS_RATE` (default
0.7) are deprioritized for structured tasks.

Routing is **advisory only** — the router returns a
`ModelRouteDecision` that callers may inspect but are not required
to follow. The provider callable is exception-safe; routing falls
back to capability-only when the data source is unavailable.

### API and CLI surface

`/api/v1/models/{evaluate,evaluations,evaluations/{id},performance/{model_id},route,compare,datasets}`
expose the full lifecycle: run an evaluation, list and query
records, query the router, compare models, and list bundled
datasets. The CLI adds `alphabrief model
{evaluate,performance,route,compare}` mirroring the API.

### Dashboard

The main `/dashboard` page now includes a Model Performance card
grid, and a new `/dashboard/models` page lists recent evaluations
plus per-model performance summaries broken down by task. Both are
read-only — no live model calls are made from the page itself.

### Hard Constraints

1. All model invocations go through `ModelGateway`. No provider SDK
   is imported outside the existing adapter modules.
2. `ModelEvalStore` does not store provider credentials or
   secrets. API key environment variable names are never persisted.
3. Routing is advisory. Callers may override any router decision.
4. Bundled datasets are local Python definitions. No benchmark
   leakage, no external network calls.
5. The phase adds no new dependencies — only `duckdb`, `pydantic`,
   `urllib` (existing), and the standard library.

## Phase 15 — Strategy Registry and Signal History

Phase 15 makes strategies first-class persistent artifacts in the
system. Two stores live under `apps/api/src/alphabrief_api/db/`:

- `StrategySpecStore` (`strategies.py`) — DuckDB-backed CRUD for
  `StrategySpec` payloads plus an `enabled` advisory flag.
- `StrategySignalStore` (`strategy_signals.py`) — DuckDB-backed
  write-only history of individual signals emitted by a strategy.

### Storage layer

`strategy_specs` table:

| Column        | Type          | Notes                                 |
|---------------|---------------|---------------------------------------|
| `strategy_id` | TEXT PRIMARY  | Stable id from `StrategySpec`         |
| `name`        | TEXT          | Display name                          |
| `version`     | TEXT          | Spec version                          |
| `enabled`     | BOOLEAN       | Advisory activation flag              |
| `spec_json`   | JSON          | Full `StrategySpec` payload           |
| `created_at`  | TIMESTAMPTZ   | Auto-set on insert                    |
| `updated_at`  | TIMESTAMPTZ   | Auto-set on update                    |

`strategy_signals` table:

| Column        | Type          | Notes                                 |
|---------------|---------------|---------------------------------------|
| `signal_id`   | TEXT PRIMARY  | Idempotent upsert key                 |
| `strategy_id` | TEXT          | Strategy that emitted the signal      |
| `symbol`      | TEXT          | Symbol from the spec universe         |
| `signal_ts`   | TIMESTAMPTZ   | Bar timestamp of the signal           |
| `direction`   | TEXT          | "long" / "short" / etc.               |
| `confidence`  | DOUBLE        | Confidence in `[0, 1]`                |
| `horizon`     | TEXT          | Signal horizon label                  |
| `source`      | TEXT          | "backtest" / "manual" / "other"       |
| `signal_json` | JSON          | Full original signal payload          |
| `created_at`  | TIMESTAMPTZ   | Auto-set on insert                    |

Index: `(strategy_id, signal_ts DESC)`.

### Advisory-only safety contract

The two Phase 15 surfaces are **strictly advisory**:

1. The `enabled` flag on a stored spec is a user opt-in marker. It
   is not wired into `RiskGate.enabled_strategies` (a separate,
   manually configured frozenset), is not consulted by
   `PaperBroker`, and never enables live trading.
2. The signal history is a write-only log of strategy output. It
   is not consulted by `RiskGate.evaluate`, by `PaperBroker.submit`,
   or by any execution path.

`GET /api/v1/strategies/enabled` is the only consumer-facing
read-only surface for the activation flag, and it is documented as
"informational only". Future rounds may opt to read it, but the
registry flag never grants, relaxes, or blocks risk decisions.

### API surface

- `POST   /api/v1/strategies/specs` — create or replace a spec
- `GET    /api/v1/strategies/specs` — list summaries
- `GET    /api/v1/strategies/specs/{id}` — full record
- `PATCH  /api/v1/strategies/specs/{id}` — flip the activation flag
- `DELETE /api/v1/strategies/specs/{id}` — remove
- `GET    /api/v1/strategies/enabled` — advisory list of enabled ids
- `POST   /api/v1/strategies/signals` — record a signal
- `GET    /api/v1/strategies/signals` — list signal summaries
- `GET    /api/v1/strategies/signals/{signal_id}` — full signal
- `DELETE /api/v1/strategies/signals/{signal_id}` — remove
- `GET    /api/v1/strategies/{strategy_id}/signals/count` — count

### CLI surface

```
alphabrief strategy save --from-yaml FILE [--from-json FILE] [--enable|--disable]
alphabrief strategy list [--enabled|--disabled]
alphabrief strategy show STRATEGY_ID
alphabrief strategy enable STRATEGY_ID
alphabrief strategy disable STRATEGY_ID
alphabrief strategy delete STRATEGY_ID
alphabrief strategy record-signal --from-yaml FILE [--source backtest|manual|other]
alphabrief strategy list-signals [--strategy-id] [--symbol] [--source] [--limit]
alphabrief strategy show-signal SIGNAL_ID
alphabrief strategy count-signals STRATEGY_ID
```

### Dashboard

A new `/dashboard/strategies` page lists saved strategies with
their name, version, enabled badge, updated timestamp, and a "View"
link to the full JSON record. Per-strategy signal counts are
shown alongside the activation badge. Both the registry and the
signal history carry explicit "advisory only" disclaimers in the
page UI.

### Hard Constraints

1. No imports from `_reference_sources/`.
2. The registry and signal history never modify `RiskDecision`
   semantics, never enable live trading, and never call broker
   code.
3. The activation flag and signal history are independent of
   `RiskGate.enabled_strategies` and `RiskGate.trading_enabled`.
4. Tests assert the advisory nature by exercising the risk gate
   with the registry flag set and confirming the gate's decision
   is unchanged.
5. The phase adds PyYAML (already a transitive of uvicorn) as a
   declared runtime dep, plus `types-PyYAML` as a dev dep.

## Phase 16 — Paper Execution Boundary and Strategy Admission

`config/paper_execution_policy.yaml` is the reviewed operating boundary for
the external-paper integration: Alpaca Paper, `SPY`, `QQQ`, `IVV`, `VOO`,
`AGG`, `BND`, `GLD`, and `SLV`, US regular session, market/limit orders,
`$100` maximum order notional, and
`$300` maximum total exposure. It has no credentials, permits only `paper`
mode, and sets `automated_execution: false` plus mandatory human review.

The API maps policy fields into `RiskGate`: symbol allowlist, maximum order
value, human review, and the `$300` total-exposure ceiling. Phase 19 supplies
an execution-side `AccountExposureContext`; when the ceiling is configured,
the risk gate fails closed without that context and can only reject or tighten
the permitted quantity.

`strategy_admissions` is an append-only DuckDB audit table. Its API creates
and reads version-matched evidence records, but neither `RiskGate` nor
`PaperBroker` reads it. `RiskLimitConfig.enabled_strategies=None` means no
strategy allowlist is configured, while an explicit empty set denies all
strategy orders. This prevents advisory registry state or admission evidence
from granting execution authority.

## Phase 17 — External Paper-Broker Adapter (Alpaca)

`alphabrief_execution/broker.py` is replaced by a `broker/` package whose
single outward face is the broker-neutral `BrokerAdapter` port
(`SubmitRequest`, `SubmitResult`, `OrderState`, `Position`, `AccountSnapshot`,
`Fill`, `CancelResult`, `BrokerHealth`). The first concrete implementation is
`AlpacaPaperAdapter`, talking to `paper-api.alpaca.markets` over stdlib
HTTP. The deterministic `PaperBroker` is preserved in
`broker/legacy.py` and re-exported from the new package so existing
imports continue to work.

Credentials are read from `ALPHABRIEF_ALPACA_KEY` and
`ALPHABRIEF_ALPACA_SECRET` only. The adapter raises `BrokerAuthError` at
construction if either is missing. Non-secret configuration (base URL,
timeouts, retry budget) lives in `config/alpaca_paper.yaml`. The adapter
rejects any symbol outside the Phase 16 `PaperExecutionPolicy` symbol set
before issuing an HTTP call, and `automated_execution: false` plus
mandatory human review are unchanged.

`broker/recon_store.py` persists three DuckDB tables:
`broker_order_id_map` (client_order_id -> broker_order_id, so restarts
do not double-submit), `broker_recon_snapshots` (per-reconciliation
diff records), and `broker_freeze_events` (append-only freeze /
unfreeze log; an open freeze has `cleared_at IS NULL`).
`ReconciliationRunner` reconciles a callable broker snapshot against
the local id-map / fills / cash / positions, records a
`ReconSnapshot`, and emits a typed freeze on drift.

The API exposes read-only and admin routes under
`/api/v1/broker/` (`status`, `reconcile`, `orders`, `positions`,
`account`, `freeze`, `unfreeze`). The CLI mirrors those subcommands
and falls back to the local store when the API is not running. The
`OperationsScheduler` scaffold (`HeartbeatStore`, `AlertSink`,
`ScheduledTask`) ships in `alphabrief_execution/operations/`; the
operator surface for it (CLI + API) is described in the next section.

Phase 19 adds the account-exposure input to `RiskGate` without changing the
paper-only execution policy, advisory `enabled` flag, or strategy-admission
authority. The `$300` total-exposure bound is now an enforced, tighten-only
runtime guard; it does not grant any execution authority.

## Phase 18 — Scheduler Operations Surface

The Phase 17 `OperationsScheduler` is a typed scaffold plus tests; this
phase adds the operator entry points on top of it without changing the
scheduler core.

1. `HeartbeatStore` gained a read-only `list_heartbeats()` method that
   returns one row per registered task, newest-first by `last_run_at`,
   in the same shape as the existing `list_alerts` method.
2. A new FastAPI router at `apps/api/src/alphabrief_api/routes/scheduler.py`
   exposes five read-only endpoints under `/api/v1/scheduler`:
   - `GET /status` — aggregate heartbeat / freeze / alert counts and
     the always-`False` `running` flag.
   - `GET /heartbeats` — per-task heartbeat rows.
   - `GET /alerts?limit=N` — recent alerts, clamped to `[1, 500]`.
   - `GET /tasks` — static description of `build_default_tasks()`.
   - `GET /freezes` — currently-open broker freezes.
3. A new Typer subapp at
   `apps/cli/src/alphabrief_cli/scheduler_commands.py` exposes the same
   surface as CLI commands (`scheduler status`, `scheduler heartbeats`,
   `scheduler alerts`, `scheduler tasks`, `scheduler freezes`) and
   proxies through the API when the server is running.
4. `scheduler run` is CLI-only: it starts the `OperationsScheduler` as
   a foreground asyncio process with options `--reconcile-interval`
   and `--max-failures`, traps SIGINT/SIGTERM, exits 2 on startup
   reconciliation freeze, and exits 3 if
   `ALPHABRIEF_LIVE_TRADING_ENABLED` is truthy. When both
   `ALPHABRIEF_ALPACA_KEY` and `ALPHABRIEF_ALPACA_SECRET` are set, it
   builds a real `AlpacaPaperAdapter`; otherwise it uses a
   `NullBrokerAdapter` that returns empty results so the scheduler
   can run in dev / CI without a live broker connection.

The scheduler never places orders. `RiskGate`, `PaperBroker`,
`KillSwitch`, the Alpaca adapter, the recon store, and the
reconciliation runner are unchanged.

## Phase 21 — Account-Level Risk Rules (R21.x)

Phase 19 R19.1 added the account-total-exposure cap. Phase 21 extends
that runtime account-level enforcement with the full set of
blueprint §6 rules: per-symbol exposure, concentration, leverage,
price deviation, market-state, signal-staleness, duplicate-order,
daily-loss, and drawdown-floor. Every new check follows the same
**tighten-only** / **fail-closed** contract as `_check_account_exposure`.

### Rule surface and failure tags

| `RiskLimitConfig` field | `RiskGate` check | Failure tags |
|---|---|---|
| `max_symbol_exposure` | `_check_symbol_exposure` | `account_context_required`, `missing_price`, `max_symbol_exposure` |
| `max_concentration_pct` | `_check_concentration` | `account_context_required`, `missing_price`, `max_concentration` |
| `max_leverage` | `_check_leverage` | `account_context_required`, `missing_equity`, `missing_price`, `max_leverage` |
| `max_price_deviation_pct` | `_check_price_deviation` | `missing_price`, `account_context_required`, `missing_mark_price`, `price_deviation` |
| `require_market_open` + `session_policy` | `_check_market_open` | `market_closed` |
| `max_signal_age_seconds` | `_check_signal_age` | `stale_signal` |
| `duplicate_order_window_seconds` + `duplicate_order_max_count` | `_check_duplicate_order` | `duplicate_order` |
| `max_daily_loss_pct` | `_check_daily_loss` | `account_context_required`, `missing_day_start_equity`, `missing_equity`, `max_daily_loss` |
| `max_drawdown_floor_pct` | `_check_drawdown` | `account_context_required`, `missing_equity_hwm`, `missing_equity`, `max_drawdown_floor` |

All checks are no-ops when their limit field is unset; the existing
48 risk-gate tests (Phase 12–19) continue to pass without
modification.

### Layer discipline (unchanged)

`alphabrief-risk` still imports only `alphabrief-core`. The new
`AccountExposureContext` fields (`equity`, `reference_mark_prices`,
`equity_high_water_mark`, `day_start_equity`, `day_realized_pnl`) are
caller-supplied inputs, computed by the execution-side projection
helper. The dependency arrow remains one-way: execution → risk.

The execution-side `build_account_exposure_context` (async, broker
adapter driven) and `build_account_exposure_context_from_portfolio`
(sync, `PortfolioState` driven) both now project `equity` and
`reference_mark_prices` into the context. The legacy `PortfolioState`
fallback computes `equity = cash + sum(qty * mark)`; without marks
the helper falls back to `average_price` and the result is
cost-basis equity (`ponytail:portfolio_equity_ceiling` — paper route
will fail-closed for `max_leverage` / `max_daily_loss_pct` /
`max_drawdown_floor_pct` until a persistent equity-snapshot store is
wired in by Phase 21.5+).

### Tighten-only / fail-closed invariant

Every new check:

- is a **no-op** when its `RiskLimitConfig` field is `None`/unset
  (legacy paths unchanged);
- **fails closed** when a required context input is missing
  (`account_context`, `equity`, `equity_high_water_mark`,
  `day_start_equity`, `reference_mark_prices`, `session_policy`).
  A missing input is a rejection, never a silent skip;
- can only **reject**, **tag**, or **reduce** `max_quantity`. None
  of the new checks can re-approve a rejected intent, lift the
  live-trading lock, relax the human-review flag, or raise
  `max_quantity` above the configured per-order cap;
- bypasses **sells** for the per-symbol, leverage, daily-loss, and
  drawdown rules (a sell is the protective action when in loss or
  drawdown — the check must not block it).

### Out of scope (Phase 21.5+)

- Persistent HWM / day-start equity across restarts. Today the paper
  route reads them from the equity-snapshot store when present and
  falls back to current `equity` when absent.
- A market-calendar provider. The `require_market_open` check uses
  the policy's `trading_days` + `session_start` / `session_end`
  (no U.S. holiday calendar; `ponytail:no-holiday-calendar`).
- Persistent duplicate-order dedup. Today's deque is in-memory
  (`ponytail:duplicate_order_state`); a restart loses dedup memory.
- 30–60-day external paper observation period
  (FINAL_ACCEPTANCE_REPORT §10).
- Live trading — out of scope for this phase and the rest of the
  paper MVP.

## Phase 22 — Kronos Forecast Integration

AlphaBrief now integrates the external Kronos financial-markets
foundation-model project as an optional market-forecasting provider.
The integration is owned by AlphaBrief and lives in
`alphabrief_models.kronos`; no code is copied from the external
repository and no files under `_reference_sources/` are imported.

```
KronosForecastRequest
    │  OHLCV Bar list, symbol, prediction_length, model/tokenizer names
    ▼
ModelRequest(task_type="market_forecast",
             required_capabilities=["structured_output",
                                    "time_series_forecasting"])
    ▼
ModelGateway
    ▼
KronosForecastAdapter
    ▼
KronosRuntime
    │   DeterministicKronosRuntime for CI / smoke tests
    │   PredictorKronosRuntime for an operator-injected external predictor
    ▼
KronosForecastReport + KronosForecastEvidence
```

Key contracts:

1. `market_forecast` is a first-class `ModelTaskType`, and
   `time_series_forecasting` is a first-class `ModelCapability`.
2. `KronosForecastReport` is structured, Pydantic-validated, and
   always `advisory_only=True`.
3. `KronosForecastEvidence` summarizes direction bias, confidence,
   and expected return for research or strategy metadata only.
4. The adapter never emits `Signal`, `OrderIntent`, `RiskDecision`,
   `Order`, fill, position, or broker activity.
5. `PredictorKronosRuntime` imports optional dependencies lazily so
   AlphaBrief's core install remains lightweight. The `kronos` extra
   declares heavyweight runtime dependencies for operators that want
   real local inference.
6. `POST /api/v1/models/kronos/forecast` and
   `alphabrief model kronos-forecast` run through `ModelGateway` and
   surface the gateway call status.
7. `runtime_mode="configured"` fails closed with an unavailable-runtime
   error when no external runtime has been injected. `deterministic`
   mode exists for tests and local smoke checks and is explicitly
   labeled in the report notes.

Out of scope:

- Vendoring or copying the external Kronos repository.
- Installing model weights automatically.
- Strategy generation, signal generation, order-intent generation, or
  paper/live execution from a Kronos forecast.
- Backtest acceptance of Kronos-derived signals without the existing
  AlphaBrief costs, slippage, data-version, and out-of-sample rules.
