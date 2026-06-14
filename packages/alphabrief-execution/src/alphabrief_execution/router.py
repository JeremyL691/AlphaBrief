"""Order routing boundary for AlphaBrief paper execution."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alphabrief_core import Order, OrderIntent, RiskDecision


class OrderRouterError(ValueError):
    """Raised when an order cannot be routed."""


class OrderRouter:
    """Create paper orders only after a matching approved RiskDecision."""

    def __init__(
        self,
        *,
        broker_name: str = "paper",
        clock: Callable[[], datetime] | None = None,
        order_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if broker_name.strip() == "":
            raise ValueError("broker_name must not be blank")
        self.broker_name = broker_name
        self._clock = clock or (lambda: datetime.now(UTC))
        self._order_id_factory = order_id_factory or (lambda: f"order_{uuid4().hex}")

    def route(
        self,
        intent: OrderIntent,
        decision: RiskDecision | None,
        *,
        quantity: Decimal,
    ) -> Order:
        if decision is None:
            raise OrderRouterError("RiskDecision is required before routing")
        if decision.intent_id != intent.intent_id:
            raise OrderRouterError("RiskDecision intent_id does not match intent")
        if not decision.approved:
            raise OrderRouterError("RiskDecision is not approved")
        if decision.requires_human_review:
            raise OrderRouterError(
                "RiskDecision requires human review before execution"
            )
        if quantity <= 0:
            raise OrderRouterError("quantity must be positive")
        if decision.max_quantity is not None and quantity > decision.max_quantity:
            raise OrderRouterError("quantity exceeds RiskDecision max_quantity")

        return Order(
            order_id=self._order_id_factory(),
            intent_id=intent.intent_id,
            risk_decision_id=decision.decision_id,
            broker=self.broker_name,
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            quantity=quantity,
            status="created",
            created_at=self._clock(),
        )
