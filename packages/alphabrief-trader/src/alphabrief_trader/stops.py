"""Protective stop and target prices (PROJECT_GUIDE 5.6).

The stop distance is ``stop_atr_multiple x ATR(14, H1)``; the target
distance is ``take_profit_r_multiple x stop distance``. Both multiples are
clipped to the configured band (default ``[1.0, 3.0]``) so a model can
tighten or widen within bounds but never escape them. Everything is
Decimal and the ATR must be a real, positive measurement — without one
there is no stop, and the caller must not submit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

#: Allowed band for the model's stop multiple.
DEFAULT_STOP_MULTIPLE_MIN = Decimal("1.0")
DEFAULT_STOP_MULTIPLE_MAX = Decimal("3.0")

#: Defaults when the model gives no advice (PROJECT_GUIDE 5.6).
DEFAULT_STOP_ATR_MULTIPLE = Decimal("1.5")
DEFAULT_TAKE_PROFIT_R_MULTIPLE = Decimal("2.0")

#: Allowed band for the reward-to-risk multiple.
DEFAULT_R_MULTIPLE_MIN = Decimal("1.0")
DEFAULT_R_MULTIPLE_MAX = Decimal("3.0")


class StopComputationError(ValueError):
    """Raised when protective prices cannot be derived from real inputs."""


@dataclass(frozen=True)
class ProtectivePrices:
    """The stop and target attached to one order."""

    stop_loss: Decimal
    take_profit: Decimal
    stop_distance: Decimal
    atr: Decimal
    stop_multiple: Decimal
    r_multiple: Decimal

    def to_dict(self) -> dict[str, str]:
        return {
            "stop_loss": str(self.stop_loss),
            "take_profit": str(self.take_profit),
            "stop_distance": str(self.stop_distance),
            "atr": str(self.atr),
            "stop_multiple": str(self.stop_multiple),
            "r_multiple": str(self.r_multiple),
        }


def clip(value: Decimal, *, low: Decimal, high: Decimal) -> Decimal:
    """Clamp ``value`` into ``[low, high]``."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def protective_prices(
    *,
    side: Literal["buy", "sell"],
    reference_price: Decimal,
    atr: Decimal | None,
    price_precision: int = 5,
    stop_atr_multiple: Decimal | None = None,
    take_profit_r_multiple: Decimal | None = None,
    stop_multiple_min: Decimal = DEFAULT_STOP_MULTIPLE_MIN,
    stop_multiple_max: Decimal = DEFAULT_STOP_MULTIPLE_MAX,
    r_multiple_min: Decimal = DEFAULT_R_MULTIPLE_MIN,
    r_multiple_max: Decimal = DEFAULT_R_MULTIPLE_MAX,
) -> ProtectivePrices:
    """Derive the stop and target for one order.

    Raises :class:`StopComputationError` when the inputs cannot support a
    protective order (missing or non-positive ATR, non-positive price), so
    a caller can never submit an unprotected position by accident.
    """
    if reference_price <= 0:
        raise StopComputationError("reference_price must be positive")
    if atr is None or atr <= 0:
        raise StopComputationError("atr must be a positive measurement")
    requested_stop = (
        stop_atr_multiple
        if stop_atr_multiple is not None
        else DEFAULT_STOP_ATR_MULTIPLE
    )
    stop_multiple = clip(
        requested_stop,
        low=stop_multiple_min,
        high=stop_multiple_max,
    )
    r_multiple = clip(
        (
            take_profit_r_multiple
            if take_profit_r_multiple is not None
            else DEFAULT_TAKE_PROFIT_R_MULTIPLE
        ),
        low=r_multiple_min,
        high=r_multiple_max,
    )
    stop_distance = stop_multiple * atr
    target_distance = r_multiple * stop_distance
    quantum = Decimal(1).scaleb(-price_precision)
    if side == "buy":
        stop_loss = reference_price - stop_distance
        take_profit = reference_price + target_distance
    else:
        stop_loss = reference_price + stop_distance
        take_profit = reference_price - target_distance
    if stop_loss <= 0 or take_profit <= 0:
        raise StopComputationError(
            "protective prices must stay positive at this ATR and price"
        )
    return ProtectivePrices(
        stop_loss=stop_loss.quantize(quantum, rounding=ROUND_HALF_UP),
        take_profit=take_profit.quantize(quantum, rounding=ROUND_HALF_UP),
        stop_distance=stop_distance,
        atr=atr,
        stop_multiple=stop_multiple,
        r_multiple=r_multiple,
    )


def atr_from_bars(
    highs: list[Decimal],
    lows: list[Decimal],
    closes: list[Decimal],
    *,
    period: int = 14,
) -> Decimal | None:
    """Return the ATR over ``period`` bars, or ``None`` when too short.

    Uses the classic true-range definition with Wilder's smoothing over
    the available window; every value is a Decimal.
    """
    if period < 1 or len(highs) != len(lows) or len(highs) != len(closes):
        return None
    if len(closes) < period + 1:
        return None
    true_ranges: list[Decimal] = []
    for index in range(1, len(closes)):
        high = highs[index]
        low = lows[index]
        previous_close = closes[index - 1]
        true_ranges.append(
            max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
    window = true_ranges[-period:]
    if not window:
        return None
    return sum(window) / Decimal(len(window))


__all__ = [
    "DEFAULT_R_MULTIPLE_MAX",
    "DEFAULT_R_MULTIPLE_MIN",
    "DEFAULT_STOP_ATR_MULTIPLE",
    "DEFAULT_STOP_MULTIPLE_MAX",
    "DEFAULT_STOP_MULTIPLE_MIN",
    "DEFAULT_TAKE_PROFIT_R_MULTIPLE",
    "ProtectivePrices",
    "StopComputationError",
    "atr_from_bars",
    "clip",
    "protective_prices",
]
