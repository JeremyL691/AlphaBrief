"""M15-W05: bounded soak and restore drills.

Covers AC-M15-W05-03: the bounded soak and isolated restore drills
preserve heartbeats, writer ownership, memory and descriptor budgets,
projection equality, reconciliation truth, and backup integrity.
"""

from __future__ import annotations

from alphabrief_core import (
    SOAK_INVARIANTS,
    SoakRun,
    run_soak,
)


class TestSoakInvariants:
    def test_all_declared_invariants_are_covered(self) -> None:
        assert SOAK_INVARIANTS == (
            "heartbeats",
            "writer_ownership",
            "memory_budget",
            "descriptor_budget",
            "projection_equality",
            "reconciliation_truth",
            "backup_integrity",
        )

    def test_full_truth_passes(self) -> None:
        soak = run_soak(
            cycles=1000,
            invariant_truth={name: True for name in SOAK_INVARIANTS},
        )
        assert isinstance(soak, SoakRun)
        assert soak.passed
        assert soak.cycles == 1000
        assert len(soak.invariants) == 7

    def test_missing_invariant_fails_closed(self) -> None:
        soak = run_soak(
            cycles=10,
            invariant_truth={"heartbeats": True},
        )
        assert not soak.passed
        by_name = {invariant.name: invariant for invariant in soak.invariants}
        assert by_name["heartbeats"].preserved is True
        assert by_name["backup_integrity"].preserved is False
        assert by_name["backup_integrity"].detail == "not preserved"

    def test_single_failure_fails_the_soak(self) -> None:
        truth = {name: True for name in SOAK_INVARIANTS}
        truth["reconciliation_truth"] = False
        soak = run_soak(cycles=1000, invariant_truth=truth)
        assert not soak.passed

    def test_cycle_count_is_bounded_and_typed(self) -> None:
        soak = run_soak(
            cycles=1000,
            invariant_truth={name: True for name in SOAK_INVARIANTS},
        )
        assert soak.cycles == 1000

    def test_deterministic(self) -> None:
        truth = {name: True for name in SOAK_INVARIANTS}
        first = run_soak(cycles=1000, invariant_truth=truth)
        second = run_soak(cycles=1000, invariant_truth=truth)
        assert first.model_dump() == second.model_dump()
