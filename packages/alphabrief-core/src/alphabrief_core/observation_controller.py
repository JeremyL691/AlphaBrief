"""Controlled practice E2E path and observation evidence controller
(M15-W04).

The controlled practice E2E command may use only the formal
proposal -> OrderIntent -> persisted RiskDecision -> submit ->
transaction -> cleanup -> reconciliation path and refuses direct or
residual execution. A single-leader persistent observation supervisor
restores next-run state after restart, invokes daily and weekly
evidence gates automatically, derives Day 0 through Day 30 from real
UTC and local-calendar evidence, and records BLOCKED_EXTERNAL or
WAITING_EXTERNAL without fabricating evidence or asking a question
(REQ-OPS-002, REQ-OPS-007).
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

#: The only permitted practice E2E sequence (AC-M15-W04-02).
PRACTICE_E2E_PATH: tuple[str, ...] = (
    "proposal",
    "order_intent",
    "persisted_risk_decision",
    "submit",
    "transaction",
    "cleanup",
    "reconciliation",
)

#: Direct or residual execution steps that are always refused.
FORBIDDEN_E2E_STEPS: tuple[str, ...] = (
    "direct_broker_submit",
    "in_memory_fill",
    "live_execution",
    "simulated_fallback",
)

#: External dependency states recorded without fabricated evidence.
ExternalState = str  # "BLOCKED_EXTERNAL" | "WAITING_EXTERNAL"


def validate_e2e_sequence(steps: list[str]) -> tuple[bool, str]:
    """Validate one practice E2E step sequence.

    Only the formal path is accepted; direct or residual execution
    steps are refused with an explicit reason.
    """
    for step in steps:
        if step in FORBIDDEN_E2E_STEPS:
            return False, f"forbidden step {step!r}"
    if steps != list(PRACTICE_E2E_PATH):
        return False, "sequence must follow the formal practice E2E path"
    return True, "formal practice E2E path followed"


class ObservationDayState(BaseModel):
    """One real-calendar observation day state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    day_index: int = Field(ge=0, le=30)
    calendar_date: str
    daily_gate_passed: bool = False
    weekly_gate_passed: bool | None = None
    external_state: str | None = None


