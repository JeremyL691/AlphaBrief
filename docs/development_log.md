# AlphaBrief Development Log

This log records completed development rounds.

## 0001 Repo Scaffold

Status: completed.

Goal: create the initial repository scaffold, project rules, documentation
shells, reference source isolation, and minimal scaffold tests.

Completed changes:

1. Renamed `Source projects/` to `_reference_sources/`.
2. Added project rules, agent instructions, README, documentation shells, and
   development plan records.
3. Added empty implementation directories with `.gitkeep` files.
4. Added minimal `pyproject.toml` configuration.
5. Added scaffold tests for required files, directories, reference-source
   isolation, and default live-trading lock.

Validation:

1. `python3 -m pytest tests/test_project_scaffold.py` passed.
2. `ruff check .` could not run because `ruff` is not installed locally.

## 0002 Core Domain Models MVP

Status: completed.

Goal: implement the minimal core domain schemas needed by future AlphaBrief
modules.

Completed changes:

1. Added `alphabrief_core` package under `packages/alphabrief-core/src`.
2. Added Pydantic models for `Bar`, `Signal`, `OrderIntent`, `RiskDecision`,
   and `Order`.
3. Added validation for timezone-aware datetimes, Decimal financial fields,
   confidence range, OHLCV consistency, order-intent sizing, limit price rules,
   and required `risk_decision_id` on orders.
4. Updated `pyproject.toml` with the Pydantic dependency, package discovery,
   pytest pythonpath, and mypy file scope.
5. Added domain model tests and architecture documentation.

Validation:

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py`
   passed.
2. `ruff check .` could not run because `ruff` is not installed locally.
3. `python3 -m mypy packages/alphabrief-core/src tests` could not run because
   `mypy` is not installed locally.

## 0003 Core Configuration System MVP

Status: completed.

Goal: implement the minimal configuration entry point for AlphaBrief core
modules.

Completed changes:

1. Added `alphabrief_core.config` with `AlphaBriefEnv`, `LogLevel`,
   `AppSettings`, and `load_settings`.
2. Added explicit `ALPHABRIEF_` environment variable mapping for environment,
   log level, live-trading lock state, and local paths.
3. Kept live trading disabled by default and did not add secret fields.
4. Updated `.env.example` with non-secret local path defaults.
5. Added configuration tests and architecture documentation.

Validation:

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py`
   passed.
2. `ruff check .` could not run because `ruff` is not installed locally.
3. `python3 -m mypy packages/alphabrief-core/src tests` could not run because
   `mypy` is not installed locally.

## 0004 CSV OHLCV Market Data Loader MVP

Status: completed.

Goal: implement the first local market data loader for single-symbol CSV OHLCV
files.

Completed changes:

1. Added `alphabrief_data` package under `packages/alphabrief-data/src`.
2. Added `CsvBarLoader`, `load_ohlcv_csv`, and `MarketDataLoadError`.
3. Implemented standard-library CSV parsing into `alphabrief_core.Bar` objects.
4. Added Decimal parsing, timezone handling, required-column checks, row-level
   error wrapping, and reuse of `Bar` validation.
5. Updated `pyproject.toml` for `alphabrief-data` package discovery,
   pytest pythonpath, and mypy scope.
6. Added CSV loader tests and architecture documentation.

Validation:

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py`
   passed.
2. `ruff check .` could not run because `ruff` is not installed locally.
3. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src tests`
   could not run because `mypy` is not installed locally.

## 0005 Market Data Quality Checks MVP

Status: completed.

Goal: implement basic in-memory quality checks for `Bar` sequences.

Completed changes:

1. Added `alphabrief_data.quality` with `DataQualityIssue`,
   `DataQualityReport`, and `check_bar_quality`.
2. Added checks for empty datasets, mixed symbols, mixed sources, mixed data
   versions, duplicate timestamps, non-increasing timestamps, missing expected
   intervals, and zero-volume bars.
3. Exported the quality API from `alphabrief_data`.
4. Added quality tests, including explicit CSV loader output integration.
5. Updated architecture documentation and development plan records.

Validation:

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py tests/test_market_data_quality.py`
   passed.
2. `ruff check .` could not run because `ruff` is not installed locally.
3. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src tests`
   could not run because `mypy` is not installed locally.

## 0006 Basic No-Lookahead Feature Generation MVP

Status: completed.

Goal: implement minimal trailing feature generation for `Bar` sequences without
future data leakage.

Completed changes:

1. Added `alphabrief_data.features` with `FeatureRow`,
   `FeatureGenerationError`, and `generate_basic_features`.
2. Added trailing returns, close SMA, and volume SMA using `Decimal` values.
3. Blocked feature generation on failed data quality reports while allowing
   warning-only reports.
4. Exported the feature API from `alphabrief_data`.
5. Added tests for insufficient history, no-lookahead behavior, divide-by-zero
   returns, quality failures, parameter validation, and CSV loader integration.
6. Updated architecture documentation and development plan records.

Validation:

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py tests/test_market_data_quality.py tests/test_feature_generation.py`
   passed.
2. `ruff check .` could not run because `ruff` is not installed locally.
3. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src tests`
   could not run because `mypy` is not installed locally.

## 0007 StrategySpec Schema MVP

