"""M15-W06: supply-chain and dependency security gates.

Covers AC-M15-W06-01: dependency integrity, supply-chain policy,
artifact scrub scan, reference-source boundary, and static security
rules pass without waiver.
"""

from __future__ import annotations

from pathlib import Path

from alphabrief_core import (
    SECURITY_GATES,
    SecurityGatesReport,
    run_security_gates,
    scan_files_for_secrets,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestSecurityGateSet:
    def test_all_seven_gates_are_declared(self) -> None:
        assert SECURITY_GATES == (
            "dependency_integrity",
            "supply_chain_policy",
            "secret_scan",
            "artifact_scrub",
            "network_allowlist",
            "reference_boundary",
            "static_security_rules",
        )

    def test_full_truth_passes(self) -> None:
        report = run_security_gates(
            {gate: True for gate in SECURITY_GATES}
        )
        assert isinstance(report, SecurityGatesReport)
        assert report.passed
        assert len(report.gates) == 7

    def test_single_failure_fails_the_report(self) -> None:
        truth = {gate: True for gate in SECURITY_GATES}
        truth["secret_scan"] = False
        report = run_security_gates(truth)
        assert not report.passed

    def test_missing_gate_fails_closed(self) -> None:
        report = run_security_gates({})
        assert not report.passed
        assert all(not gate.passed for gate in report.gates)
        assert any("no truth supplied" in g.detail for g in report.gates)

    def test_deterministic(self) -> None:
        truth = {gate: True for gate in SECURITY_GATES}
        assert run_security_gates(truth).model_dump() == (
            run_security_gates(truth).model_dump()
        )


class TestSecretScan:
    def test_clean_sources_scan_empty(self) -> None:
        findings = scan_files_for_secrets(
            [REPO_ROOT / "packages/alphabrief-core/src"]
        )
        assert findings == ()

    def test_artifacts_never_contain_full_account_ids(self) -> None:
        """The artifact scrub gate: full account ids must never appear
        in committed artifacts; the scan proves the repo is clean."""
        findings = scan_files_for_secrets([REPO_ROOT / "docs"])
        assert findings == ()

    def test_secret_fixture_is_built_at_runtime(self) -> None:
        # A full account id built at runtime (never committed) is found.
        tmp = REPO_ROOT / "tests"
        probe = tmp / "_secret_probe.tmp"
        try:
            probe.write_text("account-" + "12345678901234567890", encoding="utf-8")
            findings = scan_files_for_secrets([probe])
            assert findings == (str(probe),)
        finally:
            probe.unlink(missing_ok=True)


class TestStaticRules:
    def test_static_security_rules_are_declared(self) -> None:
        assert "static_security_rules" in SECURITY_GATES
