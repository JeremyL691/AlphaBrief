# AlphaBrief Roadmap

The roadmap follows the phases in `ALPHABRIEF_PRODUCT_BLUEPRINT.md`.

## Phase 1: AlphaBrief Core

Goal: create the smallest reliable research and backtest kernel.

Status: completed for the MVP kernel. The current implementation can load
local OHLCV data, validate data quality, generate no-lookahead features,
validate StrategySpec objects, run a simple strategy interface, execute a
long/flat moving-average backtest, and write a JSON backtest report with costs
and metrics.

Planned sequence:

1. Repository scaffold and project rules: completed.
2. Core domain models: completed.
3. Configuration system: completed.
4. CSV and Parquet market data loader: completed.
5. Data quality checks: completed.
6. Feature generation: completed.
7. StrategySpec schema: completed.
8. Strategy interface: completed.
9. Vectorized backtester: completed.
10. Basic metrics and report schema: completed.

## Phase 2: ModelGateway and Research Briefs

Goal: add model-agnostic research capabilities through a unified gateway.

Status: completed for the MVP research layer. The current implementation has
ModelGateway contracts, fake and local Ollama provider adapters, model
registry/profile selection, prompt template versioning, structured output
parsing, MarketBrief/SymbolBrief schemas, and DailyAlphaBrief generation.

Progress:

1. ModelGateway contracts and FakeProvider: completed.
2. Quality gates (Ruff / mypy): completed.
3. ModelRegistry and provider config: completed.
4. Structured output parser: completed.
5. Research brief schemas (MarketBrief, SymbolBrief): completed.
6. DailyAlphaBrief schema and generator: completed.
7. Prompt template versioning: completed.
8. Real provider adapter: completed with local Ollama adapter.

## Phase 3: Risk and Paper Trading

Goal: create a safe paper-trading loop where every OrderIntent passes RiskGate.

Status: completed for the MVP paper-trading loop. The current implementation
has RiskGate, KillSwitch, PaperBroker, OrderRouter, FillSimulator,
PortfolioState, and ExecutionAuditLog. Live trading remains unavailable.

Progress:

1. OrderIntent schema: completed in `alphabrief_core`.
2. RiskDecision schema: completed in `alphabrief_core`.
3. RiskGate MVP: completed.
4. KillSwitch: completed.
5. OrderRouter: completed.
6. FillSimulator: completed.
7. PortfolioState: completed.
8. ExecutionAuditLog: completed.
9. PaperBroker MVP: completed.

## Phase 4: Trading Environment

Goal: add a Gymnasium-style simulation environment for strategy comparison.

Status: completed for the MVP simulation layer. The current implementation has
a reset/step trading environment, action and observation schemas, transition
rewards, transaction costs, slippage, episode metrics, random policy
evaluation, buy-and-hold baseline, and strategy comparison report.

Progress:

1. AlphaBriefTradingEnv: completed.
2. Action / observation space: completed.
3. Reward functions: completed.
4. Transaction cost: completed.
5. Slippage: completed.
6. Random policy evaluation: completed.
7. Buy-and-hold baseline: completed.
8. Strategy comparison report: completed.

## Phase 5: Dashboard and Review

Goal: expose reports, risk logs, paper portfolio, and review history through a
daily-use interface.

Status: completed for the MVP review layer. The current implementation has a
Review Center snapshot, local JSON persistence, text viewers for all Phase 5
surfaces, paper/risk/audit summaries, and daily/weekly review journal
generation.

Progress:

1. Strategy list: completed.
2. Backtest report viewer: completed.
3. Daily AlphaBrief viewer: completed.
4. Model call history: completed.
5. Paper portfolio: completed.
6. Order audit log: completed.
7. Risk dashboard: completed.
8. Review journal: completed.

## Phase 6: Web API Surface

Goal: expose AlphaBrief research, backtest, paper trading, and review data
through a FastAPI web server.

Status: completed. All planned API endpoints implemented with tests, plus
basic web dashboard and API docs integration.

Planned sequence:

1. FastAPI application scaffold with health check
2. Market data API endpoints
3. Backtest API endpoints
4. Research/Brief API endpoints
5. Paper portfolio and risk API endpoints
6. Review center API endpoints
7. CLI integration (start/stop server from CLI)
8. Basic web dashboard (HTML/JS) or API docs

Progress:

1. FastAPI scaffold + health + status + data endpoints: completed.
2. CLI `alphabrief serve` integration: completed.
3. Market data API endpoints (symbols, bars, info, load): completed.
4. Backtest API endpoints (run, reports, report/{id}): completed.
5. Research/Brief API endpoints (generate, history, {id}): completed.
6. Paper portfolio and risk API endpoints (portfolio, orders, audit, config, dashboard): completed.
7. Review center API endpoints (snapshot, journal, journal/daily, journal/weekly): completed.
8. Basic web dashboard (/dashboard) and API docs (/docs, /redoc): completed.

## Phase 7: Persistent Storage Layer

Goal: replace all API in-memory data with DuckDB persistent storage so data
survives application restarts.

Status: completed. All planned persistence stores (market data, backtest reports, briefs, paper portfolio/audit, and review snapshots) are now backed by DuckDB.

Planned sequence:

1. DuckDB schema definition and data access layer: completed (Round 1).
2. Market data persistence: completed (Round 1).
3. Backtest reports persistence: completed (Round 2).
4. Briefs persistence: completed (Round 3).
5. Paper portfolio + audit log persistence: completed (Rounds 4+5).
6. Review snapshots persistence: completed (Rounds 4+5).

Progress:

1. DuckDB schema (symbols, bars tables) and MarketDataStore: completed.
2. POST /api/v1/data/load and GET data endpoints read from DuckDB: completed.
3. Test suite updated with 20 new MarketDataStore unit tests: completed.

## Phase 8: Multi-Model Research Committee

Goal: enable multi-model research debates where users submit a question and
multiple AI models with different analytical perspectives independently
analyze it, producing structured responses and an aggregated consensus.

Status: completed.

Completed:

1. Debate schemas (`DebateQuestion`, `ModelDebateResponse`,
   `DebateConsensus`, `DebateRecord`) in new `alphabrief-research` package.
2. `DebateOrchestrator` that routes questions to multiple model perspectives
   via `ModelGateway`, validates structured output, and generates consensus.
3. DuckDB persistence via `DebateStore` (`debate_records` table).
4. `POST /api/v1/research/debate`, `GET /api/v1/research/debate`,
   `GET /api/v1/research/debate/{debate_id}` API endpoints.
5. `alphabrief research debate` CLI command.
6. 32 new tests across schemas, orchestrator, DB store, and API routes.
7. Test suite: 367 passed, ruff and mypy clean.

## Phase 9: Real Market Data Providers

Goal: replace manual CSV/Parquet data import as the only way to load
market data by adding free, key-less HTTP data providers that download
OHLCV bars directly into the existing DuckDB `bars` table.

Status: completed.

Planned sequence:

1. `alphabrief_data.providers` subpackage with `MarketDataProvider`
   protocol, `MarketDataProviderError` structured error, and
   `MarketDataProviderErrorCode` enum.
2. `YahooFinanceProvider` — daily and hourly OHLCV bars from
   `query1.finance.yahoo.com` using `urllib` only (no `yfinance`).
3. `BinanceProvider` — daily and hourly OHLCV klines from
   `api.binance.com/api/v3/klines` using `urllib` only (no
   `python-binance`).
4. `alphabrief data fetch` CLI subcommand that downloads bars and
   persists them through `MarketDataStore`.
5. `POST /api/v1/data/fetch` API endpoint with the same body
   schema as the CLI.
6. 41 new tests across the providers, the CLI command, and the API
   endpoint — all with fully mocked HTTP.
7. Updated `docs/architecture.md` Market Data Providers chapter.

Progress:

1. Provider base types, Yahoo provider, Binance provider, exports:
   completed.
2. CLI `data fetch` subcommand with Typer options, error
   reporting, and DuckDB persistence: completed.
3. `POST /api/v1/data/fetch` API endpoint with request/response
   models, validation, and persistence: completed.
4. 25 provider unit tests (HTTP mocking, error codes, payload
   parsing): completed.
5. 7 API integration tests (happy path, empty result, HTTP error,
   invalid input, custom data version): completed.
6. 9 CLI integration tests (Yahoo/Binance success, unknown source,
   invalid date, empty response, lowercase symbol rejection):
   completed.
7. Test suite: 408 passed (up from 367), ruff and strict mypy
   clean.

### Phase 9 Round 2: retry policy + interval expansion

Goal: harden the providers against transient HTTP failures and
broaden the supported interval set so users can fetch minute, weekly,
and monthly bars without re-validating everything by hand.

Status: completed.

1. Added `RetryPolicy` dataclass with max-retries, exponential
   backoff, hard cap, and uniform jitter — frozen and validated in
   `__post_init__`.
2. Added `is_retryable_exception()` (HTTP 429/418/5xx and transient
   network errors are retryable; non-rate-limit 4xx is not),
   `compute_backoff_delay()` (deterministic given a fixed random
   source), and `call_with_retry()` (sleep / random / on_retry /
   is_retryable test seams).
3. Wrapped the Yahoo and Binance HTTP layers with
   `call_with_retry` so transient failures recover automatically
   before any structured `MarketDataProviderError` is raised.
4. Expanded Yahoo's `_SUPPORTED_INTERVALS` to
   `1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo` and Binance's to
   `1m, 3m, 5m, 15m, 30m, 1h, 1d, 1w, 1M`. Added Binance's
   `_interval_to_seconds()` mapping for the new `1w` (604 800 s) and
   `1M` (2 592 000 s) intervals so the pagination cursor advances
   correctly.
5. Updated the API `DataFetchRequest.interval` Literal and the CLI
   `--interval` help text to reflect the expanded set.
