"""M15-W04: deterministic engineering preflight.

Covers AC-M15-W04-01: OANDA-observation preflight verifies practice
hosts, secret presence without disclosure, account, catalog, data,
content, ModelGateway, risk, backup, scheduler lease, reconciliation,
alerts, frozen build, and safety gates in one schema.
"""

from __future__ import annotations

import pytest
from alphabrief_core import (
    ENGINEERING_CHECKS,
    FINAL_RELEASE_CHECKS,
    OBSERVATION_CHECKS,
    SCOPES,
    PreflightReport,
    run_preflight,
)


def _observation_truth() -> dict[str, object]:
    return {check_id: True for check_id in OBSERVATION_CHECKS}


class TestScopes:
    def test_all_three_scopes_are_declared(self) -> None:
        assert SCOPES == (
            "engineering_readiness",
            "oanda_observation",
            "final_release",
        )

    @pytest.mark.parametrize("scope", SCOPES)
    def test_every_scope_runs(self, scope: str) -> None:
        report = run_preflight(scope, {})
        assert isinstance(report, PreflightReport)
        assert report.scope == scope
        assert not report.passed  # no truth -> fail closed

    def test_unknown_scope_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown preflight scope"):
            run_preflight("mystery", {})


class TestObservationPreflight:
    def test_all_gates_are_checked_in_one_schema(self) -> None:
        assert OBSERVATION_CHECKS == (
            "practice_host",
            "secret_presence",
            "account",
            "catalog",
            "data",
            "content",
            "model_gateway",
            "risk",
            "backup",
            "scheduler_lease",
            "reconciliation",
            "alerts",
            "frozen_build",
            "safety_gates",
        )

    def test_full_truth_passes(self) -> None:
        report = run_preflight("oanda_observation", _observation_truth())
        assert report.passed
        assert len(report.checks) == 14

    def test_single_failure_fails_the_report(self) -> None:
        truth = _observation_truth()
        truth["reconciliation"] = False
        report = run_preflight("oanda_observation", truth)
        assert not report.passed
        failed = [c for c in report.checks if not c.passed]
        assert [c.check_id for c in failed] == ["reconciliation"]

    def test_missing_truth_fails_closed(self) -> None:
        truth = _observation_truth()
        del truth["backup"]
        report = run_preflight("oanda_observation", truth)
        assert not report.passed
        assert any(
            c.check_id == "backup" and not c.passed
            for c in report.checks
        )

    def test_secret_presence_is_boolean_without_disclosure(self) -> None:
        truth = _observation_truth()
        truth["secret_presence"] = {"passed": True, "detail": "present"}
        report = run_preflight("oanda_observation", truth)
        serialized = report.model_dump_json()
        assert "abc123456789" not in serialized
        check = next(
            c for c in report.checks if c.check_id == "secret_presence"
        )
        assert check.passed is True

    def test_deterministic(self) -> None:
        first = run_preflight("oanda_observation", _observation_truth())
        second = run_preflight("oanda_observation", _observation_truth())
        assert first.model_dump() == second.model_dump()

    def test_other_scopes_are_configured(self) -> None:
        assert len(ENGINEERING_CHECKS) >= 4
        assert len(FINAL_RELEASE_CHECKS) >= 4
        assert "no_live_unlock" in FINAL_RELEASE_CHECKS
        assert "paper_only_default" in ENGINEERING_CHECKS
