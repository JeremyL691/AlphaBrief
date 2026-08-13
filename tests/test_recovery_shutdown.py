"""M15-W05: graceful shutdown.

Covers AC-M15-W05-01: SIGTERM follows freeze, stop-new-cycle,
resolve-uncertain-submit, sync, reconcile, checkpoint, backup, and
lease-release order with bounded shutdown time.
"""

from __future__ import annotations

from decimal import Decimal

from alphabrief_core import (
    SHUTDOWN_BUDGET_S,
    SHUTDOWN_SEQUENCE,
    shutdown_plan,
)


class TestShutdownSequence:
    def test_sequence_is_exactly_eight_steps_in_order(self) -> None:
        assert SHUTDOWN_SEQUENCE == (
            "freeze",
            "stop_new_cycle",
            "resolve_uncertain_submit",
            "sync",
            "reconcile",
            "checkpoint",
            "backup",
            "lease_release",
        )

    def test_freezing_precedes_stopping_new_cycles(self) -> None:
        assert SHUTDOWN_SEQUENCE.index("freeze") < SHUTDOWN_SEQUENCE.index(
            "stop_new_cycle"
        )

    def test_uncertain_submit_resolution_precedes_sync(self) -> None:
        assert SHUTDOWN_SEQUENCE.index(
            "resolve_uncertain_submit"
        ) < SHUTDOWN_SEQUENCE.index("sync")

    def test_lease_release_is_last(self) -> None:
        assert SHUTDOWN_SEQUENCE[-1] == "lease_release"
        assert SHUTDOWN_SEQUENCE.index("backup") < SHUTDOWN_SEQUENCE.index(
            "lease_release"
        )

    def test_shutdown_budget_is_bounded(self) -> None:
        assert SHUTDOWN_BUDGET_S == Decimal("30")
        plan = shutdown_plan()
        assert plan.budget_s == SHUTDOWN_BUDGET_S
        assert plan.sequence == SHUTDOWN_SEQUENCE

    def test_plan_is_deterministic(self) -> None:
        assert shutdown_plan() == shutdown_plan()
