"""Baseline policy evaluation for AlphaBrief trading environments."""

import random
from collections.abc import Callable
from decimal import Decimal

from alphabrief_core import Bar
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_gym.env import (
    AlphaBriefTradingEnv,
    EpisodeMetrics,
    TradingAction,
    TradingObservation,
)

Policy = Callable[[TradingObservation], TradingAction]


class PolicyEvaluation(BaseModel):
    """Metrics for one evaluated policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_name: str = Field(min_length=1)
    metrics: EpisodeMetrics


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