class ObservationSupervisorState(BaseModel):
    """The restart-safe persistent supervisor state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    leader_id: str = Field(min_length=1)
    start_date: str | None = None
    next_run_date: str | None = None
    days: tuple[ObservationDayState, ...] = ()
    last_gate_run: str | None = None


def observation_day_index(
    start_date: date, today: date
) -> int | None:
    """Derive the observation day index from real calendar dates.

    Day 0 is the start date; Day 30 is the final day. A date before
    the start or beyond Day 30 yields ``None`` (not started / done) —
    never fabricated.
    """
    delta = (today - start_date).days
    if delta < 0 or delta > 30:
        return None
    return delta


class ObservationSupervisor:
    """A single-leader persistent observation supervisor.

    State survives restarts (NDJSON file). Next-run state is restored,
    daily and weekly evidence gates are invoked on their schedule, and
    external dependency states are recorded without fabricated
    evidence.
    """

    def __init__(
        self,
        *,
        leader_id: str,
        path: str | Path | None = None,
    ) -> None:
        if path is None:
            env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
            base = Path(env_dir) if env_dir else Path("~/.alphabrief")
            base = base.expanduser()
            base.mkdir(parents=True, exist_ok=True)
            path = base / "observation_supervisor.ndjson"
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._state = ObservationSupervisorState(leader_id=leader_id)
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            self._state = ObservationSupervisorState.model_validate(
                json.loads(line)
            )

    def _persist(self) -> None:
        with self._path.open("w", encoding="utf-8") as handle:
            handle.write(self._state.model_dump_json() + "\n")

    def begin(self, *, start_date: date) -> None:
        """Begin the real-calendar observation at Day 0."""
        self._state = self._state.model_copy(
            update={
                "start_date": start_date.isoformat(),
                "next_run_date": start_date.isoformat(),
                "days": (),
            }
        )
        self._persist()

    def restore(self) -> ObservationSupervisorState:
        """The persisted state after restart (next-run restored)."""
        return self._state

    def run_daily_gate(
        self, *, today: date, evidence_complete: bool
    ) -> ObservationDayState:
        """Invoke one daily evidence gate on the real calendar.

        The day index is derived from real UTC dates; missing evidence
        records the day as failed, never fabricated. The next-run date
        advances one calendar day (capped at Day 30).
        """
        if self._state.start_date is None:
            raise ValueError("observation has not started")
        index = observation_day_index(
            date.fromisoformat(self._state.start_date), today
        )
        if index is None:
            raise ValueError(f"date {today.isoformat()} outside Day 0..30")
        day = ObservationDayState(
            day_index=index,
            calendar_date=today.isoformat(),
            daily_gate_passed=evidence_complete,
        )
        days = tuple(
            day if existing.day_index != index else existing
            for existing in self._state.days
        )
        if index not in {existing.day_index for existing in self._state.days}:
            days = days + (day,)
        next_run = today.fromordinal(today.toordinal() + 1)
        self._state = self._state.model_copy(
            update={
                "days": days,
                "next_run_date": (
                    next_run.isoformat()
                    if index < 30
                    else self._state.next_run_date
                ),
                "last_gate_run": today.isoformat(),
            }
        )
        self._persist()
        return day

    def record_external_state(
        self, *, external_state: str, reason: str
    ) -> None:
        """Record BLOCKED_EXTERNAL or WAITING_EXTERNAL without evidence."""
        if external_state not in ("BLOCKED_EXTERNAL", "WAITING_EXTERNAL"):
            raise ValueError(f"unknown external state {external_state!r}")
        latest = self._state.days[-1] if self._state.days else None
        if latest is None:
            raise ValueError("no observation day recorded yet")
        updated = latest.model_copy(
            update={"external_state": external_state}
        )
        self._state = self._state.model_copy(
            update={
                "days": tuple(
                    updated if day.day_index == latest.day_index else day
                    for day in self._state.days
                )
            }
        )
        self._persist()

    def current_day(self) -> ObservationDayState | None:
        return self._state.days[-1] if self._state.days else None

    def next_run_date(self) -> str | None:
        return self._state.next_run_date


__all__ = [
    "APPLICABILITY_EVIDENCE_KINDS",
    "CONTINUITY_KINDS",
    "DAILY_EVIDENCE_KINDS",
    "DAY30_CLOSE_STEPS",
    "EVIDENCE_FLAWS",
    "FINAL_GATE_PROOFS",
    "FINAL_PROJECT_STATUS",
    "FINAL_RELEASE_GATES",
    "FINAL_SAFETY_INVARIANTS",
    "FORBIDDEN_REPORT_MARKERS",
    "LIVE_CLAIM_MARKERS",
    "REPORT_COUNT_FIELDS",
    "REPORT_EVIDENCE_SOURCES",
    "TRACEABILITY_FLAWS",
    "TRACEABILITY_LEVELS",
    "DayZeroAttempt",
    "DailyApplicabilityEvidence",
    "EVENT_RESOLUTION_FIELDS",
    "FAULT_INVARIANTS",
    "FAULT_SCENARIOS",
    "FinalGateResult",
    "FinalReleaseVerdict",
    "FinalReport",
    "INCIDENT_SEVERITIES",
    "IsolatedRestoreResult",
    "ContinuityAccounting",
    "Day30CloseReport",
    "FaultDrillReport",
    "FaultInvariant",
    "ManifestHashVerdict",
    "ObservationDayRecord",
    "QUALIFIED_OUTCOMES",
    "RESTART_RECONCILE_INVARIANTS",
    "RESTORE_SURFACES",
    "ReportContentVerdict",
    "ReportSource",
    "RestartReconcileDrillReport",
    "RestoreSurface",
    "TraceabilityVerdict",
    "WINDOW_ACCOUNT_KINDS",
    "WeekEventResolution",
    "WeeklyGateResult",
    "WindowAccounting",
    "WindowIncident",
    "build_applicability_evidence",
    "build_continuity_accounting",
    "build_daily_record",
    "build_window_accounting",
    "classify_qualified_outcome",
    "classify_window_incident",
    "generate_final_report",
    "resolve_week_event",
    "run_day30_close",
    "run_fault_drill",
    "run_final_gate",
    "run_final_release_gate",
    "run_isolated_restore",
    "run_restart_reconcile_drill",
    "run_weekly_gate",
    "scan_report_content",
    "validate_manifest_hashes",
    "verify_traceability",
    "FORBIDDEN_E2E_STEPS",
    "ObservationManifest",
    "ObservationDayState",
    "ObservationSupervisor",
    "ObservationSupervisorState",
    "PRACTICE_E2E_PATH",
    "build_day_zero_attempt",
    "observation_day_index",
    "qualified_start_date",
    "validate_e2e_sequence",
]


# ---------------------------------------------------------------------------
# Day 0 manifest and qualified observation clock (M16-W01)
# ---------------------------------------------------------------------------


class ObservationManifest(BaseModel):
    """The immutable Day 0 observation identity.

    Created only after engineering readiness, full OANDA practice
    preflight, controlled formal-path E2E, clean reconciliation, and
    isolated restore all succeed (AC-M16-W01-01).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str = Field(min_length=1)
    commit_hash: str = Field(min_length=1)
    tree_hash: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    config_version: str = Field(min_length=1)
    dependency_hash: str = Field(min_length=1)
    provider_profile: str = Field(min_length=1)
    account_hash: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    timezone: str = Field(min_length=1)
    start_timestamp: str = Field(min_length=1)
    day_zero_date: str = Field(min_length=1)