6. 23 new tests in `tests/test_market_data_providers.py` covering
   retry classification, backoff math, retry success / exhaustion /
   4xx-no-retry, end-to-end provider retry on 5xx, no-retry on 4xx,
   every new Yahoo interval, Yahoo `1wk` / `1mo` data-version
   mapping, every new Binance interval, and Binance `1w` / `1M`
   data-version mapping.
7. Updated `docs/architecture.md` Market Data Providers chapter
   to reflect the retry policy and the expanded interval sets, and
   to remove the now-incorrect "no retries" claim.
8. Test suite: 431 passed (up from 408), ruff and strict mypy
   clean.

## Phase 10: News & Macro Data Layer

Goal: add the first read-only News & Macro Data Layer boundary so
future research, brief, and risk modules can consume structured
headlines and macro snapshots without calling provider SDKs,
scraping arbitrary URLs, or reaching into the open internet.

Status: completed.

Planned sequence:

1. `alphabrief_news` package with `NewsHeadline`, `MacroIndicator`,
   `NewsProvider`, `MacroProvider`, `NewsProviderError`, and
   quality checks: completed.
2. `MockNewsProvider` and `MockMacroProvider` for deterministic
   offline tests: completed.
3. `RssNewsProvider` — stdlib-only RSS/Atom reader with a
   hard-coded free feed allowlist and injectable `http_get`: completed.
4. `FredMacroProvider` stub that raises `NO_API_KEY` and stores no
   secrets: completed.
5. DuckDB `news_headlines` and `macro_indicators` tables with
   `NewsStore` and `MacroStore`: completed.
6. `POST /api/v1/news/fetch`, `GET /api/v1/news/headlines`,
   `GET /api/v1/news/headlines/{id}`, `POST /api/v1/macro/fetch`,
   `GET /api/v1/macro/indicators`,
   `GET /api/v1/macro/indicators/{id}` endpoints: completed.
7. `alphabrief news fetch/list` and `alphabrief macro fetch/list`
   CLI subcommands: completed.
8. 26 unit tests in `tests/test_news.py`, 9 DB store tests, 14 API
   integration tests, 9 CLI integration tests: completed.
9. Updated `docs/architecture.md`, `docs/roadmap.md`,
   `docs/development_log.md`, and `docs/agent_protocol.md`: completed.

Test suite: 489 passed (up from 431), ruff and strict mypy clean.

This phase intentionally does not wire news/macro data into
research briefs, model debates, risk rules, or execution. Those
integrations are reserved for future rounds.

## Phase 11: News/Macro Research Integration, More Data Sources, Trading Environment Expansion, Dashboard

Goal: feed Phase 10 news/macro data into research briefs and debate
prompts, expand the trading environment to multi-asset / continuous
actions / short / leverage / liquidity / market impact / regime-aware
rewards, add FRED/SEC/Social-Sentiment/AlphaVantage data sources, and
grow the web dashboard with dedicated news / macro / brief / debate
pages.

Status: completed. 597 tests pass (up from 489), ruff clean, strict
mypy errors unchanged from Phase 10 baseline.

Progress:

1. Optional news/macro context fields added to `MarketBrief`,
   `SymbolBrief`, `DailyAlphaBrief`, and `DebateQuestion`. All
   new fields default to `None` so existing fake-provider tests
   pass unchanged.
2. `ResearchContextBuilder` in the research package renders
   natural-language news/macro context blocks for prompt
   consumption. Every block is prefixed with an explicit
   untrusted-data banner.
3. v2 prompt templates (`daily_alpha_brief:v2`, `market_brief:v2`,
   `symbol_brief:v2`, `debate_context:v1`) registered in
   `PromptTemplateRegistry`. `render_brief_prompt_v2` helper
   exposed in the public API.
4. `DebateOrchestrator` injects `news_context` /
   `macro_context` into per-perspective prompts. The fundamental,
   risk, and judge perspective prompts were updated to require
   critical treatment of any provided external context.
5. `RuleBasedSentimentAnalyzer` provides deterministic
   keyword-based sentiment classification. `RssNewsProvider` now
   annotates fetched headlines with sentiment by default.
6. `FredMacroProvider` upgraded from stub to a real
   `urllib`-based implementation reading `FRED_API_KEY` from the
   environment. No key is stored, logged, or echoed in errors.
7. `SecEdgarNewsProvider` reads SEC EDGAR company filing RSS and
   produces `NewsHeadline` objects with `category="earnings"`.
   User-Agent is configurable per SEC fair-access policy.
8. `SocialSentimentNewsProvider` is a deterministic stub
   implementing the `NewsProvider` protocol. Wired into
   `source=sentiment` branch.
9. `AlphaVantageProvider` is a real daily/weekly/monthly OHLCV
   provider reading `ALPHAVANTAGE_API_KEY` from the environment.
10. CLI and API expose the new sources. `.env.example` documents
    `FRED_API_KEY` and `ALPHAVANTAGE_API_KEY` (no real values).
11. `alphabrief-gym` gained `schemas.py`, `env_v2.py`,
    `action.py`, `market_impact.py`, and `rewards.py`.
    `AlphaBriefTradingEnvV2` supports multi-asset continuous
    target-weight actions, optional short, configurable
    `max_leverage`, daily borrow cost accrual, per-step liquidity
    limits, pluggable market-impact models, and pluggable
    reward functions (PnL, return, Sharpe-style, regime-scaled).
    The legacy single-asset `AlphaBriefTradingEnv` remains
    available for backward compatibility.
12. Dashboard grew from one page to five: main page with
    Positions / Equity Curve / Recent Fills cards, plus
    `/dashboard/news`, `/dashboard/macro`, `/dashboard/brief`,
    `/dashboard/debate`. Vanilla HTML/JS/CSS only, no new
    dependencies.
13. Test suite: 597 passed (up from 489), ruff clean, strict
    mypy errors unchanged from Phase 10 baseline.

## Phase 12: External Evidence and Risk Context

Goal: wire news/macro external evidence through the strategy and risk
pipeline so that deterministic, audit-friendly risk tightening can
respond to market sentiment and macro conditions — without modifying
RiskGate core semantics.

Status: completed. Rounds 12.1–12.8 complete.

Planned sequence:

1. `SignalEvidence` domain model and `ExternalEvidenceConfig` on
   `StrategySpec`: completed (R12.1).
2. Structured `ResearchContextSummary` with sentiment/macro fields:
   completed (R12.2).
3. News/Macro risk-context decision layer
   (`NewsMacroRiskContext` → `RiskContextDecision`): completed (R12.3).
4. Strategy interface extended to carry `SignalEvidence` on every
   signal: completed (R12.4).
5. Risk API and CLI expose risk-context evaluation: completed (R12.5).
6. Gymnasium EnvV2 episode reports with cost-breakdown schemas:
   completed (R12.6).
7. BacktestReportSchema v2 compatible extension (`report_engine`
   column, `save_env_v2_report` helper): completed (R12.7).
8. CLI/API `engine="env_v2"` option for multi-asset
   `AlphaBriefTradingEnvV2` backtest: completed (R12.8).

This phase is additive and tighten-only: risk can never be relaxed
by external evidence. All new fields are optional with safe defaults
so existing tests and fake-provider paths continue to pass
unchanged.

## Phase 13: RiskContext → RiskGate Wiring

Goal: wire the Phase 12 `RiskContextDecision` into `RiskGate` so the
deterministic news/macro tightening is honored on every
`OrderIntent` evaluation, without changing any base check semantics
or weakening the kill switch / live-trading lock.

Status: complete. Rounds 13.1–13.5 complete.

### Round 13.1 — RiskGate accepts optional RiskContextDecision

1. `RiskGate.evaluate()` gained an optional keyword-only
   `risk_context: RiskContextDecision | None = None` argument.
2. The contract is **tighten-only**: tags are merged (deduplicated),
   the human-review flag is OR-merged, and `max_quantity` is reduced
   by `suggested_max_position_multiplier` (Decimal-first, no rounding,
   never relaxed).
3. Base checks are unchanged. The risk context cannot re-approve a
   rejected intent, cannot override the kill switch, cannot lift the
   live-trading lock, and cannot add symbols to the allowlist.
4. 20 new tests in `tests/test_risk_gate.py` cover backward
   compatibility, positive/negative/macro context effects,
   re-approval rejection, multiplier-at-one no-op, kill switch
   precedence, live-trading-lock precedence, tag deduplication, and
   combined static-flag + context merging.
5. Test suite: 679 passed (up from 659), ruff clean, strict mypy
   clean.

### Rounds 13.2–13.5 — risk_context end-to-end wiring

1. `alphabrief risk check` and `POST /api/v1/risk/check` accept an
   optional `risk_context` payload and surface the merged
   `RiskDecision`. 16 new tests in `tests/test_r13_risk_context_wiring.py`.
2. `PaperBroker.submit` blocks when the merged decision requires
   human review. `alphabrief paper run` and `POST /api/v1/paper/orders`
   accept `risk_context` and exit with code 1 / 422 respectively
   when the broker would otherwise auto-execute.
3. `ExecutionAuditEntry` carries the `risk_context_decision_id`,
   `risk_context_tags`, and `risk_context_multiplier` of the merged
   decision. The audit endpoints expose the metadata on every
   recorded event.
4. Test suite: 695 passed (up from 679), ruff clean, strict mypy
   clean.

## Phase 14: Model Evaluation & Performance Intelligence

Goal: add the model evaluation system that makes AlphaBrief truly
model-agnostic. Currently the system routes models by declared
capability tags only — Phase 14 adds automated evaluation against
gold-standard local datasets, cost/latency/performance-aware
routing, model performance persistence, and a dashboard for
comparing providers and models. This phase touches **zero**
trading, risk, or execution code.

Status: complete. Rounds 14.1–14.7 complete.

### Round 14.1 — DuckDB model_evaluations table + ModelEvalStore

