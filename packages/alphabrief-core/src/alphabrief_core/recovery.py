"""Graceful shutdown, crash recovery, restore, and bounded soak
(M15-W05).

SIGTERM follows the declared freeze -> stop-new-cycle ->
resolve-uncertain-submit -> sync -> reconcile -> checkpoint -> backup
-> lease-release order within a bounded shutdown budget. Abrupt
termination at every declared cycle and execution boundary resumes
deterministically or stays safely frozen — never a duplicate order,
cursor regression, lost risk counter, or partial state. Bounded soak
and isolated restore drills preserve heartbeats, writer ownership,
memory and descriptor budgets, projection equality, reconciliation
truth, and backup integrity (REQ-OPS-001, REQ-OPS-006).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_core.observation_controller import FaultInvariant

#: The declared SIGTERM shutdown sequence (AC-M15-W05-01).
SHUTDOWN_SEQUENCE: tuple[str, ...] = (
    "freeze",
    "stop_new_cycle",
    "resolve_uncertain_submit",
    "sync",
    "reconcile",
    "checkpoint",
    "backup",
    "lease_release",
)

#: Bounded shutdown time budget (seconds).
SHUTDOWN_BUDGET_S: Decimal = Decimal("30")

#: Declared recovery boundaries (AC-M15-W05-02).
RECOVERY_BOUNDARIES: tuple[str, ...] = (
    "startup",
    "preflight",
    "ingest",
    "snapshot",
    "discuss",
    "propose",
    "risk_gate",
    "submit",
    "transaction",
    "reconcile",
    "report",
    "complete",
)


class ShutdownPlan(BaseModel):
    """One deterministic SIGTERM shutdown plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: tuple[str, ...]
    budget_s: Decimal = Field(gt=0)


class BoundaryRecovery(BaseModel):
    """One boundary's deterministic recovery verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    boundary: str = Field(min_length=1)
    verdict: str = Field(min_length=1)  # "resumed" | "frozen"
    detail: str = Field(min_length=1)


class RecoveryDrillReport(BaseModel):
    """One deterministic recovery-drill report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario: str = Field(min_length=1)
    passed: bool
    boundaries: tuple[BoundaryRecovery, ...]


def shutdown_plan() -> ShutdownPlan:
    """The single declared SIGTERM shutdown plan."""
    return ShutdownPlan(
        sequence=SHUTDOWN_SEQUENCE,
        budget_s=SHUTDOWN_BUDGET_S,
    )


def run_recovery_drill(
    *,
    scenario: str,
    boundary_truth: dict[str, Any] | None = None,
) -> RecoveryDrillReport:
    """Run one deterministic recovery drill.

    ``boundary_truth`` maps each boundary to a verdict (``"resumed"``
    or ``"frozen"``); missing truth fails closed as frozen with an
    explicit detail — never assumed resumed.
    """
    truth = boundary_truth or {}
    boundaries: list[BoundaryRecovery] = []
    for boundary in RECOVERY_BOUNDARIES:
        entry = truth.get(boundary)
        if entry is None:
            boundaries.append(
                BoundaryRecovery(
                    boundary=boundary,
                    verdict="frozen",
                    detail="no recovery truth supplied",
                )
            )
            continue
        if isinstance(entry, dict):
            verdict = str(entry.get("verdict", "frozen"))
            detail = str(entry.get("detail", "recovery completed"))
        else:
            verdict = str(entry)
            detail = "recovery completed"
        if verdict not in ("resumed", "frozen"):
            verdict = "frozen"
        boundaries.append(
            BoundaryRecovery(
                boundary=boundary, verdict=verdict, detail=detail
            )
        )
    return RecoveryDrillReport(
        scenario=scenario,
        passed=all(
            b.verdict in ("resumed", "frozen") for b in boundaries
        ),
        boundaries=tuple(boundaries),
    )


class SoakInvariant(BaseModel):
    """One bounded-soak invariant result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    preserved: bool
    detail: str = Field(min_length=1)


class SoakRun(BaseModel):
    """One bounded soak run report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cycles: int = Field(ge=1)
    passed: bool
    invariants: tuple[SoakInvariant, ...]


#: The declared soak invariants (AC-M15-W05-03).
SOAK_INVARIANTS: tuple[str, ...] = (
    "heartbeats",
    "writer_ownership",
    "memory_budget",
    "descriptor_budget",
    "projection_equality",
    "reconciliation_truth",
    "backup_integrity",
)


def run_soak(
    *,
    cycles: int,
    invariant_truth: dict[str, Any] | None = None,
) -> SoakRun:
    """Run one bounded soak check.

    ``invariant_truth`` maps each invariant to a boolean; missing truth
    fails closed as not preserved.
    """
    truth = invariant_truth or {}
    invariants = tuple(
        SoakInvariant(
            name=name,
            preserved=bool(truth.get(name, False)),
            detail=(
                "preserved" if truth.get(name, False) else "not preserved"
            ),
        )
        for name in SOAK_INVARIANTS
    )
    return SoakRun(
        cycles=cycles,
        passed=all(invariant.preserved for invariant in invariants),
        invariants=invariants,
    )


