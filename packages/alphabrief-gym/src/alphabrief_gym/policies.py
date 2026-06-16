"""Baseline policy evaluation for AlphaBrief trading environments."""

import random
from collections.abc import Callable, Mapping
from decimal import Decimal

from alphabrief_core import Bar
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_gym.env import (
    AlphaBriefTradingEnv,
    EpisodeMetrics,
    TradingAction,
    TradingObservation,
)
from alphabrief_gym.env_v2 import (
    AlphaBriefTradingEnvConfig,
    AlphaBriefTradingEnvV2,
)
from alphabrief_gym.schemas import (
    EnvV2Report,
    EpisodeMetricsV2,
    MultiAssetObservation,
)

Policy = Callable[[TradingObservation], TradingAction]

PolicyV2 = Callable[[MultiAssetObservation], Mapping[str, Decimal]]


class PolicyEvaluation(BaseModel):
    """Metrics for one evaluated policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_name: str = Field(min_length=1)
    metrics: EpisodeMetrics


class PolicyEvaluationV2(BaseModel):
    """Metrics for one evaluated V2 policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_name: str = Field(min_length=1)
    metrics: EpisodeMetricsV2


def run_policy_episode(
    env: AlphaBriefTradingEnv,
    policy: Policy,
    *,
    policy_name: str,
) -> PolicyEvaluation:
    """Run a policy until the environment terminates."""

    observation = env.reset()
    terminated = False
    while not terminated:
        action = policy(observation)
        result = env.step(action)
        observation = result.observation
        terminated = result.terminated or result.truncated
    return PolicyEvaluation(policy_name=policy_name, metrics=env.metrics())


def evaluate_random_policy(
    bars: list[Bar],
    *,
    seed: int = 0,
    initial_cash: Decimal = Decimal("10000"),
    fee_bps: Decimal = Decimal("0"),
    slippage_bps: Decimal = Decimal("0"),
) -> PolicyEvaluation:
    """Evaluate a deterministic-seeded random policy."""

    rng = random.Random(seed)
    env = AlphaBriefTradingEnv(
        bars,
        initial_cash=initial_cash,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )

    def policy(_observation: TradingObservation) -> TradingAction:
        return rng.choice(env.action_space)

    return run_policy_episode(env, policy, policy_name="random")


def evaluate_buy_and_hold(
    bars: list[Bar],
    *,
    initial_cash: Decimal = Decimal("10000"),
    fee_bps: Decimal = Decimal("0"),
    slippage_bps: Decimal = Decimal("0"),
) -> PolicyEvaluation:
    """Evaluate a buy-and-hold baseline."""

    env = AlphaBriefTradingEnv(
        bars,
        initial_cash=initial_cash,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )

    def policy(observation: TradingObservation) -> TradingAction:
        if observation.step_index == 0 and observation.position_quantity == 0:
            return "buy"
        return "hold"

    return run_policy_episode(env, policy, policy_name="buy_and_hold")


def run_policy_episode_v2(
    env: AlphaBriefTradingEnvV2,
    policy: PolicyV2,
    *,
    policy_name: str,
) -> PolicyEvaluationV2:
    """Run a V2 policy until the environment terminates."""

    observation = env.reset()
    terminated = False
    while not terminated:
        action = policy(observation)
        result = env.step(action)
        observation = result.observation
        terminated = result.terminated or result.truncated
    return PolicyEvaluationV2(policy_name=policy_name, metrics=env.metrics())


def evaluate_equal_weight_buy_and_hold_v2(
    bars: list[Bar],
    *,
    initial_cash: Decimal = Decimal("10000"),
    max_leverage: Decimal = Decimal("1"),
    allow_short: bool = False,
    borrow_cost_annual: Decimal = Decimal("0"),
    margin_rate: Decimal = Decimal("0.5"),
    fee_bps: Decimal = Decimal("0"),
    slippage_bps: Decimal = Decimal("0"),
    liquidity_limit_per_step: Decimal = Decimal("0"),
    max_history_steps: int = 64,
) -> EnvV2Report:
    """Run an equal-weight buy-and-hold baseline in the multi-asset env.

    At step 0 the portfolio is rebalanced to equal weights across all
    assets.  On subsequent steps the current portfolio weights are passed
    through as targets so that no further trades occur.
    """
    # Deferred import to avoid circular dependency with report.py.
    from alphabrief_gym.report import build_env_v2_report

    config = AlphaBriefTradingEnvConfig(
        initial_cash=initial_cash,
        max_leverage=max_leverage,
        allow_short=allow_short,
        borrow_cost_annual=borrow_cost_annual,
        margin_rate=margin_rate,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        liquidity_limit_per_step=liquidity_limit_per_step,
        max_history_steps=max_history_steps,
    )
    env = AlphaBriefTradingEnvV2(bars, config=config)

    def policy(observation: MultiAssetObservation) -> dict[str, Decimal]:
        n_assets = len(observation.assets)
        if n_assets == 0:
            return {}
        if observation.step_index == 0:
            equal_weight = Decimal("1") / Decimal(n_assets)
            return {symbol: equal_weight for symbol in observation.assets}
        portfolio_value = observation.portfolio.portfolio_value
        if portfolio_value == 0:
            return {symbol: Decimal("0") for symbol in observation.assets}
        action: dict[str, Decimal] = {}
        for symbol, asset_obs in observation.assets.items():
            position_value = asset_obs.position_quantity * asset_obs.close
            action[symbol] = position_value / portfolio_value
        return action

    run_policy_episode_v2(env, policy, policy_name="equal_weight_buy_and_hold")
    return build_env_v2_report(env)
