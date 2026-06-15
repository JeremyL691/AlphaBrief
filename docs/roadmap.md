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
