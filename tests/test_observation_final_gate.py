"""M16-W06: final 30-day observation gate.

Covers AC-M16-W06-01, AC-M16-W06-02, and AC-M16-W06-03: the gate
proves 30/30 real daily records, active-market decision chains, daily
backups, four weekly gates, final restore, continuous qualified timing,
and immutable manifest hashes; proves the safety invariants; and fails
closed on missing, modified, mock-only, waived, manually asserted,
future-dated, or reset-invalid evidence while the product remains OANDA
practice-only.
"""

from __future__ import annotations

from alphabrief_core import (
    EVIDENCE_FLAWS,
    FINAL_GATE_PROOFS,
    FINAL_SAFETY_INVARIANTS,
    FinalGateResult,
    run_final_gate,
)


def _full_proofs() -> dict[str, bool]:
    return {name: True for name in FINAL_GATE_PROOFS}


def _full_invariants() -> dict[str, bool]:
    return {name: True for name in FINAL_SAFETY_INVARIANTS}


class TestFinalGateProofs:
    def test_all_seven_proofs_are_declared(self) -> None:
        assert FINAL_GATE_PROOFS == (
            "thirty_of_thirty_daily_records",
            "active_market_decision_chains",
            "daily_backups",
            "four_weekly_gates",
            "final_restore",
            "continuous_qualified_timing",
            "immutable_manifest_hashes",
        )

    def test_full_truth_passes(self) -> None:
        gate = run_final_gate(
            proofs_truth=_full_proofs(),
            invariants_truth=_full_invariants(),
            flaws={},
        )
        assert isinstance(gate, FinalGateResult)
        assert gate.passed is True
        assert gate.practice_only is True
        assert gate.blockers == ()

    def test_missing_truth_fails_closed(self) -> None:
        gate = run_final_gate(proofs_truth={}, invariants_truth={}, flaws={})
        assert gate.passed is False
        assert all(not p.preserved for p in gate.proofs)
        assert all(not i.preserved for i in gate.invariants)

    def test_single_missing_proof_fails_the_gate(self) -> None:
        proofs = _full_proofs()
        proofs["final_restore"] = False
        gate = run_final_gate(
            proofs_truth=proofs,
            invariants_truth=_full_invariants(),
            flaws={},
        )
        assert gate.passed is False


class TestFinalSafetyInvariants:
    def test_all_five_invariants_are_declared(self) -> None:
        assert FINAL_SAFETY_INVARIANTS == (
            "zero_duplicate_external_orders",
            "zero_order_without_approved_risk_decision",
            "zero_live_or_other_broker_attempt",
            "zero_unexplained_cross_day_difference",
            "zero_unresolved_p0_or_p1",
        )

    def test_duplicate_order_invariant_is_required(self) -> None:
        invariants = _full_invariants()
        invariants["zero_duplicate_external_orders"] = False
        gate = run_final_gate(
            proofs_truth=_full_proofs(),
            invariants_truth=invariants,
            flaws={},
        )
        assert gate.passed is False

    def test_approved_risk_decision_invariant_is_required(self) -> None:
        invariants = _full_invariants()
        invariants["zero_order_without_approved_risk_decision"] = False
        gate = run_final_gate(
            proofs_truth=_full_proofs(),
            invariants_truth=invariants,
            flaws={},
        )
        assert gate.passed is False

    def test_live_or_other_broker_invariant_is_required(self) -> None:
        invariants = _full_invariants()
        invariants["zero_live_or_other_broker_attempt"] = False
        gate = run_final_gate(
            proofs_truth=_full_proofs(),
            invariants_truth=invariants,
            flaws={},
        )
        assert gate.passed is False


class TestEvidenceFlaws:
    def test_all_seven_flaws_are_declared(self) -> None:
        assert EVIDENCE_FLAWS == (
            "missing",
            "modified",
            "mock_only",
            "waived",
            "manually_asserted",
            "future_dated",
            "reset_invalid",
        )

    def test_any_flaw_fails_the_gate_and_records_blocker(self) -> None:
        for flaw in EVIDENCE_FLAWS:
            gate = run_final_gate(
                proofs_truth=_full_proofs(),
                invariants_truth=_full_invariants(),
                flaws={flaw: True},
            )
            assert gate.passed is False
            assert any(flaw in blocker for blocker in gate.blockers)

    def test_mock_only_evidence_never_passes(self) -> None:
        gate = run_final_gate(
            proofs_truth=_full_proofs(),
            invariants_truth=_full_invariants(),
            flaws={"mock_only": True},
        )
        assert gate.passed is False
        assert any("mock_only" in b for b in gate.blockers)

    def test_future_dated_evidence_never_passes(self) -> None:
        gate = run_final_gate(
            proofs_truth=_full_proofs(),
            invariants_truth=_full_invariants(),
            flaws={"future_dated": True},
        )
        assert gate.passed is False
        assert any("future_dated" in b for b in gate.blockers)


class TestPracticeOnly:
    def test_gate_never_unlocks_live(self) -> None:
        gate = run_final_gate(
            proofs_truth=_full_proofs(),
            invariants_truth=_full_invariants(),
            flaws={},
        )
        assert gate.practice_only is True

    def test_gate_is_deterministic(self) -> None:
        first = run_final_gate(
            proofs_truth=_full_proofs(),
            invariants_truth=_full_invariants(),
            flaws={},
        )
        second = run_final_gate(
            proofs_truth=_full_proofs(),
            invariants_truth=_full_invariants(),
            flaws={},
        )
        assert first.model_dump() == second.model_dump()