Status: completed.

Goal: implement a validated StrategySpec schema for future strategy interfaces
and backtests.

Completed changes:

1. Added `alphabrief_strategy` package under
   `packages/alphabrief-strategy/src`.
2. Added `StrategySpec`, `StrategyUniverse`, `StrategyRule`, `StrategyRisk`,
   `StrategyCosts`, `StrategyEvaluation`, and `EvaluationPeriod`.
3. Added validation for identity strings, stable symbol de-duplication,
   condition text, risk limits, cost values, and train/test period separation.
4. Updated `pyproject.toml` for `alphabrief-strategy` package discovery,
   pytest pythonpath, and mypy scope.
5. Added StrategySpec tests and documentation.

Validation:

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py tests/test_market_data_quality.py tests/test_feature_generation.py tests/test_strategy_spec_schema.py`
   passed.
2. `ruff check .` could not run because `ruff` is not installed locally.
3. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src tests`
   could not run because `mypy` is not installed locally.

## 0008 Simple Strategy Interface MVP

Status: completed.

Goal: define the first strategy execution contract without implementing
strategy logic, backtesting, or order generation.

Completed changes:

1. Added `alphabrief_strategy.interface` with `StrategyInput`,
   `StrategyOutput`, `StrategyProtocol`, `StrategyExecutionError`, and
   `run_strategy`.
2. Added input validation for non-empty bars, feature length, and bar data
   quality.
3. Added output validation for signal strategy ID, universe membership, and
   input bar timestamps.
4. Exported the interface API from `alphabrief_strategy`.
5. Added Strategy Interface tests and documentation.

Validation:

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py tests/test_market_data_quality.py tests/test_feature_generation.py tests/test_strategy_spec_schema.py tests/test_strategy_interface.py`
   passed.
2. `ruff check .` could not run because `ruff` is not installed locally.
3. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src tests`
   could not run because `mypy` is not installed locally.

## 0009 Vectorized Backtester and Metrics MVP

Status: completed.

Goal: complete the first Phase 1 research loop from imported OHLCV data through
a moving-average strategy and JSON backtest report.

Completed changes:

1. Added `alphabrief_backtest` with `VectorizedBacktester`,
   `BacktestReport`, `BacktestMetrics`, `BacktestTrade`, `EquityPoint`, and
   `write_backtest_report`.
2. Added `MovingAverageTrendStrategy` as the first built-in long/flat strategy.
3. Simulated long/flat trades using strategy risk allocation, fees, and
   slippage.
4. Added total return, max drawdown, trade count, and win rate.
5. Updated `pyproject.toml` for `alphabrief-backtest`.
6. Added backtest tests and documentation.

Validation:

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py tests/test_market_data_quality.py tests/test_feature_generation.py tests/test_strategy_spec_schema.py tests/test_strategy_interface.py tests/test_vectorized_backtester.py`
   passed.
2. `ruff check .` could not run because `ruff` is not installed locally.
3. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src tests`
   could not run because `mypy` is not installed locally.

## 0010 Parquet Market Data Loader MVP

Status: completed.

Goal: complete the Phase 1 local market data loader boundary by adding Parquet
OHLCV loading alongside CSV.

Completed changes:

1. Added `alphabrief_data.parquet_loader` with `ParquetBarLoader` and
   `load_ohlcv_parquet`.
2. Reused `Bar` validation and `MarketDataLoadError` for row-level Parquet
   loading failures.
3. Supported ISO timestamp strings and `datetime` objects with explicit
   timezone handling.
4. Rejected float values in numeric fields to preserve Decimal-first data
   handling.
5. Exported the Parquet loader API from `alphabrief_data`.
6. Added Parquet loader tests and architecture documentation.

Validation:

1. `python3 -m pytest tests/test_parquet_market_data_loader.py`
   passed.
2. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py tests/test_parquet_market_data_loader.py tests/test_market_data_quality.py tests/test_feature_generation.py tests/test_strategy_spec_schema.py tests/test_strategy_interface.py tests/test_vectorized_backtester.py`
   passed.
3. `ruff check .` could not run because `ruff` is not installed locally.
4. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src tests`
    could not run because `mypy` is not installed locally.

## 0011 ModelGateway Contract and FakeProvider MVP

Status: completed.

Goal: start Phase 2 by implementing the smallest model-call boundary and fake
provider for tests.

Completed changes:

1. Added `alphabrief_models` package under `packages/alphabrief-models/src`.
2. Added `ModelRequest`, `ModelResponse`, `ModelCallRecord`, and
   `ModelGatewayResult` schemas.
3. Added `ProviderAdapter` protocol and `ModelGateway` capability-based
   provider selection.
4. Added `FakeProviderAdapter` with deterministic success and failure modes.
5. Recorded each gateway invocation with hashes and metadata instead of raw
   prompt or raw model output.
6. Updated `pyproject.toml`, ModelGateway documentation, architecture notes, and
   development plan records.

Validation:

1. `python3 -m pytest tests/test_model_gateway.py` passed.
2. `python3 -m pytest` passed.
3. `.venv/bin/ruff check packages/alphabrief-models/src tests/test_model_gateway.py`
   passed.
