"""One deterministic reduce-only execution path for manager and system exits."""

from datetime import datetime
from decimal import Decimal

from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_risk import AccountExposureContext, RiskGate

from alphabrief_trader.execution_backend import (
    ExecutionBackend,
    ExecutionBackendError,
    ExecutionBackendResult,
)
from alphabrief_trader.intents import build_close_intent
from alphabrief_trader.schemas import CycleOutcome, OrderAttempt


def close_position(
    *,
    symbol: str,
    position_units: Decimal,
    reference_price: Decimal,
    cycle_id: str,
    now: datetime,
    risk_gate: RiskGate,
    execution_backend: ExecutionBackend,
    account_context: AccountExposureContext | None,
    trading_mode: str,
    reason: str = "operator close",
    submit: bool = True,
    committee_decision_id: str | None = None,
) -> OrderAttempt:
    """Risk-check and submit a reduction without constructing any model channel."""
    intent = build_close_intent(
        cycle_id=cycle_id,
        symbol=symbol,
        position_units=position_units,
        now=now,
        reason=reason,
    ).model_copy(update={"committee_decision_id": committee_decision_id})
    # Rule 5 (data quality) is one of the entry-only rules: a close is
    # checked against the kill switch and rule 3 only, and rule 3 reads
    # the quote from the account context.
    decision = risk_gate.evaluate(
        intent,
        estimated_price=reference_price,
        estimated_quantity=abs(position_units),
        account_context=account_context,
    )
    if not decision.approved:
        return record_attempt(
            intent=intent,
            decision=decision,
            outcome="blocked_risk_gate",
            execution_result=None,
            now=now,
        )
    if not submit or trading_mode != "on":
        return record_attempt(
            intent=intent,
            decision=decision,
            outcome="blocked_trading_off",
            execution_result=None,
            now=now,
            error_message="NO_TRADE_TRADING_OFF",
        )
    try:
        execution_result = execution_backend.submit(
            intent,
            decision,
            reference_price=reference_price,
            now=now,
            estimated_quantity=abs(position_units),
        )
    except ExecutionBackendError as exc:
        return record_attempt(
            intent=intent,
            decision=decision,
            outcome="error",
            execution_result=None,
            now=now,
            error_message=str(exc),
        )
    return record_attempt(
        intent=intent,
        decision=decision,
        outcome="executed",
        execution_result=execution_result,
        now=now,
    )


def record_attempt(
    *,
    intent: OrderIntent,
    decision: RiskDecision,
    outcome: CycleOutcome,
    execution_result: ExecutionBackendResult | None,
    now: datetime,
    error_message: str | None = None,
) -> OrderAttempt:
    return OrderAttempt(
        intent_id=intent.intent_id,
        risk_decision_id=decision.decision_id,
        approved=decision.approved,
        reason=(
            error_message if error_message is not None else decision.reason or outcome
        ),
        requires_human_review=decision.requires_human_review,
        risk_tags=list(decision.risk_tags),
        max_quantity=decision.max_quantity,
        filled=execution_result.filled if execution_result is not None else False,
        order_id=(execution_result.order_id if execution_result is not None else None),
        fill_price=(
            execution_result.fill_price if execution_result is not None else None
        ),
        fill_quantity=(
            execution_result.fill_quantity if execution_result is not None else None
        ),
        execution_backend=(
            execution_result.execution_backend if execution_result is not None else None
        ),
        client_order_id=(
            execution_result.client_order_id if execution_result is not None else None
        ),
        broker_order_id=(
            execution_result.broker_order_id if execution_result is not None else None
        ),
        broker_status=(
            execution_result.broker_status if execution_result is not None else None
        ),
        outcome=outcome,
        order_intent_json=intent.model_dump(mode="json"),
        risk_decision_json=decision.model_dump(mode="json"),
        fill_json=(
            execution_result.fill_json if execution_result is not None else None
        ),
        broker_result_json=(
            execution_result.broker_result_json
            if execution_result is not None
            else None
        ),
        created_at=now,
    )
