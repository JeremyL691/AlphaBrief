"""Reduce-only and close validation (M08-W06).

Emergency risk reduction is permitted only when the order provably
reduces the relevant position and gross risk and still satisfies
instrument, price, identity, and audit rules (REQ-RISK-008,
AC-M08-W06-02). A mislabeled reduce request, side reversal, over-close,
exposure-increasing dependent order, stale quantity, or missing
position truth fails closed — reduce-only can never be used as a bypass
(AC-M08-W06-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("reduce-only decimal values must not be floats")
    return value


class PositionTruth(BaseModel):
    """One fresh position snapshot the reduce must be validated against."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    long_units: Decimal
    short_units: Decimal
    average_price: Decimal | None = None
    captured_at: datetime
    source_id: str = Field(min_length=1)

    @field_validator("long_units", "short_units", "average_price", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @property
    def net_units(self) -> Decimal:
        return self.long_units - self.short_units


class ReduceOnlyPreconditions(BaseModel):
    """Pre-validated identity, instrument, price, and audit rules."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_matched: bool = False
    instrument_rules_ok: bool = False
    price_fresh: bool = False
    audit_recorded: bool = False

    @property
    def satisfied(self) -> bool:
        return (
            self.identity_matched
            and self.instrument_rules_ok
            and self.price_fresh
            and self.audit_recorded
        )


class ReduceOnlyOrder(BaseModel):
    """One reduce-only order candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    side: str  # "buy" or "sell"
    units: Decimal = Field(gt=0)
    price: Decimal | None = None
    dependent_increases_exposure: bool = False
    position_max_age_seconds: int = 300

    @field_validator("units", "price", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class ReduceOnlyVerdict(BaseModel):
    """One deterministic reduce-only verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    permitted: bool
    reasons: tuple[str, ...] = ()
    pre_gross: Decimal
    post_gross: Decimal
    reduced_by: Decimal


class ReduceOnlyValidationError(RuntimeError):
    """A classified fail-closed reduce-only failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"reduce-only failed ({kind}): {detail}")


def _gross(position: PositionTruth) -> Decimal:
    return (position.long_units + position.short_units) * (
        position.average_price or Decimal("0")
    )


def validate_reduce_only(
    *,
    position: PositionTruth,
    order: ReduceOnlyOrder,
    preconditions: ReduceOnlyPreconditions,
    now: datetime | None = None,
) -> ReduceOnlyVerdict:
    """Validate one emergency risk-reduction order fail-closed.

    Permitted only when every precondition holds AND the order reduces
    the relevant side without reversing it, without over-closing, and
    without an exposure-increasing dependent order. The gross risk after
    the reduce is provably smaller than before.
    """
    reasons: list[str] = []
    if not preconditions.satisfied:
        failing = [
            name
            for name, value in (
                ("identity", preconditions.identity_matched),
                ("instrument_rules", preconditions.instrument_rules_ok),
                ("price", preconditions.price_fresh),
                ("audit", preconditions.audit_recorded),
            )
            if not value
        ]
        reasons.append("preconditions failed: " + ", ".join(failing))

    observed_at = now or datetime.now(UTC)
    age = (observed_at - position.captured_at).total_seconds()
    if age > order.position_max_age_seconds:
        reasons.append(
            f"position truth is stale ({age:.1f}s older than "
            f"{order.position_max_age_seconds}s)"
        )

    long_units = position.long_units
    short_units = position.short_units
    if long_units == 0 and short_units == 0:
        reasons.append("no position truth to reduce")

    if order.side not in ("buy", "sell"):
        reasons.append(f"side {order.side!r} is not buy or sell")
    elif long_units > 0 and order.side == "buy":
        reasons.append(
            "side reversal: buying into a long position cannot reduce it"
        )
    elif short_units > 0 and order.side == "sell":
        reasons.append(
            "side reversal: selling into a short position cannot reduce it"
        )

    if long_units > 0 and order.side == "sell":
        if order.units > long_units:
            reasons.append(
                f"over-close: reduce {order.units} exceeds long position {long_units}"
            )
    if short_units > 0 and order.side == "buy":
        if order.units > short_units:
            reasons.append(
                f"over-close: reduce {order.units} exceeds short position {short_units}"
            )

    if order.dependent_increases_exposure:
        reasons.append(
            "dependent order increases exposure; not permitted for reduce-only"
        )

    pre_gross = _gross(position)
    post_long = long_units - (
        order.units if order.side == "sell" and long_units > 0 else Decimal("0")
    )
    post_short = short_units - (
        order.units if order.side == "buy" and short_units > 0 else Decimal("0")
    )
    post_long = max(post_long, Decimal("0"))
    post_short = max(post_short, Decimal("0"))
    post_gross = (post_long + post_short) * (position.average_price or Decimal("0"))
    reduced_by = pre_gross - post_gross
    if reduced_by <= 0:
        reasons.append("order does not reduce gross risk")

    return ReduceOnlyVerdict(
        permitted=not reasons,
        reasons=tuple(reasons),
        pre_gross=pre_gross,
        post_gross=post_gross,
        reduced_by=reduced_by,
    )


__all__ = [
    "PositionTruth",
    "ReduceOnlyOrder",
    "ReduceOnlyPreconditions",
    "ReduceOnlyValidationError",
    "ReduceOnlyVerdict",
    "validate_reduce_only",
]
