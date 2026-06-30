# 0059 Phase 28 External AI Paper Bridge

## Goal

Allow scheduler-run AI-approved orders to reach the configured external
paper broker adapter, while keeping default behavior local, paper-only,
and fail-closed.

## Files Changed

1. `packages/alphabrief-trader/src/alphabrief_trader/execution_backend.py`
2. `packages/alphabrief-trader/src/alphabrief_trader/daily_cycle.py`
3. `packages/alphabrief-trader/src/alphabrief_trader/schemas.py`
4. `packages/alphabrief-trader/src/alphabrief_trader/__init__.py`
5. `apps/cli/src/alphabrief_cli/scheduler_commands.py`
6. `tests/test_ai_trader_execution_backend.py`
7. `tests/test_ai_trader_scheduler.py`
8. `.env.example`
9. `docs/paper_broker_setup.md`
10. `docs/architecture.md`
11. `docs/roadmap.md`
12. `docs/development_log.md`

## Modules Not Touched

1. Dashboard/UI files.
2. API broker adapter singleton read-only behavior.
3. Live-trading lock behavior.
4. Reference sources.

## Implementation

1. Added `ExecutionBackend` as the final paper execution boundary used
   by `DailyTradingCycle`.
2. Added `LocalPaperExecutionBackend`, preserving the existing
   in-memory `PaperBroker` default.
3. Added `ExternalPaperExecutionBackend`, which maps approved
   `OrderIntent` + `RiskDecision` into broker-neutral `SubmitRequest`
   objects.
4. External paper submission uses the AI `intent_id` as
   `client_order_id`, preserving the adapter idempotency contract.
5. The scheduler injects the external backend only when
   `ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED` is truthy.
6. `RiskGate` now receives an execution-backend quantity estimate for
   target-position AI intents. The scheduler also wires
   `PaperExecutionPolicy.max_order_notional` as `max_order_value`.
7. `OrderAttempt` records `execution_backend`, `client_order_id`,
   `broker_order_id`, `broker_status`, and `broker_result_json`.

## Safety Boundaries

1. `ALPHABRIEF_AI_TRADING_ENABLED` is still required before
   `ai_daily_cycle` runs.
2. `ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED` is separately required before
   approved AI orders reach an external paper broker.
3. `ALPHABRIEF_LIVE_TRADING_ENABLED=true` still blocks the cycle before
   any committee or broker call.
4. Rejected and human-review `RiskDecision` objects are never submitted.
5. API `/api/v1/ai/run` remains a local-paper controlled run path; the
   unattended external submission path is scheduler-only.

## Tests

1. `tests/test_ai_trader_execution_backend.py` covers account-based
   quantity estimation, client-order-id propagation, risk max-quantity
   clamping, and daily-cycle external metadata.
2. `tests/test_ai_trader_scheduler.py` covers the scheduler flag path
   that injects an external paper backend and records broker metadata.

## Remaining Production-readiness Work

1. Configure a real structured-output `ModelGateway` provider instead
   of the conservative default `FakeProviderAdapter`.
2. Add pre-cycle data ingestion for fresh market data and financial
   news before `ai_daily_cycle`.
3. Reconcile `config/paper_execution_policy.yaml` with the operator's
   chosen paper provider and symbol universe.
4. Run full localhost mock-broker tests outside the restricted sandbox.
