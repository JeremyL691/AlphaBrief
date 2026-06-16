"""Reward functions for the AlphaBrief trading environment.

All reward functions in this module are pure ``Decimal`` computations.
They never read external state, never call models, and never bypass
the risk gate. They are interchangeable reward *shaping* signals only.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol


class RewardContext:
    """Inputs available to a reward function at each step.

    The base PnL change is always present. Rolling-history-aware
    rewards can also read the trailing returns and current volatility
    to scale the reward.
    """

    def __init__(
        self,
        *,
        pnl_change: Decimal,
        portfolio_value_before: Decimal,
        portfolio_value_after: Decimal,
        recent_returns: Sequence[Decimal] | None = None,
    ) -> None:
        self.pnl_change = pnl_change
        self.portfolio_value_before = portfolio_value_before
        self.portfolio_value_after = portfolio_value_after
        self.recent_returns: tuple[Decimal, ...] = tuple(recent_returns or ())


class RewardFunction(Protocol):
    """Protocol for reward functions."""

    def compute(self, ctx: RewardContext) -> Decimal:
        """Return the reward for the current step."""


class PnLReward:
    """Default reward: the raw change in portfolio value."""

    def compute(self, ctx: RewardContext) -> Decimal:
        return ctx.pnl_change


class ReturnReward:
    """Return-style reward: ``(value_after - value_before) / value_before``."""

    def compute(self, ctx: RewardContext) -> Decimal:
        if ctx.portfolio_value_before == 0:
            return Decimal("0")
        return (
            (ctx.portfolio_value_after - ctx.portfolio_value_before)
            / ctx.portfolio_value_before
        )


class SharpeStyleReward:
    """Rolling Sharpe-style reward using ``ctx.recent_returns``.

    The reward is the rolling mean divided by the rolling standard
    deviation, falling back to ``0`` when the standard deviation is
    zero or there is no history.
    """

    def __init__(self, window: int = 20) -> None:
        if window <= 1:
            raise ValueError("window must be >= 2")
        self._window = window

    def compute(self, ctx: RewardContext) -> Decimal:
        history = list(ctx.recent_returns[-self._window:])
        if len(history) < 2:
            return Decimal("0")
        mean = sum(history) / Decimal(len(history))
        variance = sum(
            (value - mean) * (value - mean) for value in history
        ) / Decimal(len(history) - 1)
        if variance <= 0:
            return Decimal("0")
        std = _decimal_sqrt(variance)
        if std == 0:
            return Decimal("0")
        return mean / std


class RegimeScaledReward:
    """Reward scaled by a regime-aware factor.

    When realized volatility over ``recent_returns`` is high, the
    reward magnitude is *shrunk* so noisy wins/losses are not over-
    rewarded. When volatility is low, the reward is amplified up to
    ``max_scale``.
    """

    def __init__(
        self,
        base: RewardFunction | None = None,
        *,
        high_vol_threshold: Decimal = Decimal("0.02"),
        max_scale: Decimal = Decimal("1.5"),
        min_scale: Decimal = Decimal("0.25"),
    ) -> None:
        self._base: RewardFunction = base or ReturnReward()
        if high_vol_threshold <= 0:
            raise ValueError("high_vol_threshold must be > 0")
        if max_scale < 1:
            raise ValueError("max_scale must be >= 1")
        if not (0 < min_scale <= 1):
            raise ValueError("min_scale must be in (0, 1]")
        if min_scale > max_scale:
            raise ValueError("min_scale must be <= max_scale")
        self._high_vol_threshold = high_vol_threshold
        self._max_scale = max_scale
        self._min_scale = min_scale

    def compute(self, ctx: RewardContext) -> Decimal:
        base_reward = self._base.compute(ctx)
        history = list(ctx.recent_returns)
        if len(history) < 2:
            return base_reward
        mean = sum(history) / Decimal(len(history))
        variance = sum(
            (value - mean) * (value - mean) for value in history
        ) / Decimal(len(history) - 1)
        if variance < 0:
            return base_reward
        std = _decimal_sqrt(variance) if variance > 0 else Decimal("0")
        if std == 0:
            return base_reward * self._max_scale
        if std >= self._high_vol_threshold:
            return base_reward * self._min_scale
        ratio = std / self._high_vol_threshold
        scale_span = self._max_scale - self._min_scale
        scale = self._min_scale + scale_span * (Decimal("1") - ratio)
        return base_reward * scale


def _decimal_sqrt(value: Decimal) -> Decimal:
    """Compute ``sqrt(value)`` as a ``Decimal``.

    Uses the standard library :func:`math.sqrt` with a small precision
    loss acceptable for reward shaping only.
    """
    import math

    return Decimal(str(math.sqrt(float(value))))


__all__ = [
    "PnLReward",
    "RegimeScaledReward",
    "ReturnReward",
    "RewardContext",
    "RewardFunction",
    "SharpeStyleReward",
]
