# Development Plan 0005: Market Data Quality Checks MVP

## Goal

Implement basic in-memory quality checks for `Bar` sequences.

## Changes

1. Add `alphabrief_data.quality`.
2. Add `DataQualitySeverity`, `DataQualityIssue`, `DataQualityReport`, and
   `check_bar_quality`.
3. Detect empty datasets, mixed symbols, duplicate timestamps, non-increasing
   timestamps, missing expected intervals, and zero-volume bars.
4. Treat mixed source and mixed data version as warnings.
5. Export the quality API from `alphabrief_data`.
6. Add focused quality tests and architecture documentation.

## Out of Scope

1. Automatic repair, resampling, or missing bar filling.
2. Statistical anomaly detection, price jump thresholds, trading calendars, or
   market session validation.
3. Automatic integration into the CSV loader.
4. Parquet, feature generation, StrategySpec, or backtesting.
5. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py tests/test_market_data_quality.py`
   passes.
2. `ruff check .` passes if ruff is installed.
3. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src tests`
   passes if mypy is installed.
