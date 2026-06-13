# Development Plan 0008: Simple Strategy Interface MVP

## Goal

Define the first strategy execution interface without implementing strategy
logic, backtesting, orders, or broker access.

## Changes

1. Add `alphabrief_strategy.interface`.
2. Add `StrategyInput`, `StrategyOutput`, `StrategyProtocol`,
   `StrategyExecutionError`, and `run_strategy`.
3. Validate non-empty bars, matching feature length, and bar data quality.
4. Validate returned signals against StrategySpec strategy ID, universe, and
   input bar timestamps.
5. Export the interface API from `alphabrief_strategy`.
6. Add tests and documentation.

## Out of Scope

1. Built-in SMA/EMA strategies.
2. Entry/exit condition parsing.
3. OrderIntent generation.
4. Backtesting, metrics, portfolio, broker, or RiskGate behavior.
5. Model-generated strategies.
6. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py tests/test_market_data_quality.py tests/test_feature_generation.py tests/test_strategy_spec_schema.py tests/test_strategy_interface.py`
   passes.
2. `ruff check .` passes if ruff is installed.
3. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src packages/alphabrief-strategy/src tests`
   passes if mypy is installed.