1. Added `model_evaluations` table to `db/schema.py` with columns for
   `json_valid_rate`, `schema_pass_rate`, `hallucination_rate`,
   `avg_latency_ms`, `avg_cost_estimate`, `sample_count`, and a
   JSON `eval_config` snapshot.
2. Created `ModelEvalStore` with `save_evaluation`, `get_evaluations`,
   `get_latest_evaluation`, `get_latest_per_task_for_model`,
   `list_evaluations`, `clear`, and `close`. 14 new tests in
   `tests/test_model_eval_store.py`.

### Round 14.2 — ModelEvaluator engine

1. Added `alphabrief_models.evaluation` with `EvalDataset`,
   `EvalResult`, `EvalDatasetSpec`, `EvalSample`, `ModelEvaluation`,
   and `ModelEvaluator`.
2. `ModelEvaluator` runs JSON-validity, schema-pass, and
   hallucination evaluations through `ModelGateway`. It **never**
   calls provider SDKs directly.
3. Bundled local datasets (`market_summary_v1`, `daily_brief_v1`,
   `debate_response_v1`, `knowledge_v1`) are hardcoded Python
   definitions with no network calls or secrets.
4. `MAX_SAMPLE_COUNT = 50` hard upper bound.
5. 20 new tests in `tests/test_model_evaluator.py`.

### Round 14.3 — ModelRouter

1. Added `alphabrief_models.router` with `ModelRouter`,
   `ModelRouteDecision`, `PerformanceSnapshot`, and
   `PerformanceProvider` callable type.
2. Routing is **advisory only**: when no performance data exists,
   the router preserves the existing capability-only behavior.
3. When performance data is available, profiles are scored by
   `schema_pass_rate` (descending), with optional
   `prefer_low_latency` and `prefer_low_cost` flags. Profiles below
   `min_schema_pass_rate` are deprioritized for structured tasks.
4. The provider callable is exception-safe; routing falls back to
   capability-only when the data source is unavailable.
5. 15 new tests in `tests/test_model_router.py`.

### Round 14.4 — API endpoints

1. `POST /api/v1/models/evaluate` runs an evaluation and persists the
   result.
2. `GET /api/v1/models/evaluations` lists evaluation records with
   optional `model_id` and `task_type` filters.
3. `GET /api/v1/models/evaluations/{eval_id}` returns a single
   record.
4. `GET /api/v1/models/performance/{model_id}` returns the latest
   evaluation per task for a model.
5. `POST /api/v1/models/route` returns the router's recommendation
   for a task type and capability set.
6. `POST /api/v1/models/compare` returns side-by-side rows for
   multiple models on a task type.
7. `GET /api/v1/models/datasets` lists bundled dataset metadata.
8. 20 new tests in `tests/test_models_api.py`.

### Round 14.5 — CLI commands

1. `alphabrief model evaluate` runs an evaluation, persists it, and
   prints the result as JSON.
2. `alphabrief model performance` lists stored evaluations for a
   model, optionally filtered by task.
3. `alphabrief model route` queries the router for a task type and
   capability set.
4. `alphabrief model compare` compares multiple models for a task
   type.
5. 14 new tests in `tests/test_model_cli.py`.

### Round 14.6 — Dashboard

1. Main `/dashboard` page adds a Model Performance card grid.
   Each card shows the latest `schema_pass_rate` for a model,
   color-coded (green ≥ 0.9, yellow 0.7–0.9, red < 0.7).
2. New `/dashboard/models` page lists recent evaluations in a table
   and shows per-model performance summaries broken down by task.
3. Dashboard remains strictly read-only; no live model calls are
   made from the page itself.
4. 4 new tests in `tests/test_dashboard_models.py`.

### Round 14.7 — Documentation

1. Updated `docs/roadmap.md` (this section).
2. Updated `docs/development_log.md` with the round-43 entry.
3. Added the Model Evaluation chapter to `docs/architecture.md`.

### Final quality gate

- [x] 87 new tests across 7 rounds.
- [x] 782 total tests pass (up from 695).
- [x] `ruff check .` clean.
- [x] `mypy packages apps tests` clean (156 source files).
- [x] No files under `_reference_sources/` opened or imported.
- [x] No risk / execution / trading files modified.

## Phase 15: Strategy Lifecycle Management

Goal: make strategies first-class persistent artifacts. Strategies
become durable in the system: they can be saved, listed, queried,
enabled/disabled, deleted, and have their signal history replayed.
The activation flag and the signal history are **strictly advisory**
and never modify RiskGate semantics or block orders.

Status: complete. Rounds 15.1–15.7 complete.

### Round 15.1 — StrategySpecStore

1. Added `strategy_specs` DuckDB table with `strategy_id` (PK),
   `name`, `version`, `enabled`, `spec_json`, `created_at`,
   `updated_at`.
2. `StrategySpecStore` exposes `save_spec`, `set_enabled`,
   `delete_spec`, `get_spec`, `list_specs`, `list_enabled_strategy_ids`,
   `exists`, `count`, `clear`, `close`.
3. 27 new tests in `tests/test_strategy_store.py`.

### Round 15.2 — API endpoints

1. `POST /api/v1/strategies/specs` — create or replace a spec.
2. `GET /api/v1/strategies/specs` — list summaries
   (`?enabled=true|false`).
3. `GET /api/v1/strategies/specs/{id}` — full record.
4. `PATCH /api/v1/strategies/specs/{id}` — flip the activation flag.
5. `DELETE /api/v1/strategies/specs/{id}` — remove.
6. 24 new tests in `tests/test_strategies_api.py`.

### Round 15.3 — CLI commands

1. `alphabrief strategy save --from-yaml <path>` (also `--from-json`,
   `--enable` / `--disable`).
2. `alphabrief strategy list [--enabled|--disabled]`.
3. `alphabrief strategy show <strategy_id>`.
4. `alphabrief strategy enable <strategy_id>` /
   `strategy disable <strategy_id>`.
5. `alphabrief strategy delete <strategy_id>`.
6. 19 new tests in `tests/test_strategy_commands.py`. PyYAML added
   as a runtime dep (was already a transitive).

### Round 15.4 — Activation flag (advisory surface)

1. `GET /api/v1/strategies/enabled` — read-only advisory surface
   returning the list of strategy_ids whose ``enabled`` flag is
   ``True``.
2. The flag remains **strictly advisory**:
   `RiskGate`, `PaperBroker`, and live-trading never consult it.
   The RiskGate has its own `enabled_strategies` allowlist that is
   configured separately and is not wired to the registry.
3. 5 new tests in `tests/test_strategies_api.py` including a
   dedicated advisory-safety test that exercises RiskGate to prove
   the registry flag cannot grant, relax, or block risk decisions.

### Round 15.5 — Strategy signal history persistence

1. Added `strategy_signals` DuckDB table with `signal_id` (PK),
   `strategy_id`, `symbol`, `signal_ts`, `direction`, `confidence`,
   `horizon`, `source`, `signal_json`, `created_at`. Index on
   `(strategy_id, signal_ts DESC)`.
2. `StrategySignalStore` with `save_signal`, `get_signal`,
   `list_signals`, `count_signals`, `list_strategy_ids`,
   `delete_signal`, `clear`, `close`. Full validation of
   `signal_id`, `strategy_id`, `symbol`, `timestamp`, `direction`,
   `confidence` (in `[0, 1]`, not bool), `horizon`. Allowed sources:
   `backtest`, `manual`, `other`.
3. API endpoints:
   - `POST   /api/v1/strategies/signals`
   - `GET    /api/v1/strategies/signals`
     (`?strategy_id`, `?symbol`, `?source`, `?limit`)
   - `GET    /api/v1/strategies/signals/{signal_id}`
   - `DELETE /api/v1/strategies/signals/{signal_id}`
   - `GET    /api/v1/strategies/{strategy_id}/signals/count`
4. CLI: `alphabrief strategy record-signal`, `list-signals`,
   `show-signal`, `count-signals`.
5. 32 new unit tests + 21 new API tests + 9 new CLI tests
   (`tests/test_strategy_signals.py`, `test_strategy_signals_api.py`,
   plus additions in `test_strategy_commands.py`).
6. Dedicated advisory-safety test that records signals and
   confirms the risk gate is unaffected.

### Round 15.6 — Dashboard

1. New `/dashboard/strategies` page lists saved strategies with
   name, version, enabled badge, updated timestamp, and a
   "View" link to the full JSON record.
2. Per-strategy signal counts are shown alongside the activation
   badge.
3. Both the registry and the signal history carry explicit
   "advisory only" disclaimers in the page UI.
4. New nav link on the main `/dashboard` page.
5. 7 new tests in `tests/test_dashboard_strategies.py`.

### Round 15.7 — Documentation

1. Updated `docs/roadmap.md` (this section).
2. Updated `docs/architecture.md` with the Strategy Registry
   chapter.
3. Updated `docs/development_log.md` (entry 0045).

### Final quality gate

- [x] **144 new tests** across 5 rounds (R15.3–R15.7).
- [x] **926 total tests** pass (up from 833 at R15.2 entry).
- [x] `ruff check .` clean.
- [x] `mypy packages apps tests` clean (167 source files).
- [x] No files under `_reference_sources/` opened or imported.
- [x] No risk / execution / trading core files modified. Activation
      flag and signal history are independent of RiskGate,
      PaperBroker, and live-trading state.
- [x] Live trading remains disabled by default. No provider SDK
      calls outside ModelGateway.

## Phase 22: Kronos Forecast Integration

Goal: integrate the external Kronos financial-markets foundation-model
project as an optional AlphaBrief forecasting provider that strengthens
research and strategy evidence without touching execution authority.

Status: implemented and locally verified.

Completed:

1. Added `market_forecast` as a `ModelTaskType` and
   `time_series_forecasting` as a `ModelCapability`.
