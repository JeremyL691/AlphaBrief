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