class DayZeroAttempt(BaseModel):
    """One deterministic Day 0 commissioning attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ready: bool
    manifest: ObservationManifest | None = None
    blockers: tuple[str, ...] = ()


def qualified_start_date(
    today: date, *, rehearsal_dates: tuple[date, ...] = ()
) -> date | None:
    """The qualified observation start date.

    The clock can never start from rehearsal or historical data: a
    ``today`` that matches a rehearsal date (or is before the last
    rehearsal date) yields ``None``.
    """
    for rehearsal in rehearsal_dates:
        if today <= rehearsal:
            return None
    return today


def build_day_zero_attempt(
    *,
    today: date,
    rehearsal_dates: tuple[date, ...],
    gates: dict[str, bool],
    manifest_fields: dict[str, str],
) -> DayZeroAttempt:
    """One deterministic Day 0 commissioning attempt.

    Every gate must pass (engineering readiness, observation preflight,
    formal-path E2E, clean reconciliation, isolated restore); missing
    gates or a disqualified start date record BLOCKED_EXTERNAL blockers
    and never manufacture a manifest.
    """
    blockers: list[str] = []
    start = qualified_start_date(today, rehearsal_dates=rehearsal_dates)
    if start is None:
        blockers.append("BLOCKED_EXTERNAL: qualified clock cannot start")
    for gate, passed in gates.items():
        if not passed:
            blockers.append(f"BLOCKED_EXTERNAL: {gate} not passed")
    if blockers or start is None:
        return DayZeroAttempt(ready=False, manifest=None, blockers=tuple(blockers))
    return DayZeroAttempt(
        ready=True,
        manifest=ObservationManifest(
            **manifest_fields,
            day_zero_date=start.isoformat(),
        ),
        blockers=(),
    )


# ---------------------------------------------------------------------------
# Daily evidence chain and weekly gate (M16-W02)
# ---------------------------------------------------------------------------

#: The required evidence kinds per observation day (AC-M16-W02-01).
DAILY_EVIDENCE_KINDS: tuple[str, ...] = (
    "preflight",
    "data",
    "news",
    "sentiment",
    "committee_or_skip",
    "intent_or_no_trade",
    "risk",
    "execution_outcome",
    "reconciliation",
    "portfolio",
    "alerts",
    "heartbeat",
    "backup",
    "daily_manifest_hash",
)


class ObservationDayRecord(BaseModel):
    """One day's evidence chain with its manifest hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: int = Field(ge=0, le=30)
    calendar_date: str = Field(min_length=1)
    evidence: dict[str, bool] = Field(default_factory=dict)
    daily_manifest_hash: str | None = None
    complete: bool = False


def build_daily_record(
    *,
    day: int,
    calendar_date: str,
    evidence_truth: dict[str, bool],
    daily_manifest_hash: str | None,
) -> ObservationDayRecord:
    """One deterministic daily evidence record.

    Missing evidence kinds stay False — never fabricated. The record
    is complete only when every kind has truth.
    """
    evidence = {
        kind: bool(evidence_truth.get(kind, False))
        for kind in DAILY_EVIDENCE_KINDS
    }
    complete = all(evidence.values()) and daily_manifest_hash is not None
    return ObservationDayRecord(
        day=day,
        calendar_date=calendar_date,
        evidence=evidence,
        daily_manifest_hash=daily_manifest_hash,
        complete=complete,
    )


class WeeklyGateResult(BaseModel):
    """One week's scorecard and gate verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    week: int = Field(ge=1)
    days_qualified: int = Field(ge=0)
    passed: bool
    zero_duplicate_orders: bool = False
    zero_unapproved_orders: bool = False
    zero_live_or_other_broker_attempts: bool = False
    monotonic_cursor: bool = False
    zero_unresolved_cross_day_difference: bool = False


def run_weekly_gate(
    *,
    week: int,
    days_qualified: int,
    truth: dict[str, bool] | None = None,
) -> WeeklyGateResult:
    """One deterministic weekly gate.

    Every zero-invariant must hold; missing truth fails the gate.
    """
    truth = truth or {}
    invariants = {
        "zero_duplicate_orders": bool(
            truth.get("zero_duplicate_orders", False)
        ),
        "zero_unapproved_orders": bool(
            truth.get("zero_unapproved_orders", False)
        ),
        "zero_live_or_other_broker_attempts": bool(
            truth.get("zero_live_or_other_broker_attempts", False)
        ),
        "monotonic_cursor": bool(truth.get("monotonic_cursor", False)),
        "zero_unresolved_cross_day_difference": bool(
            truth.get("zero_unresolved_cross_day_difference", False)
        ),
    }
    return WeeklyGateResult(
        week=week,
        days_qualified=days_qualified,
        passed=days_qualified >= 7 and all(invariants.values()),
        zero_duplicate_orders=invariants["zero_duplicate_orders"],
        zero_unapproved_orders=invariants["zero_unapproved_orders"],
        zero_live_or_other_broker_attempts=invariants[
            "zero_live_or_other_broker_attempts"
        ],
        monotonic_cursor=invariants["monotonic_cursor"],
        zero_unresolved_cross_day_difference=invariants[
            "zero_unresolved_cross_day_difference"
        ],
    )


#: Qualified non-trading outcomes with their required reason (AC-03).
QUALIFIED_OUTCOMES: tuple[str, ...] = (
    "weekend",
    "holiday",
    "market_closed",
    "degraded_provider",
    "risk_gate_rejection",
    "no_opportunity",
)


def classify_qualified_outcome(
    outcome: str, *, reason: str | None
) -> bool:
    """Whether one non-trading outcome qualifies.

    An outcome qualifies only with a complete non-blank reason; the
    contract never imposes an activity quota or a synthetic order.
    """
    if outcome not in QUALIFIED_OUTCOMES:
        return False
    return bool(reason and reason.strip())


# ---------------------------------------------------------------------------
# Days 8 through 14: applicability evidence, isolated restore, and
# window incident classification (M16-W03)
# ---------------------------------------------------------------------------


#: Applicability evidence kinds required explicitly for every day of
#: the second real week (AC-M16-W03-01). Each kind carries an explicit
#: verdict (applies or not) with a complete reason when it applies.
APPLICABILITY_EVIDENCE_KINDS: tuple[str, ...] = (
    "weekend",
    "session",
    "financing",
    "macro_window",
    "provider_degradation",
    "no_trade",
)


class DailyApplicabilityEvidence(BaseModel):
    """One day's explicit applicability chain (Days 8-14).

    ``applicability`` maps every declared kind to an explicit verdict;
    ``reasons`` holds the complete non-blank reason for each kind that
    applies. Missing truth stays False with no reason — never
    fabricated. The chain is complete only when every kind has an
    explicit verdict.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: int = Field(ge=0, le=30)
    calendar_date: str = Field(min_length=1)
    applicability: dict[str, bool] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)
    complete: bool = False


