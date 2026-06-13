# Development Plan 0006: Basic No-Lookahead Feature Generation MVP

## Goal

Implement minimal feature generation for in-memory `Bar` sequences while
preserving a no-lookahead contract.

## Changes

1. Add `alphabrief_data.features`.
2. Add `FeatureRow`, `FeatureGenerationError`, and `generate_basic_features`.
3. Generate trailing returns, trailing close SMA, and trailing volume SMA.
4. Use `Decimal` values and `None` for insufficient history.
5. Run `check_bar_quality` first and block only failed quality reports.
6. Export the feature API from `alphabrief_data`.
7. Add no-lookahead tests and architecture documentation.

## Out of Scope

1. RSI, MACD, ATR, Bollinger Bands, or advanced indicators.
2. pandas/numpy dataframe outputs.
3. Feature store, DuckDB, Parquet snapshots, or persistent storage.
4. Signal, OrderIntent, StrategySpec, or backtesting.
5. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py tests/test_market_data_quality.py tests/test_feature_generation.py`
   passes.
2. `ruff check .` passes if ruff is installed.
3. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src tests`
   passes if mypy is installed.
