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

## Phase 19: Account-Level Runtime Enforcement (planned)

Status: planned. Building on Phase 18's runnable scheduler.

Goal: enforce the `PaperExecutionPolicy` total-exposure limit
(`$300`) at runtime by querying the live broker account snapshot,
not just the static `RiskLimitConfig`. Already referenced in the
Phase 16/17 docs as Phase 19 work.

