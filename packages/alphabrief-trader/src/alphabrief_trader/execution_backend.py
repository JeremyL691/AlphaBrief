"""Execution backends for AI-approved paper orders.

The AI trading cycle decides *whether* an order candidate may proceed.
This module owns the final paper execution hop. The default backend is
the local in-memory ``PaperBroker``. The external backend is an explicit
paper-only bridge to the broker-neutral ``BrokerAdapter`` port.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_execution import (
    PaperBroker,
    PaperBrokerError,
    PaperBrokerResult,
)
from alphabrief_execution.broker.errors import BrokerAdapterError
from alphabrief_execution.broker.port import (
    BrokerAdapter,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerTimeInForce,
    SubmitRequest,
)
from alphabrief_execution.broker.risk_context import (
    BrokerRiskContextBuilder,
    RiskContextError,
    adapter_risk_sources,
)
from alphabrief_risk.instrument_rules import validate_execution_inputs


class ExecutionBackendError(ValueError):
    """Raised when a paper execution backend refuses or fails an order."""


ExecutionBackendName = Literal["local_paper", "external_paper"]


@dataclass(frozen=True)
class ExecutionBackendResult:
    """Normalized result from a local or external paper backend."""

    execution_backend: ExecutionBackendName
    order_id: str
    filled: bool
    fill_price: Decimal | None
    fill_quantity: Decimal | None
    fill_json: dict[str, object] | None
    client_order_id: str | None = None
    broker_order_id: str | None = None
    broker_status: str | None = None
    broker_result_json: dict[str, object] | None = None
    risk_context_version: str | None = None


class ExecutionBackend(Protocol):
    """Small synchronous contract used by ``DailyTradingCycle``."""

    def estimate_quantity(
        self,
        intent: OrderIntent,
        *,
        reference_price: Decimal,
    ) -> Decimal | None:
        """Return a pre-risk quantity estimate, or ``None`` when unavailable."""

    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        reference_price: Decimal,
        now: datetime,
        estimated_quantity: Decimal | None,
    ) -> ExecutionBackendResult:
        """Submit an approved, non-human-review order candidate."""


class LocalPaperExecutionBackend:
    """Execution backend that delegates to the local ``PaperBroker``."""

    def __init__(
        self,
        broker: PaperBroker,
        *,
        max_order_value: Decimal | None = None,
    ) -> None:
        self._broker = broker
        self._max_order_value = max_order_value

    def estimate_quantity(
        self,
        intent: OrderIntent,
        *,
        reference_price: Decimal,
    ) -> Decimal | None:
        if reference_price <= 0:
            raise ExecutionBackendError("reference_price must be positive")
        if intent.quantity is not None:
            return _clamp_quantity(
                intent.quantity,
                reference_price=reference_price,
                max_order_value=self._max_order_value,
            )
        if intent.target_position_pct is None:
            return None
        if intent.side == "buy":
            estimated = (self._broker.portfolio.cash * intent.target_position_pct) / (
                reference_price
            )
            return _clamp_quantity(
                estimated,
                reference_price=reference_price,
                max_order_value=self._max_order_value,
            )
        if intent.target_position_pct == 0:
            return self._broker.portfolio.position_quantity(intent.symbol)
        return None

    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        reference_price: Decimal,
        now: datetime,
        estimated_quantity: Decimal | None,
    ) -> ExecutionBackendResult:
        try:
            fill: PaperBrokerResult = self._broker.submit(
                intent, decision, reference_price=reference_price
            )
        except PaperBrokerError as exc:
            raise ExecutionBackendError(str(exc)) from exc

        return ExecutionBackendResult(
            execution_backend="local_paper",
            order_id=fill.order.order_id,
            filled=True,
            fill_price=fill.fill.price,
            fill_quantity=fill.fill.quantity,
            fill_json=fill.fill.model_dump(mode="json"),
        )


class ExternalPaperExecutionBackend:
    """Execution backend that submits to a configured external paper adapter.

    M08-W01: every external submit first builds a broker-fresh risk
    context through the shared context service (the default composition
    derives its venue sources from this backend's adapter; an explicit
    builder can be injected for tests or richer OANDA compositions). A
    missing, stale, account-mismatched, partially covered, frozen, or
    internally inconsistent context rejects the order before any submit
    — no synthesized defaults, no fallback account, no review bypass.
    """

    def __init__(
        self,
        adapter: BrokerAdapter,
        *,
        max_order_value: Decimal | None = None,
        risk_context_builder: BrokerRiskContextBuilder | None = None,
    ) -> None:
        self._adapter = adapter
        self._max_order_value = max_order_value
        self._risk_context_builder: BrokerRiskContextBuilder = (
            risk_context_builder
            or BrokerRiskContextBuilder(adapter_risk_sources(adapter))
        )

    def estimate_quantity(
        self,
        intent: OrderIntent,
        *,
        reference_price: Decimal,
    ) -> Decimal | None:
        if reference_price <= 0:
            raise ExecutionBackendError("reference_price must be positive")
        if intent.quantity is not None:
            return _clamp_quantity(
                intent.quantity,
                reference_price=reference_price,
                max_order_value=self._max_order_value,
            )
        if intent.target_position_pct is None:
            return None
        if intent.side == "buy":
            account = _run_blocking(self._adapter.get_account())
            estimated = (account.buying_power * intent.target_position_pct) / (
                reference_price
            )
            return _clamp_quantity(
                estimated,
                reference_price=reference_price,
                max_order_value=self._max_order_value,
            )
        if intent.target_position_pct == 0:
            positions = _run_blocking(self._adapter.get_positions())
            for position in positions:
                if position.symbol == intent.symbol:
                    return abs(position.quantity)
            return Decimal("0")
        raise ExecutionBackendError(
            "external paper sell requires an explicit quantity or flat target"
        )

    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        reference_price: Decimal,
        now: datetime,
        estimated_quantity: Decimal | None,
    ) -> ExecutionBackendResult:
        # M08-W01: a broker-fresh risk context is required before any
        # external submit. A missing, stale, account-mismatched, partial,
        # frozen, or inconsistent context rejects the order here — the
        # backend never submits without it (REQ-RISK-010).
        try:
            context = self._risk_context_builder.build()
        except RiskContextError as exc:
            raise ExecutionBackendError(
                f"broker-fresh risk context unavailable: {exc}"
            ) from exc
        if not context.internally_consistent:
            raise ExecutionBackendError(
                "broker-fresh risk context is internally inconsistent"
            )
        quantity = _resolve_external_quantity(
            decision=decision,
            estimated_quantity=estimated_quantity,
        )
        request = SubmitRequest(
            symbol=intent.symbol,
            side=(
                BrokerOrderSide.BUY
                if intent.side == "buy"
                else BrokerOrderSide.SELL
            ),
            order_type=(
                BrokerOrderType.MARKET
                if intent.order_type == "market"
                else BrokerOrderType.LIMIT
            ),
            quantity=quantity,
            limit_price=intent.limit_price,
            time_in_force=BrokerTimeInForce.DAY,
        )

        # M08-W02: when the approved decision binds its executable
        # inputs, any post-decision change of symbol, units, price,
        # instrument version, or snapshot hash invalidates the submit
        # (AC-M08-W02-03, REQ-RISK-010).
        if decision.execution_input_hash is not None:
            if not validate_execution_inputs(
                decision.decision_id,
                decision.execution_input_hash,
                symbol=request.symbol,
                units=request.quantity,
                price=request.limit_price,
                instrument_version=context.catalog_version,
                snapshot_hash=context.captured_at.isoformat(),
            ):
                raise ExecutionBackendError(
                    "execution inputs no longer match the approved "
                    "RiskDecision"
                )

        try:
            result = _run_blocking(
                self._adapter.submit(request, client_order_id=intent.intent_id)
            )
        except (BrokerAdapterError, NotImplementedError) as exc:
            raise ExecutionBackendError(str(exc)) from exc
        filled = result.status == BrokerOrderStatus.FILLED
        return ExecutionBackendResult(
            execution_backend="external_paper",
            order_id=result.broker_order_id,
            client_order_id=result.client_order_id,
            broker_order_id=result.broker_order_id,
            broker_status=str(result.status),
            broker_result_json=result.model_dump(mode="json"),
            filled=filled,
            fill_price=None,
            fill_quantity=quantity if filled else None,
            fill_json=None,
            risk_context_version=context.context_version,
        )


def is_ai_external_paper_enabled() -> bool:
    """Return True when AI-approved orders may reach the external paper broker."""

    raw = os.environ.get("ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED", "").lower().strip()
    return raw in {"1", "true", "yes", "on"}


def _resolve_external_quantity(
    *,
    decision: RiskDecision,
    estimated_quantity: Decimal | None,
) -> Decimal:
    if estimated_quantity is None or estimated_quantity <= 0:
        raise ExecutionBackendError("external paper requires a positive quantity")
    if decision.max_quantity is not None:
        if decision.max_quantity <= 0:
            raise ExecutionBackendError("risk decision max_quantity is zero")
        return min(estimated_quantity, decision.max_quantity)
    return estimated_quantity


def _clamp_quantity(
    quantity: Decimal,
    *,
    reference_price: Decimal,
    max_order_value: Decimal | None,
) -> Decimal:
    """Clamp an estimated quantity to the USD notional cap (tighten-only).

    The RiskGate rejects orders whose notional exceeds the policy
    ``max_order_notional``; clamping the *estimate* to the cap before
    risk evaluation keeps auto-execution functional instead of blocked.
    """
    if max_order_value is None or max_order_value <= 0:
        return quantity
    if reference_price <= 0:
        return quantity
    cap_quantity = max_order_value / reference_price
    return min(quantity, cap_quantity)


def _run_blocking[T](awaitable: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result: list[T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(awaitable))
        except BaseException as exc:  # pragma: no cover - re-raised below
            errors.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


__all__ = [
    "ExecutionBackend",
    "ExecutionBackendError",
    "ExecutionBackendResult",
    "ExternalPaperExecutionBackend",
    "LocalPaperExecutionBackend",
    "is_ai_external_paper_enabled",
]
