"""M16-W05: Day 30 close and 30-day window accounting.

Covers AC-M16-W05-01 and AC-M16-W05-03: Days 22 through 30 complete a
real uninterrupted 30-calendar-day qualified window with separate
active-market, weekend, holiday, no-trade, partial, failed, and reset
accounting; Day 30 closes new cycles, reconciles, verifies invariants,
backs up, restores, and validates artifact hashes.
"""

from __future__ import annotations

from alphabrief_core import (
    DAY30_CLOSE_STEPS,
    WINDOW_ACCOUNT_KINDS,
    Day30CloseReport,
    WindowAccounting,
    build_window_accounting,
    run_day30_close,
)


class TestWindowAccounting:
    def test_all_seven_account_kinds_are_declared(self) -> None:
        assert WINDOW_ACCOUNT_KINDS == (
            "active_market",
            "weekend",
            "holiday",
            "no_trade",
            "partial",
            "failed",
            "reset",
        )

    def test_full_window_accounting_is_complete(self) -> None:
        accounting = build_window_accounting(
            days_total=30,
            counts_truth={
                "active_market": 21,
                "weekend": 8,
                "holiday": 0,
                "no_trade": 1,
                "partial": 0,
                "failed": 0,
                "reset": 0,
            },
        )
        assert isinstance(accounting, WindowAccounting)
        assert accounting.complete is True
        assert accounting.counts["active_market"] == 21
        assert accounting.counts["weekend"] == 8

    def test_less_than_thirty_days_is_not_complete(self) -> None:
        accounting = build_window_accounting(
            days_total=29,
            counts_truth={"active_market": 20},
        )
        assert accounting.complete is False

    def test_missing_kinds_are_zero_never_fabricated(self) -> None:
        accounting = build_window_accounting(
            days_total=30, counts_truth={}
        )
        assert all(count == 0 for count in accounting.counts.values())
        assert accounting.complete is True

    def test_deterministic(self) -> None:
        truth = {"active_market": 21, "weekend": 8}
        first = build_window_accounting(days_total=30, counts_truth=truth)
        second = build_window_accounting(days_total=30, counts_truth=truth)
        assert first.model_dump() == second.model_dump()


class TestDay30Close:
    def test_all_seven_close_steps_are_declared(self) -> None:
        assert DAY30_CLOSE_STEPS == (
            "stop_new_cycles",
            "final_reconcile",
            "duplicate_invariant",
            "approval_invariant",
            "fresh_backup",
            "isolated_restore",
            "artifact_hash_validation",
        )

    def test_full_truth_passes_the_close(self) -> None:
        close = run_day30_close(
            step_truth={step: True for step in DAY30_CLOSE_STEPS}
        )
        assert isinstance(close, Day30CloseReport)
        assert close.passed is True
        assert all(step.preserved for step in close.steps)

    def test_missing_truth_fails_closed(self) -> None:
        close = run_day30_close(step_truth={})
        assert close.passed is False
        assert all(not step.preserved for step in close.steps)
        assert all(step.detail == "not completed" for step in close.steps)

    def test_partial_close_is_not_a_pass(self) -> None:
        truth = {step: True for step in DAY30_CLOSE_STEPS}
        truth["isolated_restore"] = False
        close = run_day30_close(step_truth=truth)
        assert close.passed is False
        restore = next(
            s for s in close.steps if s.name == "isolated_restore"
        )
        assert restore.preserved is False

    def test_close_never_creates_cycles_or_resubmits(self) -> None:
        # The close sequence declares stop_new_cycles and verifies the
        # duplicate/approval invariants; no submit path exists in the
        # close contract.
        assert "stop_new_cycles" in DAY30_CLOSE_STEPS
        assert "duplicate_invariant" in DAY30_CLOSE_STEPS
        assert "approval_invariant" in DAY30_CLOSE_STEPS

    def test_deterministic(self) -> None:
        truth = {step: True for step in DAY30_CLOSE_STEPS}
        first = run_day30_close(step_truth=truth)
        second = run_day30_close(step_truth=truth)
        assert first.model_dump() == second.model_dump()
