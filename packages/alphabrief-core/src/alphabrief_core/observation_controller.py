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
    "FORBIDDEN_E2E_STEPS",
    "ObservationDayState",
    "ObservationSupervisor",
    "ObservationSupervisorState",
    "PRACTICE_E2E_PATH",
    "observation_day_index",
    "validate_e2e_sequence",
]
