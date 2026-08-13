"""M17-W04: final acceptance traceability contract.

Covers AC-M17-W04-01: every required milestone, work item, requirement,
and acceptance predicate has a committed evidence reference at its
declared hierarchy level with no TBD, waiver, mock substitution,
unresolved blocker, or self-authored PASS.
"""

from __future__ import annotations

from alphabrief_core import (
    TRACEABILITY_FLAWS,
    TRACEABILITY_LEVELS,
    TraceabilityVerdict,
    verify_traceability,
)


class TestTraceabilityContract:
    def test_all_four_levels_are_declared(self) -> None:
        assert TRACEABILITY_LEVELS == (
            "milestone",
            "work_item",
            "requirement",
            "acceptance_predicate",
        )

    def test_all_five_flaws_are_declared(self) -> None:
        assert TRACEABILITY_FLAWS == (
            "tbd",
            "waiver",
            "mock_substitution",
            "unresolved_blocker",
            "self_authored_pass",
        )

    def test_full_traceability_passes(self) -> None:
        verdict = verify_traceability(
            level_truth={level: True for level in TRACEABILITY_LEVELS},
            flaws={},
        )
        assert isinstance(verdict, TraceabilityVerdict)
        assert verdict.passed is True
        assert verdict.blockers == ()

    def test_missing_level_reference_fails_closed(self) -> None:
        verdict = verify_traceability(level_truth={}, flaws={})
        assert verdict.passed is False
        assert all(not level.preserved for level in verdict.levels)

    def test_any_flaw_fails_and_records_blocker(self) -> None:
        for flaw in TRACEABILITY_FLAWS:
            verdict = verify_traceability(
                level_truth={level: True for level in TRACEABILITY_LEVELS},
                flaws={flaw: True},
            )
            assert verdict.passed is False
            assert any(flaw in blocker for blocker in verdict.blockers)

    def test_self_authored_pass_is_rejected(self) -> None:
        verdict = verify_traceability(
            level_truth={level: True for level in TRACEABILITY_LEVELS},
            flaws={"self_authored_pass": True},
        )
        assert verdict.passed is False
        assert any("self_authored_pass" in b for b in verdict.blockers)

    def test_mock_substitution_is_rejected(self) -> None:
        verdict = verify_traceability(
            level_truth={level: True for level in TRACEABILITY_LEVELS},
            flaws={"mock_substitution": True},
        )
        assert verdict.passed is False
        assert any("mock_substitution" in b for b in verdict.blockers)

    def test_deterministic(self) -> None:
        truth = {level: True for level in TRACEABILITY_LEVELS}
        first = verify_traceability(level_truth=truth, flaws={})
        second = verify_traceability(level_truth=truth, flaws={})
        assert first.model_dump() == second.model_dump()
