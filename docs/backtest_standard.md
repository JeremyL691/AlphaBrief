# Backtest Standard MVP

AlphaBrief backtests must be explicit about data, strategy version, costs, and
risk metrics.

## Current Report Fields

The MVP `BacktestReport` includes:

1. `strategy_id`
2. `strategy_version`
3. `symbol`
4. `data_version`
5. `initial_cash`
6. `final_value`
7. `fee_bps`
8. `slippage_bps`
9. `metrics`
10. `equity_curve`
11. `trades`

## Current Metrics

The MVP metrics are:

1. `total_return`
2. `max_drawdown`
3. `trade_count`
4. `win_rate`

## Current Execution Assumptions

1. Long/flat only.
2. No shorting or leverage.
3. Signal-driven entry and exit.
4. Trade notional is capped by `StrategySpec.risk.max_position_pct`.
5. Fees and slippage come from `StrategySpec.costs`.
6. Any open position is closed at the final bar for report completeness.

## Boundaries

This MVP does not submit orders, call brokers, bypass RiskGate, optimize
parameters, perform walk-forward analysis, or guarantee live-trading behavior.
