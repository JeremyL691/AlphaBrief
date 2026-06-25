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
paper execution policy: `SPY`, `QQQ`, `IVV`, `VOO`, `AGG`, `BND`, `GLD`, and
`SLV`, maximum order notional `$100`, and
mandatory human review. Therefore, the internal paper-order API records a
risk decision but does not auto-execute under this policy.

`max_total_exposure: $300` is enforced at runtime by the Phase 19
account-exposure check. When the cap is configured, `RiskGate` fails closed
without an `AccountExposureContext`; buys that would breach the cap are
rejected and the advisory quantity bound can only be reduced. Sells do not
increase the long-only paper policy's gross exposure. The context is projected
by the execution layer, so the risk package remains free of broker imports.

An explicit empty `enabled_strategies` set denies all strategy-originated
orders. `None` retains the legacy unconfigured behavior. Strategy registry
activation and strategy-admission records are audit-only and never modify this
allowlist or otherwise relax a RiskDecision.

## Account-Level Risk Rules (Phase 21)

Phase 19 R19.1 added the runtime total-exposure cap.
Phase 21 R21.x extends account-level enforcement with the rest of
the blueprint §6 rule surface. Every new check is **tighten-only**
(can only reject, tag, or reduce `max_quantity`) and **fail-closed**
(a missing required input is a rejection, never a silent skip).
None can re-approve a rejected intent, lift the live-trading lock,
relax the human-review flag, or raise `max_quantity` above the
configured per-order cap.

| `RiskLimitConfig` field | Failure tag | Required context input |
|---|---|---|
| `max_symbol_exposure` | `max_symbol_exposure` | `account_context` + `estimated_price` |
| `max_concentration_pct` | `max_concentration` | `account_context` + `estimated_price` |
| `max_leverage` | `max_leverage` | `account_context.equity` + `estimated_price` |
| `max_price_deviation_pct` | `price_deviation` | `account_context.reference_mark_prices[symbol]` + `estimated_price` |
| `require_market_open` + `session_policy` | `market_closed` | `session_policy` |
| `max_signal_age_seconds` | `stale_signal` | `intent.created_at` |
| `duplicate_order_window_seconds` + `duplicate_order_max_count` | `duplicate_order` | (none beyond the intent itself) |
| `max_daily_loss_pct` | `max_daily_loss` | `account_context.day_start_equity` + `account_context.equity` |
| `max_drawdown_floor_pct` | `max_drawdown_floor` | `account_context.equity_high_water_mark` + `account_context.equity` |

A check that requires an input which is missing tags the intent with
the corresponding `*_required` failure tag (`account_context_required`,
`missing_equity`, `missing_day_start_equity`, `missing_equity_hwm`,
`missing_mark_price`, `missing_price`, or `market_closed` when the
session policy is not wired).

**Sells** bypass the per-symbol, leverage, daily-loss, and drawdown
checks because a sell is the protective action when in loss or
drawdown — the check must not block it. The other checks
(concentration, price deviation, signal age, duplicate order, market
open) apply equally to buys and sells.

The duplicate-order detector uses an in-memory deque on the
`RiskGate` instance (`ponytail:duplicate_order_state`). A process
restart loses dedup memory; an immediate resubmit will not be
caught. Acceptable for paper; the upgrade path is a persistent
recent-intent store (Phase 21.5+).

The market-open check uses the policy's `trading_days`,
`session_start`, `session_end`, and `timezone`. It does not consult
a market-calendar provider, so U.S. holidays are not respected
(`ponytail:no-holiday-calendar`).

### Caller-supplied inputs

The R21.x checks consume new optional fields on
`AccountExposureContext`:

- `equity` (`Field(ge=0)`) — for `max_leverage`, `max_daily_loss_pct`,
  and `max_drawdown_floor_pct`. The execution-side projection
  helper computes it as `cash + sum(qty * mark)`; without
  `mark_prices` the legacy `PortfolioState` falls back to
  `average_price` (`ponytail:portfolio_equity_ceiling`).
- `reference_mark_prices` (dict of Decimal) — for
  `max_price_deviation_pct`. Without it the check rejects with
  `missing_mark_price`.
- `equity_high_water_mark` (`Field(ge=0)`) — for
  `max_drawdown_floor_pct`. Must be supplied by the caller from a
  persistent snapshot store so a restart cannot reset the peak and
  silently widen the floor. The paper route reads this from the
  equity-snapshot store when present; without it, the check
  rejects.
- `day_start_equity` (`Field(ge=0)`) — for `max_daily_loss_pct`.
  Caller-supplied for the same restart-safety reason.
- `day_realized_pnl` — surfaced for audit / diagnostics only; not
  gated on. Loss days produce a negative value.
