"""M16-W05: week-4 restart and reconciliation drill.

Covers AC-M16-W05-02: the Week 4 restart and reconciliation drill
passes with naturally present pending state or the predefined minimal
controlled scenario and leaves no unintended order, trade, position,
freeze, or unexplained difference.
"""

from __future__ import annotations

from alphabrief_core import (
    RESTART_RECONCILE_INVARIANTS,
    RestartReconcileDrillReport,
    run_restart_reconcile_drill,
)


def _full_truth() -> dict[str, bool]:
    return {name: True for name in RESTART_RECONCILE_INVARIANTS}


class TestRestartReconcileDrill:
    def test_all_five_invariants_are_declared(self) -> None:
        assert RESTART_RECONCILE_INVARIANTS == (
            "no_unintended_order",
            "no_unintended_trade",
            "no_unintended_position",
            "no_unintended_freeze",
            "no_unexplained_difference",
        )

    def test_full_truth_passes(self) -> None:
        drill = run_restart_reconcile_drill(
            scenario="restart-reconcile", invariant_truth=_full_truth()
        )
        assert isinstance(drill, RestartReconcileDrillReport)
        assert drill.scenario == "restart-reconcile"
        assert drill.passed is True
        assert drill.submits == 0
        assert all(invariant.preserved for invariant in drill.invariants)

    def test_missing_truth_fails_closed(self) -> None:
        drill = run_restart_reconcile_drill(
            scenario="restart-reconcile", invariant_truth={}
        )
        assert drill.passed is False
        assert drill.submits == 0
        assert all(
            not invariant.preserved for invariant in drill.invariants
        )

    def test_unexplained_difference_fails_the_drill(self) -> None:
        truth = _full_truth()
        truth["no_unexplained_difference"] = False
        drill = run_restart_reconcile_drill(
            scenario="restart-reconcile", invariant_truth=truth
        )
        assert drill.passed is False
        difference = next(
            i
            for i in drill.invariants
            if i.name == "no_unexplained_difference"
        )
        assert difference.preserved is False

    def test_drill_never_submits(self) -> None:
        drill = run_restart_reconcile_drill(
            scenario="restart-reconcile", invariant_truth={}
        )
        assert drill.submits == 0

    def test_deterministic(self) -> None:
        first = run_restart_reconcile_drill(
            scenario="restart-reconcile", invariant_truth=_full_truth()
        )
        second = run_restart_reconcile_drill(
            scenario="restart-reconcile", invariant_truth=_full_truth()
        )
        assert first.model_dump() == second.model_dump()
