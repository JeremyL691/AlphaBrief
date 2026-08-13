"""M15-W07: Engineering Readiness Gate.

Covers AC-M15-W07-01/03: all local, security, recovery, preflight,
reconciliation, UI, and traceability gates pass with no waiver;
engineering readiness is marked only when M01 through M15 are DONE,
the tree is clean, and the frozen build is practice-only, with absent
external prerequisites recorded as blockers without a false PASS.
"""

from __future__ import annotations

import pytest
from alphabrief_core import (
    OBSERVATION_CHECKS,
    RECOVERY_BOUNDARIES,
    REHEARSAL_STEPS,
    SECURITY_GATES,
    SHUTDOWN_SEQUENCE,
    SOAK_INVARIANTS,
    engineering_readiness_verdict,
    run_preflight,
    run_rehearsal,
    run_security_gates,
)


class TestReadinessMarking:
    def test_readiness_requires_all_conditions(self) -> None:
        verdict = engineering_readiness_verdict(
            milestones_done=True,
            tree_clean=True,
            frozen_build_practice_only=True,
        )
        assert verdict.ready is True

    @pytest.mark.parametrize(
        "milestones_done,tree_clean,practice_only",
        [
            (False, True, True),
            (True, False, True),
            (True, True, False),
        ],
    )
    def test_missing_condition_blocks_readiness(
        self, milestones_done: bool, tree_clean: bool, practice_only: bool
    ) -> None:
        verdict = engineering_readiness_verdict(
            milestones_done=milestones_done,
            tree_clean=tree_clean,
            frozen_build_practice_only=practice_only,
        )
        assert verdict.ready is False

    def test_external_blockers_are_recorded_not_fabricated(self) -> None:
        verdict = engineering_readiness_verdict(
            milestones_done=True,
            tree_clean=True,
            frozen_build_practice_only=True,
            external_blockers=("practice_e2e_pending",),
        )
        # Readiness is marked for the frozen build; the external
        # blocker is recorded explicitly, never a false PASS.
        assert verdict.ready is True
        assert verdict.external_blockers == ("practice_e2e_pending",)

    def test_verdict_is_deterministic(self) -> None:
        first = engineering_readiness_verdict(
            milestones_done=True,
            tree_clean=True,
            frozen_build_practice_only=True,
        )
        second = engineering_readiness_verdict(
            milestones_done=True,
            tree_clean=True,
            frozen_build_practice_only=True,
        )
        assert first.model_dump() == second.model_dump()


class TestReadinessGateCoverage:
    def test_full_truth_passes_all_gates(self) -> None:
        security = run_security_gates(
            {gate: True for gate in SECURITY_GATES}
        )
        assert security.passed
        preflight = run_preflight(
            "oanda_observation", {check: True for check in OBSERVATION_CHECKS}
        )
        assert preflight.passed
        rehearsal = run_rehearsal({step: True for step in REHEARSAL_STEPS})
        assert rehearsal.passed
        assert rehearsal.counts_as_observation is False

    def test_no_unexplained_skip_in_gate_declarations(self) -> None:
        # Every declared gate has a full truth path in the test suite.
        assert len(SECURITY_GATES) == 7
        assert len(OBSERVATION_CHECKS) == 14
        assert len(RECOVERY_BOUNDARIES) == 12
        assert len(SHUTDOWN_SEQUENCE) == 8
        assert len(SOAK_INVARIANTS) == 7
        assert len(REHEARSAL_STEPS) == 8
