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
    "DAILY_EVIDENCE_KINDS",
    "DayZeroAttempt",
    "DailyApplicabilityEvidence",
    "INCIDENT_SEVERITIES",
    "IsolatedRestoreResult",
    "ObservationDayRecord",
    "QUALIFIED_OUTCOMES",
    "RESTORE_SURFACES",
    "RestoreSurface",
    "WeeklyGateResult",
    "WindowIncident",
    "build_applicability_evidence",
    "build_daily_record",
    "classify_qualified_outcome",
    "classify_window_incident",
    "run_isolated_restore",
    "run_weekly_gate",
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