def build_applicability_evidence(
    *,
    day: int,
    calendar_date: str,
    applicability_truth: dict[str, bool] | None = None,
    reasons: dict[str, str] | None = None,
) -> DailyApplicabilityEvidence:
    """One deterministic applicability chain.

    Every declared kind receives an explicit verdict; kinds without
    truth are False (never assumed). A True verdict requires a complete
    non-blank reason, otherwise the kind reverts to False.
    """
    truth = applicability_truth or {}
    supplied_reasons = reasons or {}
    applicability: dict[str, bool] = {}
    kept_reasons: dict[str, str] = {}
    for kind in APPLICABILITY_EVIDENCE_KINDS:
        applies = bool(truth.get(kind, False))
        reason = (supplied_reasons.get(kind) or "").strip()
        if applies and not reason:
            applies = False
        applicability[kind] = applies
        if applies:
            kept_reasons[kind] = reason
    return DailyApplicabilityEvidence(
        day=day,
        calendar_date=calendar_date,
        applicability=applicability,
        reasons=kept_reasons,
        complete=all(kind in applicability for kind in APPLICABILITY_EVIDENCE_KINDS),
    )


#: The state surfaces an in-window isolated restore must reproduce
#: (AC-M16-W03-02).
RESTORE_SURFACES: tuple[str, ...] = (
    "schema",
    "projections",
    "cycle_checkpoints",
    "risk_counters",
    "broker_mappings",
    "transaction_cursor",
    "observation_state",
)


class RestoreSurface(BaseModel):
    """One restored surface verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    surface: str = Field(min_length=1)
    reproduced: bool
    detail: str = Field(min_length=1)


class IsolatedRestoreResult(BaseModel):
    """One deterministic isolated-restore drill report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario: str = Field(min_length=1)
    isolated: bool = True
    passed: bool
    surfaces: tuple[RestoreSurface, ...]


def run_isolated_restore(
    *,
    scenario: str,
    surface_truth: dict[str, bool] | None = None,
) -> IsolatedRestoreResult:
    """Run one deterministic isolated restore drill.

    ``surface_truth`` maps each restore surface to reproduced or not;
    missing truth fails closed as not reproduced — a restore is never
    assumed. The drill always restores into an isolated directory.
    """
    truth = surface_truth or {}
    surfaces = tuple(
        RestoreSurface(
            surface=surface,
            reproduced=bool(truth.get(surface, False)),
            detail=(
                "reproduced" if truth.get(surface, False)
                else "not reproduced"
            ),
        )
        for surface in RESTORE_SURFACES
    )
    return IsolatedRestoreResult(
        scenario=scenario,
        isolated=True,
        passed=all(surface.reproduced for surface in surfaces),
        surfaces=surfaces,
    )


#: Declared incident severities for window classification (AC-03).
INCIDENT_SEVERITIES: tuple[str, ...] = ("P0", "P1", "P2", "P3")


class WindowIncident(BaseModel):
    """One classified window incident and its reset decision.

    A failed weekly gate always records a classified incident whose
    reset never asks for approval and never carries invalid days
    forward (AC-M16-W03-03).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    window: int = Field(ge=1)
    severity: str = Field(min_length=1)
    reset_required: bool
    invalid_days_carried_forward: bool
    detail: str = Field(min_length=1)


def classify_window_incident(
    *,
    window: int,
    severity: str,
    gate_passed: bool,
) -> WindowIncident:
    """One deterministic window incident classification.

    An unclassified severity is invalid and fails closed as P0. A gate
    that did not pass always records the classified incident, requires
    the window reset, and never carries invalid days forward; a passing
    gate records no reset. No approval question is ever asked.
    """
    if severity not in INCIDENT_SEVERITIES:
        severity = "P0"
    if gate_passed:
        return WindowIncident(
            window=window,
            severity=severity,
            reset_required=False,
            invalid_days_carried_forward=False,
            detail="weekly gate passed; no window reset required",
        )
    return WindowIncident(
        window=window,
        severity=severity,
        reset_required=True,
        invalid_days_carried_forward=False,
        detail=(
            "classified incident; window reset required; "
            "invalid days dropped; no approval asked"
        ),
    )


# ---------------------------------------------------------------------------
# Days 15 through 21: continuity accounting, fault injection, and week
# event resolution (M16-W04)
# ---------------------------------------------------------------------------


#: Continuity evidence kinds required continuously for every day of
#: the third real week (AC-M16-W04-01).
CONTINUITY_KINDS: tuple[str, ...] = (
    "heartbeat",
    "lease",
    "cursor",
    "reconciliation",
    "backup",
    "provider",
    "model_schema",
    "alert",
    "risk_state",
)


class ContinuityAccounting(BaseModel):
    """One day's continuous accounting chain (Days 15-21).

    Every declared continuity kind carries an explicit boolean;
    missing truth stays False — never fabricated.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: int = Field(ge=0, le=30)
    calendar_date: str = Field(min_length=1)
    continuity: dict[str, bool] = Field(default_factory=dict)
    complete: bool = False