4. `.venv/bin/mypy packages/alphabrief-models/src tests/test_model_gateway.py`
   passed.
5. `.venv/bin/ruff check .` failed on existing `_reference_sources/` and prior
   Phase 1 files outside this round's scope.
6. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests`
   failed on existing Phase 1 type issues outside this round's scope.

## 0012 Quality Gates and Tooling Cleanup

Status: completed.

Goal: fix project-owned lint and type-check issues before the next feature
development round.

Completed changes:

1. Configured Ruff to exclude `_reference_sources/`.
2. Ran Ruff auto-fixes on AlphaBrief-owned packages and tests.
3. Fixed remaining Ruff issues in project-owned code.
4. Fixed strict mypy issues in existing packages and tests.
5. Updated invalid-input tests to use Pydantic `model_validate` where needed so
   runtime validation remains covered while static typing passes.
6. Added explicit timezone offset assertions in loader tests.
7. Added the maintenance development plan record.

Validation:

1. `python3 -m pytest` passed.
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests`
   passed.

## 0013 Model Registry and Provider Config MVP

Status: completed.

Goal: add the minimal provider and model profile configuration boundary for
Phase 2 model selection.

Completed changes:

1. Added `alphabrief_models.registry`.
2. Added `ProviderConfig`, `ModelProfile`, and `ModelRegistry`.
3. Added capability-based profile lookup and deterministic priority selection.
4. Excluded disabled providers and disabled model profiles from selection.
5. Kept config secret-safe by storing env var names only and not reading
   environment values.
6. Exported registry types from `alphabrief_models`.
7. Added registry tests and documentation.

Validation:

1. `python3 -m pytest tests/test_model_registry.py` passed.
2. `python3 -m pytest` passed.
3. `.venv/bin/ruff check .` passed.
4. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests`
   passed.

## 0014 Repository Polish and Private GitHub Push

Status: completed.

Goal: prepare the repository for private GitHub hosting with clear English
README, safe ignore rules, and passing quality gates.

Completed changes:

1. Rewrote `README.md` for GitHub readability.
2. Documented MVP status, safety boundaries, local setup, quality gates,
   reference-source policy, and private availability.
3. Added `_reference_sources/` and generated JSON reports to `.gitignore`.
4. Updated scaffold tests so local reference-source checkouts are optional and
   ignored by default.
5. Added this development plan record.

Validation:

1. `python3 -m pytest` passed.
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests`
   passed.

## 0015 Structured Output Parser MVP

Status: completed.

Goal: add the minimal structured output validation boundary for Phase 2 so
future research modules can rely on Pydantic-validated model outputs.

Completed changes:

1. Added `alphabrief_models.structured_output`.
2. Added `StructuredOutputErrorCode` (StrEnum) with stable error code values.
3. Added `StructuredOutputResult[TargetModel]` to carry either a parsed
   Pydantic target or a structured failure without raising.
4. Added `parse_structured_output(response, target)` for Pydantic target
   models.
5. Prefers `ModelResponse.structured_output` when available; falls back to
   JSON-decoded `output_text` on request.
6. Rejects empty output, invalid JSON, non-mapping JSON, and schema
   mismatches with explicit error codes.
7. Exported parser, result, and error code from `alphabrief_models`.
8. Updated model_gateway docs, architecture, roadmap, development plan
   record, and README.

Validation for 0015:

1. `python3 -m pytest tests/test_structured_output.py` passed.
2. `python3 -m pytest` passed (117 tests).
3. `.venv/bin/ruff check .` passed.
4. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests`
   passed.

## 0016 MarketBrief and SymbolBrief Schemas MVP

Status: completed.

Goal: add the minimal research brief schemas for Phase 2 so future research
layer work can produce and validate structured market and symbol briefs
without defining its own Pydantic types.

Completed changes:

1. Added `alphabrief_models.briefs`.
2. Added `MarketBrief` with required identity, timezone-aware `generated_at`,
   `trading_day`, `regime`, `summary`, `confidence`, and `key_factors`.
3. Added `SymbolVerdict` with `direction`, `confidence`, and `rationale`.
4. Added `SymbolBrief` with `brief_id`, `symbol`, `generated_at`, `horizon`,
   `verdict`, `catalysts`, and `risks`.
5. Added typed literal aliases `MarketRegime`, `SymbolDirection`,
   `BriefHorizon`.
6. Exported all brief schemas and literal aliases from `alphabrief_models`.
7. Added brief schema tests including integration with
   `parse_structured_output`.
8. Updated model gateway docs, architecture, roadmap, development plan
   record, and README.

Validation for 0016:

1. `python3 -m pytest tests/test_brief_schemas.py` passed.
2. `python3 -m pytest` passed (134 tests).
3. `.venv/bin/ruff check .` passed.
4. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests`
   passed.

## 0017 DailyAlphaBrief Schema and Generator MVP

Status: completed.

Goal: add the minimal daily research brief generation boundary for Phase 2.

Completed changes:

1. Added `DailyAlphaBrief` to `alphabrief_models.briefs`.
2. Added `alphabrief_models.daily` with `DailyBriefGenerationErrorCode`,
   `DailyBriefGenerationResult`, and `generate_daily_alpha_brief`.
