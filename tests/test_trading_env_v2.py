"""Tests for the multi-asset trading environment (Phase 11)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

import pytest
from alphabrief_core import Bar
from alphabrief_gym import (
    AlphaBriefTradingEnvConfig,
    AlphaBriefTradingEnvV2,
    LinearImpact,
    NoImpact,
    PnLReward,
    RegimeScaledReward,
    ReturnReward,
    SharpeStyleReward,
    TradingEnvError,
)

if TYPE_CHECKING:
    from alphabrief_gym.rewards import RewardContext


def _bar(symbol: str, index: int, close: str) -> Bar:
    price = Decimal(close)
    base = datetime(2026, 6, 14, 9, 30, tzinfo=UTC)
    return Bar(
        symbol=symbol,
        timestamp=base + timedelta(minutes=index),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1"),
        source="unit-test",
        data_version="v1",
    )


def _bars(symbol: str, *closes: str) -> list[Bar]:
    return [_bar(symbol, idx, close) for idx, close in enumerate(closes)]


def _multi_asset_bars(prices: dict[str, list[str]]) -> list[Bar]:
    bars: list[Bar] = []
    for symbol, closes in prices.items():
        bars.extend(_bars(symbol, *closes))
    return bars


def test_multi_asset_env_reset_returns_observation() -> None:
    bars = _multi_asset_bars(
        {"AAPL": ["100", "110", "120"], "MSFT": ["200", "210", "220"]},
    )
    env = AlphaBriefTradingEnvV2(bars)
    obs = env.reset()

    assert obs.step_index == 0
    assert set(obs.assets.keys()) == {"AAPL", "MSFT"}
    assert obs.portfolio.cash == Decimal("10000")
    assert obs.portfolio.positions == {"AAPL": Decimal("0"), "MSFT": Decimal("0")}


def test_multi_asset_env_step_targets_first_observation_close() -> None:
    bars = _multi_asset_bars(
        {"AAPL": ["100", "110", "120"], "MSFT": ["200", "210", "220"]},
    )
    env = AlphaBriefTradingEnvV2(bars)
    env.reset()
    result = env.step({"AAPL": Decimal("0.5"), "MSFT": Decimal("0.5")})

    assert result.observation.step_index == 1
    assert result.terminated is False
    assert result.observation.portfolio.cash < Decimal("10000")
    assert result.observation.portfolio.positions["AAPL"] > 0
    assert result.observation.portfolio.positions["MSFT"] > 0


def test_multi_asset_env_max_leverage_enforced() -> None:
    bars = _multi_asset_bars(
        {"AAPL": ["100", "110", "120"], "MSFT": ["200", "210", "220"]},
    )
    env = AlphaBriefTradingEnvV2(
        bars, config=AlphaBriefTradingEnvConfig(max_leverage=Decimal("1")),
    )
    env.reset()
    with pytest.raises(ValueError, match="exceeds"):
        env.step({"AAPL": Decimal("1.5"), "MSFT": Decimal("0")})


def test_multi_asset_env_short_disabled_by_default() -> None:
    bars = _multi_asset_bars(
        {"AAPL": ["100", "110", "120"], "MSFT": ["200", "210", "220"]},
    )
    env = AlphaBriefTradingEnvV2(bars)
    env.reset()
    with pytest.raises(ValueError, match="short not allowed"):
        env.step({"AAPL": Decimal("-0.1"), "MSFT": Decimal("0")})


def test_multi_asset_env_short_enabled_with_borrow_cost() -> None:
    bars = _multi_asset_bars(
        {"AAPL": ["100", "90", "80"], "MSFT": ["200", "210", "220"]},
    )
    env = AlphaBriefTradingEnvV2(
        bars,
        config=AlphaBriefTradingEnvConfig(
            allow_short=True,
            borrow_cost_annual=Decimal("0.365"),
        ),
    )
    env.reset()
    env.step({"AAPL": Decimal("-0.5"), "MSFT": Decimal("0")})
    final = env.step({"AAPL": Decimal("-0.5"), "MSFT": Decimal("0")})

    metrics = env.metrics()
    assert metrics.borrow_cost > 0
    assert cast(Decimal, final.info["borrow_cost_accrued"]) > 0


def test_multi_asset_env_short_position_can_profit() -> None:
    bars = _multi_asset_bars(
        {"AAPL": ["100", "80", "60"], "MSFT": ["200", "210", "220"]},
    )
    env = AlphaBriefTradingEnvV2(
        bars,
        config=AlphaBriefTradingEnvConfig(
            allow_short=True,
            borrow_cost_annual=Decimal("0"),
        ),
    )
    env.reset()
    env.step({"AAPL": Decimal("-1"), "MSFT": Decimal("0")})
    env.step({"AAPL": Decimal("-1"), "MSFT": Decimal("0")})
    metrics = env.metrics()
    assert metrics.total_return > 0


def test_multi_asset_env_liquidity_limit_caps_trade_value() -> None:
    bars = _multi_asset_bars(
        {"AAPL": ["100", "110", "120"], "MSFT": ["200", "210", "220"]},
    )
    env = AlphaBriefTradingEnvV2(
        bars,
        config=AlphaBriefTradingEnvConfig(
            liquidity_limit_per_step=Decimal("2000"),
        ),
    )
    env.reset()
    env.step({"AAPL": Decimal("1"), "MSFT": Decimal("0")})
    positions = env._positions
    assert positions["AAPL"] * Decimal("100") <= Decimal("2000")


def test_multi_asset_env_market_impact_reduces_execution_price() -> None:
    bars = _multi_asset_bars(
        {"AAPL": ["100", "110", "120"], "MSFT": ["200", "210", "220"]},
    )
    no_impact = AlphaBriefTradingEnvV2(bars, market_impact=NoImpact())
    with_impact = AlphaBriefTradingEnvV2(
        bars,
        market_impact=LinearImpact(
            impact_coefficient=Decimal("0.5"),
            max_impact_bps=Decimal("1000"),
        ),
    )
    no_impact.reset()
    with_impact.reset()
    no_impact.step({"AAPL": Decimal("1"), "MSFT": Decimal("0")})
    with_impact.step({"AAPL": Decimal("1"), "MSFT": Decimal("0")})

    no_metrics = no_impact.metrics()
    with_metrics = with_impact.metrics()
    assert with_metrics.market_impact_cost > 0
    assert no_metrics.market_impact_cost == 0


def test_multi_asset_env_rejects_uneven_bar_counts() -> None:
    bars = _multi_asset_bars(
        {"AAPL": ["100", "110", "120"], "MSFT": ["200", "210"]},
    )
    with pytest.raises(ValueError, match="same number of bars"):
        AlphaBriefTradingEnvV2(bars)


def test_multi_asset_env_terminates_at_end() -> None:
    bars = _multi_asset_bars(
        {"AAPL": ["100", "110"], "MSFT": ["200", "210"]},
    )
    env = AlphaBriefTradingEnvV2(bars)
    env.reset()
    result = env.step({"AAPL": Decimal("0"), "MSFT": Decimal("0")})
    assert result.terminated is True


def test_multi_asset_env_step_after_terminated_raises() -> None:
    bars = _multi_asset_bars(
        {"AAPL": ["100", "110"], "MSFT": ["200", "210"]},
    )
    env = AlphaBriefTradingEnvV2(bars)
    env.reset()
    env.step({"AAPL": Decimal("0"), "MSFT": Decimal("0")})
    with pytest.raises(TradingEnvError, match="terminated"):
        env.step({"AAPL": Decimal("0"), "MSFT": Decimal("0")})


def test_pnl_reward_returns_pnl_change() -> None:
    reward = PnLReward()
    ctx = reward_ctx(pnl=Decimal("100"), before=Decimal("1000"), after=Decimal("1100"))
    assert reward.compute(ctx) == Decimal("100")


def test_return_reward_returns_fractional_change() -> None:
    reward = ReturnReward()
    ctx = reward_ctx(pnl=Decimal("100"), before=Decimal("1000"), after=Decimal("1100"))
    assert reward.compute(ctx) == Decimal("0.1")


def test_sharpe_reward_zero_for_short_history() -> None:
    reward = SharpeStyleReward()
    ctx = reward_ctx(
        pnl=Decimal("10"),
        before=Decimal("100"),
        after=Decimal("110"),
        history=[Decimal("0.1")],
    )
    assert reward.compute(ctx) == Decimal("0")


def test_sharpe_reward_positive_for_consistent_gains() -> None:
    reward = SharpeStyleReward()
    history = [
        Decimal("0.01"), Decimal("0.011"), Decimal("0.009"),
        Decimal("0.012"), Decimal("0.008"), Decimal("0.013"),
        Decimal("0.007"), Decimal("0.014"), Decimal("0.006"),
        Decimal("0.015"),
    ]
    ctx = reward_ctx(
        pnl=Decimal("10"),
        before=Decimal("100"),
        after=Decimal("110"),
        history=history,
    )
    assert reward.compute(ctx) > 0


def test_regime_scaled_shrinks_reward_in_high_vol() -> None:
    inner = ReturnReward()
    reward = RegimeScaledReward(
        base=inner,
        high_vol_threshold=Decimal("0.01"),
        min_scale=Decimal("0.5"),
        max_scale=Decimal("1.0"),
    )
    history = [
        Decimal("0.10"), Decimal("-0.10"), Decimal("0.10"),
        Decimal("-0.10"), Decimal("0.10"), Decimal("-0.10"),
        Decimal("0.10"), Decimal("-0.10"), Decimal("0.10"),
        Decimal("-0.10"),
    ]
    ctx = reward_ctx(
        pnl=Decimal("100"),
        before=Decimal("1000"),
        after=Decimal("1100"),
        history=history,
    )
    scaled = reward.compute(ctx)
    raw = inner.compute(ctx)
    assert scaled < raw


def test_regime_scaled_amplifies_in_low_vol() -> None:
    inner = ReturnReward()
    reward = RegimeScaledReward(
        base=inner,
        high_vol_threshold=Decimal("0.05"),
        min_scale=Decimal("0.5"),
        max_scale=Decimal("2.0"),
    )
    history = [
        Decimal("0.001"), Decimal("-0.001"),
        Decimal("0.002"), Decimal("-0.001"),
        Decimal("0.001"), Decimal("0.001"),
        Decimal("-0.001"), Decimal("0.002"),
        Decimal("0.001"), Decimal("-0.001"),
    ]
    ctx = reward_ctx(
        pnl=Decimal("100"),
        before=Decimal("1000"),
        after=Decimal("1100"),
        history=history,
    )
    scaled = reward.compute(ctx)
    raw = inner.compute(ctx)
    assert scaled > raw


def test_regime_scaled_no_lookahead_uses_only_history() -> None:
    inner = ReturnReward()
    reward = RegimeScaledReward(base=inner, high_vol_threshold=Decimal("0.5"))
    ctx = reward_ctx(
        pnl=Decimal("0"),
        before=Decimal("100"),
        after=Decimal("100"),
        history=[],
    )
    assert reward.compute(ctx) == Decimal("0")


def reward_ctx(
    *,
    pnl: Decimal,
    before: Decimal,
    after: Decimal,
    history: list[Decimal] | None = None,
) -> RewardContext:
    from alphabrief_gym.rewards import RewardContext

    return RewardContext(
        pnl_change=pnl,
        portfolio_value_before=before,
        portfolio_value_after=after,
        recent_returns=history or [],
    )