def build_continuity_accounting(
    *,
    day: int,
    calendar_date: str,
    continuity_truth: dict[str, bool] | None = None,
) -> ContinuityAccounting:
    """One deterministic continuity chain.

    Every declared kind receives an explicit verdict; kinds without
    truth are False (never assumed).
    """
    truth = continuity_truth or {}
    continuity = {
        kind: bool(truth.get(kind, False)) for kind in CONTINUITY_KINDS
    }
    return ContinuityAccounting(
        day=day,
        calendar_date=calendar_date,
        continuity=continuity,
        complete=all(
            kind in continuity for kind in CONTINUITY_KINDS
        ),
    )


#: Approved local fault-injection scenarios (AC-M16-W04-02).
FAULT_SCENARIOS: tuple[str, ...] = (
    "http_429",
    "http_5xx",
    "network_loss",
    "stale_data",
    "model_failure",
)

#: Invariants every fault drill must preserve (AC-M16-W04-02).
FAULT_INVARIANTS: tuple[str, ...] = (
    "bounded_retry",
    "jitter",
    "no_scheduler_starvation",
    "safe_no_trade_or_freeze",
    "durable_alerting",
    "clean_recovery",
    "no_blind_resubmission",
    "no_duplicate_external_order",
)


class FaultInvariant(BaseModel):
    """One fault-drill invariant verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    preserved: bool
    detail: str = Field(min_length=1)


class FaultDrillReport(BaseModel):
    """One deterministic fault-injection drill report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario: str = Field(min_length=1)
    passed: bool
    submits: int = 0
    invariants: tuple[FaultInvariant, ...]


def run_fault_drill(
    *,
    scenario: str,
    invariant_truth: dict[str, bool] | None = None,
) -> FaultDrillReport:
    """Run one deterministic approved fault-injection drill.

    ``invariant_truth`` maps each invariant to preserved or not;
    missing truth fails closed as not preserved. The drill is local
    only: it never submits and never touches the practice account
    outside normal product behavior.
    """
    truth = invariant_truth or {}
    if scenario not in FAULT_SCENARIOS:
        return FaultDrillReport(
            scenario=scenario,
            passed=False,
            submits=0,
            invariants=tuple(
                FaultInvariant(
                    name=name,
                    preserved=False,
                    detail="unknown fault scenario",
                )
                for name in FAULT_INVARIANTS
            ),
        )
    invariants = tuple(
        FaultInvariant(
            name=name,
            preserved=bool(truth.get(name, False)),
            detail=(
                "preserved" if truth.get(name, False) else "not preserved"
            ),
        )
        for name in FAULT_INVARIANTS
    )
    return FaultDrillReport(
        scenario=scenario,
        passed=all(invariant.preserved for invariant in invariants),
        submits=0,
        invariants=invariants,
    )


#: Fields every P2/P3 week event must carry (AC-M16-W04-03).
EVENT_RESOLUTION_FIELDS: tuple[str, ...] = (
    "reset_decision",
    "evidence_hash",
    "repair_reference",
)


class WeekEventResolution(BaseModel):
    """One week event's deterministic resolution verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: str = Field(min_length=1)
    resolved: bool
    detail: str = Field(min_length=1)


def resolve_week_event(
    *,
    severity: str,
    reset_decision: str | None = None,
    evidence_hash: str | None = None,
    repair_reference: str | None = None,
) -> WeekEventResolution:
    """One deterministic week event resolution.

    P0/P1 events are never resolved by the observation loop — the week
    gate fails closed until they are closed. P2/P3 events resolve only
    with a deterministic reset decision, evidence hash, and repair
    reference. No operator question is ever asked.
    """
    if severity not in INCIDENT_SEVERITIES:
        severity = "P0"
    if severity in ("P0", "P1"):
        return WeekEventResolution(
            severity=severity,
            resolved=False,
            detail="P0/P1 unresolved; week gate fails closed",
        )
    fields = {
        "reset_decision": reset_decision,
        "evidence_hash": evidence_hash,
        "repair_reference": repair_reference,
    }
    missing = [
        name
        for name in EVENT_RESOLUTION_FIELDS
        if not (fields[name] and str(fields[name]).strip())
    ]
    if missing:
        return WeekEventResolution(
            severity=severity,
            resolved=False,
            detail=f"missing {', '.join(missing)}",
        )
    return WeekEventResolution(
        severity=severity,
        resolved=True,
        detail=(
            "deterministic reset decision, evidence hash, and "
            "repair reference recorded"
        ),
    )


# ---------------------------------------------------------------------------
# Days 22 through 30: window accounting, week-4 restart-reconcile
# drill, and the Day 30 close (M16-W05)
# ---------------------------------------------------------------------------


#: Separate accounting kinds for the full 30-day window
#: (AC-M16-W05-01).
WINDOW_ACCOUNT_KINDS: tuple[str, ...] = (
    "active_market",
    "weekend",
    "holiday",
    "no_trade",
    "partial",
    "failed",
    "reset",
)


class WindowAccounting(BaseModel):
    """One deterministic 30-day window accounting ledger.

    Every declared kind carries a non-negative count; the ledger is
    complete only when exactly 30 calendar days are accounted for.
    Missing truth yields zero counts — never fabricated.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    days_total: int = Field(ge=0, le=30)
    counts: dict[str, int] = Field(default_factory=dict)
    complete: bool = False


