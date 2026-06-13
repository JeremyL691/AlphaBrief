# StrategySpec MVP

StrategySpec is AlphaBrief's first strategy boundary. A strategy must be
specified before future modules can implement, test, or backtest it.

## Fields

The MVP schema contains:

1. `strategy_id`
2. `name`
3. `version`
4. `universe.symbols`
5. `timeframe`
6. `entry.condition`
7. `exit.condition`
8. `risk.max_position_pct`
9. `risk.stop_loss`
10. `costs.fee_bps`
11. `costs.slippage_bps`
12. `evaluation.train_period`
13. `evaluation.test_period`

## Boundaries

Condition fields are stored as auditable text only. They are not parsed or
executed in this round.

StrategySpec does not generate `Signal`, `OrderIntent`, orders, portfolio
changes, or broker calls. Execution remains blocked behind future strategy,
backtest, risk, and paper-trading modules.

## Strategy Interface Relationship

The simple strategy interface consumes `StrategySpec` through `StrategyInput`.
A strategy implementation receives the spec, bars, and feature rows, then
returns `StrategyOutput`.

In the MVP interface, strategies may only return `Signal` objects. `OrderIntent`
generation is reserved for a later risk and paper-trading phase.

## Validation

1. Required identity strings must be non-empty.
2. Universe symbols must be non-empty and are de-duplicated in stable order.
3. Entry and exit conditions must be non-empty.
4. Maximum position percentage must be between `0` and `1`.
5. Fee and slippage basis points must be non-negative `Decimal` values.
6. Evaluation periods must have `start <= end`.
7. Test period must start after train period ends.
8. Unknown fields are rejected.