3. Routed generation through `ModelGateway` with `task_type="daily_brief"`.
4. Validated provider output via `parse_structured_output`.
5. Returned structured failures for provider rejection, provider failure, and
   invalid structured output.
6. Exported the DailyAlphaBrief public API.
7. Added daily brief generator tests and documentation.

Validation for 0017:

1. `python3 -m pytest tests/test_daily_alpha_brief.py` passed.
2. `python3 -m pytest` passed (145 tests).
3. `.venv/bin/ruff check .` passed.
4. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests`
   passed.

## 0018 Prompt Template Versioning MVP

Status: completed.

Goal: add a local versioned prompt template boundary for Phase 2 model
requests.

Completed changes:

1. Added `alphabrief_models.prompts`.
2. Added `PromptTemplate`, `RenderedPrompt`, `PromptTemplateRegistry`, and
   `PromptTemplateError`.
3. Rendered explicit `{{ variable }}` placeholders into `input_text`.
4. Produced stable prompt versions in `template_id:version` form.
5. Rejected missing, extra, blank, duplicate, and invalid variables.
6. Exported prompt template APIs from `alphabrief_models`.
7. Added prompt template tests and documentation.

Validation for 0018:

1. `python3 -m pytest tests/test_prompt_templates.py` passed.
2. `python3 -m pytest` passed (163 tests).
3. `.venv/bin/ruff check .` passed.
4. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests`
   passed.

## 0019 Ollama Provider Adapter MVP

Status: completed.

Goal: satisfy the Phase 2 real provider adapter requirement with a local
Ollama HTTP adapter.

Completed changes:

1. Added `alphabrief_models.adapters`.
2. Added `OllamaProviderAdapter` implementing the existing ProviderAdapter
   protocol.
3. Posted non-streaming generation requests to `/api/generate`.
4. Requested JSON format for structured-output calls.
5. Parsed Ollama responses into `ModelResponse`.
6. Wrapped HTTP, connection, JSON, and invalid response failures as
   `ModelProviderError`.
7. Exported the adapter from `alphabrief_models`.
8. Added Ollama adapter tests and documentation.

Validation for 0019:

1. `python3 -m pytest tests/test_ollama_provider_adapter.py` passed.
2. `python3 -m pytest` passed (163 tests).
3. `.venv/bin/ruff check .` passed.
4. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src tests`
   passed.

## 0020 Risk and Paper Trading MVP

Status: completed.

Goal: complete the Phase 3 safe paper-trading loop where every `OrderIntent`
must pass `RiskGate` before paper execution.

Completed changes:

1. Added `alphabrief_risk` with `RiskLimitConfig`, `RiskGate`, and
   `KillSwitch`.
2. Added `alphabrief_execution` with `OrderRouter`, `FillSimulator`,
   `PortfolioState`, `PaperBroker`, and `ExecutionAuditLog`.
3. Required matching approved `RiskDecision` objects before creating orders.
4. Simulated deterministic fills with fee and slippage support.
5. Updated paper portfolio cash, positions, and realized PnL from fills.
6. Recorded risk decisions, order rejections, orders, fills, and portfolio
   updates in an audit log.
7. Kept live trading unavailable.
8. Added Phase 3 tests and documentation.

Validation for 0020:

1. `python3 -m pytest tests/test_risk_gate.py tests/test_paper_execution.py`
   passed.
2. `python3 -m pytest` passed (177 tests).
3. `.venv/bin/ruff check .` passed.
4. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src packages/alphabrief-risk/src packages/alphabrief-execution/src tests`
   passed.

## 0021 Trading Environment MVP

Status: completed.

Goal: complete Phase 4 with a Gymnasium-style simulation environment for
strategy comparison.

Completed changes:

1. Added `alphabrief_gym`.
2. Added `AlphaBriefTradingEnv` with `reset()` and `step(action)`.
3. Added `TradingObservation`, `StepResult`, and `EpisodeMetrics`.
4. Added hold/buy/sell actions.
5. Computed rewards from portfolio value transitions without exposing future
   bars in observations.
6. Added transaction cost and slippage support.
7. Added seeded random policy evaluation.
8. Added buy-and-hold baseline evaluation.
9. Added `StrategyComparisonReport`.
10. Added Phase 4 tests and documentation.

Validation for 0021:

1. `python3 -m pytest tests/test_trading_env.py` passed.
2. `python3 -m pytest` passed (187 tests).
3. `.venv/bin/ruff check .` passed.
4. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src packages/alphabrief-risk/src packages/alphabrief-execution/src packages/alphabrief-gym/src tests`
   passed.

## 0022 Review Center MVP

Status: completed.

Goal: complete Phase 5 with a read-only Review Center for research, backtest,
paper trading, risk, audit, and journal review.

Completed changes:

1. Added `alphabrief_review`.
2. Added `ReviewCenterSnapshot` and summary schemas for strategies, backtests,
   daily briefs, model calls, paper portfolio, order audit log, risk dashboard,
   and review journal entries.
3. Added local JSON snapshot read/write helpers.
4. Added plain-text viewers for every Phase 5 surface.
5. Added daily and weekly review journal generation.
6. Added Phase 5 tests and documentation.

Validation for 0022:

1. `python3 -m pytest tests/test_review_center.py` passed.
2. `python3 -m pytest` passed (196 tests).
3. `.venv/bin/ruff check .` passed.
4. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src packages/alphabrief-risk/src packages/alphabrief-execution/src packages/alphabrief-gym/src packages/alphabrief-review/src tests`
   passed.