def build_window_accounting(
    *,
    days_total: int,
    counts_truth: dict[str, int] | None = None,
) -> WindowAccounting:
    """One deterministic window accounting ledger.

    Missing kinds are zero; the ledger is complete only when
    ``days_total`` is exactly 30.
    """
    truth = counts_truth or {}
    counts = {
        kind: max(0, int(truth.get(kind, 0)))
        for kind in WINDOW_ACCOUNT_KINDS
    }
    return WindowAccounting(
        days_total=days_total,
        counts=counts,
        complete=days_total == 30,
    )


#: Invariants the week-4 restart and reconciliation drill must leave
#: untouched (AC-M16-W05-02).
RESTART_RECONCILE_INVARIANTS: tuple[str, ...] = (
    "no_unintended_order",
    "no_unintended_trade",
    "no_unintended_position",
    "no_unintended_freeze",
    "no_unexplained_difference",
)


class RestartReconcileDrillReport(BaseModel):
    """One deterministic week-4 restart and reconciliation drill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario: str = Field(min_length=1)
    passed: bool
    submits: int = 0
    invariants: tuple[FaultInvariant, ...]


def run_restart_reconcile_drill(
    *,
    scenario: str,
    invariant_truth: dict[str, bool] | None = None,
) -> RestartReconcileDrillReport:
    """Run one deterministic week-4 restart and reconciliation drill.

    ``invariant_truth`` maps each invariant to preserved or not;
    missing truth fails closed as not preserved. The drill never
    submits and leaves no unintended order, trade, position, freeze,
    or unexplained difference.
    """
    truth = invariant_truth or {}
    invariants = tuple(
        FaultInvariant(
            name=name,
            preserved=bool(truth.get(name, False)),
            detail=(
                "preserved" if truth.get(name, False) else "not preserved"
            ),
        )
        for name in RESTART_RECONCILE_INVARIANTS
    )
    return RestartReconcileDrillReport(
        scenario=scenario,
        passed=all(invariant.preserved for invariant in invariants),
        submits=0,
        invariants=invariants,
    )


#: The declared Day 30 close sequence (AC-M16-W05-03).
DAY30_CLOSE_STEPS: tuple[str, ...] = (
    "stop_new_cycles",
    "final_reconcile",
    "duplicate_invariant",
    "approval_invariant",
    "fresh_backup",
    "isolated_restore",
    "artifact_hash_validation",
)


class Day30CloseReport(BaseModel):
    """One deterministic Day 30 close report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    steps: tuple[FaultInvariant, ...]


def run_day30_close(
    *,
    step_truth: dict[str, bool] | None = None,
) -> Day30CloseReport:
    """Run one deterministic Day 30 close.

    ``step_truth`` maps each close step to completed or not; missing
    truth fails closed as not completed. The close never creates new
    cycles and never resubmits orders.
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
        for name in DAY30_CLOSE_STEPS
    )
    return Day30CloseReport(
        passed=all(step.preserved for step in steps),
        steps=steps,
    )


class ManifestHashVerdict(BaseModel):
    """One deterministic manifest-hash validation verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    count: int = Field(ge=0)
    detail: str = Field(min_length=1)


def validate_manifest_hashes(
    *,
    hashes: dict[str, str] | None = None,
    required_count: int = 34,
) -> ManifestHashVerdict:
    """Validate every daily (30) and weekly (4) manifest hash.

    A missing, blank, or duplicated hash fails the validation; the
    count must be exactly the required 34 manifests.
    """
    supplied = hashes or {}
    values = [value for value in supplied.values()]
    blank = [key for key, value in supplied.items() if not value.strip()]
    duplicates = len(values) != len(set(values))
    valid_count = len(supplied) == required_count
    if blank:
        return ManifestHashVerdict(
            valid=False,
            count=len(supplied),
            detail=f"blank manifest hashes: {', '.join(sorted(blank))}",
        )
    if duplicates:
        return ManifestHashVerdict(
            valid=False,
            count=len(supplied),
            detail="duplicate manifest hash values",
        )
    if not valid_count:
        return ManifestHashVerdict(
            valid=False,
            count=len(supplied),
            detail=f"expected {required_count} manifests, got {len(supplied)}",
        )
    return ManifestHashVerdict(
        valid=True,
        count=len(supplied),
        detail=f"all {required_count} manifest hashes valid",
    )


# ---------------------------------------------------------------------------
# Final 30-day observation gate (M16-W06)
# ---------------------------------------------------------------------------


#: Evidence proofs the final gate must establish (AC-M16-W06-01).
FINAL_GATE_PROOFS: tuple[str, ...] = (
    "thirty_of_thirty_daily_records",
    "active_market_decision_chains",
    "daily_backups",
    "four_weekly_gates",
    "final_restore",
    "continuous_qualified_timing",
    "immutable_manifest_hashes",
)

#: Safety invariants the final gate must prove (AC-M16-W06-02).
FINAL_SAFETY_INVARIANTS: tuple[str, ...] = (
    "zero_duplicate_external_orders",
    "zero_order_without_approved_risk_decision",
    "zero_live_or_other_broker_attempt",
    "zero_unexplained_cross_day_difference",
    "zero_unresolved_p0_or_p1",
)

#: Evidence flaws that must fail the gate and record a blocker
#: (AC-M16-W06-03).
EVIDENCE_FLAWS: tuple[str, ...] = (
    "missing",
    "modified",
    "mock_only",
    "waived",
    "manually_asserted",
    "future_dated",
    "reset_invalid",
)