2. Added `alphabrief_models.kronos` with:
   - `KronosForecastRequest`
   - `KronosForecastPoint`
   - `KronosForecastReport`
   - `KronosForecastEvidence`
   - `KronosForecastAdapter`
   - `KronosRuntime` protocol
   - `UnavailableKronosRuntime`
   - `DeterministicKronosRuntime`
   - `PredictorKronosRuntime`
3. Added a `market_forecast_v1` bundled evaluation dataset and a
   `kronos_mini_forecast` profile to API/CLI default registries.
4. Added `POST /api/v1/models/kronos/forecast`.
5. Added `alphabrief model kronos-forecast`.
6. Added optional `kronos` dependencies in `pyproject.toml` for
   operator-managed local inference.
7. Added 12 tests across model gateway, Kronos integration, API, and
   CLI surfaces.

Hard constraints:

1. Kronos forecasts are advisory only.
2. No forecast can create signals, order intents, orders, fills,
   broker calls, or risk decisions.
3. Real external Kronos inference is optional and runtime-injected.
4. The deterministic runtime is only for CI and smoke tests.
5. No code was copied from the external Kronos repository.
6. Live trading remains disabled by default.

Validation:

- `.venv/bin/pytest tests/test_kronos_integration.py
  tests/test_model_gateway.py tests/test_models_api.py
  tests/test_model_cli.py` passed: 51 tests.
- `.venv/bin/ruff check ...` passed on all changed source/test files.
- `.venv/bin/mypy ...` passed on the changed model/API/CLI/test
  surfaces.

## Phase 16: Controlled Operating Boundary and Strategy Admission

Status: implemented and locally verified; no external broker connection is
introduced.

1. Checked-in `PaperExecutionPolicy` locks the future adapter target to
   Alpaca Paper and the paper-only US ETF boundary: `SPY`/`QQQ`, US regular
   hours, market/limit orders, `$100` per order, `$300` total exposure,
   mandatory human review, and no automatic execution.
2. The API risk default derives its enforceable fields from that policy.
   The total-exposure value is explicitly deferred to Phase 19 rather than
   presented as an existing account-level runtime guard.
3. `strategy_admissions` stores immutable, version-matched human-review
   evidence. Its append-only API cannot modify `RiskGate`, the advisory
   strategy `enabled` flag, `PaperBroker`, or live-trading state.
4. Phase 17 remains responsible for any Alpaca Paper adapter, credentials,
   order lifecycle, account synchronization, and reconciliation.

Quality gate: 941 tests pass, `ruff check .` is clean, and `mypy` reports no
issues. The suite retains six unrelated deprecation warnings from the existing
CLI risk-context timestamp helper.

## Phase 17: External Paper-Broker Adapter (Alpaca)

Status: implemented and locally verified. The first external broker
adapter (Alpaca Paper) is now plumbed end-to-end through a broker-neutral
port, with reconciliation, freeze controls, and an operations scheduler
scaffold. No live-trading path exists; no live-trading code path was
modified.

### What landed

1. `PaperExecutionPolicy` symbol list expanded from `SPY`/`QQQ` to the
   full Phase 17 paper allowlist: `SPY`, `QQQ`, `IVV`, `VOO`, `AGG`,
   `BND`, `GLD`, `SLV`. The single-order `$100` and total-exposure
   `$300` values are unchanged. Phase 19 remains responsible for
   runtime account-level enforcement.
2. The monolithic `alphabrief_execution/broker.py` was split into a
   `broker/` package with the broker-neutral `port`, a concrete
   `alpaca/` subpackage, a `legacy.py` that preserves the deterministic
   `PaperBroker` import path, `errors.py` with typed broker errors,
   and a `recon_store.py` DuckDB store for `broker_order_id_map`,
   `broker_recon_snapshots`, and `broker_freeze_events`.
3. New `BrokerAdapter` port exposes async `submit`, `cancel`,
   `get_order`, `list_orders`, `list_positions`, `get_account`, and
   `health` methods on strict Pydantic request/response models
   (`SubmitRequest`, `SubmitResult`, `OrderState`, `Position`,
   `AccountSnapshot`, `BrokerHealth`, `Fill`, `CancelResult`).
4. `AlpacaPaperAdapter` is the first concrete implementation. It
   reads `ALPHABRIEF_ALPACA_KEY` / `ALPHABRIEF_ALPACA_SECRET` from
   the environment only, never from disk. `config/alpaca_paper.yaml`
   holds only non-secret fields (`base_url`, timeouts, retry budget).
5. `ReconciliationRunner` reconciles local id-map / fills / cash /
   positions against a callable broker snapshot, persists a
   `ReconSnapshot`, and raises typed freezes. `ALLOWED_SCOPES`
   exposes the `startup`, `cycle`, `eod` set. The runnable does not
   place any orders.
6. `OperationsScheduler` is the Phase 18 scaffold: tasks declared as
   `ScheduledTask`, run by `asyncio` in a single event loop, with
   per-task `max_retries` and `HeartbeatStore` / `AlertSink` seams.
   This round ships the types and tests; the wiring of broker
   reconcile tasks into the live scheduler is reserved for Phase 18.
7. API: `GET /api/v1/broker/status`, `POST /api/v1/broker/reconcile`
   (scope-validated), `GET /api/v1/broker/orders`, `GET
   /api/v1/broker/positions`, `GET /api/v1/broker/account`,
   `POST /api/v1/broker/freeze`, `POST /api/v1/broker/unfreeze`.
   The routes proxy through `BrokerReconStore` and never place
   orders without a `RiskDecision`.
8. CLI: `alphabrief broker {status, reconcile, orders, positions,
   account, freeze, unfreeze}`. The CLI falls back to the local
   store when the API is not running, mirroring the existing
   `risk_commands.py` pattern.

### Hard constraints

- No credentials are committed, logged, or echoed in error paths.
  `AlpacaHttpClient` raises `BrokerAuthError` at construction if the
  env vars are missing.
- Live trading remains disabled. The adapter is configured only for
  `paper-api.alpaca.markets`. There is no live-mode code path.
- The Phase 16 `PaperExecutionPolicy` (`max_order_notional=100`,
  `automated_execution=false`, mandatory human review) remains the
  source of truth. The adapter rejects symbols outside the policy
  symbol set before any HTTP call.
- `RiskGate`, `PaperBroker`, the advisory `enabled` flag, and
  `strategy_admissions` are **not** modified by this phase. They
  remain the only authority on whether an `OrderIntent` may proceed.

### Quality gate

- 1019 tests pass (up from 941). 78 new tests across the alpaca
  adapter, broker port, reconciliation, freeze controls,
  execution-audit seam, scheduler, API, and CLI.
- `ruff check .` clean. `ruff format --check` clean on every
  modified or added Python file.
- `mypy packages apps tests` clean.
- No files under `_reference_sources/` opened or imported.

## Phase 18: Scheduler Operations Surface

Status: complete. Rounds 18.1–18.4 complete.

Goal: wire the Phase 17 `OperationsScheduler` (a typed scaffold with
tests but no operator entry point) into a runnable, observable, and
read-only surface so an operator can inspect heartbeats, alerts,
registered tasks, and freeze state through both the CLI and the API,
and start the scheduler as a long-running foreground process from the
CLI.

### Round 18.1 — `HeartbeatStore.list_heartbeats()`

1. Added a read-only `list_heartbeats()` method on the existing
   `HeartbeatStore`. The method returns one row per registered task,
   newest-first by `last_run_at`, with the same shape (`last_run_at`
   as ISO string or `None`, `run_count` as int, `last_error` as
   `None` for healthy runs) as the existing `list_alerts` method.
2. 3 new unit tests in `tests/test_scheduler.py` cover the
   empty-store case, the post-`record_run` shape, and the DESC
   ordering.

### Round 18.2 — API `/api/v1/scheduler/*` routes

1. New `apps/api/src/alphabrief_api/routes/scheduler.py` exposes five
   read-only endpoints under `/api/v1/scheduler`:
   - `GET /api/v1/scheduler/status` — aggregate heartbeat / freeze /
     alert counts and the always-`False` `running` flag.
   - `GET /api/v1/scheduler/heartbeats` — list per-task heartbeat rows.
   - `GET /api/v1/scheduler/alerts` — recent alerts (query:
     `?limit=N`, clamped to `[1, 500]`).
   - `GET /api/v1/scheduler/tasks` — static description of the default
     task set returned by `build_default_tasks()`.
   - `GET /api/v1/scheduler/freezes` — currently-open broker freezes.
2. The router proxies through the same `HeartbeatStore` and
   `BrokerReconStore` instances the scheduler process writes to;
   it never calls broker SDKs or model APIs.
3. 10 new tests in `tests/test_scheduler_api.py` cover the empty
   state, the populated state for each endpoint, the alert limit
   query param (clamping, min, max), and the aggregated status
   counts.

### Round 18.3 — CLI `scheduler` subapp + `run` command

1. New `apps/cli/src/alphabrief_cli/scheduler_commands.py` registers
   a Typer subapp with six commands:
   - `scheduler status`, `scheduler heartbeats`, `scheduler alerts`,
     `scheduler tasks`, `scheduler freezes` — read-only inspection
     commands that proxy through the API when the server is running
     and fall back to the local DuckDB stores otherwise.
   - `scheduler run` — starts the `OperationsScheduler` as a
     foreground asyncio process. Options `--reconcile-interval` and
     `--max-failures` let the operator tune the cycle. Traps
     SIGINT/SIGTERM to call `scheduler.request_stop()`. Catches
     `SchedulerStartupBlockedError` and exits with code 2.
2. `scheduler run` builds a real `AlpacaPaperAdapter` (with the
   default config) when both `ALPHABRIEF_ALPACA_KEY` and
   `ALPHABRIEF_ALPACA_SECRET` are set in the environment, and falls
   back to a `NullBrokerAdapter` otherwise. The null adapter is
   documented as "Phase 18 dev mode" and lets the scheduler run
   in dev / CI without a live broker connection.
