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
