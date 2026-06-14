# AlphaBrief Risk Model

Risk controls are deterministic system boundaries. They must not be overridden
by models, prompts, natural language, strategies, or UI actions.

## MVP Default

1. Live trading is disabled.
2. Paper trading is the only allowed execution mode.
3. Execution code must require a RiskDecision.
4. Missing RiskDecision means no Order.

## Required Flow

```text
OrderIntent -> RiskGate -> RiskDecision -> PaperBroker
```

Future live trading, if ever enabled, must remain behind a separate explicit
lock, user confirmation, complete audit logging, and additional broker-specific
review.

## RiskGate Responsibilities

The blueprint defines these eventual checks:

1. trading enabled status
2. live trading enabled status
3. strategy enabled status
4. symbol allowlist
5. position limits
6. max order value
7. daily loss and drawdown limits
8. leverage limits
9. stale signal checks
10. data quality status
11. human review requirements

## Current MVP Implementation

`alphabrief_risk` implements the deterministic paper-trading risk boundary:

1. `RiskGate` evaluates every `OrderIntent` before paper execution.
2. `RiskLimitConfig` controls trading enabled status, live-trading lock,
   strategy allowlist, symbol allowlist, max quantity, max order value, data
   quality requirement, and human-review flag.
3. `KillSwitch` blocks every order while active.
4. Every evaluation returns a complete `RiskDecision`, approved or rejected.

`alphabrief_execution` implements the paper execution boundary:

1. `OrderRouter` refuses to create an `Order` without a matching approved
   `RiskDecision`.
2. `PaperBroker` simulates paper orders and fills only through the router.
3. `FillSimulator` applies deterministic fee and slippage assumptions.
4. `PortfolioState` updates cash, positions, and realized PnL from fills.
5. `ExecutionAuditLog` records risk decisions, order creation/rejection, fills,
   and portfolio updates.

No live broker adapter or live trading path is implemented.
