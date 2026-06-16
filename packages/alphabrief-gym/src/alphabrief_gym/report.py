"""Strategy comparison reports for AlphaBrief trading environments."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_gym.env_v2 import AlphaBriefTradingEnvV2
from alphabrief_gym.policies import PolicyEvaluation
from alphabrief_gym.schemas import (
    EnvV2AssetMetrics,
    EnvV2CostBreakdown,
    EnvV2Report,
)


class StrategyComparisonReport(BaseModel):
    """Comparison report for evaluated trading policies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluations: list[PolicyEvaluation] = Field(min_length=1)
    best_policy: str = Field(min_length=1)


def compare_strategies(
    evaluations: Sequence[PolicyEvaluation],
) -> StrategyComparisonReport:
    """Build a report sorted by total return descending."""

    if not evaluations:
        raise ValueError("at least one evaluation is required")
    sorted_evaluations = sorted(
        evaluations,
        key=lambda evaluation: (
            -evaluation.metrics.total_return,
            evaluation.policy_name,
        ),
    )
    return StrategyComparisonReport(
        evaluations=list(sorted_evaluations),
        best_policy=sorted_evaluations[0].policy_name,
    )


def build_env_v2_report(
    env: AlphaBriefTradingEnvV2,
    *,
    report_id: str | None = None,
    per_asset_trade_counts: Mapping[str, int] | None = None,
    per_asset_realized_pnl: Mapping[str, Decimal] | None = None,
    generated_at: datetime | None = None,
) -> EnvV2Report:
    """Build an :class:`EnvV2Report` from a finished EnvV2 episode.

    The :class:`alphabrief_gym.env_v2.AlphaBriefTradingEnvV2` does not
    track per-asset trade counts or realized PnL by default, so callers
    that record those (e.g. a custom policy loop) can pass them in via
    ``per_asset_trade_counts`` and ``per_asset_realized_pnl``. When
    omitted, the per-asset entry still contains the final position.
    """

    metrics = env.metrics()
    costs = EnvV2CostBreakdown(
        slippage_cost=metrics.slippage_cost,
        market_impact_cost=metrics.market_impact_cost,
        borrow_cost=metrics.borrow_cost,
        total_cost=(
            metrics.slippage_cost
            + metrics.market_impact_cost
            + metrics.borrow_cost
        ),
    )
    assets = _build_per_asset_metrics(
        env,
        per_asset_trade_counts=per_asset_trade_counts or {},
        per_asset_realized_pnl=per_asset_realized_pnl or {},
    )
    return EnvV2Report(
        report_id=report_id or f"envv2_{uuid4().hex[:12]}",
        environment="alphabrief_gym_v2",
        steps=metrics.steps,
        initial_value=metrics.initial_value,
        final_value=metrics.final_value,
        total_return=metrics.total_return,
        max_drawdown=metrics.max_drawdown,
        trade_count=metrics.trades,
        final_leverage=_env_final_leverage(env),
        costs=costs,
        assets=assets,
        generated_at=generated_at or datetime.now(UTC),
    )


def env_v2_report_to_dict(report: EnvV2Report) -> dict[str, Any]:
    """Return a JSON-safe dict representation of an :class:`EnvV2Report`."""

    return report.model_dump(mode="json")


def _build_per_asset_metrics(
    env: AlphaBriefTradingEnvV2,
    *,
    per_asset_trade_counts: Mapping[str, int],
    per_asset_realized_pnl: Mapping[str, Decimal],
) -> list[EnvV2AssetMetrics]:
    positions = _env_positions(env)
    assets: list[EnvV2AssetMetrics] = []
    for symbol in sorted(positions.keys()):
        assets.append(
            EnvV2AssetMetrics(
                symbol=symbol,
                final_position=positions[symbol],
                realized_pnl=per_asset_realized_pnl.get(symbol, Decimal("0")),
                trade_count=per_asset_trade_counts.get(symbol, 0),
            )
        )
    return assets


def _env_positions(env: AlphaBriefTradingEnvV2) -> dict[str, Decimal]:
    positions: dict[str, Decimal] = {}
    raw_positions = getattr(env, "_positions", None)
    if isinstance(raw_positions, dict):
        for symbol, quantity in raw_positions.items():
            positions[str(symbol)] = (
                quantity if isinstance(quantity, Decimal) else Decimal(str(quantity))
            )
    if not positions:
        assets_attr = getattr(env, "assets", None)
        if isinstance(assets_attr, (list, tuple)):
            for symbol in assets_attr:
                positions[str(symbol)] = Decimal("0")
    return positions


def _env_final_leverage(env: AlphaBriefTradingEnvV2) -> Decimal:
    observation_method = getattr(env, "_observation", None)
    if observation_method is None:
        return Decimal("0")
    try:
        observation = observation_method()
    except Exception:
        return Decimal("0")
    leverage = observation.portfolio.leverage
    if isinstance(leverage, Decimal):
        return leverage
    return Decimal(str(leverage))
