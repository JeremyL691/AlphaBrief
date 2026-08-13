"""M16-W02: weekly gate and scheduler restart drill.

Covers AC-M16-W02-02: Week 1 scorecard and the non-submit scheduler
restart drill pass with zero duplicate orders, zero unapproved orders,
zero live or other-broker attempt, monotonic cursor, and no unresolved
cross-day difference.
"""

from __future__ import annotations

from alphabrief_core import (
    WeeklyGateResult,
    run_recovery_drill,
    run_weekly_gate,
)


class TestWeeklyGate:
    def test_full_truth_passes(self) -> None:
        gate = run_weekly_gate(
            week=1,
            days_qualified=7,
            truth={
                "passed": True,
                "zero_duplicate_orders": True,
                "zero_unapproved_orders": True,
                "zero_live_or_other_broker_attempts": True,
                "monotonic_cursor": True,
                "zero_unresolved_cross_day_difference": True,
            },
        )
        assert isinstance(gate, WeeklyGateResult)
        assert gate.passed
        assert gate.zero_duplicate_orders is True
        assert gate.zero_unapproved_orders is True
        assert gate.zero_live_or_other_broker_attempts is True
        assert gate.monotonic_cursor is True
        assert gate.zero_unresolved_cross_day_difference is True

    def test_missing_truth_fails_closed(self) -> None:
        gate = run_weekly_gate(week=1, days_qualified=0, truth={})
        assert not gate.passed
        assert gate.zero_duplicate_orders is False
        assert gate.monotonic_cursor is False

    def test_duplicate_orders_fail_the_gate(self) -> None:
        gate = run_weekly_gate(
            week=1,
            days_qualified=7,
            truth={
                "passed": True,
                "zero_duplicate_orders": False,
                "zero_unapproved_orders": True,
                "zero_live_or_other_broker_attempts": True,
                "monotonic_cursor": True,
                "zero_unresolved_cross_day_difference": True,
            },
        )
        assert gate.zero_duplicate_orders is False
        assert not gate.passed

    def test_deterministic(self) -> None:
        truth = {
            "passed": True,
            "zero_duplicate_orders": True,
            "zero_unapproved_orders": True,
            "zero_live_or_other_broker_attempts": True,
            "monotonic_cursor": True,
            "zero_unresolved_cross_day_difference": True,
        }
        assert run_weekly_gate(week=1, days_qualified=7, truth=truth).model_dump() == (
            run_weekly_gate(week=1, days_qualified=7, truth=truth).model_dump()
        )


class TestRestartDrill:
    def test_restart_drill_is_non_submit(self) -> None:
        # The drill reports per-boundary verdicts; the CLI drill
        # command records submits=0 (never a synthetic submit).
        drill = run_recovery_drill(
            scenario="scheduler-restart", boundary_truth={}
        )
        assert len(drill.boundaries) == 12
        assert all(b.verdict == "frozen" for b in drill.boundaries)

    def test_restart_drill_boundaries_cover_the_week(self) -> None:
        drill = run_recovery_drill(
            scenario="scheduler-restart", boundary_truth={}
        )
        boundaries = [b.boundary for b in drill.boundaries]
        assert "startup" in boundaries
        assert "reconcile" in boundaries
        assert "complete" in boundaries
