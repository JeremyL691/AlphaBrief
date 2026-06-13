# Development Plan 0007: StrategySpec Schema MVP

## Goal

Implement the first validated StrategySpec schema for future strategy
interfaces and backtests.

## Changes

1. Add `packages/alphabrief-strategy/src/alphabrief_strategy/`.
2. Add `StrategySpec`, `StrategyUniverse`, `StrategyRule`, `StrategyRisk`,
   `StrategyCosts`, `StrategyEvaluation`, and `EvaluationPeriod`.
3. Validate required strings, stable symbol de-duplication, risk limits,
   non-negative costs, and non-overlapping train/test periods.
4. Update `pyproject.toml` for `alphabrief-strategy` package discovery,
   pytest pythonpath, and mypy scope.
5. Add StrategySpec schema tests and documentation.

## Out of Scope

1. Strategy interface.
2. Condition parsing or execution.
3. Signal or OrderIntent generation.
4. Backtesting, metrics, portfolio, broker, or RiskGate behavior.
5. Model-generated StrategySpec.
6. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py tests/test_market_data_quality.py tests/test_feature_generation.py tests/test_strategy_spec_schema.py`
   passes.
2. `ruff check .` passes if ruff is installed.
3. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src tests`
   passes if mypy is installed.
