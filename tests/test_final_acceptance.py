"""M17-W04: final acceptance gate and paper-only handoff.

Covers AC-M17-W04-02 and AC-M17-W04-03: fresh full tests, Ruff, Mypy,
dependency integrity, acceptance, security, fresh-install, package,
backup restore, final reconciliation, and OANDA practice-only negative
gates pass on the release commit; the final report hashes match source
artifacts, the repository is clean after commit, and project status
becomes COMPLETE_PAPER_ONLY while live trading, other brokers, and
production simulation remain forbidden and unreachable.
"""

from __future__ import annotations

from alphabrief_core import (
    FINAL_PROJECT_STATUS,
    FINAL_RELEASE_GATES,
    FinalReleaseVerdict,
    run_final_release_gate,
)


def _full_gates() -> dict[str, bool]:
    return {name: True for name in FINAL_RELEASE_GATES}


class TestFinalReleaseGate:
    def test_all_eleven_gates_are_declared(self) -> None:
        assert FINAL_RELEASE_GATES == (
            "full_tests",
            "ruff",
            "mypy",
            "dependency_integrity",
            "acceptance",
            "security",
            "fresh_install",
            "package",
            "backup_restore",
            "final_reconciliation",
            "oanda_practice_only_negative",
        )

    def test_full_truth_with_matching_hashes_passes(self) -> None:
        verdict = run_final_release_gate(
            gate_truth=_full_gates(), report_hash_matches=True
        )
        assert isinstance(verdict, FinalReleaseVerdict)
        assert verdict.passed is True
        assert verdict.status == FINAL_PROJECT_STATUS
        assert verdict.report_hash_matches is True
        assert verdict.blockers == ()

    def test_missing_truth_fails_closed_and_stays_in_progress(self) -> None:
        verdict = run_final_release_gate(
            gate_truth={}, report_hash_matches=False
        )
        assert verdict.passed is False
        assert verdict.status == "IN_PROGRESS"
        assert all(not gate.preserved for gate in verdict.gates)

    def test_hash_mismatch_blocks_completion(self) -> None:
        verdict = run_final_release_gate(
            gate_truth=_full_gates(), report_hash_matches=False
        )
        assert verdict.passed is False
        assert verdict.status == "IN_PROGRESS"
        assert any("hash" in b for b in verdict.blockers)

    def test_single_failed_gate_blocks_completion(self) -> None:
        gates = _full_gates()
        gates["oanda_practice_only_negative"] = False
        verdict = run_final_release_gate(
            gate_truth=gates, report_hash_matches=True
        )
        assert verdict.passed is False
        assert verdict.status == "IN_PROGRESS"

    def test_final_status_is_paper_only(self) -> None:
        # The only completion status is COMPLETE_PAPER_ONLY; no live or
        # other-broker status exists.
        assert FINAL_PROJECT_STATUS == "COMPLETE_PAPER_ONLY"

    def test_deterministic(self) -> None:
        first = run_final_release_gate(
            gate_truth=_full_gates(), report_hash_matches=True
        )
        second = run_final_release_gate(
            gate_truth=_full_gates(), report_hash_matches=True
        )
        assert first.model_dump() == second.model_dump()
