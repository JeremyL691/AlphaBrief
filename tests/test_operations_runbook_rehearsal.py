"""M15-W06: complete runbook rehearsal.

Covers AC-M15-W06-03: a non-production rehearsal completes Day 0,
daily record, no-trade day, weekly gate, incident reset, restart,
restore, and final-report flows without counting rehearsal time as
real observation.
"""

from __future__ import annotations

from alphabrief_core import (
    REHEARSAL_STEPS,
    RehearsalReport,
    run_rehearsal,
)


class TestRehearsalFlow:
    def test_all_eight_flow_steps_are_declared(self) -> None:
        assert REHEARSAL_STEPS == (
            "day_zero",
            "daily_record",
            "no_trade_day",
            "weekly_gate",
            "incident_reset",
            "restart",
            "restore",
            "final_report",
        )

    def test_full_rehearsal_passes(self) -> None:
        report = run_rehearsal(
            {step: True for step in REHEARSAL_STEPS}
        )
        assert isinstance(report, RehearsalReport)
        assert report.passed
        assert len(report.steps) == 8

    def test_rehearsal_never_counts_as_observation(self) -> None:
        report = run_rehearsal({step: True for step in REHEARSAL_STEPS})
        assert report.counts_as_observation is False

    def test_missing_step_fails_closed(self) -> None:
        report = run_rehearsal({"day_zero": True})
        assert not report.passed
        by_step = {step.step: step for step in report.steps}
        assert by_step["day_zero"].completed is True
        assert by_step["final_report"].completed is False
        assert by_step["final_report"].detail == "not completed"

    def test_no_trade_day_is_a_valid_step(self) -> None:
        truth = {step: True for step in REHEARSAL_STEPS}
        report = run_rehearsal(truth)
        by_step = {step.step: step for step in report.steps}
        assert by_step["no_trade_day"].completed is True

    def test_deterministic(self) -> None:
        truth = {step: True for step in REHEARSAL_STEPS}
        assert run_rehearsal(truth).model_dump() == (
            run_rehearsal(truth).model_dump()
        )