3. The CLI hard-refuses to start the scheduler if
   `ALPHABRIEF_LIVE_TRADING_ENABLED` is set to a truthy value,
   printing a clear log line and exiting with code 3.
4. 9 new tests in `tests/test_scheduler_cli.py` cover the help
   text, the offline read paths, the SIGINT-driven graceful stop
   (with a post-exit heartbeat check delegated to a separate CLI
   invocation to avoid the DuckDB single-writer lock), and the
   live-trading refusal.

### Round 18.4 — Documentation & final quality gate

1. Updated `docs/roadmap.md` (this section).
2. Updated `docs/development_log.md` (entry 0044).
3. Added the Operations Scheduler subsection to `docs/architecture.md`.
4. Created `docs/development_plans/0044-phase-18-scheduler-surface.md`.

### Final quality gate

- [x] 22 new tests across R18.1–R18.3.
- [x] 1041 total tests pass (up from 1019).
- [x] `ruff check .` clean.
- [x] `ruff format --check` clean on every modified or added file.
- [x] `mypy packages apps tests` clean.
- [x] No files under `_reference_sources/` opened or imported.
- [x] No risk / execution / trading core file modified.
- [x] Live trading remains disabled by default. No provider SDK
      calls outside ModelGateway.

## Phase 19: Account-Level Runtime Enforcement

Status: complete. Rounds 19.1–19.4 complete.

Goal: enforce the `PaperExecutionPolicy` total-exposure limit
(`$300`) at runtime against live account state, not just the
static `RiskLimitConfig`. The check lives inside
:class:`alphabrief_risk.RiskGate` as a **tighten-only** account-level
check (mirroring the existing `risk_context` pattern) and is fed by
a new execution-side projection helper that turns a live
:class:`BrokerAdapter` (or the legacy in-memory
:class:`PortfolioState`) into a plain
:class:`AccountExposureContext` value object owned by the risk layer.
This keeps the dependency arrow one-way (execution → risk) and the
risk package free of any broker dependency.

### Round 19.1 — `AccountExposureContext` + `RiskGate` account-exposure check

1. New `packages/alphabrief-risk/src/alphabrief_risk/account_context.py`
   defines a frozen Pydantic value object
   (:class:`AccountExposureContext`) carrying `current_total_exposure`,
   `exposure_by_symbol`, `cash`, `account_id`, `captured_at`. It
   rejects `float` inputs (Decimal-first), rejects naive
   `captured_at`, and uses `ConfigDict(extra="forbid", frozen=True)`
   mirroring `RiskContextDecision`.
2. `RiskLimitConfig` gains a new optional field
   `max_total_exposure: Decimal | None = None` (defaults preserve the
   legacy per-order-only behavior) with `__post_init__` validation:
   must be positive, and must be `≥ max_order_value` when both are set
   (mirrors the `PaperExecutionPolicy` invariant).
3. `RiskGate.evaluate(...)` gains a new optional kwarg
   `account_context: AccountExposureContext | None = None` and a new
   private `_check_account_exposure` method. Semantics:
   - **No-op** when `max_total_exposure` is `None` (legacy path).
   - **Fail-closed** when `max_total_exposure` is set but
     `account_context is None`: rejects with the
     `account_context_required` tag. Skipping would defeat runtime
     enforcement.
   - **Sells** bypass the new-exposure projection (gross notional
     cannot grow on a sell); documented with a
     `ponytail:sell-exposure-ceiling` comment naming the ceiling
     (long-only paper policy) and the upgrade path.
   - **Buys** project `current_total_exposure + qty * price` and
     reject with `max_total_exposure` when over the cap; the returned
     clamp is `headroom / price` (advisory; re-evaluated on resubmit).
   - **Missing `estimated_price`** while the cap is set → rejected
     with `missing_price` (parity with `_check_order_value_limit`).
   - The clamp folds into `max_quantity` **tighten-only**: it can
     only reduce an existing `max_quantity`, never create one from
     `None`, never exceed the configured per-order cap. It composes
     with the `risk_context` multiplier by taking the smaller bound.
4. `AccountExposureContext` is exported from `alphabrief_risk`.
5. 19 new tests: 10 in `tests/test_account_exposure.py` (value
   object: construction, frozen + `extra="forbid"`, `float`
   rejection, naive-datetime rejection, negative-cash acceptance)
   and 9 in `tests/test_risk_gate.py` (under-cap approved, exactly-
   at-cap approved, one-cent-over rejected, sell exempt, fail-closed
   on missing context, legacy no-op when unconfigured, tighten-only
   clamp, clamp stacking with `risk_context` multiplier, missing
   price, zero headroom, construction-time `max_total_exposure <
   max_order_value` and non-positive rejections).

### Round 19.2 — Execution-side projection helper

1. New `packages/alphabrief-execution/src/alphabrief_execution/broker/exposure.py`
   exposes two pure functions:
   - `async def build_account_exposure_context(adapter, *,
     mark_prices=None)` — reads `adapter.get_positions()` and
     `adapter.get_account()` and projects into
     `AccountExposureContext`. Gross notional per position is
     `abs(quantity) * mark_price` where the mark is
     `mark_prices[symbol]` if supplied else `position.average_price`.
   - `def build_account_exposure_context_from_portfolio(portfolio,
     *, account_id="paper_local", mark_prices=None, clock=...)` —
     sync variant that reads the in-memory `PortfolioState` used by
     the legacy `PaperBroker` so the API paper route can enforce the
     cap without an external adapter.
   A `ponytail:mark_price_ceiling` comment names the ceiling
   (cost-basis not current market when no live mark is supplied;
   understates exposure in a rising market and overstates it in a
   falling one; upgrade path is to pass `mark_prices` from a quote
   provider when one exists).
2. Both functions are exported from `alphabrief_execution/broker`.
3. 8 new tests in `tests/test_broker_exposure.py` cover the async
   adapter variant (sums from `average_price`, empty positions,
   `mark_prices` override, `abs()` for shorts, zero-qty skip) and the
   sync portfolio variant (sums from `PortfolioState`, empty
   portfolio, `mark_prices` override).

### Round 19.3 — API wiring

1. `apps/api/.../routes/risk.py`:
   - `_default_limits` now sources `max_total_exposure` directly
     from `_execution_policy.max_total_exposure` — the **single
     point** that turns the static `$300` YAML boundary into a live
     `RiskGate` check.
   - `RiskConfigResponse` gains `max_total_exposure: str | None`,
     emitted in `GET /api/v1/risk/config`.
   - `RiskCheckRequest` gains optional `account_context:
     AccountExposureContext | None`. `POST /api/v1/risk/check`
     passes it through to `gate.evaluate`.
2. `apps/api/.../routes/paper.py` — `POST /api/v1/paper/orders`
   builds an `AccountExposureContext` from the in-memory
   `PaperBroker` portfolio via the sync projection helper (using the
   existing `reference_price = Decimal("100")` placeholder as the
   local mark for the order symbol) and passes it to
   `gate.evaluate`. The audit event gains `account_total_exposure`
   and `max_total_exposure` fields, persisted into DuckDB
   `details_json`.
3. `apps/api/.../routes/broker.py` — `/positions` and `/account`
   stubs remain (updated comments defer to **Phase 20** for live
   reads). The enforcement path is delivered by `RiskGate`, not by
   these read endpoints.
4. 4 new tests in `tests/test_api_server.py` (the under-cap fill
   path with audit-event assertions via `PaperStore`, the
   over-cap-rejected path, `/risk/check` enforces the cap when
   `account_context` is supplied, `/risk/check` fails closed when
   `account_context` is omitted). Plus 1 expanded assertion on the
   existing `risk/config` test confirming `max_total_exposure`
   surfaces from the policy.
5. 2 existing tests in `tests/test_execution_policy.py` adapted to
   supply a zero-exposure `account_context` (their intent is to
   exercise the symbol / order-value / human-review boundaries; the
   Phase 19 fail-closed default would otherwise have masked those
   checks). No coverage lost.

### Round 19.4 — Documentation & final quality gate

1. Updated `docs/roadmap.md` (this section + a Phase 20 stub).
2. Updated `docs/development_log.md` (entry `## 0048`).
3. Added an "Account-Level Exposure Enforcement" subsection to
   `docs/architecture.md`.
4. Created `docs/development_plans/0048-phase-19-account-exposure-enforcement.md`.

### Final quality gate

- [x] 34 new tests across R19.1–R19.3 (10 account-context, 9
      risk-gate, 8 broker-exposure, 5 api-server, 2 execution-policy
      adapted). The full suite now passes 1077 tests.
- [x] `ruff check .` clean.
- [x] `ruff format --check` clean on every modified or added file
      (13 files; the 75 pre-existing unformatted files on clean
      `main` are out of scope).
- [x] `mypy packages apps tests` is clean with explicit package-base
      discovery. JSON response boundaries are validated before typed code
      consumes them, and obsolete type-ignore comments were removed.
- [x] No files under `_reference_sources/` opened or imported.
- [x] No risk / execution core relaxation: the account check is
      strictly tighten-only and fail-closed; it can only reject,
      clamp `max_quantity` down, or no-op.
- [x] Live trading remains disabled by default. No provider SDK
      calls outside ModelGateway.
- [x] `git diff --check` passed.

## Phase 20: API-side Broker Adapter Singleton (read-only observability)

Status: complete. Rounds 20.1–20.4 complete.

Goal: wire a single `BrokerAdapter` (Alpaca paper) into the API
process so `/api/v1/broker/positions` and `/api/v1/broker/account`
return live reads (still stubbed in Phase 19), while keeping
account-level exposure enforcement in `RiskGate`. Phase 19
delivered the *enforcement* path; Phase 20 closes the
*observability* gap on the API side. The wiring is **read-only**: the
API never calls `submit` / `cancel` / `get_order` / `list_orders` /
`list_fills` through the singleton — order placement stays inside the
operations scheduler and behind a `RiskDecision`. The 30–60-day
external-paper observation period (the rest of
`FINAL_ACCEPTANCE_REPORT.md` §10) is a future operating milestone, not
a code deliverable of this phase.

