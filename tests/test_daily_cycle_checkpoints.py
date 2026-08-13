"""M11-W01: durable cycle checkpoint persistence.

Covers the persisted compare-and-set checkpoint layer: transitions
survive store restarts, the transition log and the state projection stay
consistent, and resume points are correct at every boundary.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alphabrief_trader.cycle_state import CYCLE_PHASE_ORDER, CycleStateMachine
from alphabrief_trader.db_store import CycleStateStore


@pytest.fixture
def state_store(tmp_path: Path) -> Iterator[CycleStateStore]:
    store = CycleStateStore(db_path=tmp_path / "state.db")
    try:
        yield store
    finally:
        store.close()


def _run_full_cycle(machine: CycleStateMachine, cycle_id: str) -> None:
    assert machine.begin(cycle_id) is True
    current = "preflight"
    while current != "complete":
        nxt = CYCLE_PHASE_ORDER[CYCLE_PHASE_ORDER.index(current) + 1]
        outcome = "no_trade" if current == "execute" else None
        assert machine.advance(
            cycle_id,
            expected_phase=current,
            next_phase=nxt,
            input_hashes={"probe": current},
            output_ids={"out": current},
            outcome=outcome,
        ) is not None
        current = nxt


class TestCheckpointPersistence:
    def test_transitions_survive_store_restart(
        self, state_store: CycleStateStore, tmp_path: Path
    ) -> None:
        machine = CycleStateMachine(state_store)
        _run_full_cycle(machine, "cyc-1")
        assert len(machine.transitions("cyc-1")) == len(CYCLE_PHASE_ORDER)
        state_store.close()

        reopened = CycleStateStore(db_path=tmp_path / "state.db")
        try:
            machine2 = CycleStateMachine(reopened)
            transitions = machine2.transitions("cyc-1")
            assert len(transitions) == len(CYCLE_PHASE_ORDER)
            assert [t.phase for t in transitions] == list(CYCLE_PHASE_ORDER)
            assert machine2.is_complete("cyc-1") is True
            assert machine2.resume_phase("cyc-1") is None
            # The state projection survived with its outcome.
            state = machine2.state("cyc-1")
            assert state is not None
            assert state["outcome"] == "no_trade"
        finally:
            reopened.close()

    def test_begin_is_idempotent(
        self, state_store: CycleStateStore
    ) -> None:
        machine = CycleStateMachine(state_store)
        assert machine.begin("cyc-1") is True
        assert machine.begin("cyc-1") is False
        assert len(machine.transitions("cyc-1")) == 1

    def test_transition_log_matches_state_projection(
        self, state_store: CycleStateStore
    ) -> None:
        machine = CycleStateMachine(state_store)
        _run_full_cycle(machine, "cyc-1")
        state = machine.state("cyc-1")
        transitions = machine.transitions("cyc-1")
        assert state is not None
        assert state["phase"] == "complete"
        assert state["phase_order"] == len(CYCLE_PHASE_ORDER) - 1
        # The last committed transition's phase matches the projection.
        assert transitions[-1].phase == "complete"
        assert transitions[-1].prior_phase == "report"

    def test_resume_points_are_exact_at_every_boundary(
        self, state_store: CycleStateStore
    ) -> None:
        machine = CycleStateMachine(state_store)
        assert machine.begin("cyc-1") is True
        assert machine.resume_phase("cyc-1") == "preflight"
        current = "preflight"
        while current != "complete":
            nxt = CYCLE_PHASE_ORDER[CYCLE_PHASE_ORDER.index(current) + 1]
            outcome = "no_trade" if current == "execute" else None
            assert machine.advance(
                "cyc-1",
                expected_phase=current,
                next_phase=nxt,
                outcome=outcome,
            ) is not None
            if nxt != "complete":
                assert machine.resume_phase("cyc-1") == nxt
            current = nxt
        assert machine.resume_phase("cyc-1") is None

    def test_partial_cycle_resumes_at_last_committed_phase(
        self, state_store: CycleStateStore
    ) -> None:
        machine = CycleStateMachine(state_store)
        assert machine.begin("cyc-1") is True
        assert machine.advance(
            "cyc-1", expected_phase="preflight", next_phase="ingest"
        ) is not None
        assert machine.advance(
            "cyc-1", expected_phase="ingest", next_phase="snapshot"
        ) is not None
        # Crash: resume must point at the snapshot phase (not yet done).
        assert machine.resume_phase("cyc-1") == "snapshot"
        assert len(machine.transitions("cyc-1")) == 3  # begin + 2 advances

    def test_stale_writer_cannot_advance_after_restart(
        self, state_store: CycleStateStore, tmp_path: Path
    ) -> None:
        machine = CycleStateMachine(state_store)
        assert machine.begin("cyc-1") is True
        assert machine.advance(
            "cyc-1", expected_phase="preflight", next_phase="ingest"
        ) is not None
        state_store.close()

        reopened = CycleStateStore(db_path=tmp_path / "state.db")
        try:
            machine2 = CycleStateMachine(reopened)
            # A writer still expecting preflight is stale after restart.
            assert (
                machine2.advance(
                    "cyc-1",
                    expected_phase="preflight",
                    next_phase="snapshot",
                )
                is None
            )
            assert machine2.resume_phase("cyc-1") == "ingest"
        finally:
            reopened.close()

    def test_transitions_are_append_only(
        self, state_store: CycleStateStore
    ) -> None:
        machine = CycleStateMachine(state_store)
        _run_full_cycle(machine, "cyc-1")
        before = machine.transitions("cyc-1")
        # A stale writer's rejected advance must not append anything.
        assert (
            machine.advance(
                "cyc-1", expected_phase="preflight", next_phase="ingest"
            )
            is None
        )
        assert machine.transitions("cyc-1") == before
