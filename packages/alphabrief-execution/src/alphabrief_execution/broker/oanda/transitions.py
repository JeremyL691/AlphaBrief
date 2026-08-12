"""Order and dependent-order transition facts (M06-W03).

Interprets immediate fill, pending, partial fill, cancel, reject, expire,
reissue, trade reduction, trade close, and dependent-order transitions
as immutable broker facts with a deterministic projection state machine:

- every transition carries broker transaction IDs, related IDs, UTC
  times, quantities, prices, reasons, financing, and correlation IDs;
- projections update deterministically with no impossible state jumps
  and terminal facts are never mutated;
- duplicate, out-of-order, malformed, or conflicting facts are
  idempotently ignored or quarantined — never a fabricated fill.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

OrderState = Literal[
    "PENDING",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "CLOSED",
]

TransitionKind = Literal[
    "CREATED",
    "FILLED",
    "PARTIAL_FILL",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "REISSUED",
    "REDUCED",
    "CLOSED",
    "DEPENDENT_CREATED",
    "DEPENDENT_CANCELLED",
]

#: Terminal states that no later transition may mutate.
_TERMINAL_STATES = frozenset({"FILLED", "CANCELLED", "REJECTED", "EXPIRED", "CLOSED"})


class OrderTransition(BaseModel):
    """One immutable broker transition fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transition_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    related_id: str | None = None
    kind: TransitionKind
    before_state: OrderState | None = None
    after_state: OrderState | None = None
    quantity: Decimal = Decimal("0")
    price: Decimal | None = None
    reason: str = ""
    financing: Decimal = Decimal("0")
    correlation_id: str = Field(min_length=1)
    occurred_at: datetime

    @field_validator("quantity", "price", "financing", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("transition numeric fields must not be floats")
        return value

    @field_validator("occurred_at", mode="before")
    @classmethod
    def time_must_be_utc(cls, value: Any) -> Any:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, datetime):
            parsed = value
        else:
            raise ValueError("occurred_at must be a datetime")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)


class OrderProjection(BaseModel):
    """The deterministic projection of one order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: str = Field(min_length=1)
    state: OrderState
    open_quantity: Decimal
    filled_quantity: Decimal
    average_price: Decimal | None = None
    correlation_id: str = Field(min_length=1)
    updated_at: datetime


class TransitionRejection(BaseModel):
    """A quarantined transition (duplicate, out-of-order, or conflicting)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transition_id: str
    reason: str


#: Legal (kind -> resulting state) mappings for the projection machine.
_KIND_TO_STATE: dict[str, OrderState] = {
    "CREATED": "PENDING",
    "FILLED": "FILLED",
    "PARTIAL_FILL": "PARTIALLY_FILLED",
    "CANCELLED": "CANCELLED",
    "REJECTED": "REJECTED",
    "EXPIRED": "EXPIRED",
    "REISSUED": "PENDING",
    "REDUCED": "FILLED",
    "CLOSED": "CLOSED",
}


def apply_transition(
    projection: OrderProjection | None,
    transition: OrderTransition,
) -> tuple[OrderProjection | None, TransitionRejection | None]:
    """Apply one transition deterministically.

    Returns the new projection (or ``None`` when a fact is quarantined
    before any projection exists) and an optional rejection reason for
    duplicate, out-of-order, malformed, or conflicting facts: terminal
    states are never mutated and no fill is fabricated.
    """
    if transition.kind in ("DEPENDENT_CREATED", "DEPENDENT_CANCELLED"):
        # Dependent-order facts do not change the parent's own state.
        if projection is None:
            return _initial(transition, "PENDING"), None
        return projection, None

    if (
        transition.after_state is not None
        and transition.after_state != _KIND_TO_STATE[transition.kind]
    ):
        return projection, TransitionRejection(
            transition_id=transition.transition_id,
            reason="after_state conflicts with transition kind",
        )

    target = _KIND_TO_STATE[transition.kind]

    if projection is None:
        if transition.kind in ("REDUCED", "CLOSED"):
            return None, TransitionRejection(
                transition_id=transition.transition_id,
                reason="reduce/close without a prior order",
            )
        if transition.kind == "PARTIAL_FILL":
            # A partial fill without a prior order is out of order; the
            # remaining open quantity is unknowable, so it is quarantined
            # instead of fabricating a projection.
            return None, TransitionRejection(
                transition_id=transition.transition_id,
                reason="partial fill without a prior order",
            )
        if transition.kind == "FILLED":
            # Immediate-fill facts carry the whole fill: nothing stays open.
            return OrderProjection(
                order_id=transition.order_id,
                state="FILLED",
                open_quantity=Decimal("0"),
                filled_quantity=abs(transition.quantity),
                average_price=transition.price,
                correlation_id=transition.correlation_id,
                updated_at=transition.occurred_at,
            ), None
        if transition.kind in ("CANCELLED", "REJECTED", "EXPIRED"):
            # Terminal facts without a prior order: nothing was ever open.
            return OrderProjection(
                order_id=transition.order_id,
                state=transition.kind,
                open_quantity=Decimal("0"),
                filled_quantity=Decimal("0"),
                average_price=None,
                correlation_id=transition.correlation_id,
                updated_at=transition.occurred_at,
            ), None
        return _initial(transition, target), None

    if transition.kind in ("REDUCED", "CLOSED"):
        # Trade transitions apply only to filled trades, never to a
        # pending order or an already closed trade.
        if projection.state not in ("FILLED", "PARTIALLY_FILLED"):
            return projection, TransitionRejection(
                transition_id=transition.transition_id,
                reason=f"reduce/close requires a filled trade, got {projection.state}",
            )
    elif projection.state in _TERMINAL_STATES:
        return projection, TransitionRejection(
            transition_id=transition.transition_id,
            reason=f"terminal state {projection.state} cannot be mutated",
        )

    if transition.kind == "REISSUED":
        # Reissue keeps the projection identity; the new broker order id
        # is recorded on the transition itself.
        return projection.model_copy(
            update={"updated_at": transition.occurred_at}
        ), None

    quantity = projection.open_quantity
    filled = projection.filled_quantity
    average = projection.average_price
    if transition.kind == "FILLED":
        filled = projection.filled_quantity + abs(transition.quantity)
        quantity = Decimal("0")
        if transition.price is not None:
            average = transition.price
    elif transition.kind == "PARTIAL_FILL":
        filled = projection.filled_quantity + abs(transition.quantity)
        remaining = projection.open_quantity - abs(transition.quantity)
        quantity = max(Decimal("0"), remaining)
        if transition.price is not None:
            average = transition.price
    elif transition.kind == "REDUCED":
        remaining = projection.open_quantity - abs(transition.quantity)
        quantity = max(Decimal("0"), remaining)
    elif transition.kind == "CLOSED":
        quantity = Decimal("0")
        filled = projection.filled_quantity

    return projection.model_copy(
        update={
            "state": target,
            "open_quantity": quantity,
            "filled_quantity": filled,
            "average_price": average,
            "updated_at": transition.occurred_at,
        }
    ), None


def _initial(transition: OrderTransition, state: OrderState) -> OrderProjection:
    return OrderProjection(
        order_id=transition.order_id,
        state=state,
        open_quantity=abs(transition.quantity),
        filled_quantity=Decimal("0"),
        average_price=transition.price,
        correlation_id=transition.correlation_id,
        updated_at=transition.occurred_at,
    )


__all__ = [
    "OrderProjection",
    "OrderState",
    "OrderTransition",
    "TransitionKind",
    "TransitionRejection",
    "apply_transition",
]
