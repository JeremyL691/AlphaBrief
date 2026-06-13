# Development Plan 0009: Vectorized Backtester and Metrics MVP

## Goal

Complete the first Phase 1 backtesting loop: CSV bars -> features -> moving
average strategy -> long/flat backtest -> JSON report.

## Changes

1. Add `alphabrief_backtest` package.
2. Add `VectorizedBacktester`, `BacktestReport`, `BacktestMetrics`,
   `BacktestTrade`, `EquityPoint`, and `write_backtest_report`.
3. Add `MovingAverageTrendStrategy` as the first built-in strategy.
4. Simulate long/flat trades using `StrategySpec.risk.max_position_pct`,
   `fee_bps`, and `slippage_bps`.
5. Add total return, max drawdown, trade count, and win rate.
6. Update `pyproject.toml` package discovery, pytest pythonpath, and mypy
   scope for `alphabrief-backtest`.
7. Add tests and documentation.

## Out of Scope

1. Shorting, leverage, multi-asset allocation, margin, or liquidity modeling.
2. Broker, order router, RiskGate, PaperBroker, or live trading.
3. Strategy condition parsing.
4. Parameter optimization or walk-forward evaluation.
5. Any implementation copied from `_reference_sources/`.

## Acceptance

1. Full Phase 1 test suite passes including `tests/test_vectorized_backtester.py`.
2. A moving-average strategy can run over imported OHLCV data.
3. A `backtest_report.json` can be written.
4. The report includes fees, slippage, total return, max drawdown, trade count,
   win rate, data version, strategy ID, and strategy version.
