# Development Plan 0004: CSV OHLCV Market Data Loader MVP

## Goal

Implement the first local market data loader: single-symbol CSV OHLCV to
`Bar` objects.

## Changes

1. Add `packages/alphabrief-data/src/alphabrief_data/`.
2. Add `CsvBarLoader`, `load_ohlcv_csv`, and `MarketDataLoadError`.
3. Parse required OHLCV columns with the standard library `csv` module.
4. Parse numeric fields directly into `Decimal`.
5. Parse ISO timestamps, assigning a configured timezone to naive values and
   preserving offsets for aware values.
6. Reuse `alphabrief_core.Bar` validation for OHLCV consistency.
7. Wrap missing columns, empty cells, invalid decimals, invalid timestamps, and
   invalid bars as `MarketDataLoadError`.
8. Update `pyproject.toml` package discovery, pytest pythonpath, and mypy
   scope for `alphabrief-data`.
9. Add CSV loader tests and architecture documentation.

## Out of Scope

1. Parquet loading.
2. Data quality reports for missing, duplicate, or anomalous rows.
3. Feature generation.
4. DuckDB, Parquet snapshots, or persistent storage.
5. StrategySpec, backtesting, API, CLI, or dashboard work.
6. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `python3 -m pytest tests/test_project_scaffold.py tests/test_core_domain_models.py tests/test_core_config.py tests/test_csv_market_data_loader.py`
   passes.
2. `ruff check .` passes if ruff is installed.
3. `python3 -m mypy packages/alphabrief-core/src packages/alphabrief-data/src tests`
   passes if mypy is installed.
