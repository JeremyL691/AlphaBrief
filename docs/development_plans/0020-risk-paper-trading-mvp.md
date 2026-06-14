# Development Plan 0020: Risk and Paper Trading MVP

## Goal

Complete Phase 3 by implementing the safe paper-trading loop:
`OrderIntent -> RiskGate -> RiskDecision -> OrderRouter -> PaperBroker`.

## Changes

1. Add `alphabrief_risk` with `RiskGate`, `RiskLimitConfig`, and `KillSwitch`.
2. Add `alphabrief_execution` with `OrderRouter`, `FillSimulator`,
   `PortfolioState`, `PaperBroker`, and `ExecutionAuditLog`.
3. Require a matching approved `RiskDecision` before any `Order` can be
   created.
4. Simulate paper fills with deterministic fee and slippage.
5. Update portfolio cash, positions, and realized PnL from fills.
6. Record risk decisions, order rejections, order creation, fills, and
   portfolio updates in an audit log.
7. Keep live trading unavailable.
8. Add tests and documentation.

## Out of Scope

1. Live broker adapters or live order routing.
2. Margin, leverage, shorting, partial fills, or external persistence.
3. CLI, API, dashboard, or background worker surfaces.
4. Model-generated orders bypassing RiskGate.
5. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `tests/test_risk_gate.py` passes.
2. `tests/test_paper_execution.py` passes.
3. Full project tests pass.
4. Ruff and mypy pass.
5. The completion audit proves every Phase 3 blueprint item is present.