## 0023 CLI + OpenAI Provider Adapter MVP

Status: completed.

Goal: implement typer CLI entry point with 9 subcommands covering all 5 MVP
phases, plus an OpenAI cloud provider adapter.

Completed changes:

1. Added `apps/cli/` directory with `alphabrief_cli` typer CLI package (10
   files).
2. Added 8 CLI subcommand groups: data (import/check), backtest (run), brief
   (daily), model (test), paper (run/status), risk (check), audit (list), review
   (daily).
3. Configured pyproject.toml with typer dependency and [project.scripts] entry
   point.
4. Added `OpenAIProviderAdapter` to `alphabrief_models` using urllib (no SDK
   deps).
5. Added 3 OpenAI adapter tests + 8 paper command integration tests.
6. Added per-file-ignore for ruff B008 (typer.Option pattern) on CLI files.
7. Updated .env.example (no changes needed for MVP - API key read at runtime).

Validation for 0023:

1. `python3 -m pytest` passed (216 tests, up from 208).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src packages/alphabrief-backtest/src packages/alphabrief-models/src packages/alphabrief-risk/src packages/alphabrief-execution/src packages/alphabrief-gym/src packages/alphabrief-review/src tests`
   passed.
4. `alphabrief --help` shows all 8 subcommands.

## 0024 FastAPI Web API Surface Round 1

Status: completed.

Goal: implement the first FastAPI application scaffold with health, project
status, and data status endpoints, plus CLI integration through
`alphabrief serve`.

Completed changes:

1. Added `apps/api/src/alphabrief_api` with a FastAPI app factory and exported
   `app` object.
2. Added read-only health, project status, and data status route modules.
3. Added Pydantic response schemas for every API endpoint.
4. Added `alphabrief_cli.serve_commands` and registered the `serve` CLI group.
5. Added FastAPI and Uvicorn dependencies plus API source paths for pytest,
   setuptools package discovery, and mypy.
6. Added API endpoint tests and serve command registration tests.
7. Updated architecture documentation with the API Layer boundary.

Validation for 0024:

1. `python3 -m pytest tests/test_api_server.py tests/test_serve_command.py`
   passed.
2. `.venv/bin/ruff check apps/api/ apps/cli/src/alphabrief_cli/serve_commands.py apps/cli/src/alphabrief_cli/main.py tests/test_api_server.py tests/test_serve_command.py`
   passed.
3. `.venv/bin/mypy apps/api/src apps/cli/src/alphabrief_cli/main.py apps/cli/src/alphabrief_cli/serve_commands.py tests/test_api_server.py tests/test_serve_command.py`
   passed.
4. `python3 -m pytest` passed.
5. `.venv/bin/ruff check .` passed.

## 0025 FastAPI Web API Surface Round 2 — Market Data

Status: completed.

Goal: expose market data loading and querying through FastAPI v1 endpoints,
leveraging the existing `alphabrief_data` CSV and Parquet loaders.

Completed changes:

1. Added in-memory data store in `apps/api/src/alphabrief_api/routes/data.py`
   keyed by symbol with source and data-version metadata.
2. Added `POST /api/v1/data/load` — accepts file path, symbol, source,
   data_version, and file_type (csv/parquet); loads via existing
   `load_ohlcv_csv` / `load_ohlcv_parquet`; stores bars in memory.
3. Added `GET /api/v1/data/symbols` — lists all loaded symbols with bar count,
   source, and data version.
4. Added `GET /api/v1/data/{symbol}/bars` — returns OHLCV bars with
   `?limit=N&offset=N` pagination.
5. Added `GET /api/v1/data/{symbol}/info` — returns symbol metadata including
   time range and bar count.
6. Updated existing `/api/data/status` to `/api/v1/data/status` prefix to match
   the v1 API surface.
7. Added 16 new API endpoint tests covering CSV/Parquet load, symbols list,
   bars pagination, symbol info, and error cases.
8. Updated `docs/roadmap.md` Phase 6 progress and this development log.

Files changed:
- `apps/api/src/alphabrief_api/routes/data.py` — new endpoints + store
- `tests/test_api_server.py` — prefix update + 16 new tests
- `docs/roadmap.md` — progress marker
- `docs/development_log.md` — this entry

Validation for 0025:

1. `python3 -m pytest` passed (239 tests, up from 216+).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests/test_api_server.py` passed.

## 0026 FastAPI Web API Surface Round 3 — Backtest

Status: completed.

Goal: expose backtest functionality through FastAPI v1 endpoints.

Completed changes:

1. Added `apps/api/src/alphabrief_api/routes/backtest.py` with in-memory
   report store and 3 endpoints.
2. Added `POST /api/v1/backtest/run` — accepts strategy params + symbol,
   runs `VectorizedBacktester` with `MovingAverageTrendStrategy`, returns
   full report with metrics, trades, and equity curve.
