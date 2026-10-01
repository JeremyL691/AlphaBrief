"""Decision → OrderIntent conversion (PROJECT_GUIDE 5.5).

Every intent is derived deterministically from the cycle it belongs to:

* ``intent_id = hash(cycle_id, instrument, action)`` — rerunning the same
  cycle produces the same ID, so a duplicate submission can be detected
  before the broker is called (PROJECT_GUIDE 5.5);
* an ``open_*`` action becomes a sized entry with stop loss and take
  profit from 5.6;
* a ``close`` action becomes a reduce-only intent whose quantity is the
  opposite of the current position, so it can only flatten.

The module is pure: no clock, no broker, no persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from alphabrief_core import OrderIntent, OrderSide

#: Actions an intent can carry. They are part of the deterministic ID, so
#: the same cycle can hold an entry and a close for one instrument without
#: the two colliding.
ACTION_ENTRY = "entry"
ACTION_CLOSE = "close"


class IntentError(ValueError):
    """Raised when an intent cannot be built from the given decision."""


@dataclass(frozen=True)
class IntentSizing:
    """The 5.6 sizing verdict attached to one entry intent."""

    units: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    risk_amount: Decimal
    notional: Decimal
    actual_risk: Decimal | None = None

    def describe(self) -> str:
        risk = self.actual_risk if self.actual_risk is not None else self.risk_amount
        return (
            f"units={self.units} risk_budget={self.risk_amount} "
            f"actual_risk={risk} notional={self.notional} "
            f"stop={self.stop_loss} target={self.take_profit}"
        )


def intent_action(*, reduce_only: bool, side: OrderSide) -> str:
    """Return the deterministic action string for an intent."""
    kind = ACTION_CLOSE if reduce_only else ACTION_ENTRY
    return f"{kind}:{side}"


def deterministic_intent_id(
    cycle_id: str, instrument: str, action: str
) -> str:
    """``hash(cycle_id, instrument, action)`` from PROJECT_GUIDE 5.5."""
    if not cycle_id:
        raise IntentError("cycle_id is required for a deterministic intent id")
    if not instrument:
        raise IntentError("instrument is required for a deterministic intent id")
    if not action:
        raise IntentError("action is required for a deterministic intent id")
    digest = sha256(f"{cycle_id}|{instrument}|{action}".encode()).hexdigest()
    return f"ai_{digest[:12]}"


def build_close_intent(
    *,
    cycle_id: str,
    symbol: str,
    position_units: Decimal,
    now: datetime,
    reason: str,
) -> OrderIntent:
    """Build the reduce-only intent that flattens ``position_units``.

    ``position_units`` is the signed broker position (positive long). A
    long is closed by selling the same size, a short by buying it back.
    The intent carries no protective prices: it exists to flatten, and the
    entry rules that require them do not apply to closes.
    """
    if position_units == 0:
        raise IntentError(f"{symbol} has no position to close")
    side: OrderSide = "sell" if position_units > 0 else "buy"
    quantity = abs(position_units)
    action = intent_action(reduce_only=True, side=side)
    return OrderIntent(
        intent_id=deterministic_intent_id(cycle_id, symbol, action),
        source="manual",
        symbol=symbol,
        side=side,
        order_type="market",
        quantity=quantity,
        stop_loss=None,
        take_profit=None,
        cycle_id=cycle_id,
        reduce_only=True,
        rationale=f"close {symbol}: {reason}",
        created_at=now,
    )


def build_entry_intent(
    *,
    cycle_id: str,
    symbol: str,
    side: OrderSide,
    sizing: IntentSizing | None,
    target_position_pct: Decimal | None,
    now: datetime,
    rationale: str,
    stop_loss: Decimal | None = None,
    take_profit: Decimal | None = None,
) -> OrderIntent:
    """Build an entry intent from the committee decision and 5.6 sizing.

    Exactly one of ``sizing`` (risk-based units) or
    ``target_position_pct`` (the committee's own fraction) must be given:
    the risk-based path is the production one, the percentage path keeps
    the pre-sizing committee estimate usable where no NAV/ATR is known.
    """
    if sizing is not None and target_position_pct is not None:
        raise IntentError("provide either sizing or target_position_pct, not both")
    if sizing is None and target_position_pct is None:
        raise IntentError("an entry intent needs a size")
    action = intent_action(reduce_only=False, side=side)
    payload: dict[str, object] = {
        "intent_id": deterministic_intent_id(cycle_id, symbol, action),
        "source": "model",
        "symbol": symbol,
        "side": side,
        "order_type": "market",
        "cycle_id": cycle_id,
        "rationale": rationale,
        "created_at": now,
    }
    if sizing is not None:
        payload["quantity"] = sizing.units
        payload["stop_loss"] = sizing.stop_loss
        payload["take_profit"] = sizing.take_profit
    else:
        payload["target_position_pct"] = target_position_pct
        payload["stop_loss"] = stop_loss
        payload["take_profit"] = take_profit
    return OrderIntent.model_validate(payload)


__all__ = [
    "ACTION_CLOSE",
    "ACTION_ENTRY",
    "IntentError",
    "IntentSizing",
    "build_close_intent",
    "build_entry_intent",
    "deterministic_intent_id",
    "intent_action",
]
