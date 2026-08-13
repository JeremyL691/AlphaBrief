"""Deterministic execution-readiness gate (M11-W03).

Research scheduling (data, news, snapshots, committee, reporting) runs
independently of the deterministic gate that permits OANDA practice
execution. The gate evaluates preflight facts and returns exactly one
machine-readable mode — ``executable``, ``execution_disabled``,
``research_only``, or ``blocked`` — with stable reasons. Every blocking
condition prevents submission **before** any broker invocation, and the
mode is persisted so operators and surfaces see the same authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExecutionMode(StrEnum):
    """Distinct persisted execution states (AC-M11-W03-03)."""

    EXECUTABLE = "executable"
    EXECUTION_DISABLED = "execution_disabled"
    RESEARCH_ONLY = "research_only"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PreflightFacts:
    """Everything the gate needs to know, injected deterministically."""

    trading_enabled: bool = True
    research_only: bool = False
    credentials_present: bool = True
    account_truth_fresh: bool = True
    reconciliation_clean: bool = True
    data_fresh: bool = True
    backup_ok: bool = True
    model_healthy: bool = True
    kill_switch_active: bool = False


@dataclass(frozen=True)
class ExecutionReadiness:
    """One gate verdict: a mode plus stable machine-readable reasons."""

    mode: ExecutionMode
    reasons: tuple[str, ...] = ()


class ExecutionGate:
    """Stateless deterministic gate; identical facts produce one verdict."""

    def evaluate(self, facts: PreflightFacts) -> ExecutionReadiness:
        if facts.kill_switch_active:
            return ExecutionReadiness(
                ExecutionMode.BLOCKED, ("kill_switch_active",)
            )
        reasons: list[str] = []
        if not facts.credentials_present:
            reasons.append("missing_credentials")
        if not facts.account_truth_fresh:
            reasons.append("stale_account_truth")
        if not facts.reconciliation_clean:
            reasons.append("reconciliation_failed")
        if not facts.data_fresh:
            reasons.append("stale_data")
        if not facts.backup_ok:
            reasons.append("backup_failed")
        if not facts.model_healthy:
            reasons.append("unhealthy_model")
        if reasons:
            return ExecutionReadiness(ExecutionMode.BLOCKED, tuple(reasons))
        if not facts.trading_enabled:
            return ExecutionReadiness(
                ExecutionMode.EXECUTION_DISABLED, ("trading_disabled",)
            )
        if facts.research_only:
            return ExecutionReadiness(
                ExecutionMode.RESEARCH_ONLY, ("research_only",)
            )
        return ExecutionReadiness(ExecutionMode.EXECUTABLE)


__all__ = [
    "ExecutionGate",
    "ExecutionMode",
    "ExecutionReadiness",
    "PreflightFacts",
]
