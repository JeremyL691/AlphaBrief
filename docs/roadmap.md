# AlphaBrief Roadmap

The roadmap follows the phases in `ALPHABRIEF_PRODUCT_BLUEPRINT.md`.

## Phase 1: AlphaBrief Core

Goal: create the smallest reliable research and backtest kernel.

Status: completed for the MVP kernel. The current implementation can load
local OHLCV data, validate data quality, generate no-lookahead features,
validate StrategySpec objects, run a simple strategy interface, execute a
long/flat moving-average backtest, and write a JSON backtest report with costs
and metrics.

Planned sequence:

1. Repository scaffold and project rules: completed.
2. Core domain models: completed.
3. Configuration system: completed.
4. CSV and Parquet market data loader: completed.
5. Data quality checks: completed.
6. Feature generation: completed.
7. StrategySpec schema: completed.
8. Strategy interface: completed.
9. Vectorized backtester: completed.
10. Basic metrics and report schema: completed.

## Phase 2: ModelGateway and Research Briefs

Goal: add model-agnostic research capabilities through a unified gateway.

## Phase 3: Risk and Paper Trading

Goal: create a safe paper-trading loop where every OrderIntent passes RiskGate.

## Phase 4: Trading Environment

Goal: add a Gymnasium-style simulation environment for strategy comparison.

## Phase 5: Dashboard and Review

Goal: expose reports, risk logs, paper portfolio, and review history through a
daily-use interface.
