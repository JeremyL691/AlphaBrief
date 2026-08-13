"""Durable daily-cycle state machine (M11-W01).

Replaces one-shot orchestration with a persisted compare-and-set state
machine covering every required daily-cycle phase: preflight, ingest,
snapshot, discuss, propose, risk, execute (or no-trade), reconcile,
report, complete. Every legal advance atomically appends one immutable
transition row (input hashes, output IDs, attempt count, timestamps,
prior phase) and advances the current state; a stale writer whose
expected phase does not match the stored state is rejected without
mutating anything. A restart resumes from the phase after the last
committed gate, so a completed side effect is never repeated.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_trader.db_store import CYCLE_STATE_PHASE_ORDER, CycleStateStore

CyclePhase = str

CYCLE_PHASE_ORDER: tuple[str, ...] = CYCLE_STATE_PHASE_ORDER

CYCLE_EXECUTE_OUTCOMES: tuple[str, ...] = (
    "executed",
    "no_trade",
    "blocked",
    "error",
)


class CycleTransition(BaseModel):
    """One immutable, committed phase transition (audit fact)."""

    model_config = ConfigDict(extra="forbid")

    transition_id: str = Field(min_length=1)
    cycle_id: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    phase_order: int = Field(ge=0)
    prior_phase: str | None = None
    attempt_count: int = Field(default=1, ge=1)
    input_hashes: dict[str, str] = Field(default_factory=dict)
    output_ids: dict[str, str] = Field(default_factory=dict)
    outcome: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class CycleStateMachine:
    """Typed, deterministic facade over the persisted cycle state store.

    The machine owns no mutable state: identical calls with identical
    stores produce identical results.
    """

    def __init__(self, store: CycleStateStore) -> None:
        if store is None:
            raise TypeError("store is required")
        self._store = store

    def begin(self, cycle_id: str) -> bool:
        """Initialize a new cycle at the preflight phase."""
        return self._store.begin(cycle_id, "preflight")

    def advance(
        self,
        cycle_id: str,
        *,
        expected_phase: str,
        next_phase: str,
        input_hashes: dict[str, str] | None = None,
        output_ids: dict[str, str] | None = None,
        attempt_count: int = 1,
        outcome: str | None = None,
    ) -> CycleTransition | None:
        """Advance the cycle; ``None`` when the advance is stale/illegal."""
        if expected_phase not in CYCLE_PHASE_ORDER:
            raise ValueError(f"unknown expected phase {expected_phase!r}")
        if next_phase not in CYCLE_PHASE_ORDER:
            raise ValueError(f"unknown next phase {next_phase!r}")
        if expected_phase == "execute" and outcome not in CYCLE_EXECUTE_OUTCOMES:
            raise ValueError(
                "the transition leaving the execute phase must record an "
                f"outcome in {CYCLE_EXECUTE_OUTCOMES}"
            )
        now = datetime.now(UTC)
        transition_id = f"t_{cycle_id}_{next_phase}_{int(now.timestamp())}"
        ok = self._store.advance(
            cycle_id,
            expected_phase=expected_phase,
            next_phase=next_phase,
            input_hashes=input_hashes,
            output_ids=output_ids,
            attempt_count=attempt_count,
            outcome=outcome,
            transition_id=transition_id,
        )
        if not ok:
            return None
        return CycleTransition(
            transition_id=transition_id,
            cycle_id=cycle_id,
            phase=next_phase,
            phase_order=CYCLE_PHASE_ORDER.index(next_phase),
            prior_phase=expected_phase,
            attempt_count=attempt_count,
            input_hashes=input_hashes or {},
            output_ids=output_ids or {},
            outcome=outcome,
            created_at=now,
        )

    def state(self, cycle_id: str) -> dict[str, object] | None:
        """Return the current persisted state, or ``None``."""
        return self._store.get_state(cycle_id)

    def transitions(self, cycle_id: str) -> list[CycleTransition]:
        """Return every committed transition in legal order."""
        raw = self._store.get_transitions(cycle_id)
        return [
            CycleTransition(
                transition_id=row["transition_id"],
                cycle_id=row["cycle_id"],
                phase=row["phase"],
                phase_order=row["phase_order"],
                prior_phase=row["prior_phase"],
                attempt_count=row["attempt_count"],
                input_hashes=row["input_hashes"],
                output_ids=row["output_ids"],
                outcome=row["outcome"],
                created_at=datetime.fromisoformat(str(row["created_at"])),
            )
            for row in raw
        ]

    def resume_phase(self, cycle_id: str) -> str | None:
        """Return the phase to resume at, or ``None`` when complete."""
        return self._store.resume_phase(cycle_id)

    def is_complete(self, cycle_id: str) -> bool:
        state = self._store.get_state(cycle_id)
        return state is not None and state["phase"] == "complete"

    def phases(self) -> Sequence[str]:
        return CYCLE_PHASE_ORDER


__all__ = [
    "CYCLE_EXECUTE_OUTCOMES",
    "CYCLE_PHASE_ORDER",
    "CyclePhase",
    "CycleStateMachine",
    "CycleTransition",
]
