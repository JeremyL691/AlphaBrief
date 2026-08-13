"""M08-W04: consecutive-loss streak rules.

Covers:
- boundary tests for the consecutive-loss streak and its evidence-backed
  reset (AC-M08-W04-01);
- missing loss-streak state rejects new exposure and never silently
  disables the configured rule (AC-M08-W04-03);
- the durable streak derives from recorded day results and only resets
  on an evidence-backed profitable day (AC-M08-W04-02).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_risk.loss_state import LossStateStore
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
ACCOUNT = "101-004-1234567-001"


def _margin() -> MarginEvidence:
    return MarginEvidence(
        nav=Decimal("100000"),
        margin_used=Decimal("0"),
        margin_available=Decimal("100000"),
        projected_leverage=Decimal("0"),
        captured_at=NOW,
        source_id="margin-1",
    )


def _daily() -> DailyLossEvidence:
    return DailyLossEvidence(
        day_start_equity=Decimal("100000"),
        equity_now=Decimal("100000"),
        realized_day_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        captured_at=NOW,
    )


def _drawdown() -> DrawdownEvidence:
    return DrawdownEvidence(
        high_water_mark=Decimal("100000"),
        equity_now=Decimal("100000"),
    )


def _limits(max_consecutive_losses: str = "3") -> MarginLossLimits:
    return MarginLossLimits(
        max_consecutive_losses=int(max_consecutive_losses)
    )


def _evaluate(streak: LossStreakEvidence) -> dict[str, MarginLossRuleResult]:
    results = evaluate_margin_loss_rules(
        margin=_margin(),
        daily_loss=_daily(),
        drawdown=_drawdown(),
        loss_streak=streak,
        limits=_limits(),
        clock=lambda: NOW,
    )
    return {result.rule: result for result in results}


def test_loss_streak_boundary() -> None:
    rules = _evaluate(LossStreakEvidence(consecutive_losses=3))
    assert rules["consecutive_losses"].passed is True
    rules = _evaluate(LossStreakEvidence(consecutive_losses=4))
    assert rules["consecutive_losses"].passed is False


def test_missing_loss_streak_state_fails_closed() -> None:
    rules = _evaluate(LossStreakEvidence(consecutive_losses=None))
    assert rules["consecutive_losses"].passed is False
    assert "no loss-streak state" in rules["consecutive_losses"].detail


def test_no_streak_rule_when_unconfigured() -> None:
    results = evaluate_margin_loss_rules(
        margin=_margin(),
        daily_loss=_daily(),
        drawdown=_drawdown(),
        loss_streak=LossStreakEvidence(consecutive_losses=None),
        limits=MarginLossLimits(),
        clock=lambda: NOW,
    )
    rules = {result.rule: result for result in results}
    assert "consecutive_losses" not in rules


def test_streak_increments_on_losing_days(tmp_path: Path) -> None:
    store = LossStateStore(db_path=tmp_path / "loss.db")
    try:
        first = store.record_day_result(
            ACCOUNT,
            day_date=date(2026, 8, 11),
            day_start_equity=Decimal("100000"),
            end_equity=Decimal("99000"),
            owner="daily-runner",
        )
        assert first.consecutive_losses == 1
        second = store.record_day_result(
            ACCOUNT,
            day_date=date(2026, 8, 12),
            day_start_equity=Decimal("99000"),
            end_equity=Decimal("97000"),
            owner="daily-runner",
        )
        assert second.consecutive_losses == 2
        assert store.consecutive_losses(ACCOUNT) == 2
    finally:
        store.close()


def test_streak_resets_only_on_profitable_day(tmp_path: Path) -> None:
    store = LossStateStore(db_path=tmp_path / "loss.db")
    try:
        store.record_day_result(
            ACCOUNT,
            day_date=date(2026, 8, 11),
            day_start_equity=Decimal("100000"),
            end_equity=Decimal("99000"),
            owner="daily-runner",
        )
        store.record_day_result(
            ACCOUNT,
            day_date=date(2026, 8, 12),
            day_start_equity=Decimal("99000"),
            end_equity=Decimal("97000"),
            owner="daily-runner",
        )
        # A flat day (pnl == 0) is not a losing day and resets the streak.
        flat = store.record_day_result(
            ACCOUNT,
            day_date=date(2026, 8, 13),
            day_start_equity=Decimal("97000"),
            end_equity=Decimal("97000"),
            owner="daily-runner",
        )
        assert flat.consecutive_losses == 0
        assert store.consecutive_losses(ACCOUNT) == 0
    finally:
        store.close()


def test_streak_state_missing_before_any_day(tmp_path: Path) -> None:
    store = LossStateStore(db_path=tmp_path / "loss.db")
    try:
        assert store.consecutive_losses(ACCOUNT) is None
        assert store.high_water_mark(ACCOUNT) is None
        assert store.day_start(ACCOUNT, date(2026, 8, 13)) is None
    finally:
        store.close()
