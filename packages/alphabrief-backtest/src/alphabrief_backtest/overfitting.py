"""Parameter-stability and overfitting audit (M12-W06).

Deterministic audits over declared inputs: parameter perturbation
spread, subperiod stability, walk-forward degradation, and
multiple-testing warnings. Every audit emits explicit stability
metrics and warnings; ``None`` values mark degenerate inputs, never
misleading numbers (REQ-STRAT-006).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

#: More trials than this triggers a multiple-testing warning (any
#: best-of-N result is inflated by selection).
MULTIPLE_TESTING_TRIAL_THRESHOLD = 20

#: Walk-forward degradation above this fraction of the IS return (or
#: any positive degradation on a non-positive IS run) is an overfit
#: warning (mirrors the evaluation runner's flag semantics).
WALK_FORWARD_DEGRADATION_FRACTION = Decimal("0.5")


class StabilityMetric(BaseModel):
    """One deterministic stability measure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    value: Decimal | None
    unit: str = Field(min_length=1)


class OverfitWarning(BaseModel):
    """One explicit overfitting warning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class OverfittingAudit(BaseModel):
    """The aggregate stability and overfitting audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stability_metrics: tuple[StabilityMetric, ...]
    warnings: tuple[OverfitWarning, ...]
    passed: bool


def perturbation_stability(
    returns_by_parameter: Mapping[str, Decimal],
) -> StabilityMetric:
    """Spread of returns across a parameter perturbation grid.

    ``max - min`` over the grid; ``None`` when fewer than two
    perturbations are declared.
    """
    if len(returns_by_parameter) < 2:
        return StabilityMetric(
            name="perturbation_return_spread",
            value=None,
            unit="return",
        )
    returns = list(returns_by_parameter.values())
    spread = max(returns) - min(returns)
    return StabilityMetric(
        name="perturbation_return_spread",
        value=spread,
        unit="return",
    )


def best_margin(
    returns_by_parameter: Mapping[str, Decimal],
) -> StabilityMetric:
    """How far the best parameter outperforms the median of its grid.

    A large positive margin means the best result depends on one lucky
    point rather than a stable neighborhood. ``None`` with fewer than
    three perturbations.
    """
    if len(returns_by_parameter) < 3:
        return StabilityMetric(name="best_margin", value=None, unit="return")
    returns = sorted(returns_by_parameter.values())
    median = returns[len(returns) // 2]
    margin = returns[-1] - median
    return StabilityMetric(name="best_margin", value=margin, unit="return")


def subperiod_stability(subperiod_returns: tuple[Decimal, ...]) -> StabilityMetric:
    """Coefficient of variation of returns across subperiods.

    ``std / |mean|``; ``None`` when there are fewer than two subperiods,
    the mean is zero, or the variance is degenerate.
    """
    if len(subperiod_returns) < 2:
        return StabilityMetric(
            name="subperiod_cv", value=None, unit="coefficient_of_variation"
        )
    import numpy as np

    values = np.array([float(value) for value in subperiod_returns], dtype=float)
    mean = float(values.mean())
    std = float(values.std(ddof=1))
    if mean == 0 or std != std or std <= 0:
        return StabilityMetric(
            name="subperiod_cv", value=None, unit="coefficient_of_variation"
        )
    return StabilityMetric(
        name="subperiod_cv",
        # Quantize to kill float noise while keeping determinism.
        value=Decimal(str(std / abs(mean))).quantize(Decimal("1e-12")),
        unit="coefficient_of_variation",
    )


def multiple_testing_warning(
    trial_count: int,
    *,
    threshold: int = MULTIPLE_TESTING_TRIAL_THRESHOLD,
) -> OverfitWarning | None:
    """Warn when many trials were searched before choosing the best."""
    if trial_count > threshold:
        return OverfitWarning(
            code="multiple_testing",
            message=(
                f"{trial_count} trials were searched; a best-of-N result "
                f"is inflated by selection (threshold {threshold})"
            ),
        )
    return None


def walk_forward_warning(
    *,
    is_avg_total_return: Decimal,
    oos_avg_total_return: Decimal,
    avg_degradation: Decimal,
) -> OverfitWarning | None:
    """Warn when OOS underperforms IS beyond the degradation rule."""
    if is_avg_total_return > 0:
        threshold = is_avg_total_return * WALK_FORWARD_DEGRADATION_FRACTION
        overfit = avg_degradation > threshold
    else:
        overfit = avg_degradation > 0
    if overfit:
        return OverfitWarning(
            code="walk_forward_degradation",
            message=(
                f"OOS average return {oos_avg_total_return} underperforms "
                f"IS average return {is_avg_total_return} by "
                f"{avg_degradation}"
            ),
        )
    return None


def run_overfitting_audit(
    *,
    returns_by_parameter: Mapping[str, Decimal],
    subperiod_returns: tuple[Decimal, ...],
    trial_count: int,
    is_avg_total_return: Decimal,
    oos_avg_total_return: Decimal,
    avg_degradation: Decimal,
) -> OverfittingAudit:
    """Run every stability audit and assemble the warnings."""
    metrics = (
        perturbation_stability(returns_by_parameter),
        best_margin(returns_by_parameter),
        subperiod_stability(subperiod_returns),
    )
    warnings: list[OverfitWarning] = []
    testing = multiple_testing_warning(trial_count)
    if testing is not None:
        warnings.append(testing)
    walk_forward = walk_forward_warning(
        is_avg_total_return=is_avg_total_return,
        oos_avg_total_return=oos_avg_total_return,
        avg_degradation=avg_degradation,
    )
    if walk_forward is not None:
        warnings.append(walk_forward)
    return OverfittingAudit(
        stability_metrics=metrics,
        warnings=tuple(warnings),
        passed=not warnings,
    )


__all__ = [
    "MULTIPLE_TESTING_TRIAL_THRESHOLD",
    "OverfittingAudit",
    "OverfitWarning",
    "StabilityMetric",
    "WALK_FORWARD_DEGRADATION_FRACTION",
    "best_margin",
    "multiple_testing_warning",
    "perturbation_stability",
    "run_overfitting_audit",
    "subperiod_stability",
    "walk_forward_warning",
]