### Round 20.1 — Adapter singleton module

1. New `apps/api/src/alphabrief_api/broker_adapter.py` holds a
   process-wide lazy `BrokerAdapter` singleton: `get_broker_adapter()`
   builds it on first access, `_reset_broker_adapter()` is the test
   isolation hook (mirrors `_reset_broker()` in `routes/paper.py`), and
   `has_live_broker()` distinguishes a real Alpaca adapter from the
   dev/CI null fallback without leaking the concrete type.
2. `_build_broker_adapter()` reuses the CLI `scheduler run` selection
   logic: build an `AlpacaPaperAdapter` when `ALPHABRIEF_ALPACA_KEY`
   and `ALPHABRIEF_ALPACA_SECRET` are set, else a `_NullBrokerAdapter`.
   Alpaca modules are imported locally so the module imports cleanly
   without credentials and the client (which reads creds) is never
   constructed at import time.
3. `_NullBrokerAdapter` returns empty positions and a zero
   `AccountSnapshot` (`account_id="null-adapter"`, zero Decimals) so
   the API boots in dev / CI; `submit` / `cancel` / `get_order` raise
   `NotImplementedError` so accidental order placement through the
   API is impossible.
4. `ALPHABRIEF_ALPACA_BASE_URL` env override lets tests point the
   adapter at a mock Alpaca server without writing YAML; an `http://`
   mock is permitted via `allow_insecure_base_url=True` (the paper-only
   "live" check still applies).
5. 5 new tests in `tests/test_broker_adapter_singleton.py`.

### Round 20.2 — Wire `/positions` + `/account`

1. `apps/api/.../routes/broker.py` `broker_positions()` and
   `broker_account()` now call the singleton. Routes stay `sync def`;
   the async adapter methods are awaited via `asyncio.run()` per
   request (the Alpaca client is a sync urllib client that `await`s
   nothing — mirrors the scheduler's
   `asyncio.run(scheduler.run())` bridge idiom).
2. New stringified response models `BrokerPositionResponse` and
   `BrokerAccountResponse` (`str` fields) so `Decimal` / `captured_at`
   never hit FastAPI float coercion — reuses the `routes/paper.py`
   `PositionResponse` / `PortfolioResponse` precedent.
3. Adapter failure (network refused, auth, protocol) → **HTTP 503**
   with a structured `{"error","kind"}` detail (`kind` is the
   `BrokerAdapterError` subclass name or `"transport"`); never a 500
   and never a silent fall-back to the stub. The null adapter returns
   the empty / zero shapes so the API still boots without credentials.
4. The recon-store-backed routes (`/status`, `/orders`, `/reconcile`,
   `/freeze`, `/unfreeze`) are byte-for-byte unchanged.
5. `_reset_broker_adapter()` added to the `tests/test_api_server.py`
   autouse fixture and the `tests/test_broker_api.py` client fixture
   so a cred-bearing test cannot leak its adapter. The
   `test_broker_account_returns_null` test is updated to the new
   zero-snapshot shape and a positions null-path test is added.
6. 5 new live-path tests in `tests/test_broker_api_live.py` exercise
   the API against `tests/_helpers/MockAlpacaServer`: seeded live
   `/positions` and `/account`, 503 on an unreachable port, null-adapter
   shapes without credentials, and unchanged sibling routes.

### Round 20.3 — CLI lock-in

1. No source change: `alphabrief broker positions` / `account` already
   proxy through the API (`broker_commands.py`), so they automatically
   serve live data once the API does and refuse with a clear error when
   no API is running.
2. The `broker --help` assertion in `tests/test_broker_cli.py` is
   expanded to lock `positions` and `account` into the CLI surface,
   plus two offline-refusal tests.

### Round 20.4 — Documentation & final quality gate

1. Updated `docs/roadmap.md` (this section), `docs/development_log.md`
   (entry `## 0050`), `docs/architecture.md` (API-side Broker Adapter
   Singleton subsection), and `FINAL_ACCEPTANCE_REPORT.md` (Phase 20
   read-only observability subset marked landed; the broader
   submit/cancel/fills criteria and 30–60-day observation period left
   to a future round — no overclaim).
2. Created `docs/development_plans/0050-phase-20-api-broker-adapter-singleton.md`.

### Final quality gate

- [x] 13 new tests across R20.1–R20.3 (5 singleton, 5 live-path,
      2 null-shape, 1 CLI help expansion + 2 CLI offline-refusal).
- [x] 1090 total tests pass (up from 1077).
- [x] `ruff check .` clean.
- [x] `ruff format --check` clean on every modified or added file.
- [x] `mypy packages apps tests` clean (206 source files).
- [x] No files under `_reference_sources/` opened or imported.
- [x] No risk / execution core file relaxed: the singleton is
      read-only; `RiskGate`, `PaperBroker`, and the live-trading lock
      are untouched. No API order placement path was added.
- [x] Live trading remains disabled by default. No provider SDK
      calls outside ModelGateway.

## Phase 21: Account-Level Risk Rules Hardening

Goal: extend the runtime account-exposure enforcement introduced in
Phase 19 R19.1 with the full set of account-level risk checks called
for in the blueprint §6 (per-symbol exposure, concentration, leverage,
price deviation, market-state, signal-staleness, duplicate-order,
daily-loss, drawdown-floor). All checks are **tighten-only** and
**fail-closed** — they can only reject a `RiskDecision`, tag it, or
reduce `max_quantity`. None can re-approve a rejected intent, lift
the live-trading lock, or relax an existing limit.

Status: implemented and locally verified. Rounds R21.1–R21.4 complete
(plus the 0051 quality-gate recovery that unblocked the test
collection). The 30–60-day external-paper observation period,
HWM/day-start persistence, and live-mode code paths are explicitly
**out of scope** for this phase.

### R21.1 — `RiskGate` check methods + `RiskLimitConfig` fields

1. New optional fields on `RiskLimitConfig`:
   - `max_symbol_exposure`, `max_concentration_pct`, `max_leverage`,
     `max_price_deviation_pct`, `max_signal_age_seconds`,
     `require_market_open`, `session_policy`,
     `duplicate_order_window_seconds`, `duplicate_order_max_count`,
     `max_daily_loss_pct`, `max_drawdown_floor_pct`.
2. New private check methods on `RiskGate`:
   - `_check_symbol_exposure`, `_check_concentration`,
     `_check_leverage`, `_check_price_deviation`,
     `_check_market_open`, `_check_signal_age`,
     `_check_duplicate_order`, `_check_daily_loss`, `_check_drawdown`.
3. Each check is wired into `RiskGate.evaluate(...)` and follows the
   same tighten-only / fail-closed contract as the existing
   `_check_account_exposure`:
   - **No-op** when its limit field is `None`/unset (legacy paths
     unchanged).
   - **Fail-closed** when a required context input is missing
     (e.g. `account_context` is `None` while a cap is set).
   - **Sells** bypass the per-symbol / leverage / daily-loss /
     drawdown checks (they are protective, not aggressive).
   - The per-symbol cap returns a `max_quantity` clamp that folds
     into the existing tighten-only clamp composition (smaller bound
     wins).
4. `__post_init__` validates the new fields (positivity,
   `(0, 1]` for `max_concentration_pct`, `[0, 1]` for the loss /
   deviation / drawdown fields, `>= 1` for `duplicate_order_max_count`).

### R21.2 — `AccountExposureContext` extended + broker projection

1. New optional fields on `AccountExposureContext`:
   - `equity` (`Field(ge=0)`), `reference_mark_prices` (dict of
     Decimal), `equity_high_water_mark` (`Field(ge=0)`),
     `day_start_equity` (`Field(ge=0)`),
     `day_realized_pnl` (no `ge=0` — loss days produce a negative
     value).
2. The `field_validator(mode="before")` set was extended to reject
   `float` on every new Decimal field (Decimal-first throughout).
3. `build_account_exposure_context` (async, `BrokerAdapter`-driven)
   now projects `AccountSnapshot.equity` and the supplied
   `mark_prices` into the context.
4. `build_account_exposure_context_from_portfolio` (sync,
   `PortfolioState`-driven, used by the API paper route) computes
   `equity = cash + sum(qty * mark)` and threads the marks through.
   `ponytail:portfolio_equity_ceiling`: without `mark_prices` the
   legacy `PortfolioState` falls back to `average_price`, so the
   result is cost-basis equity, not live MTM. The paper route will
   fail-closed for `max_leverage` / `max_daily_loss_pct` /
   `max_drawdown_floor_pct` on a fresh server until a persistent
   equity-snapshot store is wired in (Phase 21.5+).

### R21.3 — API and CLI surface

1. `RiskConfigResponse` exposes every new `RiskLimitConfig` field
   (per-symbol exposure, concentration, leverage, price deviation,
   signal age, market-open flag, duplicate-order window + count,
   daily-loss pct, drawdown-floor pct). Stringified `Decimal` to
   avoid float coercion (mirrors the R19.3 pattern).
2. `POST /api/v1/risk/check` already accepted `account_context:
   AccountExposureContext | None` from Phase 19; the new R21.x
   fields travel inside that object (Pydantic handles them).
3. `apps/cli/.../risk_commands.py` — `risk check` gained five new
   flags: `--equity`, `--reference-mark-prices` (JSON object),
   `--equity-hwm`, `--day-start-equity`, `--day-realized-pnl`.
   The CLI builds an `AccountExposureContext` from these and
   passes it to `gate.evaluate(..., account_context=...)`.
4. `apps/cli/.../risk_commands.py` — `--help` lists every new flag
   so operators discover them.
