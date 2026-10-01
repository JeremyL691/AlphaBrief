"""Risk-based position sizing (PROJECT_GUIDE 5.6).

The size of a position is derived from the risk the operator is willing to
lose, never from a fraction of buying power:

* risk per trade is ``NAV x risk_pct`` (default 0.25%, halved during the
  first three days of the soak);
* the stop distance is ``stop_atr_multiple x ATR(14, H1)`` (see
  :mod:`alphabrief_trader.stops`);
* units are ``floor(risk_amount / (stop_distance x quote_to_home))``,
  normalized to the instrument's ``tradeUnitsPrecision`` and refused when
  the result is below ``minimumTradeSize`` or rounds to zero (that case is
  a legitimate ``no_trade``);
* the resulting notional is capped at ``max_order_notional_pct`` of NAV,
  and a clamped order is recomputed rather than silently oversized.

Everything is Decimal and deterministic: the same inputs always produce
the same units.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Literal

#: Fraction of NAV risked per trade.
DEFAULT_RISK_PCT = Decimal("0.0025")

#: Soak-day multiplier: the first three days risk half.
SOAK_FIRST_DAYS_RISK_MULTIPLIER = Decimal("0.5")

#: Number of leading soak days that risk half.
SOAK_HALF_RISK_DAYS = 3

#: Cap on a single order's notional as a fraction of NAV.
DEFAULT_MAX_ORDER_NOTIONAL_PCT = Decimal("0.50")


class SizingError(ValueError):
    """Raised when the inputs cannot support a sized order."""


SizingOutcome = Literal["sized", "no_trade"]


@dataclass(frozen=True)
class SizingResult:
    """One deterministic sizing verdict.

    ``risk_amount`` is the risk *budget* the size was derived from
    (``nav x risk_pct``); ``actual_risk`` is what the returned units really
    risk if the stop fills, which is smaller when the notional cap clamped
    the order.
    """

    outcome: SizingOutcome
    units: Decimal
    risk_amount: Decimal
    stop_distance: Decimal
    notional: Decimal
    reason: str
    risk_per_unit: Decimal = Decimal("0")

    @property
    def tradeable(self) -> bool:
        return self.outcome == "sized" and self.units > 0

    @property
    def actual_risk(self) -> Decimal:
        """The loss if the stop fills: units x risk per unit (home ccy)."""
        return self.units * self.risk_per_unit

    def to_dict(self) -> dict[str, str]:
        return {
            "outcome": self.outcome,
            "units": str(self.units),
            "risk_amount": str(self.risk_amount),
            "actual_risk": str(self.actual_risk),
            "stop_distance": str(self.stop_distance),
            "notional": str(self.notional),
            "reason": self.reason,
        }


def soak_risk_pct(
    *,
    base_risk_pct: Decimal = DEFAULT_RISK_PCT,
    soak_day: int | None = None,
) -> Decimal:
    """Return the risk fraction for a soak day (half during the first 3)."""
    if soak_day is None or soak_day > SOAK_HALF_RISK_DAYS:
        return base_risk_pct
    if soak_day < 0:
        raise SizingError("soak_day must not be negative")
    return base_risk_pct * SOAK_FIRST_DAYS_RISK_MULTIPLIER


@dataclass(frozen=True)
class SizingInputs:
    """The account- and instrument-specific inputs 5.6 sizing needs.

    ``nav`` is the broker account NAV, ``quote_to_home`` the home-currency
    conversion factor for the instrument's quote currency, and the
    precision/minimum come from the instrument metadata. ``soak_day``
    selects the halved risk of the first three soak days.
    """

    nav: Decimal
    quote_to_home: Decimal = Decimal("1")
    trade_units_precision: int = 0
    minimum_trade_size: Decimal = Decimal("1")
    soak_day: int | None = None
    #: Applied on top of the soak risk (0.5 after a 3% drawdown block
    #: expires, per PROJECT_GUIDE 5.7 rule 11).
    risk_multiplier: Decimal = Decimal("1")


def size_entry(
    *,
    inputs: SizingInputs,
    reference_price: Decimal,
    stop_loss: Decimal,
    risk_pct: Decimal | None = None,
) -> SizingResult:
    """Size an entry from its protective stop and the account inputs.

    The stop distance is the distance between the reference price and the
    stop computed by :mod:`alphabrief_trader.stops`; the risk fraction
    comes from the soak day unless the caller pins one.
    """
    if stop_loss <= 0:
        raise SizingError("stop_loss must be positive")
    stop_distance = abs(reference_price - stop_loss)
    if stop_distance <= 0:
        raise SizingError("the stop sits on the reference price")
    if inputs.risk_multiplier <= 0:
        raise SizingError("risk_multiplier must be positive")
    base_risk = (
        soak_risk_pct(soak_day=inputs.soak_day) if risk_pct is None else risk_pct
    )
    return compute_units(
        nav=inputs.nav,
        stop_distance=stop_distance,
        quote_to_home=inputs.quote_to_home,
        trade_units_precision=inputs.trade_units_precision,
        minimum_trade_size=inputs.minimum_trade_size,
        risk_pct=base_risk * inputs.risk_multiplier,
        price=reference_price,
    )


def _quantize_units(units: Decimal, precision: int) -> Decimal:
    if precision <= 0:
        return units.quantize(Decimal("1"), rounding=ROUND_DOWN)
    step = Decimal(1).scaleb(-precision)
    return (units / step).to_integral_value(rounding=ROUND_DOWN) * step


def compute_units(
    *,
    nav: Decimal,
    stop_distance: Decimal,
    quote_to_home: Decimal = Decimal("1"),
    trade_units_precision: int = 0,
    minimum_trade_size: Decimal = Decimal("1"),
    risk_pct: Decimal = DEFAULT_RISK_PCT,
    max_order_notional_pct: Decimal | None = DEFAULT_MAX_ORDER_NOTIONAL_PCT,
    price: Decimal | None = None,
) -> SizingResult:
    """Size one order from the risk budget and the stop distance.

    ``quote_to_home`` converts the instrument's quote-currency loss into the
    account's home currency, so a JPY-quoted pair is sized correctly (see
    the OANDA ``includeHomeConversions`` factor). ``price`` enables the
    notional cap; without it the cap cannot be applied and the size is
    still bounded by the risk budget alone.
    """
    if nav <= 0:
        raise SizingError("nav must be positive")
    if stop_distance <= 0:
        raise SizingError("stop_distance must be positive")
    if quote_to_home <= 0:
        raise SizingError("quote_to_home must be positive")
    if risk_pct <= 0:
        raise SizingError("risk_pct must be positive")

    risk_amount = nav * risk_pct
    risk_per_unit = stop_distance * quote_to_home
    if risk_per_unit <= 0:
        raise SizingError("risk per unit must be positive")
    raw_units = risk_amount / risk_per_unit
    units = _quantize_units(raw_units, trade_units_precision)

    if units <= 0 or units < minimum_trade_size:
        return SizingResult(
            outcome="no_trade",
            units=Decimal("0"),
            risk_amount=risk_amount,
            stop_distance=stop_distance,
            notional=Decimal("0"),
            reason=(
                "computed size is below the instrument's minimum trade size"
                if units > 0
                else "computed size rounds to zero units"
            ),
            risk_per_unit=risk_per_unit,
        )

    # Notional is expressed in the account's home currency, so a
    # JPY-quoted pair is compared against the cap correctly.
    notional = units * (price if price is not None else stop_distance)
    if price is not None:
        notional = notional * quote_to_home
    if price is not None and max_order_notional_pct is not None:
        cap = nav * max_order_notional_pct
        if notional > cap:
            capped_units = _quantize_units(
                cap / (price * quote_to_home), trade_units_precision
            )
            if capped_units <= 0 or capped_units < minimum_trade_size:
                return SizingResult(
                    outcome="no_trade",
                    units=Decimal("0"),
                    risk_amount=risk_amount,
                    stop_distance=stop_distance,
                    notional=Decimal("0"),
                    reason="notional cap leaves no tradeable size",
                    risk_per_unit=risk_per_unit,
                )
            units = capped_units
            notional = units * price * quote_to_home
            return SizingResult(
                outcome="sized",
                units=units,
                risk_amount=risk_amount,
                stop_distance=stop_distance,
                notional=notional,
                reason=f"clamped to {max_order_notional_pct} of NAV notional",
                risk_per_unit=risk_per_unit,
            )

    return SizingResult(
        outcome="sized",
        units=units,
        risk_amount=risk_amount,
        stop_distance=stop_distance,
        notional=notional,
        reason="sized from the risk budget",
        risk_per_unit=risk_per_unit,
    )


__all__ = [
    "DEFAULT_MAX_ORDER_NOTIONAL_PCT",
    "DEFAULT_RISK_PCT",
    "SOAK_FIRST_DAYS_RISK_MULTIPLIER",
    "SOAK_HALF_RISK_DAYS",
    "SizingError",
    "SizingInputs",
    "SizingOutcome",
    "SizingResult",
    "compute_units",
    "size_entry",
    "soak_risk_pct",
]