3. Added `GET /api/v1/backtest/reports` — lists backtest report summaries.
4. Added `GET /api/v1/backtest/report/{id}` — retrieves single full report.
5. Registered backtest router in `main.py`.
6. Added 8 API endpoint tests covering successful run, custom params,
   missing symbol, insufficient bars, empty list, multiple reports,
   full report retrieval, and 404.

Files changed:
- `apps/api/src/alphabrief_api/routes/backtest.py` — new
- `apps/api/src/alphabrief_api/main.py` — register router
- `tests/test_api_server.py` — 8 new tests + store isolation
- `docs/roadmap.md` — progress marker
- `docs/development_log.md` — this entry

Validation for 0026:

1. `python3 -m pytest` passed (247 tests, up from 239).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests/test_api_server.py` passed.

## 0027 FastAPI Web API Surface Round 4 — Research Briefs

Status: completed.

Goal: expose DailyAlphaBrief generation through FastAPI v1 endpoints.

Completed changes:

1. Added `apps/api/src/alphabrief_api/routes/brief.py` with in-memory
   brief store and 3 endpoints.
2. Added `POST /api/v1/brief/generate` — calls `ModelGateway` with
   `FakeProviderAdapter` to generate and validate a `DailyAlphaBrief`.
3. Added `GET /api/v1/brief/history` — lists brief summaries.
4. Added `GET /api/v1/brief/{id}` — retrieves single full brief.
5. Registered brief router in `main.py`.
6. Added 6 API endpoint tests covering generation, defaults, empty history,
   multiple briefs, full brief retrieval, and 404.

Files changed:
- `apps/api/src/alphabrief_api/routes/brief.py` — new
- `apps/api/src/alphabrief_api/main.py` — register router
- `tests/test_api_server.py` — 6 new tests + store isolation
- `docs/roadmap.md` — progress marker
- `docs/development_log.md` — this entry

Validation for 0027:

1. `python3 -m pytest` passed (253 tests, up from 247).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests/test_api_server.py` passed.

## 0028 FastAPI Web API Surface Round 5 — Paper Portfolio & Risk

Status: completed.

Goal: expose paper trading portfolio and risk gate data through FastAPI
v1 endpoints.

Completed changes:

1. Added `apps/api/src/alphabrief_api/routes/paper.py` with module-level
   `PaperBroker` and `PortfolioState` defaulting to 100k cash.
2. Added `GET /api/v1/paper/portfolio` — returns cash, positions, realized PnL.
3. Added `GET /api/v1/paper/orders` — returns audit log entries with
   optional `?status=` filter.
4. Added `GET /api/v1/paper/audit` — returns complete execution audit log.
5. Added `apps/api/src/alphabrief_api/routes/risk.py` with module-level
   `RiskGate` and `RiskLimitConfig`.
6. Added `GET /api/v1/risk/config` — returns current risk limit configuration.
7. Added `GET /api/v1/risk/dashboard` — returns risk overview with kill
   switch state.
8. Registered paper and risk routers in `main.py`.
9. Added 7 API endpoint tests covering portfolio, positions, orders,
   status filter, audit, risk config, and risk dashboard.

Files changed:
- `apps/api/src/alphabrief_api/routes/paper.py` — new
- `apps/api/src/alphabrief_api/routes/risk.py` — new
- `apps/api/src/alphabrief_api/main.py` — register routers
- `tests/test_api_server.py` — 7 new tests + reset helpers
- `docs/roadmap.md` — progress marker
- `docs/development_log.md` — this entry

Validation for 0028:

1. `python3 -m pytest` passed (260 tests, up from 253).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests/test_api_server.py` passed.

## 0029 FastAPI Web API Surface Round 6 — Review Center

Status: completed.

Goal: expose review center snapshot and journal generation through FastAPI
v1 endpoints.

Completed changes:

1. Added `apps/api/src/alphabrief_api/routes/review.py` with a default
   `ReviewCenterSnapshot` containing sample strategies, backtests, briefs,
   model calls, portfolio, audit, and risk data.
2. Added `GET /api/v1/review/snapshot` — returns complete snapshot as JSON.
3. Added `GET /api/v1/review/journal` — lists journal entries from snapshot.
4. Added `GET /api/v1/review/journal/daily` — generates daily journal entry
   with optional `?trading_day=` query param.
5. Added `GET /api/v1/review/journal/weekly` — generates weekly journal entry
   with optional `?week_start=` query param.
6. Registered review router in `main.py`.
7. Added 7 API endpoint tests covering snapshot, journal list, daily/weekly
   generation, and invalid date error handling.

Files changed:
- `apps/api/src/alphabrief_api/routes/review.py` — new
- `apps/api/src/alphabrief_api/main.py` — register router
- `tests/test_api_server.py` — 7 new tests
- `docs/roadmap.md` — progress marker
- `docs/development_log.md` — this entry

Validation for 0029:

1. `python3 -m pytest` passed (266 tests, up from 260).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests/test_api_server.py` passed.

## 0030 FastAPI Web API Surface Round 7 — Dashboard

Status: completed.

Goal: implement a simple HTML web dashboard and finalize API documentation.

Completed changes:

1. Added `apps/api/src/alphabrief_api/routes/dashboard.py` with a
   self-contained HTML dashboard served at `/dashboard`.
