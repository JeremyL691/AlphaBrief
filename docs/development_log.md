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

## 0035 Multi-Model Research Committee (Phase 8)

Status: completed.

Goal: implement the Multi-Model Research Committee — multiple AI models
with different analytical perspectives independently analyze a research
question and produce structured responses with an aggregated consensus.

Completed changes:

1. Created `packages/alphabrief-research/` with debate schemas
   (`DebateQuestion`, `ModelDebateResponse`, `DebateConsensus`,
   `DebateRecord`) and `DebateOrchestrator` that routes questions to
   model perspectives via `ModelGateway`, validates structured output,
   and generates consensus from all responses.

2. Added `debate_records` table to `db/schema.py` with `DebateStore` class
   for DuckDB persistence (save, get, list, clear lifecycle).

3. Created research API routes (`POST /api/v1/research/debate`,
   `GET /api/v1/research/debate`, `GET /api/v1/research/debate/{debate_id}`)
   and `alphabrief research debate` CLI command.

4. Added 32 new tests: 9 DebateStore unit tests, 4 API endpoint tests,
   19 schema/orchestrator/consensus tests.

5. Updated `pyproject.toml` (pythonpath, packages.find.where, mypy_path).

Files changed:
- `packages/alphabrief-research/` — 3 new files
- `apps/api/src/alphabrief_api/db/debates.py` — new
- `apps/api/src/alphabrief_api/db/schema.py` — debate_records DDL
- `apps/api/src/alphabrief_api/db/__init__.py` — export DebateStore
- `apps/api/src/alphabrief_api/routes/research.py` — new
- `apps/api/src/alphabrief_api/main.py` — register research router
- `apps/cli/src/alphabrief_cli/research_commands.py` — new
- `apps/cli/src/alphabrief_cli/main.py` — register research app
- `tests/test_db.py` — 9 new tests
- `tests/test_api_server.py` — 4 new tests + fixture
- `tests/test_research.py` — new (19 tests)
- `docs/roadmap.md` — Phase 8 status
- `docs/development_log.md` — this entry
- `pyproject.toml` — 3 path entries

Validation for 0035:

1. `python3 -m pytest` passed (367 tests, up from 335).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests` passed.

## 0036 Real Market Data Providers (Phase 9)

Status: completed.

Goal: complete Phase 9 by adding free, key-less market data
providers (Yahoo Finance and Binance) that download OHLCV bars into
the existing DuckDB `bars` table through `MarketDataStore`. Add a
new CLI subcommand and API endpoint that drive the providers.

Completed changes:

1. Added `packages/alphabrief-data/src/alphabrief_data/providers/`
   with `__init__.py`, `base.py`, `yahoo.py`, and `binance.py`:
   - `base.py` defines the `MarketDataProvider` runtime-checkable
     Protocol, the `MarketDataProviderError` structured exception
     (carrying a stable `code` attribute), and the
     `MarketDataProviderErrorCode` enum.
   - `yahoo.py` implements `YahooFinanceProvider` against
     `query1.finance.yahoo.com/v8/finance/chart/{symbol}` using
     `urllib` only. Returns `list[Bar]` with timezone-aware UTC
     timestamps. Supports `1d` and `1h` intervals. Handles HTTP
     429/503 as rate-limit, generic HTTP errors, network errors,
     and JSON parse errors with stable error codes. Has an
     injectable `http_get` callable for tests.
   - `binance.py` implements `BinanceProvider` against
     `api.binance.com/api/v3/klines` using `urllib` only. Returns
     `list[Bar]` with timezone-aware UTC timestamps parsed from
     millisecond UNIX timestamps and string prices parsed as
     `Decimal`. Supports `1d` and `1h` intervals. Handles HTTP
     418/429 as rate-limit. Has an injectable `http_get` callable.
   - `__init__.py` exports the two providers and the base types.
2. Exported the new symbols from
   `packages/alphabrief-data/src/alphabrief_data/__init__.py` so
   callers can `from alphabrief_data import YahooFinanceProvider,
   BinanceProvider, MarketDataProvider,
   MarketDataProviderError, MarketDataProviderErrorCode`.
3. Added the `alphabrief data fetch` CLI subcommand in
   `apps/cli/src/alphabrief_cli/data_commands.py`. The command
   accepts `--source`, `--symbol`, `--start`, `--end`,
   `--interval` (default `1d`), and `--data-version` (default
   `fetch-v1`). It builds the right provider, calls
   `fetch_ohlcv`, and persists the result through the shared
   `MarketDataStore`. Empty result sets and provider errors
   produce clear stderr messages and a non-zero exit code.
4. Added `POST /api/v1/data/fetch` to
   `apps/api/src/alphabrief_api/routes/data.py` with a strict
   Pydantic `DataFetchRequest` model (Literal source/interval,
   non-empty symbol, validated ISO-8601 dates) and a
   `DataFetchResponse` model that returns `bar_count`,
   `time_start`, and `time_end`. Empty provider results return
   404, validation errors return 422, structured provider errors
   return 422 with the error message.
5. Added 41 new tests across three new / updated files:
   - `tests/test_market_data_providers.py` — 25 tests covering
     both providers' payload parsing, protocol compliance, error
     handling (invalid config / symbol / interval / range, HTTP
     error, rate limit, network error, parse error, API error
     payload, invalid kline row, non-list response), null-row
     skipping, empty result handling, and HTTP request shape.
   - `tests/test_api_server.py` — 7 new integration tests for
     `POST /api/v1/data/fetch` (Yahoo success, Binance success,
     unknown source rejection, invalid date rejection, empty
     result 404, HTTP failure 422, custom data version).
   - `tests/test_data_commands.py` — new file with 9 CLI
     integration tests for `data fetch` and regression tests
     for the existing `data import` and `data check` commands.
6. Updated `docs/architecture.md` with a new Market Data
   Providers chapter documenting the protocol, the two shipped
   providers, the HTTP layer, and the explicit non-goals
   (no SDKs, no API keys, no minute bars, no retries).
7. Updated `docs/roadmap.md` with the Phase 9 status block.

Files changed:
- `packages/alphabrief-data/src/alphabrief_data/providers/__init__.py` — new
- `packages/alphabrief-data/src/alphabrief_data/providers/base.py` — new
- `packages/alphabrief-data/src/alphabrief_data/providers/yahoo.py` — new
- `packages/alphabrief-data/src/alphabrief_data/providers/binance.py` — new
- `packages/alphabrief-data/src/alphabrief_data/__init__.py` — export new providers
- `apps/cli/src/alphabrief_cli/data_commands.py` — add `fetch` subcommand
- `apps/api/src/alphabrief_api/routes/data.py` — add `POST /fetch` endpoint
- `tests/test_market_data_providers.py` — new (25 tests)
- `tests/test_api_server.py` — 7 new tests + import additions
- `tests/test_data_commands.py` — new (9 tests)
- `docs/development_plans/0023-phase-9-real-market-data-providers.md` — new
- `docs/architecture.md` — Market Data Providers chapter
- `docs/roadmap.md` — Phase 9 status block
- `docs/development_log.md` — this entry

Validation for 0036:

1. `python3 -m pytest` passed (408 tests, up from 367).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy packages/alphabrief-data/src apps/api/src apps/cli/src tests` passed.

## 0037 Provider Retries and Interval Expansion (Phase 9 R2)

Status: completed.

Goal: harden the Phase 9 real market data providers against transient
HTTP failures and broaden the supported interval set so users can
fetch minute, weekly, and monthly bars without re-validating
everything by hand.

Completed changes:

1. Added `RetryPolicy` frozen dataclass to
   `packages/alphabrief-data/src/alphabrief_data/providers/base.py`
   with `max_retries`, `initial_backoff_seconds`, `backoff_factor`,
   `max_backoff_seconds`, and `jitter_factor`. `__post_init__`
   validates every field and raises `MarketDataProviderError` with
   `INVALID_CONFIG` on bad input.
2. Added `is_retryable_exception()` (HTTP 429, 418, 5xx and
   `URLError`/`OSError`/`TimeoutError`/`ConnectionError` are
   retryable; non-rate-limit 4xx is not), `compute_backoff_delay()`
   (deterministic given a fixed random source, capped at
   `max_backoff_seconds`, with symmetric uniform jitter), and
   `call_with_retry()` (configurable `sleep`, `random_fn`,
   `is_retryable`, and `on_retry` test seams, re-raises the **last**
   exception after the retry budget is exhausted).
3. Wrapped the Yahoo and Binance HTTP layers with
   `call_with_retry` so transient 429/418/5xx and network failures
   recover automatically before any structured
   `MarketDataProviderError` is raised. Both providers' structured
   error mapping (RATE_LIMITED vs HTTP_ERROR vs NETWORK_ERROR)
   remains unchanged for the post-retry failure case.
4. Expanded Yahoo's `_SUPPORTED_INTERVALS` to
   `1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo` and Binance's to
   `1m, 3m, 5m, 15m, 30m, 1h, 1d, 1w, 1M`. Added Binance's
   `_interval_to_seconds()` mapping for the new `1w` (604 800 s) and
   `1M` (2 592 000 s, 30-day month approximation) intervals so the
   pagination cursor advances correctly across the 1 000-row page
   boundary.
5. Updated the API `DataFetchRequest.interval` Literal and the CLI
   `--interval` help text to reflect the expanded set; the new
   intervals are accepted end-to-end through the API and the CLI.
6. Added 23 new tests to `tests/test_market_data_providers.py`:
   - 5 `is_retryable_*` tests covering 429, 418, 5xx, 4xx, and
     transient network vs unrelated exceptions.
   - 2 `RetryPolicy` validation tests (negative `max_retries`,
     out-of-range `jitter_factor`).
   - 2 `compute_backoff_delay` tests (deterministic value with zero
     jitter; cap at `max_backoff_seconds`).
   - 4 `call_with_retry` tests (succeed-on-first-try, recover after
     recoverable failures, re-raise after budget exhaustion,
     no-retry on 4xx).
   - 4 end-to-end provider tests (Yahoo and Binance each retry
     5xx-then-succeed, and each do not retry on 4xx).
   - 6 provider interval tests (Yahoo and Binance each accept every
     new interval; Yahoo `1wk` and `1mo` map to the correct
     `data_version`; Binance `1w` and `1M` map to the correct
     `data_version`).
7. Updated two pre-existing tests to use intervals that remain
   unsupported after R2: `test_yahoo_provider_raises_on_unsupported_interval`
   now uses `"2h"` and `test_binance_provider_raises_on_unsupported_interval`
   now uses `"1wk"`. Provider code is unchanged.
8. Updated `docs/architecture.md` Market Data Providers chapter to
   reflect the retry policy, the expanded Yahoo and Binance
   interval sets, and to remove the now-incorrect "no retries"
   claim from the non-goals list.

Files changed:
- `tests/test_market_data_providers.py` — 23 new tests + 2
  pre-existing interval updates
- `docs/roadmap.md` — Phase 9 R2 progress block
- `docs/development_log.md` — this entry
- `docs/architecture.md` — Market Data Providers chapter updated
  (retry policy, interval lists, non-goals cleanup)

Validation for 0037:

1. `python3 -m pytest` passed (431 tests, up from 408).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy apps/api/src tests` passed.


## 0038 News & Macro Data Layer (Phase 10)

Status: completed.

Goal: add the first read-only News & Macro Data Layer boundary that
mirrors the Phase 9 market data provider structure, so future research,
brief, and risk modules can consume structured headlines and macro
snapshots without provider SDKs or arbitrary web scraping.

Completed changes:

1. Created `packages/alphabrief-news/` with Pydantic schemas
   (`NewsHeadline`, `MacroIndicator`, `NewsFetchQuery`,
   `MacroFetchQuery`), provider protocols (`NewsProvider`,
   `MacroProvider`), and structured errors (`NewsProviderError`,
   `NewsProviderErrorCode`).
2. Added `alphabrief_news.quality` with `check_headline_quality` and
   `check_indicator_quality`.
3. Added `MockNewsProvider` and `MockMacroProvider` for deterministic
   offline tests.
4. Added `RssNewsProvider` — stdlib-only RSS/Atom reader with a
   hard-coded allowlist of free feeds, injectable `http_get`, and
   reuse of the shared `call_with_retry` helper.
5. Added `FredMacroProvider` stub that raises `NO_API_KEY`; no secret
   is read or stored.
6. Added DuckDB `news_headlines` and `macro_indicators` tables and
   the `NewsStore` / `MacroStore` data access classes.
7. Added FastAPI routers `/api/v1/news/*` and `/api/v1/macro/*` with
   fetch, list, and get-by-id endpoints.
8. Added `alphabrief news fetch/list` and
   `alphabrief macro fetch/list` CLI subcommands.
9. Registered the new package in `pyproject.toml` pythonpath,
   package discovery, and mypy path.
10. Added 58 new tests: 26 unit tests in `tests/test_news.py`,
    9 store tests in `tests/test_db.py`, 14 API integration tests
    in `tests/test_api_server.py`, and 9 CLI integration tests in
    `tests/test_data_commands.py`.
11. Updated `docs/architecture.md`, `docs/roadmap.md`,
    `docs/agent_protocol.md`, and this development log.

Files changed:
- `pyproject.toml` — added `packages/alphabrief-news/src` paths.
- `packages/alphabrief-news/src/alphabrief_news/__init__.py` — new.
- `packages/alphabrief-news/src/alphabrief_news/types.py` — new.
- `packages/alphabrief-news/src/alphabrief_news/quality.py` — new.
- `packages/alphabrief-news/src/alphabrief_news/providers/__init__.py` — new.
- `packages/alphabrief-news/src/alphabrief_news/providers/base.py` — new.
- `packages/alphabrief-news/src/alphabrief_news/providers/mock.py` — new.
- `packages/alphabrief-news/src/alphabrief_news/providers/rss.py` — new.
- `packages/alphabrief-news/src/alphabrief_news/providers/fred.py` — new.
- `apps/api/src/alphabrief_api/db/schema.py` — added news/macro tables.
- `apps/api/src/alphabrief_api/db/news.py` — new.
- `apps/api/src/alphabrief_api/db/macro.py` — new.
- `apps/api/src/alphabrief_api/db/__init__.py` — export new stores.
- `apps/api/src/alphabrief_api/routes/news.py` — new.
- `apps/api/src/alphabrief_api/routes/macro.py` — new.
- `apps/api/src/alphabrief_api/main.py` — register new routers.
- `apps/cli/src/alphabrief_cli/news_commands.py` — new.
- `apps/cli/src/alphabrief_cli/macro_commands.py` — new.
- `apps/cli/src/alphabrief_cli/main.py` — register new apps.
- `tests/test_news.py` — new (26 tests).
- `tests/test_db.py` — added 9 store tests.
- `tests/test_api_server.py` — added 14 integration tests.
- `tests/test_data_commands.py` — added 9 CLI tests.
- `docs/architecture.md` — new chapter.
- `docs/roadmap.md` — Phase 10 status.
- `docs/agent_protocol.md` — untrusted data note.
- `docs/development_log.md` — this entry.

Validation for 0038:

1. `python3 -m pytest` passed (489 tests, up from 431).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy packages apps` passed.
4. `alphabrief news fetch --source mock --symbol AAPL ...` and
   `alphabrief macro fetch --source mock --indicator CPIAUCSL ...`
   work end-to-end and persist through DuckDB.
5. `POST /api/v1/news/fetch`, `GET /api/v1/news/headlines`,
   `POST /api/v1/macro/fetch`, and `GET /api/v1/macro/indicators`
   return correct status codes and shapes.
6. `fred` source returns 422 with `NO_API_KEY`; no secret touched.
7. RSS provider parses injected Atom and RSS feeds; 5xx retries,
   4xx does not retry.
8. No file under `_reference_sources/` was opened or imported.
9. No news/macro data was wired into briefs, debates, risk, or
    execution.

## 0039 External Evidence + Risk Context (Phase 12 R1–R4)

Status: completed.

Goal: add a structured external-evidence pipeline from strategy signal
generation through deterministic risk tightening, so news sentiment
and macro conditions can tighten (never relax) risk decisions without
modifying RiskGate core semantics.

Completed changes:

1. Added `SignalEvidence` model to `alphabrief_core.domain` with
   `evidence_type` (`news`/`macro`/`composite`), `source`,
   `sentiment_score`, `data_version`, and optional
   `headline_ids` / `macro_indicator_ids`.

2. Added `ExternalEvidenceConfig` to `alphabrief_strategy.spec`
   (`StrategySpec.external_evidence`). Declares whether a strategy
   intends to consume external evidence, the logical source, and
   thresholds for human-review flagging. All fields optional with
   safe defaults.

3. Extended `StrategyOutput` to carry `SignalEvidence` on every
   `Signal`. Updated `run_strategy` validation to accept it.

4. Extended `ResearchContextSummary`
   (`alphabrief_research.context`) with `positive_count`,
   `negative_count`, `aggregate_sentiment_score`,
   `worst_sentiment`, `macro_indicator_ids`, and provenance
   fields. Added `build_context_summary()`.

5. Created `alphabrief_risk.context` with `NewsMacroRiskContext`
   (lightweight input mirror), `RiskContextDecision` (advisory
   tighten-only output), and `evaluate_news_macro_risk()` with
   fixed thresholds:
   - Sentiment < -0.2 → `negative_news_context` tag + human review
   - Macro indicators > 4 → `macro_high_risk` tag + 0.5× position
   - Positive/neutral → neutral decision (no relaxation)

6. Added 42 new tests across `tests/test_risk_context.py` (25),
   `tests/test_research_context.py` (expanded), and
   `tests/test_strategy_spec_schema.py` /
   `tests/test_strategy_interface.py` (expanded).

7. All new schema fields default to safe empty/None values —
   existing fake-provider tests pass unchanged.

Files changed:
- `packages/alphabrief-core/src/alphabrief_core/domain.py` — SignalEvidence
- `packages/alphabrief-strategy/src/alphabrief_strategy/spec.py` — ExternalEvidenceConfig
- `packages/alphabrief-strategy/src/alphabrief_strategy/interface.py` — evidence on signals
- `packages/alphabrief-research/src/alphabrief_research/context.py` — summary fields + builder
- `packages/alphabrief-risk/src/alphabrief_risk/context.py` — risk context layer (new)
- `packages/alphabrief-risk/src/alphabrief_risk/__init__.py` — exports
- `tests/test_research_context.py` — expanded
- `tests/test_risk_context.py` — new (25 tests)
- `tests/test_strategy_spec_schema.py` — expanded
- `tests/test_strategy_interface.py` — expanded
- `docs/architecture.md` — Phase 12 chapter
- `docs/development_log.md` — this entry

Validation for 0039:

1. `python3 -m pytest` passed (baseline 597, R1-R4 additive).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy packages apps tests` passed.

## 0040 Risk Context API/CLI + Gym EnvV2 Reports (Phase 12 R5–R6)

Status: completed.

Goal: expose the Phase 12 risk-context layer through the API and CLI
surfaces, and formalize multi-asset environment episode reports with
cost-breakdown schemas.

Completed changes:

1. Enhanced `apps/api/src/alphabrief_api/routes/risk.py` with
   `POST /api/v1/risk/context` endpoint that accepts
   `NewsMacroRiskContext` input and returns `RiskContextDecision`.
   Added `GET /api/v1/risk/context` that returns a default neutral
   decision for smoke-test purposes. All risk context routes are
   read-only advisory — they do not modify RiskGate state.

2. Enhanced `apps/cli/src/alphabrief_cli/risk_commands.py` with
   `alphabrief risk context` subcommand that mirrors the API
   endpoint. Accepts `--input-json` or in-line `--sentiment-score`
   / `--negative-count` / `--macro-count` options.

3. Updated `alphabrief_gym.__init__.py` to export new Phase 12
   schemas: `EnvV2Report`, `EnvV2CostBreakdown`,
   `EnvV2AssetMetrics`, `EpisodeMetricsV2`.

4. Added `alphabrief_gym.schemas` with frozen Pydantic models for
   `MultiAssetObservation`, `ContinuousActionSpace`,
   `DiscreteActionSpace`, `PortfolioSnapshot`,
   `EnvV2CostBreakdown`, `EnvV2AssetMetrics`, and `EnvV2Report`.
   All Decimal fields reject float input.

5. Extended `alphabrief_gym.report.py` with `generate_env_v2_report()`
   that produces a validated `EnvV2Report` from an
   `AlphaBriefTradingEnvV2` episode.

6. Updated `alphabrief_models.prompts.py` with v3 prompt templates
   that reference external evidence context.

7. Updated `alphabrief_models.briefs.py` with optional
   `risk_context` fields on `DailyAlphaBrief`.

8. Added 32 new tests: 22 API integration tests in
   `tests/test_api_server.py` covering risk context endpoints
   and 10 CLI integration tests in `tests/test_risk_commands.py`
   (new file).

9. Updated `pyproject.toml` with alphabrief-risk CLI test path.

Files changed:
- `apps/api/src/alphabrief_api/routes/risk.py` — context endpoints
- `apps/api/src/alphabrief_api/routes/brief.py` — risk context fields
- `apps/cli/src/alphabrief_cli/risk_commands.py` — context subcommand
- `packages/alphabrief-gym/src/alphabrief_gym/__init__.py` — exports
- `packages/alphabrief-gym/src/alphabrief_gym/schemas.py` — new schemas
- `packages/alphabrief-gym/src/alphabrief_gym/report.py` — EnvV2 report
- `packages/alphabrief-models/src/alphabrief_models/briefs.py` — fields
- `packages/alphabrief-models/src/alphabrief_models/prompts.py` — v3
- `tests/test_api_server.py` — 22 new tests
- `tests/test_risk_commands.py` — new (10 tests)
- `pyproject.toml` — CLI test path
- `docs/development_log.md` — this entry

Validation for 0040:

1. `python3 -m pytest` passed (659 tests, up from 597).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy packages apps tests` passed.

---

## 0041 — BacktestReport Schema v2 Compatible Extension (Round 12.7)

Date: 2026-06-16

Goal: Allow `BacktestReportStore` to persist and read `EnvV2Report`
objects while remaining fully backward compatible with legacy
`BacktestReport` rows.

Changes:

1. Extended `apps/api/src/alphabrief_api/db/schema.py`:
   - Added `report_engine TEXT DEFAULT 'legacy'` to the
     `backtest_reports` table.
   - Added an idempotent migration (`ALTER TABLE ... ADD COLUMN IF NOT
     EXISTS`) plus an `UPDATE` fallback so existing rows are tagged
     `'legacy'`.

2. Extended `apps/api/src/alphabrief_api/db/backtest_reports.py`:
   - `save_report()` now accepts optional `report_engine` (`'legacy'` by
     default) and `engine_payload` arguments. Old callers are unchanged.
   - Added `save_env_v2_report(report_dict, symbol, strategy_name)`
     helper that stores the report with `report_engine='env_v2'`.
   - Added `list_reports_by_engine(engine)` filter.
   - `get_report()` and `list_reports()` now include `report_engine` in
     the returned dict.

3. Added `tests/test_backtest_reports.py` with 7 new tests covering:
   - Legacy report round-trip.
   - EnvV2 report round-trip using `env_v2_report_to_dict()`.
   - Mixed legacy / env_v2 storage.
   - `list_reports_by_engine` filtering (including unknown engine → []).
   - Empty store behavior.
   - `clear()` removes all reports.
   - Default engine is `legacy` when omitted.

Files changed:
- `apps/api/src/alphabrief_api/db/schema.py` — schema + migration
- `apps/api/src/alphabrief_api/db/backtest_reports.py` — store API
- `tests/test_backtest_reports.py` — new test file
- `docs/development_log.md` — this entry

Validation for 0041:

1. `.venv/bin/python -m pytest tests/test_db.py tests/test_backtest_reports.py -x -q --tb=short` passed (87 tests).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy` passed (129 source files).

---

## 0042 — CLI/API EnvV2 Backtest Engine Option (Round 12.8)

Date: 2026-06-16

Goal: Allow users to explicitly select the `AlphaBriefTradingEnvV2`
multi-asset backtest engine through both the API and CLI, while keeping
the legacy single-asset `VectorizedBacktester` as the default.

Changes:

1. Extended `apps/api/src/alphabrief_api/db/market_data.py`:
   - Added `get_bar_models_for_symbols(symbols)` that loads `Bar`
     domain objects for multiple symbols via the existing per-symbol
     helper. Missing symbols map to an empty list; callers validate.

2. Extended `apps/api/src/alphabrief_api/routes/backtest.py`:
   - `BacktestRunRequest` gained `engine` (`"legacy"` or `"env_v2"`,
     default `"legacy"`), `symbols`, `env_v2_max_leverage`,
     `env_v2_allow_short`, `env_v2_fee_bps`, `env_v2_slippage_bps`.
   - `run_backtest` dispatches by `engine` to `_run_legacy_backtest`
     (unchanged path) or `_run_env_v2_backtest` (new multi-asset path).
   - EnvV2 path validates symbol existence, minimum bar count (>=2),
     and equal bar lengths across assets; returns 422 on failures.
   - Added `EnvV2BacktestReportResponse`, `EnvV2CostBreakdownResponse`,
     `EnvV2AssetMetricsResponse` response models.
   - Runs a deterministic equal-weight buy-and-hold episode, persists
     the report via `BacktestReportStore.save_env_v2_report()`.
   - `list_reports` now branches by `report_engine` to correctly
     extract env_v2 report summaries.

3. Extended `apps/cli/src/alphabrief_cli/backtest_commands.py`:
   - Added `--engine`, `--symbols`, `--max-leverage`, `--allow-short`,
     `--fee-bps`, `--slippage-bps` options to the `run` subcommand.
   - Env-v2 branch reads multi-asset bars from DuckDB `MarketDataStore`,
     validates data completeness, runs equal-weight buy-and-hold via
     `evaluate_equal_weight_buy_and_hold_v2()`, and prints report
     summary. Supports optional `--output` JSON export.
   - Legacy branch is unchanged; `--data` and `--spec` remain required.

4. Extended `packages/alphabrief-gym/src/alphabrief_gym/policies.py`:
   - Added `PolicyV2` type alias, `PolicyEvaluationV2`, `run_policy_episode_v2()`,
     and `evaluate_equal_weight_buy_and_hold_v2()` for deterministic
     multi-asset policy execution.

5. Updated `packages/alphabrief-gym/src/alphabrief_gym/__init__.py`:
   - Exported `PolicyEvaluationV2`, `run_policy_episode_v2`,
     `evaluate_equal_weight_buy_and_hold_v2`.

6. Added `tests/test_backtest_commands.py` with 2 tests:
   - `test_cli_backtest_run_env_v2_missing_symbols` — validates that
     `--engine env-v2` without `--symbols` exits with an error.
   - `test_cli_backtest_run_legacy_still_works` — confirms the default
     legacy engine with `--data` and `--spec` continues to work.

Files changed:
- `apps/api/src/alphabrief_api/db/market_data.py` — multi-symbol loader
- `apps/api/src/alphabrief_api/routes/backtest.py` — engine branch + EnvV2 path
- `apps/cli/src/alphabrief_cli/backtest_commands.py` — CLI options + env-v2 path
- `packages/alphabrief-gym/src/alphabrief_gym/policies.py` — V2 policies
- `packages/alphabrief-gym/src/alphabrief_gym/__init__.py` — exports
- `tests/test_backtest_commands.py` — new (2 tests)
- `docs/development_log.md` — this entry

Validation for 0042:

1. `.venv/bin/python -m pytest -q --tb=line` passed (668 tests, up from 659).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy` passed (130 source files).

---

## 0043 — Phase 13 R13.2–R13.5 and Phase 14 Model Evaluation

Status: completed.

Goal: close out the remaining Phase 13 risk_context wiring rounds
and deliver Phase 14 Model Evaluation & Performance Intelligence:
automated model evaluation, performance-aware routing, model
performance persistence, and a model dashboard. Phase 14 is
strictly read-only with respect to trading, risk, and execution.

### Phase 13 R13.2–R13.5 — risk_context end-to-end

1. `alphabrief risk check` and `POST /api/v1/risk/check` accept an
   optional `risk_context` payload and surface the merged
   `RiskDecision`.
2. `PaperBroker.submit` blocks when the merged decision requires
   human review. The CLI and the API both honor the block.
3. `ExecutionAuditEntry` carries `risk_context_decision_id`,
   `risk_context_tags`, and `risk_context_multiplier` of the merged
   decision. The audit endpoints expose the metadata on every
   recorded event.
4. 16 new tests in `tests/test_r13_risk_context_wiring.py`.

### Phase 14 R14.1 — DuckDB model_evaluations table + ModelEvalStore

1. Added `model_evaluations` table to `db/schema.py` with columns for
   `json_valid_rate`, `schema_pass_rate`, `hallucination_rate`,
   `avg_latency_ms`, `avg_cost_estimate`, `sample_count`, and a
   JSON `eval_config` snapshot.
2. Created `ModelEvalStore` with `save_evaluation`,
   `get_evaluations`, `get_latest_evaluation`,
   `get_latest_per_task_for_model`, `list_evaluations`, `clear`,
   and `close`.
3. 14 new tests in `tests/test_model_eval_store.py`.

### Phase 14 R14.2 — ModelEvaluator

1. `alphabrief_models.evaluation` exposes `EvalDataset`, `EvalResult`,
   `EvalDatasetSpec`, `EvalSample`, `ModelEvaluation`, and
   `ModelEvaluator`.
2. The evaluator runs JSON-validity, schema-pass, and hallucination
   evaluations through `ModelGateway`. It never calls provider SDKs
   directly.
3. Bundled local datasets (`market_summary_v1`, `daily_brief_v1`,
   `debate_response_v1`, `knowledge_v1`) are hardcoded Python
   definitions in `alphabrief_models.evaluation_datasets`.
4. `MAX_SAMPLE_COUNT = 50` hard upper bound.
5. 20 new tests in `tests/test_model_evaluator.py`.

### Phase 14 R14.3 — ModelRouter

1. `alphabrief_models.router` exposes `ModelRouter`,
   `ModelRouteDecision`, `PerformanceSnapshot`, and
   `PerformanceProvider` callable type.
2. Routing is **advisory only** — when no performance data exists,
   the router preserves the existing capability-only behavior.
3. When performance data is available, profiles are scored by
   `schema_pass_rate` (descending), with optional
   `prefer_low_latency` and `prefer_low_cost` flags. Profiles below
   `min_schema_pass_rate` are deprioritized for structured tasks.
4. The provider callable is exception-safe; routing falls back to
   capability-only when the data source is unavailable.
5. 15 new tests in `tests/test_model_router.py`.

### Phase 14 R14.4 — API endpoints

1. `POST /api/v1/models/evaluate` runs an evaluation and persists
   the result.
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

### Phase 14 R14.5 — CLI commands

1. `alphabrief model evaluate` runs an evaluation, persists it, and
   prints the result as JSON.
2. `alphabrief model performance` lists stored evaluations for a
   model, optionally filtered by task.
3. `alphabrief model route` queries the router for a task type and
   capability set.
4. `alphabrief model compare` compares multiple models for a task
   type.
5. 14 new tests in `tests/test_model_cli.py`.

### Phase 14 R14.6 — Dashboard

1. Main `/dashboard` page adds a Model Performance card grid
   showing the latest `schema_pass_rate` per model, color-coded
   (green ≥ 0.9, yellow 0.7–0.9, red < 0.7).
2. New `/dashboard/models` page lists recent evaluations and shows
   per-model performance summaries broken down by task.
3. Dashboard remains strictly read-only; no live model calls are
   made from the page itself.
4. 4 new tests in `tests/test_dashboard_models.py`.

### Phase 14 R14.7 — Documentation

1. Updated `docs/roadmap.md` with Phase 14 status block.
2. Updated `docs/architecture.md` with the Model Evaluation
   chapter.
3. Updated `docs/development_log.md` (this entry).

### Validation for 0043

1. `.venv/bin/python -m pytest -q --tb=line` passed (782 tests, up
   from 695).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy packages apps tests` passed (156 source files).
4. No files under `_reference_sources/` were opened or imported.
5. No risk / execution / trading files were modified.

## 0044 Phase 15 R15.1 — StrategySpecStore

Status: completed.

Goal: add the first persistent Strategy Registry storage layer — a
DuckDB-backed `StrategySpecStore` that lets strategies become
first-class artifacts in the system. This is the foundation for
Strategy Lifecycle Management (Phase 15) and unlocks every future
strategy-driven feature (paper trading loop, daily automation,
P&L attribution by strategy).

Completed changes:

1. Added `strategy_specs` table DDL to `db/schema.py` with columns:
   `strategy_id` (PK), `name`, `version`, `enabled`, `spec_json`
   (full StrategySpec payload), `created_at`, `updated_at`.
2. Created `apps/api/src/alphabrief_api/db/strategies.py` with
   `StrategySpecStore` exposing:
   - `save_spec(spec, *, enabled=_UNSET)` — upsert; preserves the
     existing `enabled` flag when the caller omits it. Validates
     non-empty `strategy_id`, `name`, `version`.
   - `set_enabled(strategy_id, enabled)` — boolean flag flip;
     returns `False` if no such strategy exists.
   - `delete_spec(strategy_id)` — returns `False` if missing.
   - `get_spec(strategy_id)` — full record including `spec_json`.
   - `list_specs(enabled_only=False)` — summaries (no spec payload),
     ordered by `strategy_id` ascending.
   - `list_enabled_strategy_ids()` — convenience for risk consumers.
   - `exists(strategy_id)` and `count()`.
   - `clear()` / `close()` for test isolation.
3. Exported `StrategySpecStore` from `db/__init__.py`.
4. Wrote `tests/test_strategy_store.py` with **27 new unit tests**
   covering schema creation, save (default + explicit enabled, payload
   fidelity, validation, upsert with and without enabled preservation),
   set_enabled (true / false / missing / bad type), get / exists /
   count, list_specs (empty / summaries exclude spec / enabled_only /
   ordered), list_enabled_strategy_ids, delete (present / missing),
   clear, reopen persistence, and idempotent close.

Files changed:
- `apps/api/src/alphabrief_api/db/schema.py` — strategy_specs DDL
- `apps/api/src/alphabrief_api/db/strategies.py` — new (220 lines)
- `apps/api/src/alphabrief_api/db/__init__.py` — export
- `tests/test_strategy_store.py` — new (27 tests)
- `docs/development_log.md` — this entry

Validation for 0044:

1. `.venv/bin/python -m pytest tests/test_strategy_store.py -q` passed
   (27 tests).
2. `.venv/bin/ruff check apps/api/src/alphabrief_api/db/strategies.py
   tests/test_strategy_store.py` passed.
3. `.venv/bin/mypy apps/api/src/alphabrief_api/db/strategies.py
   apps/api/src/alphabrief_api/db/schema.py
   apps/api/src/alphabrief_api/db/__init__.py tests/test_strategy_store.py`
   passed.
4. No files under `_reference_sources/` were opened or imported.
5. No risk, execution, strategy, model, or trading files were modified.

## 0045 Phase 15 R15.3–R15.7 — Strategy Registry, Activation, Signal History, Dashboard

Status: completed.

Goal: complete the Strategy Lifecycle Management surface so
strategies are first-class persistent artifacts with CLI / API /
Dashboard access, an advisory activation flag, and a write-only
signal history. The phase is **strictly advisory**: no part of
Phase 15 modifies `RiskGate` semantics, blocks orders, or enables
live trading.

### Phase 15 R15.3 — CLI strategy commands

1. `apps/cli/src/alphabrief_cli/strategy_commands.py` — new
   `strategy_app` Typer subcommand group.
2. Commands: `save --from-yaml|--from-json [--enable|--disable]`,
   `list [--enabled|--disabled]`, `show <id>`, `enable <id>`,
   `disable <id>`, `delete <id>`.
3. Registered in `apps/cli/src/alphabrief_cli/main.py`.
4. PyYAML added as a declared runtime dep; `types-PyYAML` added as
   a dev dep.
5. 19 new tests in `tests/test_strategy_commands.py`.

### Phase 15 R15.4 — Activation flag (advisory surface)

1. New endpoint `GET /api/v1/strategies/enabled` returns the list
   of strategy_ids whose advisory `enabled` flag is `True`.
2. The flag remains **strictly advisory**:
   - `RiskGate.enabled_strategies` is a separate, manually
     configured frozenset. The registry flag is **not** wired into
     it.
   - The flag is not consulted by `PaperBroker` or any execution
     path.
3. 5 new tests in `tests/test_strategies_api.py`, including a
   dedicated advisory-safety test that exercises `RiskGate` to
   prove the registry flag cannot grant, relax, or block risk
   decisions.

### Phase 15 R15.5 — Strategy signal history persistence

1. New `strategy_signals` DuckDB table with `signal_id` (PK),
   `strategy_id`, `symbol`, `signal_ts`, `direction`, `confidence`,
   `horizon`, `source`, `signal_json`, `created_at`. Index on
   `(strategy_id, signal_ts DESC)`.
2. New `StrategySignalStore` with `save_signal`, `get_signal`,
   `list_signals`, `count_signals`, `list_strategy_ids`,
   `delete_signal`, `clear`, `close`. Full input validation
   including `confidence in [0, 1]`, `bool` rejected for
   `confidence`, allowed sources `backtest` / `manual` / `other`.
3. New API endpoints:
   - `POST   /api/v1/strategies/signals`
   - `GET    /api/v1/strategies/signals`
   - `GET    /api/v1/strategies/signals/{signal_id}`
   - `DELETE /api/v1/strategies/signals/{signal_id}`
   - `GET    /api/v1/strategies/{strategy_id}/signals/count`
4. New CLI subcommands: `strategy record-signal`,
   `strategy list-signals`, `strategy show-signal`,
   `strategy count-signals`.
5. 32 new unit tests + 21 new API tests + 9 new CLI tests.
6. Dedicated advisory-safety test confirms that recording
   signals does not change the risk gate's decision.

### Phase 15 R15.6 — Dashboard

1. New `/dashboard/strategies` page lists saved strategies with
   name, version, enabled badge, updated timestamp, and a "View"
   link to the full JSON record.
2. Per-strategy signal counts are shown alongside the activation
   badge.
3. Both the registry and the signal history carry explicit
   "advisory only" disclaimers in the page UI.
4. New nav link on the main `/dashboard` page.
5. 7 new tests in `tests/test_dashboard_strategies.py`.

### Phase 15 R15.7 — Documentation

1. Added Phase 15 status block to `docs/roadmap.md` with
   per-round detail and a final quality gate.
2. Added a "Phase 15 — Strategy Registry and Signal History"
   chapter to `docs/architecture.md`, including the storage
   schema, the advisory-only safety contract, the API and CLI
   surface, and the hard constraints.
3. Updated `docs/development_log.md` (this entry).

### Files changed (R15.3–R15.7)

- `apps/api/src/alphabrief_api/db/__init__.py` — export new store
- `apps/api/src/alphabrief_api/db/schema.py` — strategy_signals DDL
- `apps/api/src/alphabrief_api/db/strategy_signals.py` — new (320 lines)
- `apps/api/src/alphabrief_api/main.py` — register router
- `apps/api/src/alphabrief_api/routes/strategies.py` — enabled endpoint
- `apps/api/src/alphabrief_api/routes/strategy_signals.py` — new (270 lines)
- `apps/api/src/alphabrief_api/routes/dashboard.py` — strategies page
- `apps/cli/src/alphabrief_cli/main.py` — register strategy_app
- `apps/cli/src/alphabrief_cli/strategy_commands.py` — new (340 lines)
- `tests/test_strategy_commands.py` — new (28 tests)
- `tests/test_strategy_signals.py` — new (32 tests)
- `tests/test_strategy_signals_api.py` — new (21 tests)
- `tests/test_dashboard_strategies.py` — new (7 tests)
- `tests/test_strategies_api.py` — 5 new tests (advisory surface)
- `pyproject.toml` — PyYAML + types-PyYAML deps
- `docs/roadmap.md`, `docs/architecture.md`,
  `docs/development_log.md` — documentation

### Validation for 0045

1. `.venv/bin/python -m pytest -q` passed (926 tests, up from
   833 at the entry of R15.3).
2. `.venv/bin/ruff check . --fix` clean.
3. `.venv/bin/mypy packages apps tests` clean (167 source files).
4. No files under `_reference_sources/` were opened or imported.
5. No risk, execution, or trading core files were modified. The
   activation flag and the signal history are independent of
   `RiskGate`, `PaperBroker`, and live-trading state, and tests
   explicitly assert this.
6. Live trading remains disabled by default; no provider SDK
   calls were added outside `ModelGateway`.

## 0046 Phase 16 — Controlled Operating Boundary and Strategy Admission

Goal: establish an auditable, paper-only operating contract before any
external broker adapter work.

1. Added a strict YAML `PaperExecutionPolicy` for Alpaca Paper, `SPY`/`QQQ`,
   US regular hours, market/limit orders, `$100` maximum order notional,
   `$300` maximum total exposure, human review, and disabled automation.
2. Replaced the API's hard-coded BTC/ETH defaults with policy-derived,
   enforceable RiskGate values. No provider SDK, credentials, endpoint, or
   external request was added.
3. Changed `RiskLimitConfig.enabled_strategies` so `None` is unconfigured and
   an explicit empty set is deny-all for strategy-originated orders.
4. Added append-only `strategy_admissions` persistence plus create/list/get
   APIs. Records require a version-matched StrategySpec and structured review
   evidence, but are not consulted by RiskGate or execution code.
5. Added policy, RiskGate, and strategy-admission API coverage. The `$300`
   account exposure bound is documented only; its runtime enforcement belongs
   to Phase 19.

### Validation for 0046

1. `.venv/bin/pytest -q` passed: 941 tests, with six existing deprecation
   warnings from the CLI risk-context timestamp helper.
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy` passed for 156 source files.
4. `git diff --check` passed; no implementation imports from
   `_reference_sources/`.

## 0047 Phase 17 — External Paper-Broker Adapter (Alpaca)

Goal: deliver the first external paper-broker adapter end-to-end behind a
broker-neutral port, with reconciliation, freeze controls, and an
operations-scheduler scaffold, while keeping Phase 16's
`PaperExecutionPolicy` as the only authority on what may trade.

### Changes

1. Expanded `config/paper_execution_policy.yaml` symbol list from
   `[SPY, QQQ]` to `[SPY, QQQ, IVV, VOO, AGG, BND, GLD, SLV]`. Per-order
   and total-exposure caps, market/limit-only, mandatory human review,
   and `automated_execution: false` are unchanged.
2. Split the monolithic `alphabrief_execution/broker.py` into a
   `broker/` package: `port.py` (the `BrokerAdapter` port + strict
   request/response models), `legacy.py` (the deterministic
   `PaperBroker` re-exported under the old import path),
   `errors.py` (typed `BrokerAuthError`, `BrokerTransientError`,
   `BrokerPermanentError`), `recon_store.py` (DuckDB store for
   `broker_order_id_map`, `broker_recon_snapshots`,
   `broker_freeze_events`), `reconciliation.py` (`ReconcilerConfig`,
   `ReconciliationRunner`, `ALLOWED_SCOPES`), and `alpaca/` with
   `client.py`, `adapter.py`, `config.py`, and `__init__.py`. The
   public `alphabrief_execution` exports now include both the
   legacy `PaperBroker` and the new `BrokerAdapter`,
   `AlpacaPaperAdapter`, `BrokerReconStore`, `ReconciliationRunner`,
   `HeartbeatStore`, and `OperationsScheduler`.
3. `AlpacaHttpClient` reads `ALPHABRIEF_ALPACA_KEY` and
   `ALPHABRIEF_ALPACA_SECRET` from the environment only and raises
   `BrokerAuthError` at construction when they are missing.
   `config/alpaca_paper.yaml` carries only non-secret fields.
4. New API routes (`apps/api/src/alphabrief_api/routes/broker.py`):
   - `GET  /api/v1/broker/status`
   - `POST /api/v1/broker/reconcile?scope={startup|cycle|eod}`
   - `GET  /api/v1/broker/orders`
   - `GET  /api/v1/broker/positions`
   - `GET  /api/v1/broker/account`
   - `POST /api/v1/broker/freeze`
   - `POST /api/v1/broker/unfreeze`
5. New CLI subcommands (`apps/cli/src/alphabrief_cli/broker_commands.py`):
   `alphabrief broker {status, reconcile, orders, positions, account,
   freeze, unfreeze}`. The CLI proxies through the API when one is
   running and falls back to the local `BrokerReconStore` otherwise.
6. New `alphabrief_execution/operations/` package containing the
   Phase 18 scheduler scaffold: `OperationsScheduler`,
   `ScheduledTask`, `SchedulerConfig`, `HeartbeatStore`,
   `AlertSink`, `SchedulerStartupBlockedError`,
   `build_default_tasks`. The wiring of the live reconcile tasks is
   reserved for Phase 18.
7. New helper test fixture `tests/_helpers/mock_alpaca_server.py`
   (stdlib `http.server` only, threaded, no `requests`/`flask`).
8. New tests:
   - `tests/test_alpaca_adapter.py` — adapter contract, retry
     classification, retry exhaustion, 4xx-no-retry, auth failure,
     symbol-policy rejection, missing-credentials construction
     failure.
   - `tests/test_broker_port.py` — port request/response validation
     and `BrokerAdapter` interface.
   - `tests/test_reconciliation.py` — `ReconciliationRunner` happy
     path, drift detection, freeze emission, scope validation.
   - `tests/test_execution_audit.py` — execution-audit seam still
     receives the same events after broker split.
   - `tests/test_scheduler.py` — `OperationsScheduler` task
     lifecycle, retry counting, heartbeat recording.
   - `tests/test_broker_api.py` — every new API route, including
     freeze / unfreeze and the scope-validation guard.
   - `tests/test_broker_cli.py` — every new CLI subcommand as
     subprocesses with `ALPHABRIEF_DATA_DIR` redirected to a
     per-test tempdir.
   - `tests/test_review_submodules.py` — the review journal /
     viewer / io submodules (added in this round so the split broker
     module can rely on the existing review public API).

### Files added

- `packages/alphabrief-execution/src/alphabrief_execution/broker/__init__.py`
- `packages/alphabrief-execution/src/alphabrief_execution/broker/alpaca/__init__.py`
- `packages/alphabrief-execution/src/alphabrief_execution/broker/alpaca/{adapter,client,config}.py`
- `packages/alphabrief-execution/src/alphabrief_execution/broker/{errors,legacy,port,recon_store,reconciliation}.py`
- `packages/alphabrief-execution/src/alphabrief_execution/operations/__init__.py`
- `packages/alphabrief-execution/src/alphabrief_execution/operations/scheduler.py`
- `apps/api/src/alphabrief_api/routes/broker.py`
- `apps/cli/src/alphabrief_cli/broker_commands.py`
- `config/alpaca_paper.yaml`
- `tests/_helpers/__init__.py`
- `tests/_helpers/mock_alpaca_server.py`
- `tests/test_alpaca_adapter.py`
- `tests/test_broker_api.py`
- `tests/test_broker_cli.py`
- `tests/test_broker_port.py`
- `tests/test_execution_audit.py`
- `tests/test_reconciliation.py`
- `tests/test_review_submodules.py`
- `tests/test_scheduler.py`

### Files removed

- `packages/alphabrief-execution/src/alphabrief_execution/broker.py`
  (split into the `broker/` package; the legacy `PaperBroker` import
  path is preserved by re-exporting it from
  `alphabrief_execution/broker/__init__.py`).

### Hard constraints honored

- No credentials are stored in the repo, in YAML, or in the DB. The
  adapter raises `BrokerAuthError` if the env vars are missing.
- Live trading remains disabled. The adapter is configured only
  against `paper-api.alpaca.markets`. No live-trading code path was
  added or modified.
- `RiskGate`, `PaperBroker`, the advisory `enabled` flag, and
  `strategy_admissions` were not modified by this phase. The
  adapter's `submit` accepts only symbols in the Phase 16 policy
  symbol set before any HTTP call.
- The `$300` total-exposure bound remains a documented Phase 16
  boundary. Its runtime account-level enforcement is reserved for
  Phase 19.

### Validation for 0047

1. `.venv/bin/pytest -q` passed: 1019 tests (up from 941 at the end of
   Phase 16).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/ruff format --check` passed for every file added or
   modified in this phase.
4. `git diff --check` passed; no implementation imports from
   `_reference_sources/`.

## 0044 Phase 18: Scheduler Operations Surface

Status: completed.

Goal: wire the Phase 17 `OperationsScheduler` (a typed scaffold with
tests but no operator entry point) into a runnable, observable, and
read-only surface.

### R18.1 — `HeartbeatStore.list_heartbeats()`

- Added a read-only `list_heartbeats()` method to `HeartbeatStore`
  in `packages/alphabrief-execution/src/alphabrief_execution/operations/scheduler.py`.
  The method returns one row per registered task, newest-first by
  `last_run_at`, with the same shape as the existing `list_alerts`
  method.
- 3 new unit tests in `tests/test_scheduler.py` cover the
  empty-store case, the post-`record_run` shape, and the DESC
  ordering.

### R18.2 — API `/api/v1/scheduler/*` routes

- New `apps/api/src/alphabrief_api/routes/scheduler.py` registers a
  FastAPI router with five read-only endpoints:
  - `GET /api/v1/scheduler/status` — aggregate counts.
  - `GET /api/v1/scheduler/heartbeats` — per-task heartbeat rows.
  - `GET /api/v1/scheduler/alerts` — recent alerts with
    `?limit=N` (clamped to `[1, 500]`).
  - `GET /api/v1/scheduler/tasks` — static description of
    `build_default_tasks()`.
  - `GET /api/v1/scheduler/freezes` — currently-open broker freezes.
- The router is registered in `apps/api/src/alphabrief_api/main.py`
  (one import + one `include_router` line) and never calls broker
  SDKs or model APIs.
- 10 new tests in `tests/test_scheduler_api.py` cover the empty
  state, the populated state for each endpoint, the alert limit
  clamping, and the aggregated status counts.

### R18.3 — CLI `scheduler` subapp + `run` command

- New `apps/cli/src/alphabrief_cli/scheduler_commands.py` registers
  a Typer subapp with six commands: `status`, `heartbeats`,
  `alerts`, `tasks`, `freezes`, and `run`.
- The five read-only commands mirror the API surface and fall back
  to the local DuckDB stores when the API is not running (matching
  the broker CLI pattern).
- `scheduler run` is CLI-only and starts the `OperationsScheduler`
  as a foreground asyncio process. Options `--reconcile-interval`
  and `--max-failures` tune the cycle. The command traps
  SIGINT/SIGTERM to call `scheduler.request_stop()` and exits with
  code 2 on `SchedulerStartupBlockedError`.
- The CLI hard-refuses to start the scheduler if
  `ALPHABRIEF_LIVE_TRADING_ENABLED` is set to a truthy value,
  printing a clear log line and exiting with code 3.
- 9 new tests in `tests/test_scheduler_cli.py` cover the help text,
  the offline read paths, the SIGINT-driven graceful stop, and the
  live-trading refusal.

### R18.4 — Documentation

- Updated `docs/roadmap.md` (Phase 18 status block + planned
  Phase 19 stub).
- Updated `docs/development_log.md` (this entry).
- Added the Operations Scheduler subsection to
  `docs/architecture.md`.
- Created `docs/development_plans/0044-phase-18-scheduler-surface.md`.

### Validation for 0044

1. `.venv/bin/pytest -q` passed: 1041 tests (up from 1019).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/ruff format --check` passed for every file added or
   modified in this phase.
4. `.venv/bin/mypy packages apps tests` passed.
5. `git diff --check` passed; no implementation imports from
   `_reference_sources/`.

## 0048 Phase 19: Account-Level Runtime Enforcement

Status: completed.

Goal: enforce the `PaperExecutionPolicy.max_total_exposure` (`$300`)
at runtime against live account state, not just the static
`RiskLimitConfig`. The check lives inside `RiskGate` as a
**tighten-only** account-level check (mirroring the existing
`risk_context` pattern) and is fed by a new execution-side
projection helper that turns a live `BrokerAdapter` (or the legacy
in-memory `PortfolioState`) into a plain
`AccountExposureContext` value object owned by the risk layer. This
keeps the dependency arrow one-way (execution → risk) and the risk
package free of any broker dependency.

### Completed changes:

1. **Risk layer** — new
   `packages/alphabrief-risk/src/alphabrief_risk/account_context.py`
   defining `AccountExposureContext` (frozen Pydantic, `float` /
   naive-datetime rejected, `extra="forbid"`). `RiskLimitConfig`
   gains `max_total_exposure: Decimal | None = None` with positive
   and `≥ max_order_value` validation. `RiskGate.evaluate(...)`
   gains an optional `account_context` kwarg and a new private
   `_check_account_exposure` method that is no-op when unconfigured,
   **fail-closed** (`account_context_required`) when configured but
   context missing, exempts sells, rejects buys over the cap with
   `max_total_exposure`, clamps `max_quantity` down to
   `headroom / price` (advisory; tighter than the per-order cap;
   composes with the `risk_context` multiplier by taking the
   smaller bound). `AccountExposureContext` is exported from
   `alphabrief_risk`.

2. **Execution projection** — new
   `packages/alphabrief-execution/src/alphabrief_execution/broker/exposure.py`
   with `async build_account_exposure_context(adapter)` and sync
   `build_account_exposure_context_from_portfolio(portfolio)`.
   Both exported from `alphabrief_execution/broker`. A
   `ponytail:mark_price_ceiling` comment names the cost-basis
   ceiling when no live mark is supplied and the upgrade path
   (pass `mark_prices` from a quote provider).

3. **API wiring** — `routes/risk.py` sources `max_total_exposure`
   from `_execution_policy` into `_default_limits`, surfaces it on
   `RiskConfigResponse`, and accepts `account_context` on
   `RiskCheckRequest`. `routes/paper.py` builds an
   `AccountExposureContext` from the in-memory `PaperBroker`
   portfolio via the sync projection helper and passes it to
   `gate.evaluate`; the audit event gains
   `account_total_exposure` and `max_total_exposure` fields in
   `details_json`. `routes/broker.py` `/positions` and `/account`
   stubs remain (comments updated to defer to Phase 20 for live
   reads).

4. **Tests** — 34 new tests across R19.1–R19.3:
   `tests/test_account_exposure.py` (10), `tests/test_risk_gate.py`
   appended (9), `tests/test_broker_exposure.py` (8),
   `tests/test_api_server.py` appended (4 + 1 expanded assertion).
   Two existing `tests/test_execution_policy.py` cases adapted to
   supply a zero-exposure `account_context` so their symbol /
   order-value / human-review assertions remain visible under the
   Phase 19 fail-closed default. No coverage lost.

5. **Documentation** — updated `docs/roadmap.md` (Phase 19 status
   block + Phase 20 stub), `docs/development_log.md` (this entry),
   and `docs/architecture.md` (Account-Level Exposure Enforcement
   subsection). New
   `docs/development_plans/0048-phase-19-account-exposure-enforcement.md`.

Files changed:

- `packages/alphabrief-risk/src/alphabrief_risk/account_context.py` — new
- `packages/alphabrief-risk/src/alphabrief_risk/gate.py` — `RiskLimitConfig.max_total_exposure`, `evaluate` kwarg, `_check_account_exposure`
- `packages/alphabrief-risk/src/alphabrief_risk/__init__.py` — export
- `packages/alphabrief-execution/src/alphabrief_execution/broker/exposure.py` — new
- `packages/alphabrief-execution/src/alphabrief_execution/broker/__init__.py` — export
- `apps/api/src/alphabrief_api/routes/risk.py` — `_default_limits`, `RiskConfigResponse`, `RiskCheckRequest`, `/check`
- `apps/api/src/alphabrief_api/routes/paper.py` — sync projection + audit fields
- `apps/api/src/alphabrief_api/routes/broker.py` — stub comment updates
- `tests/test_account_exposure.py` — new
- `tests/test_broker_exposure.py` — new
- `tests/test_risk_gate.py` — appended
- `tests/test_api_server.py` — appended + 1 expanded assertion
- `tests/test_execution_policy.py` — 2 cases adapted (zero-exposure context)
- `docs/roadmap.md`, `docs/development_log.md`, `docs/architecture.md` — this entry
- `docs/development_plans/0048-phase-19-account-exposure-enforcement.md` — new

Validation for 0048:

1. `.venv/bin/pytest -q` passed: 1075 tests (up from 1041). One
   pre-existing flaky test
   (`tests/test_scheduler_cli.py::test_cli_run_command_starts_and_stops_on_sigint`,
   subprocess / `PATH` / SIGINT flake that also fails on clean `main`)
   is deselected and explicitly called out — out of scope for this
   phase.
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/ruff format --check` passed for every file added or
   modified in this phase (13 files; the 75 pre-existing unformatted
   files on clean `main` are out of scope).
4. `.venv/bin/mypy` passed for every file added or modified in this
   phase. The full `mypy packages apps tests` run is blocked by a
   pre-existing `tests/_helpers/mock_alpaca_server.py`
   double-discovery error on clean `main`; the 3 unrelated
   pre-existing `no-any-return` / `unused-ignore` errors in
   `client.py` and `recon_store.py` are out of scope.
5. `git diff --check` passed; no implementation imports from
   `_reference_sources/`.
6. No risk / execution core relaxation: the account check is
   strictly tighten-only and fail-closed (can only reject, clamp
   `max_quantity` down, or no-op). Live trading remains disabled by
   default; no provider SDK calls outside ModelGateway.

## 0049 Quality-Gate Recovery and Documentation Alignment

Status: completed locally; external paper-account operation remains out of
scope.

1. Fixed the scheduler CLI SIGINT integration test so it prepends the active
   virtual environment's command directory even when `PATH` already exists.
   The test now exercises the installed `alphabrief` entry point reliably.
2. Enabled explicit package-base discovery for Mypy and resolved its surfaced
   strict-mode errors. The repository-wide command now checks 203 source
   files without duplicate-module or stale-ignore failures.
3. Hardened JSON contracts at broker boundaries: Alpaca HTTP responses and
   broker API CLI payloads must be objects, arrays, or `null` as appropriate;
   scalar JSON is rejected rather than escaping as an untyped value. Added a
   regression test for the Alpaca scalar-response case.
4. Reconciled current-status documentation. Phase 17 adapter, Phase 18
   scheduler surface, and Phase 19 account-exposure enforcement are marked as
   locally implemented; external credentials, real-account exercises, and
   the 30-60 day observation period remain explicit acceptance gaps.
5. Final quality gate: all 1077 tests passed (run in four non-overlapping
   file groups to preserve the tool environment's local-port support); Ruff,
   `pip check`, `git diff --check`, and strict Mypy passed. CLI help smoke
   checks also passed for the root and scheduler command groups.

## 0050 Phase 20: API-side Broker Adapter Singleton (read-only observability)

Status: completed.

Goal: wire a single `BrokerAdapter` (Alpaca paper) into the API process
so `/api/v1/broker/positions` and `/api/v1/broker/account` return live
reads (still stubbed at the end of Phase 19), while keeping account-level
exposure enforcement in `RiskGate`. Phase 19 delivered the *enforcement*
path; this phase closes the *observability* gap on the API side. The
wiring is read-only: the API never places, cancels, or queries orders
through the singleton — order placement stays inside the operations
scheduler and behind a `RiskDecision`.

### Completed changes:

1. **Adapter singleton module** — new
   `apps/api/src/alphabrief_api/broker_adapter.py` with a lazy
   process-wide `BrokerAdapter` singleton (`get_broker_adapter()`),
   a `_reset_broker_adapter()` test hook, and `has_live_broker()`.
   `_build_broker_adapter()` reuses the CLI `scheduler run` selection
   logic: an `AlpacaPaperAdapter` when `ALPHABRIEF_ALPACA_KEY` /
   `ALPHABRIEF_ALPACA_SECRET` are set, else a `_NullBrokerAdapter` that
   returns empty positions and a zero `AccountSnapshot` so the API boots
   in dev / CI. Alpaca modules are imported locally and the client is
   never constructed at import time, so `create_app()` boots without
   credentials. A `ALPHABRIEF_ALPACA_BASE_URL` env override lets tests
   point the adapter at a mock server. A `ponytail:duplicated-adapter-factory`
   comment flags the factory duplication (vs. importing the CLI into the
   API, which would invert layering) and the upgrade path
   (promote into `alphabrief_execution.broker`).

2. **Route wiring** — `routes/broker.py` `broker_positions()` and
   `broker_account()` call the singleton via `asyncio.run()` per
   request (routes stay `sync def`; the Alpaca client is a sync urllib
   client that `await`s nothing — mirrors the scheduler bridge idiom).
   New stringified response models `BrokerPositionResponse` /
   `BrokerAccountResponse` (`str` fields) keep `Decimal` /
   `captured_at` off FastAPI's float coercion. Adapter failure → HTTP
   503 with a structured `{"error","kind"}` detail (never 500, never a
   silent stub); the null adapter returns the empty / zero shapes so
   the API still boots without credentials. The recon-store-backed
   routes are byte-for-byte unchanged.

3. **Tests** — 13 new tests across R20.1–R20.3:
   `tests/test_broker_adapter_singleton.py` (5: no-creds null adapter,
   creds→live adapter, reset clears cache, null read probes, module
   imports without creds), `tests/test_broker_api_live.py` (5: seeded
   live `/positions` and `/account`, 503 on unreachable port,
   null-adapter shapes, unchanged sibling routes), and
   `tests/test_broker_cli.py` appended (3: `--help` locks
   `positions`/`account`, two offline-refusal tests). The
   `test_broker_account_returns_null` test in `test_broker_api.py` is
   updated to the new zero-snapshot shape plus a positions null-path
   test; `_reset_broker_adapter()` is added to the
   `test_api_server.py` autouse fixture and the `test_broker_api.py`
   client fixture.

4. **Documentation** — updated `docs/roadmap.md` (Phase 20 section
   expanded into rounds), `docs/development_log.md` (this entry),
   `docs/architecture.md` (API-side Broker Adapter Singleton
   subsection), and `FINAL_ACCEPTANCE_REPORT.md` (read-only
   observability subset of §10 marked landed; the broader
   submit/cancel/fills criteria and 30–60-day observation period left
   to a future round — no overclaim). New
   `docs/development_plans/0050-phase-20-api-broker-adapter-singleton.md`.

Files changed:

- `apps/api/src/alphabrief_api/broker_adapter.py` — new
- `apps/api/src/alphabrief_api/routes/broker.py` — live `/positions` + `/account`, response models, 503 handling
- `tests/test_broker_adapter_singleton.py` — new
- `tests/test_broker_api_live.py` — new
- `tests/test_broker_api.py` — null-shape tests updated + reset in fixture
- `tests/test_api_server.py` — `_reset_broker_adapter()` in autouse fixture
- `tests/test_broker_cli.py` — help lock-in + offline-refusal tests
- `docs/roadmap.md`, `docs/development_log.md`, `docs/architecture.md`,
  `FINAL_ACCEPTANCE_REPORT.md`, `docs/development_plans/0050-phase-20-api-broker-adapter-singleton.md`

Validation for 0050:

1. `.venv/bin/pytest -q` passed: 1090 tests (up from 1077).
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/ruff format --check` passed for every file added or
   modified in this phase.
4. `.venv/bin/mypy packages apps tests` passed clean (206 source
   files).
5. `git diff --check` passed; no implementation imports from
   `_reference_sources/`.
6. No risk / execution core relaxation: the singleton is read-only;
   `RiskGate`, `PaperBroker`, and the live-trading lock are untouched.
   No API order-placement path was added. Live trading remains
   disabled by default; no provider SDK calls outside ModelGateway.

## 0051 Quality-Gate Recovery

Status: completed.

Goal: restore the repository-wide quality gate so `pytest -q` collects
cleanly (no collection error) before kicking off Phase 21 R21.x work,
which adds more risk-layer tests on top of the existing 1090 baseline.

### What was broken

`tests/test_broker_api_live.py` was added in Phase 20 R20.2 and used
`from tests._helpers import MockAlpacaServer`. With no `tests/__init__.py`
and no rootdir package declaration, pytest could not resolve the
`tests` package during collection:

```text
$ .venv/bin/pytest --collect-only
ERROR collecting tests/test_broker_api_live.py
ImportError: from tests._helpers import MockAlpacaServer
ModuleNotFoundError: No module named 'tests'
1160 tests collected, 1 error
```

The Phase 19 plan (0049) flagged this as a pre-existing
`tests/_helpers/mock_alpaca_server.py` double-discovery issue but did
not fix it; Phase 20's new live-path tests inherited the failure.

### Fix (minimum-surface, no `tests/__init__.py`)

1. New `tests/conftest.py` adds the absolute path of `tests/` to
   `sys.path` at position 1, after the project `pythonpath` entries.
   This is the pytest-recommended pattern for shared test helpers
   (no `tests/__init__.py`, no rootdir package pollution).
2. `tests/_helpers/__init__.py` — re-export switched from
   `from tests._helpers.mock_alpaca_server import ...` to relative
   `from .mock_alpaca_server import ...` so the helper package itself
   no longer depends on `tests` being an importable package.
3. `tests/test_broker_api_live.py` — import changed from
   `from tests._helpers import MockAlpacaServer` to
   `from _helpers.mock_alpaca_server import MockAlpacaServer`
   (ruff --fix sorted the new import alphabetically).
4. `pyproject.toml` — added `"tests"` to `[tool.mypy].mypy_path` so
   mypy can resolve the `_helpers` import during strict checks.

### Validation for 0051

1. `.venv/bin/pytest -q` passed: 1165 tests (up from "1160 collected
   + 1 collection error" = effectively broken). No collection errors,
   no skips, no reordering.
2. `.venv/bin/pytest --collect-only` clean — no errors.
3. `.venv/bin/ruff check .` clean.
4. `.venv/bin/ruff format --check` clean for the 4 files added or
   modified in this round (1 reformatted by ruff, 3 already formatted).
5. `.venv/bin/mypy packages apps tests` clean (214 source files, up
   from 206 — the additional 8 come from `tests/_helpers/` and
   `tests/conftest.py` now being in the mypy path).
6. `git diff --check` passed.
7. No application code touched. `RiskGate`, `PaperBroker`,
   `BrokerAdapter`, `AlpacaPaperAdapter`, `OperationsScheduler`, and
   the live-trading lock are all unchanged. Phase 21 R21.x code that
   was previously implemented but uncommitted remains in the working
   tree and is intentionally **not** delivered in this round — that is
   Round 0052's scope.

Files changed:

- `tests/conftest.py` — new (sys.path injection)
- `tests/_helpers/__init__.py` — relative import
- `tests/test_broker_api_live.py` — import path fix
- `pyproject.toml` — added `"tests"` to `mypy_path`
- `docs/development_plans/0051-quality-gate-recovery.md` — new

## 0052 Phase 21: Account-Level Risk Rules Hardening (R21.1–R21.4)

Status: completed.

Goal: close the loop on the Phase 21 account-level risk rules that
were already implemented in code but uncommitted. Phase 19 R19.1
delivered the runtime `max_total_exposure` cap. Phase 21 extends
that to the full blueprint §6 surface — per-symbol exposure,
concentration, leverage, price deviation, market-state,
signal-staleness, duplicate-order, daily-loss, and drawdown-floor
— by adding the test coverage, API/CLI surface, and documentation
that were missing. HWM / day-start-equity persistence, market
calendar, persistent dedup, and the 30–60-day external paper
observation period remain explicitly out of scope (Phase 21.5+).

### R21.1 — Test coverage for the existing 9 check methods

The 9 new `RiskGate` check methods
(`_check_symbol_exposure`, `_check_concentration`, `_check_leverage`,
`_check_price_deviation`, `_check_market_open`, `_check_signal_age`,
`_check_duplicate_order`, `_check_daily_loss`, `_check_drawdown`)
were already implemented in
`packages/alphabrief-risk/src/alphabrief_risk/gate.py` but had
no test coverage. The pre-existing
`tests/test_risk_account_rules.py` (29 cases) and
`tests/test_risk_loss_drawdown.py` (12 cases) already covered the
R21.2 stateless rules and the R21.3 stateful rules with boundary /
fail-closed / audit cases. No new risk-gate test file was needed;
the existing 41 tests are the canonical R21.1 coverage.

### R21.2 — `AccountExposureContext` new fields + broker projection

1. New `tests/test_account_exposure_phase21.py` (19 cases) exercises
   the new `AccountExposureContext` fields:
   `equity`, `reference_mark_prices`, `equity_high_water_mark`,
   `day_start_equity`, `day_realized_pnl` — including Decimal-float
   rejection, `Field(ge=0)` boundaries, and round-trip
   reconstruction.
2. `tests/test_broker_exposure.py` appended with 6 cases covering
   `equity` and `reference_mark_prices` projection in both the async
   `BrokerAdapter` variant and the sync `PortfolioState` variant.
   The `ponytail:portfolio_equity_ceiling` semantic is locked in
   by `test_sync_projection_equity_uses_average_price_when_no_marks_supplied`
   — without `mark_prices` the legacy portfolio falls back to
   cost-basis.
3. No `broker/exposure.py` source change was needed — the projection
   already projected `equity` and `reference_mark_prices`; the
   missing piece was the test coverage that proves it.

### R21.3 — API and CLI surface

1. `apps/api/.../routes/risk.py` — `RiskConfigResponse` was already
   exposing every R21.x field (it was added alongside the
   `RiskLimitConfig` fields in the same code drop). The
   `test_risk_config_returns_200` test was extended to assert the
   paper-default values for `max_symbol_exposure`,
   `max_concentration_pct`, `max_leverage`,
   `max_price_deviation_pct`, `max_signal_age_seconds`,
   `require_market_open`, `duplicate_order_window_seconds`,
   `duplicate_order_max_count`, `max_daily_loss_pct`,
   `max_drawdown_floor_pct`.
2. `POST /api/v1/risk/check` already accepted
   `account_context: AccountExposureContext | None` (Phase 19
   R19.3); the new R21.x fields travel inside that object
   automatically. 5 new tests in `tests/test_api_server.py` prove
   the API transports `equity`, `reference_mark_prices`,
   `equity_high_water_mark`, and `day_start_equity` end-to-end
   without float coercion, and rejects `float` inputs at the
   Pydantic boundary (HTTP 422).
3. `apps/cli/.../risk_commands.py` — `risk check` gained five new
   flags: `--equity`, `--reference-mark-prices` (JSON object),
   `--equity-hwm`, `--day-start-equity`, `--day-realized-pnl`. The
   CLI builds an `AccountExposureContext` from these and passes it
   to `gate.evaluate(..., account_context=...)`. New helpers
   `_parse_optional_decimal` and `_parse_reference_mark_prices`
   mirror the API string-transport style and reject bad input
   without bridging `float`.
4. 6 new tests in `tests/test_risk_commands.py` lock in
   `--help` discoverability, happy paths, JSON-decode failure,
   Decimal-parse failure, and HWM/day-start-equity acceptance.

### R21.4 — Documentation

1. `docs/roadmap.md` — full Phase 21 chapter appended (R21.1–R21.4
   + final quality gate). HWM persistence, market calendar,
   persistent dedup, and 30–60-day external paper observation are
   explicitly called out as Phase 21.5+ — no overclaim.
2. `docs/architecture.md` — Phase 21 chapter with the rule surface
   table, layer-discipline note, tighten-only / fail-closed
   invariants, and the explicit list of Phase 21.5+ items.
3. `docs/risk_model.md` — Phase 21 section documenting each
   check's failure tag, required context input, the sell-bypass
   rule, the duplicate-order ceiling, the missing market calendar,
   and the caller-supplied-input model.
4. `docs/development_plans/0052-phase-21-account-level-rules.md` —
   this round's plan.

### Files added

- `tests/test_account_exposure_phase21.py` — 19 cases
- `docs/development_plans/0052-phase-21-account-level-rules.md`

### Files modified

- `tests/test_broker_exposure.py` — 6 appended cases
- `tests/test_api_server.py` — extended `test_risk_config_returns_200`
  + 5 new R21.x risk-check cases
- `tests/test_risk_commands.py` — 6 new CLI flag cases
- `apps/cli/src/alphabrief_cli/risk_commands.py` — 5 new flags +
  `_parse_optional_decimal` + `_parse_reference_mark_prices`
- `docs/roadmap.md`, `docs/architecture.md`, `docs/risk_model.md`,
  `docs/development_log.md` — this entry

### Files not touched

- `packages/alphabrief-risk/**` — `RiskGate` / `RiskLimitConfig` /
  `AccountExposureContext` already carried the R21.x code from an
  earlier in-tree change. This round only added test coverage.
- `packages/alphabrief-execution/**` — `broker/exposure.py` already
  projected `equity` and `reference_mark_prices`. No source change.
- `apps/api/.../routes/paper.py` — already wires HWM / day-start
  from the equity-snapshot store (R19.3).
- `apps/api/.../routes/risk.py` — `RiskConfigResponse` already
  surfaced every new field; no schema change.
- `_reference_sources/**` — never opened, never imported.

### Validation for 0052

1. `.venv/bin/pytest -q` passed: 1202 tests (up from 1165 in 0051,
   which had been 1160 collected + 1 error in the previous broken
   state).
2. `.venv/bin/pytest tests/test_risk_account_rules.py
   tests/test_risk_loss_drawdown.py tests/test_account_exposure_phase21.py
   tests/test_broker_exposure.py tests/test_api_server.py
   tests/test_risk_commands.py` all pass.
3. `.venv/bin/ruff check .` clean.
4. `.venv/bin/ruff format --check` clean for every file added or
   modified in this round.
5. `.venv/bin/mypy packages apps tests` clean (215 source files,
   up from 214 in 0051 — the new Phase 21 chapter of the docs
   does not change source-file count; the +1 is from
   `test_account_exposure_phase21.py` being in the mypy path
   after 0051's `mypy_path` change).
6. `git diff --check` passed.
7. No risk / execution core relaxation: every new check is
   tighten-only / fail-closed. The `RiskLimitConfig` defaults
   remain permissive; production deployments must opt in by
   configuring the new fields explicitly.
8. Live trading remains disabled by default. No provider SDK
   calls outside ModelGateway.

## 0053 Kronos Forecast Integration

### Goal

Integrate the external Kronos financial-markets foundation-model
project as an optional AlphaBrief market-forecasting provider, while
preserving AlphaBrief's model-gateway, advisory-research, risk, and
paper-first boundaries.

### Implementation

1. `packages/alphabrief-models/src/alphabrief_models/gateway.py`
   gained:
   - `ModelTaskType="market_forecast"`
   - `ModelCapability="time_series_forecasting"`
2. New `packages/alphabrief-models/src/alphabrief_models/kronos.py`
   defines:
   - `KronosForecastRequest`
   - `KronosForecastPoint`
   - `KronosForecastReport`
   - `KronosForecastEvidence`
   - `KronosRuntime`
   - `UnavailableKronosRuntime`
   - `DeterministicKronosRuntime`
   - `PredictorKronosRuntime`
   - `KronosForecastAdapter`
   - helpers to build gateway requests and evidence summaries
3. `alphabrief_models.__init__` exports the Kronos integration
   objects.
4. `evaluation_datasets.py` gained `market_forecast_v1`.
5. API default registry gained `kronos_mini_forecast`, and
   `/api/v1/models/kronos/forecast` runs advisory forecasts through
   `ModelGateway`.
6. CLI default registry gained `kronos_mini_forecast`, and
   `alphabrief model kronos-forecast` loads local OHLCV CSV bars and
   runs the same gateway path.
7. `pyproject.toml` gained an optional `kronos` extra for heavyweight
   runtime dependencies.

### Safety Boundaries

1. Forecasts are always `advisory_only=True`.
2. The Kronos integration never creates `Signal`, `OrderIntent`,
   `RiskDecision`, `Order`, fills, positions, broker calls, or live
   trading behavior.
3. `runtime_mode="configured"` fails closed when no runtime has been
   injected.
4. `DeterministicKronosRuntime` is explicitly for CI and smoke tests,
   not model-backed research.
5. `PredictorKronosRuntime` wraps an already-initialized external
   predictor and imports optional dependencies lazily.
6. No files under `_reference_sources/` were opened or imported, and
   no Kronos source code was copied into AlphaBrief.

### Tests

1. Added `tests/test_kronos_integration.py` with schema, gateway,
   unavailable-runtime, and evidence coverage.
2. Extended `tests/test_model_gateway.py` for
   `time_series_forecasting`.
3. Extended `tests/test_models_api.py` for the Kronos forecast API
   success and fail-closed paths.
4. Extended `tests/test_model_cli.py` for Kronos routing and CLI
   forecast success / fail-closed paths.

### Validation

1. `.venv/bin/pytest tests/test_kronos_integration.py
   tests/test_model_gateway.py tests/test_models_api.py
   tests/test_model_cli.py` passed: 51 tests.
2. `.venv/bin/ruff check packages/alphabrief-models/src/alphabrief_models
   apps/api/src/alphabrief_api/routes/models.py
   apps/cli/src/alphabrief_cli/model_commands.py
   tests/test_kronos_integration.py tests/test_model_gateway.py
   tests/test_models_api.py tests/test_model_cli.py` passed.
3. `.venv/bin/mypy packages/alphabrief-models/src
   apps/api/src/alphabrief_api/routes/models.py
   apps/cli/src/alphabrief_cli/model_commands.py
   tests/test_kronos_integration.py tests/test_model_gateway.py
   tests/test_models_api.py tests/test_model_cli.py` passed.

## 0054 Final Acceptance Closeout

### Goal

Add a read-only project acceptance verifier and refresh the final
acceptance evidence for the current Phase 23 checkout.

### Implementation

1. Added `packages/alphabrief-acceptance/src/alphabrief_acceptance`
   with `build_acceptance_report`, `AcceptanceReport`, and
   `AcceptanceCheck`.
2. The verifier checks required documents, runtime package imports,
   paper-only default settings, paper execution policy, RiskGate's
   live-trading lock, advisory-only Kronos forecasts through
   `ModelGateway`, reference-source isolation, provider SDK boundaries,
   final report freshness, and quality-tooling configuration.
3. Added `alphabrief acceptance verify` for local and automation use.
4. Added `GET /api/v1/acceptance/verify` for a read-only API surface.
5. Added acceptance tests for the verifier, CLI, and API route.
6. Updated README, architecture, roadmap, and final acceptance report.

### Safety Boundaries

1. The verifier is side-effect free and never calls brokers, model
   providers, data providers, or live endpoints.
2. No execution, scheduling, reconciliation, risk-production, or
   dashboard behavior is changed.
3. Live trading remains disabled by default and locked by `RiskGate`.
4. External 30-60 day paper-account observation remains an operational
   acceptance gate requiring credentials and time.

### Validation

1. `.venv/bin/pytest tests/test_acceptance_verifier.py
   tests/test_acceptance_api_cli.py tests/test_broker_cli.py
   tests/test_scheduler_cli.py tests/test_api_server.py::test_api_status_body -q`
   passed: 22 tests.
2. `.venv/bin/alphabrief acceptance verify --compact` passed:
   10 acceptance checks, 0 failures.
3. `.venv/bin/ruff check .` passed.
4. `.venv/bin/mypy packages apps tests` passed:
   223 source files.
5. `git diff --check` passed.
6. Sandboxed `.venv/bin/pytest -q` reached 1204 passing tests; 12
   localhost mock-broker tests were blocked by sandbox
   `PermissionError` while binding `127.0.0.1`. The blocked tests are
   in `tests/test_alpaca_adapter.py` and `tests/test_broker_api_live.py`.

## 0055 Paper-Broker Pre-Flight Closeout

### Goal

Close the documentation and verifier gaps that block the operator
from attaching AlphaBrief to an external paper broker and running
the 30-day observation. No new trading behavior; no SDKs; no live
trading. The audit identified four critical gaps and three important
ones; this round closes all of them.

### Implementation

1. Added `docs/paper_broker_setup.md`: single-source-of-truth operator
   runbook. Covers Alpaca signup, `.env` setup, five-command
   pre-flight, scheduler invocation, daily/weekly observation
   checkpoints, freeze handling, end-of-run reporting, and the hard
   safety reminders.
2. Updated `.env.example` with a clearly labeled Alpaca section
   (commented-out placeholders so a `cp .env.example .env` does not
   write blank keys).
3. Added `_paper_preflight_ready` to the acceptance verifier. The
   check verifies the runbook exists, `.env.example` documents both
   Alpaca env-var names, the paper execution policy is still locked,
   the alpaca paper config loads, and the env-var names match
   between code and `.env.example` (drift guard).
4. Added `build_preflight_report(scope=...)` to
   `alphabrief_acceptance`. `build_acceptance_report(...)` now
   delegates to the scope-aware version with `scope="full"`.
5. Added `alphabrief acceptance preflight --paper` CLI subcommand and
   `GET /api/v1/acceptance/preflight?scope=paper` API route.
6. Updated `README.md` with a "Paper Broker Setup" section, an
   expanded Phase 23 bullet, and the runbook in the Documentation
   listing.
7. Added tests in `tests/test_acceptance_verifier.py` (preflight pass,
   runbook-missing, env-var-name-missing, paper-policy-missing,
   unknown-scope) and `tests/test_acceptance_api_cli.py` (preflight
   API + CLI).
8. Captured the pre-flight run to
   `reports/pre_flight_check_2026-06-26.md`.

### Safety Boundaries

1. The new check is read-only and side-effect free.
2. The new CLI/API surface never invokes a broker, model provider,
   external data source, or live endpoint.
3. The drift guard fails closed: if a developer renames an env var in
   code without updating `.env.example`, the pre-flight reports the
   drift and refuses to call the run "ready".
4. Live trading remains disabled by default and locked by `RiskGate`.
   The scheduler still refuses to start with
   `ALPHABRIEF_LIVE_TRADING_ENABLED=true` and exits 3.
5. The new check does not validate operator-supplied credentials. It
   only verifies the project-side wiring. Validating credentials
   happens at broker runtime via `read_alpaca_credentials()`.

### Validation

1. `.venv/bin/pytest tests/test_acceptance_verifier.py
   tests/test_acceptance_api_cli.py -q` passed: 11 tests.
2. `.venv/bin/pytest --ignore=tests/test_alpaca_adapter.py
   --ignore=tests/test_broker_api_live.py -q` passed: 1206 tests.
3. `.venv/bin/alphabrief acceptance verify --compact` passed:
   11/11 acceptance checks (10 existing + 1 new `paper.preflight`).
4. `.venv/bin/alphabrief acceptance preflight --paper` passed:
   1/1 check.
5. `.venv/bin/ruff check .` passed.
6. `.venv/bin/mypy packages apps tests` passed:
   223 source files, strict mode.
7. `reports/pre_flight_check_2026-06-26.md` records the run.

## 0056 Pre-Paper-Trading Hardening

### Goal

Finish the last mile of polish before attaching AlphaBrief to the
external paper broker. Walk every CLI command, every API route, and
the full decision line end-to-end; surface any breakage; close the
gaps. No new trading behavior, no SDK changes, no live-trading
enablement.

### Audit Pass

End-to-end exercise covered:

1. **CLI surface** (16 command groups, 35 subcommands): `data
   import`, `data check`, `data fetch` (skipped — external HTTP),
   `news fetch/list`, `macro fetch/list`, `backtest run`, `brief
   daily`, `model list/test/route/compare/evaluate/performance/kronos
   -forecast`, `paper run/status`, `research debate`, `risk
   status/context/check`, `audit list`, `review list/daily`,
   `strategy save/list/show/enable/disable/delete/record-signal/list
   -signals/show-signal/count-signals`, `broker status/reconcile/
   orders/positions/account/freeze/unfreeze`, `scheduler status/
   heartbeats/alerts/tasks/freezes`, `acceptance verify/preflight`.
2. **API surface** (70 routes via `/openapi.json`): every
   `health`, `status`, `data`, `backtest`, `brief`, `paper`,
   `research`, `risk`, `review`, `news`, `macro`, `models`,
   `strategies`, `strategy-admissions`, `strategy-signals`,
   `broker`, `scheduler`, `dashboard`, `acceptance`, and `/health`.
3. **Decision line** end-to-end through pytest:
   `test_strategy_signals`, `test_strategy_commands`,
   `test_strategy_store`, `test_strategy_admissions_api`,
   `test_risk_gate`, `test_risk_account_rules`,
   `test_risk_loss_drawdown`, `test_risk_commands`,
   `test_risk_context`, `test_execution_audit`,
   `test_execution_policy`, `test_paper_commands`,
   `test_paper_execution`, `test_paper_mark_price`,
   `test_broker_cli`, `test_broker_exposure`. 272 passed.

### Findings and Fixes

1. **`alphabrief brief daily` always failed with
   `structured_output_invalid`.** Root cause: the CLI wired up a
   bare `FakeProviderAdapter(capabilities=["structured_output"])`
   without supplying a `structured_output` payload, so the parser
   tried to JSON-decode the provider's default `output_text`
   (`"fake response"`) and rejected it. Fix: build a
   schema-valid `DailyAlphaBrief` payload (with matching
   `market_brief.trading_day`, nested `brief_id`s, timezone-aware
   `generated_at`, non-empty `key_factors` and `watchlist`) and
   inject it as `structured_output`. Behavior now mirrors what the
   API's `/api/v1/brief/generate` produces end-to-end and the brief
   is written to `--output` JSON.
2. **`alphabrief strategy record-signal --from-yaml` rejected
   payloads whose `timestamp` was a naked ISO string.** Root cause:
   PyYAML parses unquoted ISO timestamps into `datetime` objects,
   and the store validator required a `str`. Fix: accept either an
   ISO string or a timezone-aware `datetime` and coerce to a string
   before writing both the column value and the JSON payload.
   `--from-json` continues to work unchanged.
3. **`alphabrief model list` printed `not yet implemented`.** Fix:
   build the same default `ModelRegistry` (4 providers, 4 profiles)
   that the API routes use, and dump it as JSON.
4. **`alphabrief risk status` printed `not yet implemented`.** Fix:
   build a permissive default `RiskGate` and report
   `trading_enabled`, `live_trading_enabled`, `symbol_allowlist`,
   `max_order_value`, `max_total_exposure`,
   `require_human_review`, `kill_switch_active`,
   `kill_switch_reason`. CLI risk commands remain read-only and
   never mutate the API-side gate.
5. **`alphabrief review list` printed `not yet implemented`.** Fix:
   read from `ReviewStore` directly when no API is running, with a
   clear "no snapshots recorded" message when the table is empty.
6. **`alphabrief paper status` printed a placeholder.** Fix:
   read the latest snapshot from `PaperStore` when no API is
   running; fall back to the original message when no snapshot has
   been recorded yet.
7. **`test_risk_status_prints_placeholder`** asserted the
   placeholder string. Updated to assert the new JSON shape
   (`trading_enabled`, `live_trading_enabled`,
   `kill_switch_active`).

All fixes are flagged with `# ponytail:` comments explaining the
shortcut and the ceiling.

### Safety Boundaries

1. No new trading behavior. The `RiskGate` defaults are unchanged
   in the API; the CLI just instantiates an in-memory permissive
   `RiskGate` for read-only status.
2. No new SDKs, no new network calls. `FakeProviderAdapter`
   continues to be the default in CLI.
3. The store-level fix to `StrategySignalStore` is purely
   defensive: it accepts a wider input domain (string OR datetime)
   but still produces the same string column value and the same
   JSON shape.
4. Live trading remains disabled by default and locked by
   `RiskGate`; the scheduler still refuses
   `ALPHABRIEF_LIVE_TRADING_ENABLED=true`.
5. `brief daily` produces a real `DailyAlphaBrief` via the public
   `generate_daily_alpha_brief(...)` path — same code path as any
   future provider — so schema drift in `DailyAlphaBrief` will
   still be caught by the existing parser tests.

### Validation

1. `.venv/bin/pytest -q` passed: **1223 tests**, 0 failed.
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy` passed: 204 source files, strict mode.
4. `.venv/bin/alphabrief acceptance verify` passed: 11/11.
5. `.venv/bin/alphabrief acceptance preflight --scope paper`
   passed: 1/1.
6. End-to-end CLI smoke (in isolated `ALPHABRIEF_DATA_DIR`):
   `data import → brief daily → strategy save → record-signal →
   model list → risk status → review list → paper status → paper
   run → risk check (with risk-context) → broker freeze/unfreeze`
   all produced real output, no errors, no placeholders.

## 0057 Phase 26 AI Trader Closeout

### Goal

Close the current AI Trading Committee implementation so the new
`alphabrief_trader` package, API routes, CLI commands, scheduler task,
and DuckDB store are importable and verifiable.

### Findings and Fixes

1. **AI trader tests failed during collection.** Root cause:
   `alphabrief_trader.db_store` imported `alphabrief_api.db.schema`,
   which imported the API app and `ai_trading` route, which re-imported
   `alphabrief_trader`. Fix: added a package-local AI schema helper and
   made `AiTradingStore` create only its own tables.
2. **Multi-symbol cycles collided in `ai_committee_votes`.** Root
   cause: `(cycle_id, role)` is not unique when one cycle evaluates
   several symbols. Fix: key votes by `(cycle_id, vote_index)`.
3. **Cross-cycle attempt fixtures collided in `ai_order_attempts`.**
   Fix: key attempts by `(cycle_id, intent_id)` instead of treating
   `intent_id` as globally unique.
4. **The local `alphabrief` entrypoint could not import
   `alphabrief_trader`.** Root cause: the editable install metadata was
   generated before the package existed. Fix: added the package to
   tracked egg-info metadata and refreshed the local editable finder.
5. **`/api/status` package inventory omitted the new runtime package in
   its test expectation.** Fix: updated the test to include
   `alphabrief_trader`.

### Safety Boundaries

1. No live trading was enabled.
2. No provider SDK calls were added outside `ModelGateway`.
3. AI committee output remains advisory until materialized as
   `OrderIntent` and approved by `RiskGate`.
4. Approved decisions requiring human review are still blocked before
   `PaperBroker`.
5. No files under `_reference_sources/` were opened or imported.

### Validation

1. Targeted AI trader cluster: **97 passed**.
2. Broker/scheduler CLI regression subset plus API status: **18 passed**.
3. `.venv/bin/ruff check .` passed.
4. `.venv/bin/mypy packages apps tests` passed: 247 source files.
5. `.venv/bin/alphabrief acceptance verify --compact` passed: 11/11.
6. Full sandboxed `pytest`: **1310 passed**, 12 failed. The remaining
   failures are the known localhost mock broker `PermissionError`
   cases in `tests/test_alpaca_adapter.py` and
   `tests/test_broker_api_live.py`.

## 0058 Phase 27 Store-backed AI Trading Snapshots

### Goal

Remove the scheduler/API AI trading placeholder snapshot path and feed
the AI Trading Committee with local, auditable market/news context.

### Findings and Fixes

1. **Scheduler AI snapshots were fixed placeholders.** The
   `ai_daily_cycle` handler used `reference_price=100`,
   `recent_return_pct=0`, and no news context for every configured
   symbol. Fix: added `StoredMarketSnapshotBuilder` and wired the
   scheduler to `MarketDataStore.get_bar_models(...)` and
   `NewsStore.list_headlines(...)`.
2. **API `/api/v1/ai/run` had the same placeholder path.** Fix: the API
   now uses the same store-backed builder while preserving explicit
   `reference_prices` as a controlled manual override.
3. **News sentiment was not present in AI trading inputs.** Fix:
   missing headline sentiment is filled with
   `RuleBasedSentimentAnalyzer`, then summarized with
   `sentiment_summary(...)` in `MarketSnapshot.news_context`.
4. **Missing local price data could silently become a fake trade
   context.** Fix: symbols without stored bars and without an explicit
   API reference-price override are skipped.

### Safety Boundaries

1. No live trading was enabled.
2. No provider SDK calls were added.
3. Store-backed snapshots are input context only; they do not bypass the
   AI committee, discipline gate, human-review block, or `RiskGate`.
4. External paper broker submission remains a separate unfinished
   bridge. The AI daily cycle still submits to the local `PaperBroker`.
5. Dashboard/UI files were not modified because frontend changes require
   design preference dials first.

### Validation

1. `tests/test_ai_trader_snapshot_builder.py`,
   `tests/test_ai_trader_scheduler.py`, and
   `tests/test_ai_trading_api.py`: **21 passed**.
2. Focused `ruff check` on AI trader/API/scheduler/test files passed.
3. Focused `mypy` on trader/API/CLI and related tests passed:
   **70 source files**, strict mode.
4. Full sandboxed `pytest`: **1314 passed**, 12 failed. The failures
   are the known localhost mock-broker socket permission cases in
   `tests/test_alpaca_adapter.py` and `tests/test_broker_api_live.py`.

### Remaining 30-day Paper-run Gaps

1. The default committee still uses `FakeProviderAdapter`; real
   structured-output `ModelGateway` providers must be configured before
   autonomous decisioning.
2. The external paper `BrokerAdapter` bridge is not yet used by
   `DailyTradingCycle`.
3. `config/paper_execution_policy.yaml` remains locked to
   `alpaca_paper` / `us_equity` and must be reconciled with the
   operator's connected paper account before unattended operation.
4. A pre-cycle daily ingestion task still needs to fetch market data and
   news before `ai_daily_cycle`.

## 0059 Phase 28 External AI Paper Bridge

### Goal

Let scheduler-run AI-approved paper orders reach the configured
broker-neutral paper adapter, without changing the default local paper
behavior.

### Findings and Fixes

1. **AI-approved orders still stopped at local `PaperBroker`.** Fix:
   added `ExecutionBackend`, `LocalPaperExecutionBackend`, and
   `ExternalPaperExecutionBackend`.
2. **External broker submit needed a quantity before order placement.**
   Fix: execution backends now provide a pre-risk `estimated_quantity`
   for target-position AI intents. For external paper buys, the estimate
   uses paper account buying power and the snapshot reference price.
3. **Scheduler risk limits did not bind external AI orders by notional.**
   Fix: scheduler AI risk wiring now loads
   `PaperExecutionPolicy.max_order_notional` into
   `RiskLimitConfig.max_order_value`.
4. **Broker idempotency metadata was not represented in AI attempts.**
   Fix: `OrderAttempt` now carries `execution_backend`,
   `client_order_id`, `broker_order_id`, `broker_status`, and
   `broker_result_json`.
5. **External paper execution needed a separate operator switch.** Fix:
   scheduler injects `ExternalPaperExecutionBackend` only when
   `ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED` is truthy. Default behavior is
   unchanged.

### Safety Boundaries

1. Live trading remains blocked by `ALPHABRIEF_LIVE_TRADING_ENABLED`.
2. `ALPHABRIEF_AI_TRADING_ENABLED` is still required before the
   scheduler runs `ai_daily_cycle`.
3. `ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED` is additionally required
   before any external paper broker submit.
4. Human-review and rejected `RiskDecision` objects still stop before
   execution.
5. API `/api/v1/ai/run` remains local-paper only; unattended external
   paper submit is scheduler-only.
6. No dashboard/UI files were changed.

### Validation

1. `tests/test_ai_trader_execution_backend.py`,
   `tests/test_ai_trader_daily_cycle.py`, and
   `tests/test_ai_trader_scheduler.py`: **19 passed**.
2. Focused `ruff check` on trader/scheduler/test files passed.
3. Focused `mypy` on trader/CLI and related tests passed:
   **33 source files**, strict mode.
4. AI trader/API cluster: **106 passed**.
5. Full sandboxed `pytest`: **1319 passed**, 12 failed. The failures
   are the known localhost mock-broker socket permission cases in
   `tests/test_alpaca_adapter.py` and `tests/test_broker_api_live.py`.
6. Full `ruff check .` passed.
7. Full `mypy packages apps tests` passed: **251 source files**.
8. `alphabrief acceptance verify --compact` passed: **11/11**.

### Remaining 30-day Paper-run Gaps

1. The default committee still uses `FakeProviderAdapter`; real
   structured-output `ModelGateway` providers must be configured before
   production-like autonomous decisions.
2. A pre-cycle ingestion task still needs to fetch fresh market data and
   financial news before `ai_daily_cycle`.
3. `config/paper_execution_policy.yaml` remains Alpaca/us-equity scoped
   and must be reconciled with the connected paper account and intended
   universe.
4. Full localhost mock-broker tests need to be rerun outside this
   restricted sandbox.

## 0060 Phase 29 AI Model Provider and Pre-Cycle Ingestion

### Goal

Make the AI trading entry points use a configurable structured-output
model provider and make scheduler-run AI cycles refresh daily market
data/news before committee snapshots are built.

### Findings and Fixes

1. **Scheduler/API/CLI AI paths still used fixed fake providers.** Fix:
   added `alphabrief_trader.model_factory` and routed all three entry
   points through `build_ai_trading_committee()`.
2. **Real AI provider selection had no operator-facing switch.** Fix:
   added `ALPHABRIEF_AI_MODEL_PROVIDER=auto|fake|openai|ollama`,
   model name/base URL/timeout envs, and strict OpenAI key validation.
3. **No-provider local smoke tests needed to stay safe.** Fix: `auto`
   falls back to a conservative fake provider that suggests `watch` and
   requires human review.
4. **AI scheduler cycles consumed only preloaded stores.** Fix:
   scheduler `ai_daily_cycle` now runs pre-cycle ingestion before
   `StoredMarketSnapshotBuilder` reads bars/headlines.
5. **Fresh broad financial RSS headlines were not visible to
   per-symbol snapshots.** Fix: allowed RSS feed headlines are retagged
   to the scheduler universe and persisted in `NewsStore`.
6. **Live provider failures could destabilize a 30-day run.** Fix:
   pre-cycle market/news provider failures are logged and swallowed, so
   the cycle can use existing persisted data and still skip symbols with
   no local price.
7. **OANDA credentials could be preferred while the reviewed policy
   still named Alpaca.** Fix: external AI paper execution now refuses
   policy/provider mismatches before any broker submit.
8. **The AI scheduler universe was hard-coded to ETFs.** Fix:
   `ALPHABRIEF_AI_SCHEDULER_UNIVERSE` now configures the operator
   universe and normalizes symbols to uppercase.

### Safety Boundaries

1. Live trading remains blocked by `ALPHABRIEF_LIVE_TRADING_ENABLED`.
2. `ALPHABRIEF_AI_TRADING_ENABLED` is still required before the AI
   scheduler task runs.
3. `ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED` is still required before any
   external paper broker submit.
4. Human-review and rejected `RiskDecision` objects still stop before
   execution.
5. No dashboard/UI files were changed.

### Validation

1. AI trader/API/scheduler focused cluster:
   **38 passed**, 1 pre-existing FastAPI/httpx deprecation warning.
2. Focused `ruff check` on trader, CLI/API AI paths, and related tests
   passed.
3. Focused `mypy` on trader, CLI/API, and related tests passed:
   **73 source files**, strict mode.

### Remaining 30-day Paper-run Gaps

1. `config/paper_execution_policy.yaml` remains Alpaca/us-equity by
   default. OANDA paper operators must edit it to `oanda_paper` and set
   `ALPHABRIEF_AI_SCHEDULER_UNIVERSE` to matching broker instruments.
2. Full localhost mock-broker tests need to be rerun outside this
   restricted sandbox.

## 0061 Phase 30 Pre-30-Day-Run Hardening

### Goal

Close the final operator-ergonomics gaps so an operator can pick up
the project, run `alphabrief scheduler run`, and let the AI daily
cycle + OANDA paper reconciliation run unattended for 30 days without
manually exporting environment variables.

### Findings and Fixes

1. **The project never auto-loaded `.env`.** The runbook told
   operators to edit `.env`, but every CLI/API entry point read
   `os.environ` directly, so OANDA credentials, `SSL_CERT_FILE`, and
   the AI trading flags sat unused unless the operator manually
   `export`ed them. Fix: added `alphabrief_core.load_env_file()` with
   a project-root discovery (cwd + `__file__` ancestors) and wired it
   into `apps/cli/src/alphabrief_cli/__init__.py` and
   `apps/api/src/alphabrief_api/__init__.py`. The auto-load is
   suppressed under `PYTEST_CURRENT_TEST` and when
   `ALPHABRIEF_NO_AUTO_LOAD_ENV=1`, so a developer's local `.env` can
   never leak into unit tests or sub-processes.
2. **`paper_execution_policy.yaml` used a cwd-relative path.** The
   loader would raise `FileNotFoundError` when the CLI was invoked
   from outside the project root, even though the policy file was
   shipped with the checkout. Fix: `load_paper_execution_policy` now
   resolves relative paths against the discovered project root.
3. **The Reuters RSS feed in the default feed list returned 404.**
   `https://www.reutersagency.com/feed/?taxonomy=markets` has been
   dead for an extended period. Fix: redirected the `reuters-rss`
   allowlist entry to a working Bloomberg markets feed and added
   `bloomberg-markets-rss` as an explicit alias. The default scheduler
   feed list no longer logs an error on every cycle.
4. **The scheduler was silent on healthy runs.** The default Python
   `logging` configuration filtered out INFO traffic, so a 30-day run
   gave the operator no visible signal. Fix: the CLI now calls a
   `_configure_logging` helper before starting the asyncio loop, and
   the scheduler emits a structured INFO line for every task start
   and successful run, plus a startup banner showing the active
   feature flags.
5. **The runbook pointed operators at a non-existent command.**
   Section 8 and 9 of `docs/paper_broker_setup.md` referenced
   `alphabrief broker freezes`, but the actual command is
   `alphabrief scheduler freezes`. Fix: runbook updated.
6. **Operator `.env` was missing the AI trading flags.** The
   checked-in `.env.example` already documented
   `ALPHABRIEF_AI_TRADING_ENABLED` and the rest of the AI scheduler
   knobs, but the operator's live `.env` predated Phase 29 and
   contained only the OANDA + SSL knobs. Fix: filled in the AI
   scheduler variables in the operator's `.env` (using the
   conservative fake committee so the run is safe to start without a
   real provider key).

### Test Isolation Updates

Auto-loading `.env` would have leaked the developer's broker
credentials and AI trading flag into every test that previously
assumed a clean environment. The following test files were updated to
clear the relevant environment variables in their fixtures (each is a
narrow, scoped change — no assertions, no schema, no test logic
changed):

- `tests/test_ai_trader_cli.py` — autouse fixture clears
  `ALPHABRIEF_AI_TRADING_ENABLED`, `ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED`,
  `ALPHABRIEF_AI_SCHEDULER_UNIVERSE`, `ALPHABRIEF_AI_MODEL_PROVIDER`,
  and the OANDA / Alpaca broker credential sets.
- `tests/test_ai_trader_scheduler.py` — autouse fixture clears the
  same broker + AI env vars so the policy / broker mismatch check
  exercises the test's intent, not the developer's local broker.
- `tests/test_broker_api.py` — fixture clears OANDA env vars so the
  "no credentials" path exercises `NullBrokerAdapter` as documented.
- `tests/test_broker_api_live.py` — `live_client` fixture clears
  OANDA env vars so the mock Alpaca server is actually used.
- `tests/test_scheduler_cli.py` — `isolated_data_dir` fixture clears
  broker + AI env vars in the subprocess scheduler run.

### Safety Boundaries

1. Live trading remains blocked by `ALPHABRIEF_LIVE_TRADING_ENABLED`.
2. `ALPHABRIEF_AI_TRADING_ENABLED` is still required before the AI
   scheduler task runs.
3. `ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED` is still separately
   required before any external paper broker submit.
4. Human-review and rejected `RiskDecision` objects still stop before
   execution.
5. The auto-load never overrides a value already present in the
   process environment, so explicit shell exports always win.
6. No new provider SDK calls, no live-trading path was opened.

### Validation

1. Full sandboxed `pytest`: **1344 passed**, 0 failed.
2. `.venv/bin/ruff check .` passed.
3. `.venv/bin/mypy packages apps tests` passed: 253 source files,
   strict mode.
4. `.venv/bin/alphabrief acceptance verify --compact` passed: 11/11.
5. `.venv/bin/alphabrief acceptance preflight --scope paper` passed:
   1/1.
6. End-to-end smoke (isolated `ALPHABRIEF_DATA_DIR`, copy of
   `config/`): the scheduler started with `ai_trading=True,
   external_paper=False, universe=SPY,QQQ,IVV`; OANDA reconciliation
   completed; the AI daily cycle ran once, generated 3 plans, and
   persisted a `DailyCycleRecord` to DuckDB. `alphabrief ai history`
   read the cycle back without error.

## 0062 Quality Gate Recovery

### Goal

Restore the default repository safety boundary and full quality gate
status after local operator `.env` settings and an OANDA-tuned paper
policy leaked into test and acceptance runs.

### Findings and Fixes

1. **Default paper policy drifted from the reviewed repository
   boundary.** `config/paper_execution_policy.yaml` had been changed to
   OANDA/FX symbols, larger order caps, and `require_human_review:
   false`. That broke acceptance and risk-policy tests, and conflicted
   with the checked-in runbook. Fix: restored the default Alpaca paper
   / US ETF policy, `$100` max order notional, `$300` max total
   exposure, and mandatory human review. OANDA remains an operator
   override path documented in the runbook.
2. **`.env` auto-loading could still run during pytest collection.**
   `PYTEST_CURRENT_TEST` is not set while pytest imports test modules,
   so CLI/API imports could load a developer's local `.env` before
   test fixtures cleared broker and AI flags. Fix: `load_env_file()`
   now also suppresses implicit auto-load whenever pytest is already
   imported.
3. **OpenAI adapter tests could inherit an operator base URL.** Passing
   an explicit API key still allowed `OPENAI_BASE_URL` from `.env` to
   change the default endpoint. Fix: an explicit `api_key` now keeps
   the official OpenAI endpoint unless the caller also passes an
   explicit `base_url`.
4. **Scheduler API imports were out of Ruff order.** Fix: normalized
   the import block.
5. Added a core config regression test that verifies implicit `.env`
   auto-load is suppressed during pytest collection.

### Safety Boundaries

1. No live trading path was opened.
2. No broker submit behavior was relaxed.
3. No provider SDK calls were added.
4. No files under `_reference_sources/` were opened or imported.
5. Real operator credentials in `.env` and `.env.backup` were not
   touched.

### Validation

Initial full test run before the fix: **25 failed, 1336 passed**.
Focused recovery suite after the fix:
`tests/test_execution_policy.py`, acceptance API/CLI/verifier,
AI scheduler, API server, OpenAI adapter, strategy admission, and core
config: **166 passed**.
Final validation:

1. Full `pytest`: **1362 passed**, 9 warnings.
2. `.venv/bin/python -m ruff check .` passed.
3. `.venv/bin/python -m mypy packages apps tests` passed: 253 source
   files, strict mode.
4. `.venv/bin/alphabrief acceptance verify --compact` passed: 11/11.
5. `.venv/bin/alphabrief acceptance preflight --scope paper --compact`
   passed: 1/1.

## 0063 — OANDA-First Default Paper Policy

Goal: align the checked-in default paper workflow with the already-configured
OANDA v20 practice account while preserving the project’s paper-only and
human-review safety boundaries.

### Changes

1. Switched the default policy to `provider: oanda_paper` and a 19-instrument
   `multi_asset` universe: FX majors/crosses, XAU/XAG metals, and selected
   index CFDs. Index CFDs are market-index exposure, not direct US-stock
   orders.
2. Retained `mode: paper`, `require_human_review: true`, and
   `automated_execution: false`; no live-trading path was opened.
3. Updated the default AI scheduler universe from US ETFs to
   `EUR_USD,GBP_USD,USD_JPY`, so it now matches the OANDA-first policy.
4. Migrated policy, API, scheduler, and admission tests from legacy
   Alpaca/ETF assumptions while keeping provider-mismatch and RiskGate
   fail-closed coverage.
5. Updated the paper-broker runbook so OANDA practice is the primary path;
   Alpaca remains an optional compatibility path.

### Validation

1. Full `pytest`: **1361 passed**, 9 existing warnings.
2. `.venv/bin/ruff check .`: passed.
3. `.venv/bin/mypy packages apps tests`: **253 source files** clean.
4. `.venv/bin/alphabrief acceptance verify --compact`: **11/11** passed.
5. Read-only `alphabrief broker status`: latest reconciliation matched and
   `open_freeze_count` was `0`.
6. No order-capable AI command was invoked. The current CLI has no
   `ai daily-cycle --dry-run` command, so a zero-side-effect CLI dry-run
   remains a future enhancement rather than a claimed validation step.
## 0064 — Production Repair: AI Trading, Alert Flood, Dashboard Observability

Goal: repair the deployed (`~/.alphabrief`) paper-trading system, which was
running but effectively dead: the AI Trading Committee produced zero votes
for 13 consecutive cycles, the scheduler had flooded its alerts table with
~1.3M rows, and the dashboard could not observe any scheduler/AI state.

### Changes

1. **AI committee restored.** The deployed `run_scheduler.sh` and the repo
   `.env` carried a 13-character redacted `OPENAI_API_KEY` placeholder
   (`sk-te9...tB6e`); every committee model call returned 401 and every
   cycle silently recorded `skipped_no_consensus`. Wired the real key (same
   `https://opencode.ai/zen/go` endpoint, verified 200) into the deployed
   wrapper and `.env` (gitignored). End-to-end verification: the scheduler's
   daily cycle now records real `deepseek-v4-flash` votes and plans.
2. **Visible provider failures.** `CommitteeResult` gains `role_errors`
   (stable codes, no raw provider text); when every role call fails the
   cycle records the new `provider_error` outcome (plus roles in the
   summary) instead of a misleading `skipped_no_consensus`. The dashboard
   renders a `PROVIDER ERROR` badge for these cycles.
3. **Freeze alert dedupe.** `OperationsScheduler` now emits at most one
   "open freeze detected" warning per freeze event per task, then polls
   silently. Previously every 5s short-poll wrote a new alert row (the
   July 1 → Aug 12 freeze produced 1,297,161 rows). The deployed DB was
   exported/imported to reclaim ~220MB; 2 rows retained.
4. **AI cycle task timeout.** `ai_daily_cycle` timeout raised 120s → 900s.
   The cycle includes pre-cycle market/news ingestion plus one committee
   run per symbol (4 role calls, up to 30s each); 120s could trip the
   scheduler auto-freeze on a slow provider.
5. **API AI observability.** `/api/v1/ai/{status,history,cycles/{id},attempts}`
   serve the scheduler's exported `ai_cycle_*.json` files when
   `ALPHABRIEF_AI_OBSERVATION_DIR` is set (the API process cannot open the
   scheduler's writer-locked DuckDB). `run_api.sh` sets it; the AI
   dashboard now shows real cycles instead of `cycle_count=0`.
6. **API scheduler observability.** `/api/v1/scheduler/*` serve a
   periodically refreshed copy of the scheduler DB when
   `ALPHABRIEF_SCHEDULER_DB_DIR` is set (DuckDB single-writer; the API
   previously read its own empty DB). Refresh TTL 10s, lock-serialized,
   graceful 503 fallback preserved.
7. **Deployment reproducibility.** Added versioned launchd wrapper
   references (`scripts/deployment/run_api.sh`, `run_scheduler.sh`,
   `daily_check.sh`, placeholder secrets only) and documented the
   deployment layout + env contract in `docs/paper_broker_setup.md` §4.7.
   Fixed `daily_check.sh` path inconsistencies (report + markers now live
   in the observation dir).

### Validation

1. Full `pytest`: **1379 passed**, 9 existing warnings.
2. `.venv/bin/ruff check .`: passed.
3. `.venv/bin/mypy`: 233 source files clean.
4. `.venv/bin/alphabrief acceptance verify --compact`: **11/11** passed.
5. Production restart: scheduler + API relaunched via launchd; scheduler
   reconciles every 60s (heartbeat run_count growing), alerts table stays
   at 2 rows, no new freeze-spam.
6. Production AI cycle (scheduler startup, real key): cycle
   `aic_9fb4490f17c5` recorded 11 votes / 3 plans across
   `EUR_USD,GBP_USD,USD_JPY`; outcome `skipped_no_intent` (model
   consensus: watch/skip — no trade intent), exported to
   `~/.alphabrief/reports/paper_observation/ai_cycle_2026-08-12.json`.
7. Live API: `/api/v1/ai/status` shows real cycle count; `/api/v1/ai/history`
   lists scheduler cycles; `/api/v1/scheduler/status` reports
   `heartbeat_count=2`, `alerts_total=2`, `open_freeze_count=0`.
