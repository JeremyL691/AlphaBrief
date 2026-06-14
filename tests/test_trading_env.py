from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alphabrief_core import Bar
from alphabrief_gym import (
    AlphaBriefTradingEnv,
    TradingEnvError,
    compare_strategies,
    evaluate_buy_and_hold,
    evaluate_random_policy,
)

START = datetime(2026, 6, 14, 9, 30, tzinfo=UTC)


def _bar(index: int, close: str) -> Bar:
    price = Decimal(close)
    return Bar(
        symbol="BTC-USD",
        timestamp=START + timedelta(minutes=index),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1"),
        source="unit-test",
        data_version="v1",
    )


def _bars(*closes: str) -> list[Bar]:
    return [_bar(index, close) for index, close in enumerate(closes)]


def test_trading_env_reset_returns_initial_observation() -> None:
    env = AlphaBriefTradingEnv(_bars("100", "110"), initial_cash=Decimal("1000"))

    observation = env.reset()

    assert observation.step_index == 0
    assert observation.symbol == "BTC-USD"
    assert observation.close == Decimal("100")
    assert observation.cash == Decimal("1000")
    assert observation.position_quantity == Decimal("0")
    assert observation.portfolio_value == Decimal("1000")


def test_trading_env_step_executes_buy_and_advances_observation() -> None:
    env = AlphaBriefTradingEnv(
        _bars("100", "110", "90"),
        initial_cash=Decimal("1000"),
    )

    result = env.step("buy")

    assert result.observation.step_index == 1
    assert result.observation.position_quantity == Decimal("10")
    assert result.observation.portfolio_value == Decimal("1100")
    assert result.reward == Decimal("0.1")
    assert result.terminated is False
    assert result.truncated is False
    assert result.info["trades"] == 1


def test_trading_env_metrics_after_episode() -> None:
    env = AlphaBriefTradingEnv(
        _bars("100", "110", "90"),
        initial_cash=Decimal("1000"),
    )

    env.step("buy")
    result = env.step("hold")

    metrics = env.metrics()
    assert result.terminated is True
    assert metrics.initial_value == Decimal("1000")
    assert metrics.final_value == Decimal("900")
    assert metrics.total_return == Decimal("-0.1")
    assert metrics.max_drawdown == Decimal("200") / Decimal("1100")
    assert metrics.steps == 2
    assert metrics.trades == 1


def test_trading_env_rejects_step_after_terminal_observation() -> None:
    env = AlphaBriefTradingEnv(_bars("100", "110"), initial_cash=Decimal("1000"))

    first = env.step("hold")
    assert first.terminated is True

    with pytest.raises(TradingEnvError, match="terminated"):
        env.step("hold")


def test_reward_uses_next_bar_only_not_later_future_bars() -> None:
    early_crash = AlphaBriefTradingEnv(
        _bars("100", "110", "1"),
        initial_cash=Decimal("1000"),
    )
    later_rally = AlphaBriefTradingEnv(
        _bars("100", "110", "1000"),
        initial_cash=Decimal("1000"),
    )

    assert early_crash.step("buy").reward == later_rally.step("buy").reward


def test_transaction_costs_and_slippage_reduce_buying_power() -> None:
    no_cost = AlphaBriefTradingEnv(
        _bars("100", "110"),
        initial_cash=Decimal("1000"),
    )
    with_cost = AlphaBriefTradingEnv(
        _bars("100", "110"),
        initial_cash=Decimal("1000"),
        fee_bps=Decimal("100"),
        slippage_bps=Decimal("100"),
    )

    no_cost_result = no_cost.step("buy")
    with_cost_result = with_cost.step("buy")

    assert with_cost_result.observation.position_quantity < (
        no_cost_result.observation.position_quantity
    )
    assert with_cost_result.observation.portfolio_value < (
        no_cost_result.observation.portfolio_value
    )


def test_environment_rejects_bad_bar_quality() -> None:
    bars = _bars("100", "110")
    bars[1] = bars[1].model_copy(update={"timestamp": bars[0].timestamp})

    with pytest.raises(ValueError, match="quality"):
        AlphaBriefTradingEnv(bars)


def test_random_policy_evaluation_is_seeded() -> None:
    bars = _bars("100", "101", "102", "103")

    first = evaluate_random_policy(bars, seed=42)
    second = evaluate_random_policy(bars, seed=42)

    assert first == second
    assert first.policy_name == "random"
    assert first.metrics.steps == 3


def test_buy_and_hold_baseline_and_comparison_report() -> None:
    bars = _bars("100", "110", "120")

    buy_and_hold = evaluate_buy_and_hold(bars, initial_cash=Decimal("1000"))
    random_eval = evaluate_random_policy(bars, seed=0, initial_cash=Decimal("1000"))
    report = compare_strategies([random_eval, buy_and_hold])

    assert buy_and_hold.policy_name == "buy_and_hold"
    assert buy_and_hold.metrics.final_value == Decimal("1200")
    assert report.best_policy == "buy_and_hold"
    assert report.evaluations[0].policy_name == "buy_and_hold"


def test_comparison_report_requires_evaluations() -> None:
    with pytest.raises(ValueError, match="at least one"):
        compare_strategies([])
