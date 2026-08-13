"""M08-W04: margin available/used, closeout proximity, projected leverage.

Covers:
- boundary tests for margin available and used, margin closeout
  proximity, projected leverage, and margin freshness (AC-M08-W04-01);
- missing or stale margin evidence rejects new exposure and never
  silently disables a configured rule (AC-M08-W04-03).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alphabrief_risk.margin_loss_rules import (
    DailyLossEvidence,
    DrawdownEvidence,
    LossStreakEvidence,
    MarginEvidence,
    MarginLossLimits,
    MarginLossRuleResult,
    evaluate_margin_loss_rules,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _margin(**overrides: object) -> MarginEvidence:
    payload: dict[str, object] = {
        "nav": Decimal("100000"),
        "margin_used": Decimal("20000"),
        "margin_available": Decimal("80000"),
        "projected_leverage": Decimal("0.5"),
        "captured_at": NOW,
        "source_id": "margin-1",
    }
    payload.update(overrides)
    return MarginEvidence.model_validate(payload)


def _daily(**overrides: object) -> DailyLossEvidence:
    payload: dict[str, object] = {
        "day_start_equity": Decimal("100000"),
        "equity_now": Decimal("100000"),
        "realized_day_pnl": Decimal("0"),
        "unrealized_pnl": Decimal("0"),
        "captured_at": NOW,
    }
    payload.update(overrides)
    return DailyLossEvidence.model_validate(payload)


def _drawdown(**overrides: object) -> DrawdownEvidence:
    payload: dict[str, object] = {
        "high_water_mark": Decimal("100000"),
        "equity_now": Decimal("100000"),
    }
    payload.update(overrides)
    return DrawdownEvidence.model_validate(payload)


def _streak(**overrides: object) -> LossStreakEvidence:
    payload: dict[str, object] = {"consecutive_losses": 0}
    payload.update(overrides)
    return LossStreakEvidence.model_validate(payload)


def _limits(**overrides: object) -> MarginLossLimits:
    return MarginLossLimits.model_validate(overrides)


def _evaluate(
    *,
    margin: MarginEvidence | None = None,
    daily: DailyLossEvidence | None = None,
    drawdown: DrawdownEvidence | None = None,
    streak: LossStreakEvidence | None = None,
    limits: MarginLossLimits | None = None,
    evidence_max_age_seconds: int = 300,
) -> dict[str, MarginLossRuleResult]:
    results = evaluate_margin_loss_rules(
        margin=margin or _margin(),
        daily_loss=daily or _daily(),
        drawdown=drawdown or _drawdown(),
        loss_streak=streak or _streak(),
        limits=limits or _limits(),
        evidence_max_age_seconds=evidence_max_age_seconds,
        clock=lambda: NOW,
    )
    return {result.rule: result for result in results}


def _rule(
    rules: dict[str, MarginLossRuleResult], name: str
) -> MarginLossRuleResult:
    return rules[name]


def test_margin_utilization_boundary() -> None:
    rules = _evaluate(
        limits=_limits(max_margin_utilization_pct=Decimal("0.5"))
    )
    # 20000 / 100000 = 0.2 <= 0.5.
    assert _rule(rules, "margin_utilization").passed is True
    rules = _evaluate(
        margin=_margin(margin_used=Decimal("60000")),
        limits=_limits(max_margin_utilization_pct=Decimal("0.5")),
    )
    assert _rule(rules, "margin_utilization").passed is False


def test_closeout_proximity_boundary() -> None:
    rules = _evaluate(
        limits=_limits(min_margin_available_pct=Decimal("0.1"))
    )
    # 80000 / 100000 = 0.8 >= 0.1.
    assert _rule(rules, "closeout_proximity").passed is True
    rules = _evaluate(
        margin=_margin(margin_available=Decimal("5000")),
        limits=_limits(min_margin_available_pct=Decimal("0.1")),
    )
    assert _rule(rules, "closeout_proximity").passed is False


def test_projected_leverage_boundary() -> None:
    rules = _evaluate(limits=_limits(max_leverage=Decimal("1")))
    assert _rule(rules, "projected_leverage").passed is True
    rules = _evaluate(
        margin=_margin(projected_leverage=Decimal("1.5")),
        limits=_limits(max_leverage=Decimal("1")),
    )
    assert _rule(rules, "projected_leverage").passed is False


def test_margin_freshness_boundary() -> None:
    rules = _evaluate(
        margin=_margin(captured_at=NOW - timedelta(seconds=299)),
        limits=_limits(),
    )
    assert _rule(rules, "margin_fresh").passed is True
    rules = _evaluate(
        margin=_margin(captured_at=NOW - timedelta(seconds=301)),
        limits=_limits(),
    )
    assert _rule(rules, "margin_fresh").passed is False


def test_missing_margin_inputs_fail_closed() -> None:
    # Missing leverage evidence never disables the configured rule.
    rules = _evaluate(
        margin=_margin(projected_leverage=None),
        limits=_limits(max_leverage=Decimal("1")),
    )
    assert _rule(rules, "projected_leverage").passed is False
    assert "no leverage evidence" in _rule(rules, "projected_leverage").detail


def test_unconfigured_margin_limits_emit_nothing() -> None:
    rules = _evaluate(limits=_limits())
    assert "margin_utilization" not in rules
    assert "closeout_proximity" not in rules
    assert "projected_leverage" not in rules


def test_float_margin_values_rejected() -> None:
    with pytest.raises(ValueError):
        _margin(nav=100000.0)
    with pytest.raises(ValueError):
        _limits(max_leverage=1.0)
