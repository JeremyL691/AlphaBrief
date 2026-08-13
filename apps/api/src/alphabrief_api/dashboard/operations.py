"""Scheduler, Observation, Settings, and operator controls (M14-W06).

Scheduler and 30-Day Observation views are shaped deterministically
from one runtime authority: leader, running, heartbeat, last and next
run, phase, qualified day, weekly gate, incident, blocker, and evidence
completeness. The only write controls are the REQ-UI-010 set, each
requiring validation, idempotency, confirmation, and audit. Settings
reveals non-secret provider and version health only: it cannot edit
broker hosts, unlock live trading, select another broker, expose
credentials, or send an arbitrary broker request (REQ-UI-004,
REQ-UI-005, REQ-UI-010).
"""

from __future__ import annotations

from typing import Any

from alphabrief_core.write_contracts import OPERATOR_MUTATIONS
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Scheduler workspace
# ---------------------------------------------------------------------------


class SchedulerView(BaseModel):
    """One runtime-authority scheduler state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    leader_id: str | None = None
    running: bool | None = None
    heartbeat_at: str | None = None
    last_run_at: str | None = None
    next_run_at: str | None = None
    phase: str | None = None


def build_scheduler_view(truth: dict[str, Any] | None = None) -> SchedulerView:
    """Shape the Scheduler workspace from the runtime truth record."""
    truth = truth or {}
    return SchedulerView(
        leader_id=_str_or_none(truth, "leader_id"),
        running=_bool_or_none(truth, "running"),
        heartbeat_at=_str_or_none(truth, "heartbeat_at"),
        last_run_at=_str_or_none(truth, "last_run_at"),
        next_run_at=_str_or_none(truth, "next_run_at"),
        phase=_str_or_none(truth, "phase"),
    )


# ---------------------------------------------------------------------------
# 30-Day Observation workspace
# ---------------------------------------------------------------------------


class WeeklyGateRow(BaseModel):
    """One weekly gate result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    week: str
    passed: bool
    detail: str | None = None


class ObservationView(BaseModel):
    """One runtime-authority 30-day observation state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    qualified_days: int | None = None
    required_days: int = 30
    weekly_gates: tuple[WeeklyGateRow, ...] = ()
    incidents: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    evidence_completeness: str | None = None


def build_observation_view(
    truth: dict[str, Any] | None = None,
    *,
    weekly_gates: list[dict[str, Any]] | None = None,
    incidents: list[str] | None = None,
    blockers: list[str] | None = None,
) -> ObservationView:
    """Shape the 30-Day Observation workspace from runtime truth.

    Qualified days, weekly gates, incidents, blockers, and evidence
    completeness come only from the truth record; a blocker is never
    hidden.
    """
    truth = truth or {}
    return ObservationView(
        qualified_days=(
            int(truth["qualified_days"])
            if truth.get("qualified_days") is not None
            else None
        ),
        required_days=30,
        weekly_gates=tuple(
            WeeklyGateRow(
                week=str(gate.get("week", "")),
                passed=bool(gate.get("passed", False)),
                detail=(
                    str(gate["detail"]) if gate.get("detail") else None
                ),
            )
            for gate in (weekly_gates or [])
        ),
        incidents=tuple(str(item) for item in (incidents or [])),
        blockers=tuple(str(item) for item in (blockers or [])),
        evidence_completeness=_str_or_none(truth, "evidence_completeness"),
    )


# ---------------------------------------------------------------------------
# Operator controls
# ---------------------------------------------------------------------------


class ControlAction(BaseModel):
    """One approved practice control with its safety requirements."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mutation: str = Field(min_length=1)
    requires_validation: bool = True
    requires_idempotency: bool = True
    requires_confirmation: bool = True
    audited: bool = True


def control_actions() -> tuple[ControlAction, ...]:
    """The strictly bounded practice-control set (REQ-UI-010)."""
    return tuple(
        ControlAction(
            mutation=mutation,
            requires_validation=True,
            requires_idempotency=True,
            requires_confirmation=True,
            audited=True,
        )
        for mutation in sorted(OPERATOR_MUTATIONS)
    )


# ---------------------------------------------------------------------------
# Settings workspace
# ---------------------------------------------------------------------------


class SettingsView(BaseModel):
    """Read-only non-secret provider and version health."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str | None = None
    provider_health: str | None = None
    blueprint_version: str | None = None
    schema_version: str | None = None
    #: Settings can never alter these; declared for the audit.
    editable_broker_hosts: bool = False
    live_unlock_available: bool = False
    broker_selection_available: bool = False
    credentials_exposed: bool = False
    arbitrary_broker_request: bool = False


def build_settings_view(health: dict[str, Any] | None = None) -> SettingsView:
    """Shape the Settings workspace from non-secret health truth."""
    health = health or {}
    return SettingsView(
        provider=_str_or_none(health, "provider"),
        provider_health=_str_or_none(health, "provider_health"),
        blueprint_version=_str_or_none(health, "blueprint_version"),
        schema_version=_str_or_none(health, "schema_version"),
    )


def _str_or_none(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    return str(value) if value is not None else None


def _bool_or_none(mapping: dict[str, Any], key: str) -> bool | None:
    value = mapping.get(key)
    return bool(value) if value is not None else None


__all__ = [
    "ControlAction",
    "ObservationView",
    "SchedulerView",
    "SettingsView",
    "WeeklyGateRow",
    "build_observation_view",
    "build_scheduler_view",
    "build_settings_view",
    "control_actions",
]
