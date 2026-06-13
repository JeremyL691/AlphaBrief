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

The first implementation round does not implement RiskGate; it only records
the required boundary.
