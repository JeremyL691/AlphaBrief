# Development Plan 0010: Parquet Market Data Loader MVP

## Goal

Complete the Phase 1 market data loader boundary by adding local Parquet OHLCV
loading alongside the existing CSV loader.

## Changes

1. Add `alphabrief_data.parquet_loader`.
2. Export `ParquetBarLoader` and `load_ohlcv_parquet`.
3. Reuse `Bar` validation and `MarketDataLoadError` for row-level failures.
4. Support ISO string timestamps and `datetime` values.
5. Assign the configured timezone to naive timestamps and preserve aware
   offsets.
6. Keep Decimal parsing explicit and reject float values.
7. Use optional pandas parquet support; report a clear loader error when the
   local parquet engine is unavailable.
8. Add tests and architecture documentation.

## Out of Scope

1. Installing pyarrow, fastparquet, duckdb, or pandas as a required runtime
   dependency.
2. Data quality checks, feature generation, feature store snapshots, or
   persistent storage.
3. Backtest or strategy changes.
4. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `tests/test_parquet_market_data_loader.py` passes.
2. Full Phase 1 tests pass.
3. Parquet loader failures include row numbers for bad row data.
4. Missing parquet engine failures are explicit and do not silently fall back
   to another format.