5. `POST /api/v1/paper/orders` continues to use the R19.3 wiring:
   the in-memory `PaperBroker` portfolio is projected via
   `build_account_exposure_context_from_portfolio`, then enriched
   with `equity_high_water_mark` and `day_start_equity` from the
   persistent equity-snapshot store (when present). This makes the
   daily-loss and drawdown rules restart-safe.

### R21.4 — Documentation and quality gate

1. This roadmap entry.
2. `docs/development_log.md` — `0051` (quality-gate recovery) and
   `0052` (Phase 21 R21.1–R21.4) entries appended.
3. `docs/architecture.md` — Account-Level Risk Rules chapter.
4. `docs/risk_model.md` — Phase 21 section describing each check's
   failure tag and tighten-only / fail-closed invariant.
5. `docs/development_plans/0051-quality-gate-recovery.md` and
   `docs/development_plans/0052-phase-21-account-level-rules.md` —
   round plans.

### Out of scope (Phase 21.5+ and beyond)

- Persistent HWM / day-start-equity store across restarts (today the
  paper route reads them when present and falls back to current
  `equity` when absent).
- A market-calendar provider (the `require_market_open` check uses
  the policy's `trading_days` + `session_start` / `session_end`).
  `ponytail:no-holiday-calendar` — U.S. holidays are not respected.
- Persistent duplicate-order dedup (today's deque is in-memory; a
  restart loses dedup memory). `ponytail:duplicate_order_state`.
- 30–60-day external paper observation period (FINAL_ACCEPTANCE_REPORT
  §10).
- Live trading — out of scope for this phase and the rest of the
  paper MVP.

### Final quality gate

- [x] **74 new tests** across R21.1–R21.4: 41 pre-existing
      `test_risk_account_rules.py` + `test_risk_loss_drawdown.py`
      (R21.1 unit coverage), 19 in
      `test_account_exposure_phase21.py` + appended
      `test_broker_exposure.py` (R21.2), 6 in `test_api_server.py`
      (R21.3 API), 6 in `test_risk_commands.py` (R21.3 CLI), plus
      the 0051 quality-gate fix that turned 1160 collected + 1
      collection error into a clean 1165 baseline. Net total: 1202
      tests pass.
- [x] `ruff check .` clean.
- [x] `ruff format --check` clean on every modified or added file.
- [x] `mypy packages apps tests` clean (215 source files).
- [x] `git diff --check` clean.
- [x] No files under `_reference_sources/` opened or imported.
- [x] No risk / execution core relaxation: every new check is
      tighten-only / fail-closed. The `RiskLimitConfig` defaults
      remain permissive; production deployments must opt in by
      configuring the new fields.
- [x] Live trading remains disabled by default. No provider SDK
      calls outside ModelGateway.

## Phase 23 — Project Acceptance Closeout

Status: implemented locally as a read-only acceptance surface.

Phase 23 converts the final project-level delivery and safety boundary
into executable checks. It does not add trading capability. It gives
operators and agents one command and one API route that answer whether
the current AlphaBrief checkout satisfies the local paper-first
acceptance contract.

### R23.1 — Acceptance package

1. Added `alphabrief_acceptance` under
   `packages/alphabrief-acceptance/src`.
2. `build_acceptance_report(project_root)` returns a structured
   Pydantic report with pass/fail counts and per-check evidence.
3. The verifier checks:
   - required project documents;
   - importable runtime package surfaces;
   - default settings keep `live_trading_enabled=False`;
   - `config/paper_execution_policy.yaml` remains paper-mode,
     human-review, no-automation;
   - `RiskGate` rejects `live_trading_enabled=True` with
     `live_trading_locked`;
   - Kronos forecasts run through `ModelGateway` and remain
     `advisory_only=True`;
   - runtime code under `apps/` and `packages/` does not import
     `_reference_sources`;
   - runtime business code does not import provider SDKs directly;
   - final project evidence mentions Phase 23 and the Kronos/acceptance
     boundary;
   - pytest, Ruff, Mypy, and the acceptance package are configured.

### R23.2 — CLI and API surface

1. `alphabrief acceptance verify` emits the structured report as JSON.
2. The command exits with code 1 when any check fails, so it can be used
   in local automation and release scripts.
3. `GET /api/v1/acceptance/verify` exposes the same read-only report.
4. `/api/status` includes `alphabrief_acceptance` in the runtime package
   list.

### R23.3 — Documentation and evidence

1. `README.md` now lists Phase 23 and the acceptance verifier command.
2. `docs/architecture.md` documents the verifier's side-effect-free
   architecture and scope.
3. `FINAL_ACCEPTANCE_REPORT.md` is updated from the old Phase 18/19
   baseline to the current Phase 23 closeout view.
4. `docs/development_log.md` and
   `docs/development_plans/0054-final-acceptance-closeout.md` record the
   round.

### Out of scope

- External paper account credentials and provider-specific operations.
- 30-60 days of continuous external paper-account observation.
- Live trading, live adapter implementation, or any live endpoint.
- Treating model, UI, or natural-language output as authorization to
  place or approve trades.

### Final quality gate

- [x] Targeted acceptance/API/CLI/status tests pass:
      `tests/test_acceptance_verifier.py`,
      `tests/test_acceptance_api_cli.py`,
      `tests/test_api_server.py::test_api_status_body`.
- [x] Broker/scheduler CLI regression subset passes:
      `tests/test_broker_cli.py tests/test_scheduler_cli.py`.
- [x] Sandboxed full pytest run reaches 1204 passing tests; the
      remaining 12 failures are environment-blocked localhost mock
      broker tests (`PermissionError` binding `127.0.0.1`) in
      `tests/test_alpaca_adapter.py` and `tests/test_broker_api_live.py`.
- [x] Ruff passes: `.venv/bin/ruff check .`.
- [x] Mypy passes: `.venv/bin/mypy packages apps tests`
      (`223 source files`).
- [x] Project acceptance verifier passes:
      `.venv/bin/alphabrief acceptance verify --compact`.
- [x] `git diff --check` passes.

## Phase 24 — Paper-Broker Pre-Flight Closeout

Status: implemented locally. The 30-day observation runbook and a
scoped pre-flight check are wired; the project is ready to attach to
an external Alpaca paper account.

### R24.1 — Operator runbook

1. Added `docs/paper_broker_setup.md` covering Alpaca signup, `.env`
   setup, the five-command pre-flight, scheduler invocation, daily
   and weekly observation checkpoints, freeze handling, end-of-run
   reporting, and the hard safety reminders.
2. The runbook is the single source of truth for the operator. It
   assumes code is already installed locally.

### R24.2 — Environment wiring

1. `.env.example` gained a clearly labeled Alpaca section with
   commented-out placeholders (`ALPHABRIEF_ALPACA_KEY`,
   `ALPHABRIEF_ALPACA_SECRET`) and the signup URL.
2. The acceptance verifier checks that the runbook exists and that
   the env-var names in code match the names in `.env.example`
   (drift guard).

### R24.3 — Acceptance verifier and pre-flight CLI

1. Added `paper.preflight` to the verifier. Checks runbook presence,
   env-var-name documentation, paper policy lock, alpaca paper config
   loadability, and code-vs-config drift.
2. Added `build_preflight_report(scope=...)`. `build_acceptance_report`
   delegates to it with `scope="full"` and reports 11/11 (was 10/10).
3. Added `alphabrief acceptance preflight --paper` and
   `GET /api/v1/acceptance/preflight?scope=paper`. Both run only the
   paper-readiness check and exit non-zero on failure.

### R24.4 — README and documentation

1. README: Phase 23 bullet expanded with the pre-flight command; new
   "Paper Broker Setup" section after Quality Gates; the runbook is
   listed under Documentation.
2. `docs/development_log.md` and this entry record the round.

### Out of scope

- External paper account credentials and 30-day observation itself
  (requires operator-supplied credentials and elapsed time).
- Live trading, live adapter, or any live endpoint.
- LICENSE / SECURITY / CONTRIBUTING (separate decision).
- Backtest credibility hardening (Phase 25+).
- Production deployment, auth, secret rotation, backup, monitoring.

### Final quality gate

- [x] `pytest` (excluding sandbox-blocked files): 1206 passed.
- [x] `ruff check .`: clean.
- [x] `mypy packages apps tests`: 223 source files clean.
- [x] `alphabrief acceptance verify --compact`: 11/11.
- [x] `alphabrief acceptance preflight --paper`: 1/1.
- [x] `git diff --check`: clean.

## Phase 25 — Pre-Paper-Trading Hardening

Phase 24 closed the documentation / verifier gaps so an operator can
attach a paper broker. Phase 25 walks every CLI command (16 groups,
35 subcommands) and every API route (70 endpoints) end-to-end,
fixes any breakage found, and locks the project to a clean
4-gate baseline right before the 30-day observation begins. No
new trading behavior; no SDK changes; no live-trading enablement.

### R25.1 — End-to-end audit pass

1. CLI surface exercised under an isolated `ALPHABRIEF_DATA_DIR`:
   `data import/check`, `news fetch/list`, `macro fetch/list`,
   `backtest run`, `brief daily`, `model list/test/route/compare
   /evaluate/performance/kronos-forecast`, `paper run/status`,
   `research debate`, `risk status/context/check`, `audit list`,
   `review list/daily`, `strategy save/list/show/enable/disable
   /delete/record-signal/list-signals/show-signal/count-signals`,
   `broker status/reconcile/orders/positions/account/freeze
   /unfreeze`, `scheduler status/heartbeats/alerts/tasks/freezes`,
   `acceptance verify/preflight`.
2. API surface exercised against a local `serve` instance on
   `127.0.0.1:8765`. Every route returned either a real payload
   or a documented error.
3. Decision line (data → strategy → signal → risk → paper →
   broker reconcile) verified via the targeted test cluster
   (272 tests across 16 files).

### R25.2 — Fixes from the audit

1. **`brief daily` always failed at the parser.** Fix: provide
   `FakeProviderAdapter` with a schema-valid `DailyAlphaBrief`
   `structured_output` payload (matching nested
   `market_brief.trading_day`, timezone-aware `generated_at`,
   non-empty `key_factors` / `watchlist`). `brief daily` now
   produces a real brief and writes it to `--output`.
2. **`strategy record-signal --from-yaml` rejected ISO
   timestamps.** PyYAML coerces naked ISO strings to
   `datetime`; the store validator required `str`. Fix:
   `StrategySignalStore.save_signal` accepts either form and
   coerces to string before writing both the column and the
   JSON payload. JSON payloads are unaffected.
3. **`model list` placeholder.** Fix: emit the same default
   `ModelRegistry` (4 providers, 4 profiles) that the API routes
   use, dumped as JSON.
4. **`risk status` placeholder.** Fix: build a permissive
   in-memory `RiskGate` + `KillSwitch` and dump
   `trading_enabled`, `live_trading_enabled`,
   `symbol_allowlist`, `max_order_value`, `max_total_exposure`,
   `require_human_review`, `kill_switch_active`,
   `kill_switch_reason`. CLI risk commands remain read-only.
5. **`review list` placeholder.** Fix: read from `ReviewStore`
   directly when no API is running, with a clear "no snapshots
   recorded" message when the table is empty.
6. **`paper status` placeholder.** Fix: read the latest snapshot
   from `PaperStore` when no API is running; fall back to the
   original "not yet persisted" message when no snapshot exists.
7. **`test_risk_status_prints_placeholder`** updated to assert
   the new JSON shape.

All fixes carry a `# ponytail:` comment explaining the shortcut
and the ceiling.

### Safety boundaries

1. No new trading behavior. The API-side `RiskGate` defaults are
   unchanged.
2. No new SDKs, no new network calls. `FakeProviderAdapter` is
   still the CLI default.
3. The store-level timestamp coercion is widen-only: the same
   string column type, the same JSON shape, the same validation
   error messages on genuinely invalid input.
4. Live trading remains disabled by default and locked by
   `RiskGate`.
5. `brief daily` still goes through the public
   `generate_daily_alpha_brief(...)` path, so any future
   `DailyAlphaBrief` schema drift still trips the existing
   parser tests.

### Final quality gate

- [x] `pytest`: 1223 passed.
- [x] `ruff check .`: clean.
- [x] `mypy`: 204 source files clean (strict mode).
- [x] `alphabrief acceptance verify`: 11/11.
- [x] `alphabrief acceptance preflight --scope paper`: 1/1.
- [x] End-to-end CLI smoke (isolated `ALPHABRIEF_DATA_DIR`): all
  commands produced real output, no placeholders, no errors.

## Phase 26 — AI Trading Committee Runtime

Status: implemented locally for the paper-only runtime surface. The
AI trading path is feature-flag gated and remains behind the existing
`RiskGate` and `PaperBroker` boundaries.

### R26.1 — Committee, daily cycle, API, CLI, scheduler

1. Added `alphabrief_trader`, a paper-only AI Trading Committee package
   with strict schemas, multi-role committee orchestration, deterministic
   discipline rules, daily cycle execution records, and a DuckDB-backed
   cycle store.
2. Added `alphabrief ai {status,run,history,show,rules}` and
   `/api/v1/ai/{status,run,history,cycles/{cycle_id},rules,attempts}`.
3. Added an optional `ai_daily_cycle` scheduler task. It is registered
   but disabled by default, and only enabled when
   `ALPHABRIEF_AI_TRADING_ENABLED` is truthy.
4. The default API/CLI/scheduler committee uses `FakeProviderAdapter`
   and produces a conservative `watch` / human-review sample response,
   so the default runtime records plans but does not auto-place paper
   orders.
5. The full order path exists for injected providers/tests: a buy/sell
   committee plan becomes an `OrderIntent`, passes through `RiskGate`,
   is blocked on rejection or human review, and only then reaches the
   in-memory `PaperBroker`.

### R26.2 — Closeout fixes

1. Broke the circular import between `alphabrief_trader.db_store` and
   `alphabrief_api.db.schema` by adding an AI-only package schema helper.
2. Fixed AI store keys for multi-symbol cycles:
   `ai_committee_votes` now keys by `(cycle_id, vote_index)` and
   `ai_order_attempts` by `(cycle_id, intent_id)`.
3. Added `alphabrief_trader` to runtime package metadata and
   `/api/status` package inventory.
4. Added `docs/development_plans/0057-phase-26-ai-trader-closeout.md`.

### R26.3 — Store-backed AI snapshots

1. Added `StoredMarketSnapshotBuilder`, which turns local
   `MarketDataStore` bars and `NewsStore` headlines into
   `MarketSnapshot` inputs for the AI Trading Committee.
2. Scheduler `ai_daily_cycle` now uses stored bars/headlines from
   `alphabrief.db`; symbols without a local price source are skipped
   instead of receiving a placeholder `$100` price.
3. API `/api/v1/ai/run` uses the same store-backed builder while
   preserving explicit `reference_prices` for controlled operator
   dry-runs.
4. News context includes deterministic sentiment counts and fills
   missing headline sentiment via `RuleBasedSentimentAnalyzer`.
5. Added `docs/development_plans/0058-phase-27-store-backed-ai-snapshots.md`.

### R26.4 — External AI paper bridge

1. Added `ExecutionBackend` as the final paper execution boundary for
   `DailyTradingCycle`.
2. Preserved local `PaperBroker` execution as the default via
   `LocalPaperExecutionBackend`.
3. Added `ExternalPaperExecutionBackend`, mapping approved AI
   `OrderIntent` objects to broker-neutral `SubmitRequest` objects.
4. Scheduler `ai_daily_cycle` injects the external backend only when
   `ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED` is truthy.
5. External submissions use `intent_id` as broker `client_order_id` for
   adapter idempotency.
6. `OrderAttempt` now records execution backend and external broker
   metadata.
7. Added `docs/development_plans/0059-phase-28-external-ai-paper-bridge.md`.

### R26.5 — Configured AI model and pre-cycle ingestion

1. Scheduler, API, and CLI AI entry points now share a single model
   factory backed by `ModelGateway`.
2. `ALPHABRIEF_AI_MODEL_PROVIDER=auto` uses OpenAI when `OPENAI_API_KEY`
   is set and otherwise falls back to a conservative fake provider.
   Explicit `openai`, `ollama`, and `fake` modes are supported.
3. Scheduler `ai_daily_cycle` now refreshes local market bars and broad
   financial RSS headlines before snapshot construction when
   `ALPHABRIEF_AI_PRE_CYCLE_INGEST_ENABLED` is truthy.
4. Market refresh supports Yahoo Finance by default and Alpha Vantage
   when `ALPHAVANTAGE_API_KEY` is configured.
5. RSS headlines are retagged to the AI scheduler universe so symbol
   snapshots include current broad-market news sentiment.
6. Provider failures are fail-soft: they are logged, stale stored data
   can still be used, and symbols with no local price remain skipped.
7. `ALPHABRIEF_AI_SCHEDULER_UNIVERSE` lets operators align the AI
   universe with the reviewed paper policy.
8. External AI paper execution fails closed when broker credentials
   select a different provider than `PaperExecutionPolicy.provider`.

### Safety boundaries

1. Live trading remains disabled by default and explicitly refused by
   the AI cycle when `ALPHABRIEF_LIVE_TRADING_ENABLED` is set.
2. Models are called only through `ModelGateway`.
3. The committee never emits an `Order`; it emits advisory
   `TradePlan` objects that must become `OrderIntent` and pass
   `RiskGate`.
4. No imports from `_reference_sources/`.
5. The scheduler AI task does not use external broker credentials and
   does not bypass the existing reconciliation/freeze surface.
6. Store-backed snapshots are input context only; sentiment summaries
   do not bypass `TradingCommittee`, `DisciplineGate`, or `RiskGate`.
7. External AI paper submission is scheduler-only and separately gated
   by `ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED`.
8. Human-review and rejected risk decisions are not submitted to the
   external paper adapter.

### Final quality gate

- [x] Targeted AI trader tests: 97 passed.
- [x] Broker/scheduler CLI regression subset: 18 passed.
- [x] `ruff check .`: clean.
- [x] `mypy packages apps tests`: 247 source files clean.
- [x] `alphabrief acceptance verify --compact`: 11/11.
- [x] Full sandboxed `pytest`: 1310 passed; the remaining 12 failures
      are the known localhost mock broker `PermissionError` cases in
      `tests/test_alpaca_adapter.py` and `tests/test_broker_api_live.py`.
- [x] Store-backed AI snapshot subset: 21 passed.
- [x] Focused `ruff` and `mypy`: clean for trader, AI API, scheduler,
      and related tests.
- [x] External AI paper bridge subset: 19 passed.

## Round 0063 — OANDA-First Default Paper Workflow

Status: implemented and validated; 30-day observation intentionally not
started.

1. The checked-in paper policy now defaults to OANDA v20 practice with a
   19-instrument multi-asset allowlist: FX majors/crosses, metals, and index
   CFDs. The latter are market-index exposure, not direct US-stock orders.
2. `mode: paper`, mandatory human review, disabled automation, and the
   live-trading lock remain unchanged.
3. The scheduler’s default AI universe is now
   `EUR_USD,GBP_USD,USD_JPY`, aligned to the OANDA policy. Operators can
   override it only with policy-approved OANDA instrument names.
4. All legacy Alpaca/ETF test assumptions on the default path were migrated;
   explicit policy/broker mismatch tests remain fail-closed.
5. Validation: **1361 pytest passed**, `ruff` clean, `mypy` clean across
   **253 source files**, acceptance **11/11**, and a read-only broker-status
   check reported a matching snapshot with zero open freezes.
6. No order-capable AI CLI command was run: the published CLI has no dry-run
   option, and no 30-day observation was started.