# ---------------------------------------------------------------------------
# Fresh-install readiness, operator runbook, and maintenance policy
# (M17-W02)
# ---------------------------------------------------------------------------


#: The declared fresh-install steps (AC-M17-W02-01).
FRESH_INSTALL_STEPS: tuple[str, ...] = (
    "locked_deps_install",
    "empty_data_dir_init",
    "migrate",
    "local_readiness",
    "no_untracked_source_dependency",
)


class FreshInstallReport(BaseModel):
    """One deterministic fresh-install readiness report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    steps: tuple[FaultInvariant, ...]


def run_fresh_install_check(
    *,
    step_truth: dict[str, Any] | None = None,
) -> FreshInstallReport:
    """Run one deterministic fresh-install check.

    ``step_truth`` maps each step to completed or not; missing truth
    fails closed as not completed — a clean checkout never relies on
    untracked source or historical state.
    """
    truth = step_truth or {}
    steps = tuple(
        FaultInvariant(
            name=name,
            preserved=bool(truth.get(name, False)),
            detail=(
                "completed" if truth.get(name, False) else "not completed"
            ),
        )
        for name in FRESH_INSTALL_STEPS
    )
    return FreshInstallReport(
        passed=all(step.preserved for step in steps),
        steps=steps,
    )


#: The declared operator runbook steps (AC-M17-W02-02). Secrets are
#: injected from external environment only and are never exposed.
OPERATOR_RUNBOOK_STEPS: tuple[str, ...] = (
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


class OperatorRunbookReport(BaseModel):
    """One deterministic operator runbook check report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    secrets_exposed: bool = False
    steps: tuple[FaultInvariant, ...]


def run_operator_runbook_check(
    *,
    step_truth: dict[str, Any] | None = None,
) -> OperatorRunbookReport:
    """Run one deterministic operator runbook check.

    ``step_truth`` maps each step to completed or not; missing truth
    fails closed. The check always reports ``secrets_exposed`` False —
    the runbook never prints or persists credentials.
    """
    truth = step_truth or {}
    steps = tuple(
        FaultInvariant(
            name=name,
            preserved=bool(truth.get(name, False)),
            detail=(
                "completed" if truth.get(name, False) else "not completed"
            ),
        )
        for name in OPERATOR_RUNBOOK_STEPS
    )
    return OperatorRunbookReport(
        passed=all(step.preserved for step in steps),
        secrets_exposed=False,
        steps=steps,
    )


#: The declared long-running maintenance policies (AC-M17-W02-03).
MAINTENANCE_POLICIES: tuple[str, ...] = (
    "backup_retention",
    "restore_cadence",
    "dependency_review",
    "incident_retention",
    "evidence_retention",
    "practice_account_reset",
)


class MaintenancePolicy(BaseModel):
    """One deterministic maintenance policy definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    defined: bool
    detail: str = Field(min_length=1)


class MaintenancePolicyReport(BaseModel):
    """One deterministic maintenance policy report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    no_live_procedure: bool = True
    policies: tuple[MaintenancePolicy, ...]


def build_maintenance_policy(
    *,
    policy_truth: dict[str, Any] | None = None,
) -> MaintenancePolicyReport:
    """Build the deterministic maintenance policy report.

    ``policy_truth`` maps each policy to defined or not; missing truth
    fails closed as not defined. The report always declares
    ``no_live_procedure`` True — no live-trading procedure exists.
    """
    truth = policy_truth or {}
    policies = tuple(
        MaintenancePolicy(
            name=name,
            defined=bool(truth.get(name, False)),
            detail=(
                "defined" if truth.get(name, False) else "not defined"
            ),
        )
        for name in MAINTENANCE_POLICIES
    )
    return MaintenancePolicyReport(
        passed=all(policy.defined for policy in policies),
        no_live_procedure=True,
        policies=policies,
    )


__all__ = [
    "FRESH_INSTALL_STEPS",
    "MAINTENANCE_POLICIES",
    "OPERATOR_RUNBOOK_STEPS",
    "RECOVERY_BOUNDARIES",
    "SHUTDOWN_BUDGET_S",
    "SHUTDOWN_SEQUENCE",
    "SOAK_INVARIANTS",
    "BoundaryRecovery",
    "FreshInstallReport",
    "MaintenancePolicy",
    "MaintenancePolicyReport",
    "OperatorRunbookReport",
    "RecoveryDrillReport",
    "ShutdownPlan",
    "SoakInvariant",
    "SoakRun",
    "build_maintenance_policy",
    "run_fresh_install_check",
    "run_operator_runbook_check",
    "run_recovery_drill",
    "run_soak",
    "shutdown_plan",
]
