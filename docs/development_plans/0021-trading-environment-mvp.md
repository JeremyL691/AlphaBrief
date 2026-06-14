# Development Plan 0021: Trading Environment MVP

## Goal

Complete Phase 4 by adding a Gymnasium-style single-asset trading environment
for strategy comparison.

## Changes

1. Add `alphabrief_gym`.
2. Add `AlphaBriefTradingEnv` with `reset()` and `step(action)`.
3. Add action and observation schemas.
4. Compute rewards from no-lookahead portfolio value transitions.
5. Support transaction costs and slippage in basis points.
6. Add episode metrics.
7. Add random policy evaluation.
8. Add buy-and-hold baseline evaluation.
9. Add strategy comparison report.
10. Add tests and documentation.

## Out of Scope

1. Gymnasium dependency or vectorized spaces.
2. Agent training, model learning, or RL algorithms.
3. Shorting, leverage, margin, partial fills, or multi-asset portfolios.
4. CLI, API, dashboard, or persistence.
5. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `tests/test_trading_env.py` passes.
2. Full project tests pass.
3. Ruff and mypy pass.
4. The completion audit proves every Phase 4 blueprint item is present.