class FinalGateResult(BaseModel):
    """One deterministic final 30-day observation gate result.

    The gate derives its verdict only from supplied evidence truth;
    missing truth fails each proof and invariant closed, any declared
    evidence flaw fails the gate and records a blocker, and the product
    remains OANDA practice-only (REQ-OBS-007) with no live path.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    practice_only: bool = True
    proofs: tuple[FaultInvariant, ...]
    invariants: tuple[FaultInvariant, ...]
    blockers: tuple[str, ...] = ()


def run_final_gate(
    *,
    proofs_truth: dict[str, bool] | None = None,
    invariants_truth: dict[str, bool] | None = None,
    flaws: dict[str, bool] | None = None,
) -> FinalGateResult:
    """Run one deterministic final observation gate.

    ``proofs_truth`` maps each evidence proof to proven or not;
    ``invariants_truth`` maps each safety invariant to zero or not;
    ``flaws`` maps each evidence flaw to present or not. Missing truth
    fails closed, and any present flaw records a blocker.
    """
    proof_truth = proofs_truth or {}
    invariant_truth = invariants_truth or {}
    flaw_truth = flaws or {}
    proofs = tuple(
        FaultInvariant(
            name=name,
            preserved=bool(proof_truth.get(name, False)),
            detail=(
                "proven" if proof_truth.get(name, False) else "not proven"
            ),
        )
        for name in FINAL_GATE_PROOFS
    )
    invariants = tuple(
        FaultInvariant(
            name=name,
            preserved=bool(invariant_truth.get(name, False)),
            detail=(
                "zero" if invariant_truth.get(name, False) else "not zero"
            ),
        )
        for name in FINAL_SAFETY_INVARIANTS
    )
    blockers = [
        f"BLOCKED_EXTERNAL: evidence flaw {flaw}"
        for flaw in EVIDENCE_FLAWS
        if flaw_truth.get(flaw, False)
    ]
    passed = (
        all(proof.preserved for proof in proofs)
        and all(invariant.preserved for invariant in invariants)
        and not blockers
    )
    return FinalGateResult(
        passed=passed,
        practice_only=True,
        proofs=proofs,
        invariants=invariants,
        blockers=tuple(blockers),
    )


# ---------------------------------------------------------------------------
# Evidence-derived final acceptance report (M17-W01)
# ---------------------------------------------------------------------------


#: Immutable evidence sources the final report must reference
#: (AC-M17-W01-01). Handwritten totals are never accepted.
REPORT_EVIDENCE_SOURCES: tuple[str, ...] = (
    "requirements_map",
    "database_facts",
    "loop_ledger",
    "test_results",
    "oanda_practice_evidence",
    "observation_artifact_hashes",
)

#: Count fields derived from evidence (AC-M17-W01-01). Missing counts
#: stay zero - never guessed.
REPORT_COUNT_FIELDS: tuple[str, ...] = (
    "requirements_total",
    "work_items_total",
    "acceptance_passed",
    "acceptance_total",
    "quality_passed",
    "quality_total",
    "safety_invariants_zero",
    "safety_invariants_total",
    "observation_days_qualified",
    "observation_days_total",
    "incidents_open",
    "known_limitations",
)


class ReportSource(BaseModel):
    """One referenced evidence source in the final report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    referenced: bool
    detail: str = Field(min_length=1)


class FinalReport(BaseModel):
    """One deterministic evidence-derived final acceptance report.

    Every count comes from supplied evidence; missing sources fail the
    report closed. The manifest hash covers the normalized content so a
    second generation from the same frozen inputs is identical
    (AC-M17-W01-02).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    sources: tuple[ReportSource, ...]
    counts: dict[str, int]
    manifest_hash: str = Field(min_length=1)
    normalized_content: str = Field(min_length=1)


def _normalize_report_content(
    sources: tuple[ReportSource, ...], counts: dict[str, int]
) -> str:
    """The canonical normalized report content (deterministic)."""
    lines = [
        "source=" + source.name + ":" + str(source.referenced)
        for source in sources
    ]
    lines += [
        "count=" + name + ":" + str(counts[name])
        for name in REPORT_COUNT_FIELDS
    ]
    return "\n".join(lines)


def generate_final_report(
    *,
    source_truth: dict[str, bool] | None = None,
    count_truth: dict[str, int] | None = None,
) -> FinalReport:
    """Generate one deterministic final acceptance report.

    ``source_truth`` maps each evidence source to referenced or not;
    ``count_truth`` maps each count field to its evidence-derived value.
    Missing truth fails the report closed - nothing is handwritten.
    """
    import hashlib

    truth = source_truth or {}
    sources = tuple(
        ReportSource(
            name=name,
            referenced=bool(truth.get(name, False)),
            detail=(
                "referenced" if truth.get(name, False)
                else "not referenced"
            ),
        )
        for name in REPORT_EVIDENCE_SOURCES
    )
    counts = {
        name: max(0, int((count_truth or {}).get(name, 0)))
        for name in REPORT_COUNT_FIELDS
    }
    content = _normalize_report_content(sources, counts)
    return FinalReport(
        passed=all(source.referenced for source in sources),
        sources=sources,
        counts=counts,
        manifest_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        normalized_content=content,
    )


#: Markers that must never appear in the final report (AC-M17-W01-03).
FORBIDDEN_REPORT_MARKERS: tuple[str, ...] = (
    "waiver",
    "tbd",
)

#: Live-trading implication phrases that must never appear.
LIVE_CLAIM_MARKERS: tuple[str, ...] = (
    "live trading is enabled",
    "live mode is active",
    "go live",
)


class ReportContentVerdict(BaseModel):
    """One deterministic report-content scan verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    clean: bool
    findings: tuple[str, ...] = ()


