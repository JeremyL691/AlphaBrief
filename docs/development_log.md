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
