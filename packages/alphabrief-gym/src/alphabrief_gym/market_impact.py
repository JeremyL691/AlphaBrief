"""Market-impact models for the AlphaBrief trading environment.

All functions in this module are pure ``Decimal`` computations that
estimate the *additional* slippage imposed by the size of a trade.
They never read or store external state and never make network calls.
The default :class:`LinearImpact` is the simplest reasonable model:
``price_impact = impact_coefficient * (trade_value / adv)``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol


class MarketImpactModel(Protocol):
    """Protocol for a market-impact estimator."""

    def estimate_impact(
        self,
        *,
        trade_value: Decimal,
        adv: Decimal,
        side: str,
    ) -> Decimal:
        """Return the price impact as a positive fraction of price."""


class LinearImpact:
    """Linear market-impact model.

    The impact is computed as
    ``impact_coefficient * (trade_value / max(adv, MIN_ADV))``,
    capped at ``max_impact_bps`` basis points.
    """

    def __init__(
        self,
        *,
        impact_coefficient: Decimal = Decimal("0.1"),
        max_impact_bps: Decimal = Decimal("100"),
    ) -> None:
        if impact_coefficient < 0:
            raise ValueError("impact_coefficient must be >= 0")
        if max_impact_bps < 0:
            raise ValueError("max_impact_bps must be >= 0")
        self._coefficient = impact_coefficient
        self._max_impact = max_impact_bps / Decimal("10000")

    def estimate_impact(
        self,
        *,
        trade_value: Decimal,
        adv: Decimal,
        side: str,
    ) -> Decimal:
        if adv <= 0:
            return self._max_impact
        if trade_value < 0:
            raise ValueError("trade_value must be >= 0")
        if side not in {"buy", "sell"}:
            raise ValueError(f"invalid side: {side!r}")
        ratio = trade_value / adv
        raw = self._coefficient * ratio
        if raw < 0:
            raw = -raw
        if raw > self._max_impact:
            return self._max_impact
        return raw


class NoImpact:
    """No-op impact model that always returns zero."""

    def estimate_impact(
        self,
        *,
        trade_value: Decimal,
        adv: Decimal,
        side: str,
    ) -> Decimal:
        return Decimal("0")


__all__ = ["LinearImpact", "MarketImpactModel", "NoImpact"]