2. Dashboard uses vanilla JavaScript `fetch()` to pull data from backend
   API endpoints and renders project status, data symbols count, last
   backtest, last brief, paper portfolio, and risk status cards.
3. FastAPI auto-generated `/docs` (Swagger) and `/redoc` (ReDoc) remain
   accessible without blocking.
4. Added per-file-ignore for E501 (line length) on the dashboard file
   since inline HTML cannot be practically broken.
5. Added 3 smoke tests verifying /dashboard returns 200 with expected
   HTML content, and /docs + /redoc are accessible.
6. Marked Phase 6 complete in `docs/roadmap.md`.

Files changed:
- `apps/api/src/alphabrief_api/routes/dashboard.py` — new
- `apps/api/src/alphabrief_api/main.py` — register router
- `pyproject.toml` — per-file-ignore E501 for dashboard
- `tests/test_api_server.py` — 3 new smoke tests
- `docs/roadmap.md` — Phase 6 complete
- `docs/development_log.md` — this entry

Validation for 0030:

1. `python3 -m pytest` passed (269 tests, up from 266).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests/test_api_server.py` passed.

## 0031 Phase 7 Round 1 — DuckDB Schema + Market Data Persistence

Status: completed.

Goal: add DuckDB persistent storage layer and migrate market data endpoints
from in-memory storage to DuckDB.

Completed changes:

1. Added `duckdb>=1.0` dependency to `pyproject.toml`.
2. Created `apps/api/src/alphabrief_api/db/` package:
   - `db/__init__.py` — exports `MarketDataStore`.
   - `db/schema.py` — `symbols` and `bars` table DDL with `apply_schema`
     and `drop_schema` helpers.
   - `db/market_data.py` — `MarketDataStore` class providing `insert_bars`,
     `get_symbols`, `get_bars`, `get_symbol_info`, `get_bar_models`,
     `get_bar_count`, `symbol_exists`, `clear`, and `close`.
3. Data directory defaults to `~/.alphabrief/data/`, overridable via
   `ALPHABRIEF_DATA_DIR`.
4. Replaced in-memory `_data_store` dict in `routes/data.py` with
   singleton `MarketDataStore`. All four market-data endpoints
   (`POST /load`, `GET /symbols`, `GET /{symbol}/bars`,
   `GET /{symbol}/info`) now read from DuckDB.
5. Retained `_get_stored_bars` helper for backtest route compatibility
   via new `MarketDataStore.get_bar_models()`.
6. Wrote `tests/test_db.py` with 20 unit tests covering schema creation,
   insert, query, pagination, ordering, symbol metadata, clear, close/reopen,
   and multi-symbol isolation.
7. Updated `tests/test_api_server.py` fixture to set `ALPHABRIEF_DATA_DIR`
   to a temp directory and close the store after each test, ensuring
   complete isolation without writing to the user's home directory.
8. All timestamps normalized to UTC before serialization.
9. Decimal values compacted (trailing zeros stripped) for clean API output.
10. Added Storage Layer chapter to `docs/architecture.md`.
11. Added Phase 7 definition and Round 1 progress to `docs/roadmap.md`.
12. Updated `README.md` "In progress" and "Not implemented yet" lists.

Files changed:
- `pyproject.toml` — duckdb dependency
- `apps/api/src/alphabrief_api/db/__init__.py` — new
- `apps/api/src/alphabrief_api/db/schema.py` — new
- `apps/api/src/alphabrief_api/db/market_data.py` — new
- `apps/api/src/alphabrief_api/routes/data.py` — replaced in-memory store
- `tests/test_db.py` — new (20 tests)
- `tests/test_api_server.py` — updated fixture for tmpdir isolation
- `docs/architecture.md` — Storage Layer chapter
- `docs/roadmap.md` — Phase 7 + progress
- `README.md` — updated status lists
- `docs/development_log.md` — this entry

Validation for 0031:

1. `python3 -m pytest` passed (289 tests, up from 269).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests/test_db.py tests/test_api_server.py`
   passed.

## 0032 Backtest Reports DuckDB Persistence

Status: completed.

Goal: replace the in-memory backtest report store with DuckDB-backed persistence.

Completed changes:

1. Added `backtest_reports` table DDL to `db/schema.py` with columns: `id`,
   `symbol`, `strategy_name`, `created_at`, `report_json`.
2. Created `apps/api/src/alphabrief_api/db/backtest_reports.py` with
   `BacktestReportStore` class providing `save_report`, `get_report`,
   `list_reports`, `clear`, and `close` — following the same pattern as
   `MarketDataStore`.
3. Exported `BacktestReportStore` from `db/__init__.py`.
4. Replaced in-memory `_report_store` dict in `routes/backtest.py` with
   singleton `BacktestReportStore`. All three backtest endpoints
   (`POST /run`, `GET /reports`, `GET /report/{id}`) now read from DuckDB.
5. Wrote `tests/test_db.py` with 9 new tests covering save, get, list,
   clear, and reopen scenarios.
6. Updated `tests/test_api_server.py` fixture to use `_clear_report_store`.

