"""Deterministic in-test execution backend.

Runtime code has no in-memory fill simulator any more: orders go to the
OANDA practice adapter or they fail closed. Cycle tests still need a
deterministic, network-free backend, so this double lives in the test
tree. It records every submission and fills at the reference price.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_trader.execution_backend import (
    ExecutionBackendError,
    ExecutionBackendResult,
)


@dataclass(frozen=True)
class RecordedSubmission:
    """One recorded submit call."""

    intent: OrderIntent
    decision: RiskDecision
    reference_price: Decimal
    now: datetime
    estimated_quantity: Decimal | None


class FakeExecutionBackend:
    """Deterministic :class:`ExecutionBackend` double for tests.

    Fills every accepted submission at ``reference_price`` with the
    quantity the cycle estimated, and records the call so tests can
    assert how many orders were submitted.
    """

    def __init__(
        self,
        *,
        filled: bool = True,
        order_id_prefix: str = "fake-order",
        max_order_value: Decimal | None = None,
        cash: Decimal = Decimal("100000"),
    ) -> None:
        self.filled = filled
        self._order_id_prefix = order_id_prefix
        self._max_order_value = max_order_value
        self.cash = cash
        self.positions: dict[str, Decimal] = {}
        self.submissions: list[RecordedSubmission] = []

    @property
    def submission_count(self) -> int:
        """Number of submit calls recorded so far."""
        return len(self.submissions)

    def estimate_quantity(
        self,
        intent: OrderIntent,
        *,
        reference_price: Decimal,
    ) -> Decimal | None:
        if reference_price <= 0:
            raise ExecutionBackendError("reference_price must be positive")
        if intent.quantity is not None:
            return self._clamp(intent.quantity, reference_price=reference_price)
        if intent.target_position_pct is None:
            return None
        if intent.side == "buy":
            if intent.target_position_pct == 0:
                return abs(self.positions.get(intent.symbol, Decimal("0")))
            estimated = (self.cash * intent.target_position_pct) / reference_price
            return self._clamp(estimated, reference_price=reference_price)
        if intent.target_position_pct == 0:
            return abs(self.positions.get(intent.symbol, Decimal("0")))
        return None

    def _clamp(self, quantity: Decimal, *, reference_price: Decimal) -> Decimal:
        if self._max_order_value is not None and self._max_order_value > 0:
            cap = self._max_order_value / reference_price
            return min(quantity, cap)
        return quantity

    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        reference_price: Decimal,
        now: datetime,
        estimated_quantity: Decimal | None,
    ) -> ExecutionBackendResult:
        self.submissions.append(
            RecordedSubmission(
                intent=intent,
                decision=decision,
                reference_price=reference_price,
                now=now,
                estimated_quantity=estimated_quantity,
            )
        )
        estimate = estimated_quantity
        if estimate is None or estimate <= 0:
            # The durable cycle path submits without an estimate; resolve
            # the quantity from the intent the way the risk gate does.
            estimate = self.estimate_quantity(
                intent, reference_price=reference_price
            )
        if estimate is None or estimate <= 0:
            raise ExecutionBackendError("fake backend requires a positive quantity")
        if decision.max_quantity is not None:
            if decision.max_quantity <= 0:
                raise ExecutionBackendError("risk decision max_quantity is zero")
            quantity = min(estimate, decision.max_quantity)
        else:
            quantity = estimate
        if self.filled:
            signed = quantity if intent.side == "buy" else -quantity
            self.positions[intent.symbol] = (
                self.positions.get(intent.symbol, Decimal("0")) + signed
            )
        order_id = f"{self._order_id_prefix}-{len(self.submissions)}"
        return ExecutionBackendResult(
            broker_order_id=order_id if self.filled else None,
            execution_backend="external_paper",
            order_id=order_id,
            filled=self.filled,
            fill_price=reference_price if self.filled else None,
            fill_quantity=quantity if self.filled else None,
            fill_json={"order_id": order_id} if self.filled else None,
        )


__all__ = ["FakeExecutionBackend", "RecordedSubmission"]
