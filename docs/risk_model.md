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

## RiskContext Tightening (Phase 13.1)

`RiskGate.evaluate()` accepts an optional `RiskContextDecision`. When
provided, the gate applies the decision in a **tighten-only** manner.
The context can never re-approve a rejected intent, can never relax the
human-review flag, and can never increase `max_quantity` above the
configured limit.

The gate may:

1. Merge the context's `risk_tags` into the decision tags
   (deduplicated, original order preserved).
2. Flip the final `requires_human_review` flag on when
   `risk_context.requires_human_review` is `True`. The static
   `RiskLimitConfig.require_human_review` flag is honored as well, so
   the merge is effectively an OR.
3. Reduce `max_quantity` by
   `risk_context.suggested_max_position_multiplier` when that
   multiplier is strictly below `1.0` and `max_order_quantity` is
   configured. The reduction is Decimal-first with no rounding; the
   cap is never relaxed even if the multiplier were 1.0.

The context **cannot** override the kill switch, lift the live-trading
lock, add symbols to the allowlist, or re-approve a rejected intent.
A `RiskContextDecision` is produced by
`alphabrief_risk.evaluate_news_macro_risk`, which is a pure
deterministic function over `ResearchContextSummary` (or a
`NewsMacroRiskContext` mirror) — it never calls ModelGateway, never
reads a database, and never invokes a provider.

When no `risk_context` is supplied, `evaluate()` is byte-for-byte
backward compatible with the Phase 12 contract.

## Phase 16 Paper Boundary

The runtime's default enforceable boundary is loaded from the checked-in
paper execution policy: `SPY`/`QQQ`, maximum order notional `$100`, and
mandatory human review. Therefore, the internal paper-order API records a
risk decision but does not auto-execute under this policy.

`max_total_exposure: $300` is an approved operating constraint, but it is
not yet enforced against account state. It must not be represented as a
runtime risk check until Phase 19 implements account-level exposure controls.

An explicit empty `enabled_strategies` set denies all strategy-originated
orders. `None` retains the legacy unconfigured behavior. Strategy registry
activation and strategy-admission records are audit-only and never modify this
allowlist or otherwise relax a RiskDecision.
