"""M17-W02: operator runbook readiness.

Covers AC-M17-W02-02: the operator runbook proves practice credential
injection, startup, preflight, scheduler control, freeze, safe
shutdown, backup, isolated restore, restart, reconciliation, and
blocker inspection without exposing secrets.
"""

from __future__ import annotations

from alphabrief_core import (
    OPERATOR_RUNBOOK_STEPS,
    OperatorRunbookReport,
    run_operator_runbook_check,
)


class TestOperatorRunbook:
    def test_all_eleven_steps_are_declared(self) -> None:
        assert OPERATOR_RUNBOOK_STEPS == (
            "credential_injection",
            "startup",
            "preflight",
            "scheduler_control",
            "freeze",
            "safe_shutdown",
            "backup",
            "isolated_restore",
            "restart",
            "reconciliation",
            "blocker_inspection",
        )

    def test_full_truth_passes(self) -> None:
        report = run_operator_runbook_check(
            step_truth={step: True for step in OPERATOR_RUNBOOK_STEPS}
        )
        assert isinstance(report, OperatorRunbookReport)
        assert report.passed is True
        assert report.secrets_exposed is False
        assert all(step.preserved for step in report.steps)

    def test_missing_truth_fails_closed(self) -> None:
        report = run_operator_runbook_check(step_truth={})
        assert report.passed is False
        assert report.secrets_exposed is False
        assert all(not step.preserved for step in report.steps)

    def test_credential_injection_is_required(self) -> None:
        truth = {step: True for step in OPERATOR_RUNBOOK_STEPS}
        truth["credential_injection"] = False
        report = run_operator_runbook_check(step_truth=truth)
        assert report.passed is False

    def test_secrets_are_never_exposed(self) -> None:
        report = run_operator_runbook_check(
            step_truth={step: True for step in OPERATOR_RUNBOOK_STEPS}
        )
        assert report.secrets_exposed is False

    def test_deterministic(self) -> None:
        truth = {step: True for step in OPERATOR_RUNBOOK_STEPS}
        first = run_operator_runbook_check(step_truth=truth)
        second = run_operator_runbook_check(step_truth=truth)
        assert first.model_dump() == second.model_dump()
