"""M17-W02: long-running maintenance policy.

Covers AC-M17-W02-03: maintenance defines automatic backup retention,
restore cadence, dependency review, incident retention, evidence
retention, and practice-account reset behavior with no live-trading
procedure.
"""

from __future__ import annotations

from alphabrief_core import (
    MAINTENANCE_POLICIES,
    MaintenancePolicy,
    MaintenancePolicyReport,
    build_maintenance_policy,
)


class TestMaintenancePolicy:
    def test_all_six_policies_are_declared(self) -> None:
        assert MAINTENANCE_POLICIES == (
            "backup_retention",
            "restore_cadence",
            "dependency_review",
            "incident_retention",
            "evidence_retention",
            "practice_account_reset",
        )

    def test_full_truth_defines_all_policies(self) -> None:
        report = build_maintenance_policy(
            policy_truth={name: True for name in MAINTENANCE_POLICIES}
        )
        assert isinstance(report, MaintenancePolicyReport)
        assert report.passed is True
        assert report.no_live_procedure is True
        assert all(policy.defined for policy in report.policies)

    def test_missing_truth_fails_closed(self) -> None:
        report = build_maintenance_policy(policy_truth={})
        assert report.passed is False
        assert all(not policy.defined for policy in report.policies)

    def test_practice_account_reset_is_required(self) -> None:
        truth = {name: True for name in MAINTENANCE_POLICIES}
        truth["practice_account_reset"] = False
        report = build_maintenance_policy(policy_truth=truth)
        assert report.passed is False

    def test_no_live_trading_procedure_ever(self) -> None:
        report = build_maintenance_policy(
            policy_truth={name: True for name in MAINTENANCE_POLICIES}
        )
        assert report.no_live_procedure is True

    def test_policies_are_typed(self) -> None:
        report = build_maintenance_policy(
            policy_truth={name: True for name in MAINTENANCE_POLICIES}
        )
        assert isinstance(report.policies[0], MaintenancePolicy)

    def test_deterministic(self) -> None:
        truth = {name: True for name in MAINTENANCE_POLICIES}
        first = build_maintenance_policy(policy_truth=truth)
        second = build_maintenance_policy(policy_truth=truth)
        assert first.model_dump() == second.model_dump()