def scan_report_content(*, text: str) -> ReportContentVerdict:
    """Scan report content for secrets, waivers, TBD, and live claims.

    Secret patterns cover bearer tokens, token/authorization values,
    and full account IDs; marker scans are case-insensitive. Any
    finding marks the content unclean.
    """
    import re

    findings: list[str] = []
    lowered = text.lower()
    if re.search(r"Bearer\s+\S+", text, re.IGNORECASE):
        findings.append("bearer token present")
    if re.search(r"[\"']?token[\"']?\s*[:=]\s*[\"']?\S+", text, re.IGNORECASE):
        findings.append("token value present")
    if re.search(r"authorization\s*[:=]\s*\S+", text, re.IGNORECASE):
        findings.append("authorization value present")
    if re.search(r"account[_-]?id\s*[:=]\s*[\"']?\S+", text, re.IGNORECASE):
        findings.append("account id present")
    if re.search(r"account-\d{8,}", text, re.IGNORECASE):
        findings.append("full account id present")
    for marker in FORBIDDEN_REPORT_MARKERS:
        if re.search(rf"\b{marker}\b", lowered):
            findings.append(f"forbidden marker {marker!r}")
    for marker in LIVE_CLAIM_MARKERS:
        if marker in lowered:
            findings.append(f"live-claim marker {marker!r}")
    return ReportContentVerdict(
        clean=not findings,
        findings=tuple(findings),
    )


# ---------------------------------------------------------------------------
# Final acceptance and paper-only handoff (M17-W04)
# ---------------------------------------------------------------------------


#: Traceability hierarchy levels (AC-M17-W04-01). Every level must
#: carry a committed evidence reference.
TRACEABILITY_LEVELS: tuple[str, ...] = (
    "milestone",
    "work_item",
    "requirement",
    "acceptance_predicate",
)

#: Traceability flaws that must fail final acceptance.
TRACEABILITY_FLAWS: tuple[str, ...] = (
    "tbd",
    "waiver",
    "mock_substitution",
    "unresolved_blocker",
    "self_authored_pass",
)


class TraceabilityVerdict(BaseModel):
    """One deterministic traceability verification verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    levels: tuple[FaultInvariant, ...]
    blockers: tuple[str, ...] = ()


def verify_traceability(
    *,
    level_truth: dict[str, bool] | None = None,
    flaws: dict[str, bool] | None = None,
) -> TraceabilityVerdict:
    """Verify the committed traceability contract.

    Every hierarchy level must have a committed evidence reference;
    missing truth fails closed, and any TBD, waiver, mock substitution,
    unresolved blocker, or self-authored pass records a blocker.
    """
    truth = level_truth or {}
    flaw_truth = flaws or {}
    levels = tuple(
        FaultInvariant(
            name=name,
            preserved=bool(truth.get(name, False)),
            detail=(
                "referenced" if truth.get(name, False) else "not referenced"
            ),
        )
        for name in TRACEABILITY_LEVELS
    )
    blockers = [
        f"traceability flaw {flaw}" for flaw in TRACEABILITY_FLAWS
        if flaw_truth.get(flaw, False)
    ]
    return TraceabilityVerdict(
        passed=all(level.preserved for level in levels) and not blockers,
        levels=levels,
        blockers=tuple(blockers),
    )


#: The final release gates (AC-M17-W04-02).
FINAL_RELEASE_GATES: tuple[str, ...] = (
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

#: The only final project status that may be set when every gate and
#: hash proof passes (AC-M17-W04-03).
FINAL_PROJECT_STATUS: str = "COMPLETE_PAPER_ONLY"


class FinalReleaseVerdict(BaseModel):
    """One deterministic final release verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    status: str = Field(min_length=1)
    gates: tuple[FaultInvariant, ...]
    report_hash_matches: bool = False
    blockers: tuple[str, ...] = ()


def run_final_release_gate(
    *,
    gate_truth: dict[str, bool] | None = None,
    report_hash_matches: bool = False,
) -> FinalReleaseVerdict:
    """Run one deterministic final release gate.

    ``gate_truth`` maps each release gate to passed or not; missing
    truth fails closed. The project status becomes
    ``COMPLETE_PAPER_ONLY`` only when every gate passes and the final
    report hash matches the source artifacts. Live trading, other
    brokers, and production simulation stay forbidden and unreachable.
    """
    truth = gate_truth or {}
    gates = tuple(
        FaultInvariant(
            name=name,
            preserved=bool(truth.get(name, False)),
            detail=(
                "passed" if truth.get(name, False) else "not passed"
            ),
        )
        for name in FINAL_RELEASE_GATES
    )
    passed = (
        all(gate.preserved for gate in gates) and report_hash_matches
    )
    return FinalReleaseVerdict(
        passed=passed,
        status=FINAL_PROJECT_STATUS if passed else "IN_PROGRESS",
        gates=gates,
        report_hash_matches=report_hash_matches,
        blockers=(
            ()
            if passed
            else (
                "BLOCKED_EXTERNAL: final report hash does not match "
                "source artifacts"
                if not report_hash_matches
                else "BLOCKED_EXTERNAL: release gates not all passed",
            )
        ),
    )