Files changed:
- `apps/api/src/alphabrief_api/db/backtest_reports.py` — new
- `apps/api/src/alphabrief_api/db/__init__.py` — export BacktestReportStore
- `apps/api/src/alphabrief_api/db/schema.py` — backtest_reports DDL
- `apps/api/src/alphabrief_api/routes/backtest.py` — DuckDB integration
- `tests/test_db.py` — 9 new tests
- `tests/test_api_server.py` — fixture update

Validation for 0032:

1. `.venv/bin/python -m pytest` passed (298 tests, up from 289).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests` passed.

## 0033 Briefs DuckDB Persistence

Status: completed.

Goal: replace the in-memory brief store with DuckDB-backed persistence.

Completed changes:

1. Added `briefs` table DDL to `db/schema.py` with columns: `id`,
   `created_at`, `brief_json`.
2. Created `apps/api/src/alphabrief_api/db/briefs.py` with
   `BriefStore` class providing `save_brief`, `get_brief`,
   `list_briefs`, `clear`, and `close` — following the same pattern as
   `BacktestReportStore`.
3. Exported `BriefStore` from `db/__init__.py`.
4. Replaced in-memory `_brief_store` dict in `routes/brief.py` with
   singleton `BriefStore`. All three brief endpoints
   (`POST /generate`, `GET /history`, `GET /{brief_id}`) now read from DuckDB.
5. Wrote `tests/test_db.py` with 10 new tests covering save, get, list,
   summary fields, clear, and reopen scenarios.
6. Updated `tests/test_api_server.py` fixture to use `_clear_brief_store`.
7. Updated `docs/roadmap.md` Phase 7 Round 3 status.

Files changed:
- `apps/api/src/alphabrief_api/db/briefs.py` — new
- `apps/api/src/alphabrief_api/db/__init__.py` — export BriefStore
- `apps/api/src/alphabrief_api/db/schema.py` — briefs DDL
- `apps/api/src/alphabrief_api/routes/brief.py` — DuckDB integration
- `tests/test_db.py` — 10 new tests
- `tests/test_api_server.py` — fixture update
- `docs/roadmap.md` — progress marker
- `docs/development_log.md` — this entry

1. `python3 -m pytest` passed (308 tests, up from 298).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests` passed.

## 0034 PaperStore + ReviewStore DuckDB Persistence

Status: completed.

Goal: complete Phase 7 by adding DuckDB-persisted paper trading and review
snapshot stores, replacing the remaining in-memory state.

Completed changes:

1. Added three new tables to `db/schema.py`: `audit_events`, `portfolio_snapshot`,
   and `review_snapshots` — following the same DDL pattern as prior Phase 7 tables.
2. Created `apps/api/src/alphabrief_api/db/paper.py` with `PaperStore` class
   providing `save_audit_event`, `get_audit_events` (with optional `event_type`
   filter), `save_portfolio_snapshot`, `get_latest_portfolio_snapshot`,
   `list_portfolio_snapshots`, `save_order`, `get_orders` (with optional
   `status` filter), `clear`, and `close`.
3. Created `apps/api/src/alphabrief_api/db/review.py` with `ReviewStore` class
   providing `save_snapshot`, `get_snapshot`, `get_latest_snapshot`,
   `list_snapshots`, `clear`, and `close`.
4. Exported `PaperStore` and `ReviewStore` from `db/__init__.py`.
5. Replaced in-memory broker/audit state in `routes/paper.py` with singleton
   `PaperStore`. Added `POST /api/v1/paper/orders` endpoint for creating broker
   orders with audit event recording. All paper endpoints (`portfolio`, `orders`,
   `audit`) now read from DuckDB.
6. Replaced in-memory snapshot state in `routes/review.py` with singleton
   `ReviewStore`. All review endpoints (`snapshot`, `journal`, `journal/daily`,
   `journal/weekly`) now read from DuckDB.
7. Exported `_get_risk_gate` and `_reset_risk_gate` helpers from
   `routes/risk.py` for test fixture use with the paper route.
8. Added 27 new tests across `tests/test_db.py` (17 PaperStore + ReviewStore
   unit tests) and `tests/test_api_server.py` (10 paper/review endpoint
   integration tests).
9. Marked Phase 7 complete in `docs/roadmap.md`.

Files changed:
- `apps/api/src/alphabrief_api/db/paper.py` — new (250 lines)
- `apps/api/src/alphabrief_api/db/review.py` — new (174 lines)
- `apps/api/src/alphabrief_api/db/__init__.py` — export PaperStore, ReviewStore
- `apps/api/src/alphabrief_api/db/schema.py` — 3 new tables
- `apps/api/src/alphabrief_api/db/briefs.py` — minor doc cleanup
- `apps/api/src/alphabrief_api/routes/paper.py` — DuckDB integration + POST orders
- `apps/api/src/alphabrief_api/routes/review.py` — DuckDB integration
- `apps/api/src/alphabrief_api/routes/risk.py` — export helpers
- `tests/test_db.py` — 17 new tests (411 lines)
- `tests/test_api_server.py` — 10 new tests + fixture isolation
- `docs/roadmap.md` — Phase 7 complete
- `docs/development_log.md` — this entry

Validation for 0034:

1. `python3 -m pytest` passed (335 tests, up from 308).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests` passed.
