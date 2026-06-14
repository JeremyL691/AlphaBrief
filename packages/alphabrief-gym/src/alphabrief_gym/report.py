"""Strategy comparison reports for AlphaBrief trading environments."""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_gym.policies import PolicyEvaluation


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
