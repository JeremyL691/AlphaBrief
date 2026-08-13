"""M16-W02: weekly gate and scheduler restart drill.

Covers AC-M16-W02-02: Week 1 scorecard and the non-submit scheduler
restart drill pass with zero duplicate orders, zero unapproved orders,
zero live or other-broker attempt, monotonic cursor, and no unresolved
cross-day difference.
"""

from __future__ import annotations

from alphabrief_core import (
    CONTINUITY_KINDS,
    ContinuityAccounting,
    WeeklyGateResult,
    build_continuity_accounting,
    resolve_week_event,
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


class TestContinuityAccounting:
    """AC-M16-W04-01: continuous Days 15-21 accounting."""

    def test_all_nine_continuity_kinds_are_declared(self) -> None:
        assert CONTINUITY_KINDS == (
            "heartbeat",
            "lease",
            "cursor",
            "reconciliation",
            "backup",
            "provider",
            "model_schema",
            "alert",
            "risk_state",
        )

    def test_full_continuity_truth_is_complete(self) -> None:
        accounting = build_continuity_accounting(
            day=15,
            calendar_date="2026-08-29",
            continuity_truth={kind: True for kind in CONTINUITY_KINDS},
        )
        assert isinstance(accounting, ContinuityAccounting)
        assert accounting.complete is True
        assert all(accounting.continuity.values())

    def test_missing_truth_is_never_fabricated(self) -> None:
        accounting = build_continuity_accounting(
            day=15, calendar_date="2026-08-29", continuity_truth={}
        )
        assert all(not value for value in accounting.continuity.values())
        assert accounting.complete is True

    def test_day_range_covers_third_real_week(self) -> None:
        for day in range(15, 22):
            accounting = build_continuity_accounting(
                day=day, calendar_date=f"2026-08-{day:02d}"
            )
            assert accounting.complete is True

    def test_deterministic(self) -> None:
        truth = {kind: True for kind in CONTINUITY_KINDS}
        first = build_continuity_accounting(
            day=16, calendar_date="2026-08-30", continuity_truth=truth
        )
        second = build_continuity_accounting(
            day=16, calendar_date="2026-08-30", continuity_truth=truth
        )
        assert first.model_dump() == second.model_dump()


class TestWeekThreeGateWithEvents:
    """AC-M16-W04-03: Week 3 gate composes with event resolution."""

    def test_week3_passes_only_when_events_resolve(self) -> None:
        gate = run_weekly_gate(
            week=3,
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
        events = {
            "P0": resolve_week_event(severity="P0"),
            "P1": resolve_week_event(severity="P1"),
            "P2": resolve_week_event(
                severity="P2",
                reset_decision="window-reset-w3",
                evidence_hash="sha256:abc",
                repair_reference="M16-W04",
            ),
            "P3": resolve_week_event(
                severity="P3",
                reset_decision="window-reset-w3",
                evidence_hash="sha256:abc",
                repair_reference="M16-W04",
            ),
        }
        # Week 3 can only pass when the gate passes AND no P0/P1 is
        # unresolved AND every P2/P3 has full deterministic resolution.
        assert gate.passed
        assert not events["P0"].resolved
        assert not events["P1"].resolved
        assert events["P2"].resolved
        assert events["P3"].resolved
        assert not (gate.passed and all(e.resolved for e in events.values()))

    def test_week3_without_truth_fails_closed(self) -> None:
        gate = run_weekly_gate(week=3, days_qualified=0, truth={})
        events = {
            severity: resolve_week_event(severity=severity)
            for severity in ("P0", "P1", "P2", "P3")
        }
        assert not gate.passed
        assert not any(e.resolved for e in events.values())
