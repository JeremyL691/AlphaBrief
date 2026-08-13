"""Deterministic engineering preflight scopes (M15-W04).

Engineering-readiness, OANDA-observation, and final-release preflight
scopes verify every gate in one schema. The OANDA-observation scope
checks practice hosts, secret presence without disclosure, account,
catalog, data, content, ModelGateway, risk, backup, scheduler lease,
reconciliation, alerts, frozen build, and safety gates. Any missing
truth fails closed; secret values are never disclosed (REQ-OPS-007,
REQ-OPS-002).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PreflightScope = str  # "engineering_readiness" | "oanda_observation" | "final_release"

SCOPES: tuple[str, ...] = (
    "engineering_readiness",
    "oanda_observation",
    "final_release",
)


class PreflightCheck(BaseModel):
    """One deterministic preflight check result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    passed: bool
    detail: str = Field(min_length=1)


class PreflightReport(BaseModel):
    """One complete preflight report in a single schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: str = Field(min_length=1)
    passed: bool
    checks: tuple[PreflightCheck, ...]


#: The OANDA-observation gate set (AC-M15-W04-01).
OBSERVATION_CHECKS: tuple[str, ...] = (
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

ENGINEERING_CHECKS: tuple[str, ...] = (
    "schema_migrations",
    "quality_tooling",
    "docs_authority",
    "reference_isolation",
    "provider_sdk_isolation",
    "paper_only_default",
)

FINAL_RELEASE_CHECKS: tuple[str, ...] = (
    "observation_complete",
    "final_evidence_hashes",
    "paper_only_lock",
    "no_live_unlock",
)


def _check(
    check_id: str, scope: str, passed: bool, detail: str
) -> PreflightCheck:
    return PreflightCheck(
        check_id=check_id, scope=scope, passed=passed, detail=detail
    )


def run_preflight(
    scope: str,
    truth: dict[str, Any] | None = None,
) -> PreflightReport:
    """Run one deterministic preflight scope.

    ``truth`` maps each check id to a boolean (or a dict with
    ``passed``/``detail``). Missing truth fails closed with an explicit
    detail; secret values are never present in the report.
    """
    truth = truth or {}
    if scope not in SCOPES:
        raise ValueError(f"unknown preflight scope {scope!r}")
    check_ids = {
        "engineering_readiness": ENGINEERING_CHECKS,
        "oanda_observation": OBSERVATION_CHECKS,
        "final_release": FINAL_RELEASE_CHECKS,
    }[scope]

    checks: list[PreflightCheck] = []
    for check_id in check_ids:
        entry = truth.get(check_id)
        if entry is None:
            checks.append(
                _check(check_id, scope, False, "no truth supplied")
            )
            continue
        if isinstance(entry, dict):
            passed = bool(entry.get("passed", False))
            detail = str(entry.get("detail", "check completed"))
        else:
            passed = bool(entry)
            detail = "check completed"
        checks.append(_check(check_id, scope, passed, detail))

    return PreflightReport(
        scope=scope,
        passed=all(check.passed for check in checks),
        checks=tuple(checks),
    )


class ReadinessVerdict(BaseModel):
    """One deterministic engineering-readiness verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ready: bool
    milestones_done: bool
    tree_clean: bool
    frozen_build_practice_only: bool
    external_blockers: tuple[str, ...] = ()


def engineering_readiness_verdict(
    *,
    milestones_done: bool,
    tree_clean: bool,
    frozen_build_practice_only: bool,
    external_blockers: tuple[str, ...] = (),
) -> ReadinessVerdict:
    """The deterministic readiness verdict (AC-M15-W07-03).

    Readiness is marked only when M01 through M15 are DONE, the tree
    is clean, and the frozen build is practice-only. Absent external
    prerequisites are recorded as blockers — never a false PASS.
    """
    ready = (
        milestones_done
        and tree_clean
        and frozen_build_practice_only
    )
    return ReadinessVerdict(
        ready=ready,
        milestones_done=milestones_done,
        tree_clean=tree_clean,
        frozen_build_practice_only=frozen_build_practice_only,
        external_blockers=external_blockers,
    )


__all__ = [
    "ENGINEERING_CHECKS",
    "FINAL_RELEASE_CHECKS",
    "OBSERVATION_CHECKS",
    "PreflightCheck",
    "PreflightReport",
    "ReadinessVerdict",
    "engineering_readiness_verdict",
    "SCOPES",
    "run_preflight",
]
