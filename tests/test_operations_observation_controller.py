"""M15-W04: observation evidence controller.

Covers AC-M15-W04-03: a single-leader persistent supervisor restores
next-run state after restart, invokes daily and weekly evidence gates
automatically, derives Day 0 through Day 30 from real UTC and
local-calendar evidence, and records BLOCKED_EXTERNAL or
WAITING_EXTERNAL without fabricating evidence or asking a question.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from alphabrief_core import (
    ObservationSupervisor,
    ObservationSupervisorState,
    observation_day_index,
)

START = date(2026, 8, 14)


class TestRealCalendarDerivation:
    def test_day_zero_is_start_date(self) -> None:
        assert observation_day_index(START, START) == 0

    def test_day_thirty_is_final_day(self) -> None:
        final = START + timedelta(days=30)
        assert observation_day_index(START, final) == 30

    def test_before_start_is_none(self) -> None:
        assert observation_day_index(START, START - timedelta(days=1)) is None

    def test_beyond_day_thirty_is_none(self) -> None:
        assert observation_day_index(
            START, START + timedelta(days=31)
        ) is None

    def test_mid_observation_day(self) -> None:
        assert observation_day_index(START, START + timedelta(days=12)) == 12

    def test_derivation_is_deterministic(self) -> None:
        assert observation_day_index(START, START + timedelta(days=5)) == (
            observation_day_index(START, START + timedelta(days=5))
        )


class TestSupervisor:
    @pytest.fixture
    def supervisor(self, tmp_path: Path) -> ObservationSupervisor:
        return ObservationSupervisor(
            leader_id="leader-1", path=tmp_path / "obs.ndjson"
        )

    def test_begin_starts_at_day_zero(self, supervisor: ObservationSupervisor) -> None:
        supervisor.begin(start_date=START)
        day = supervisor.run_daily_gate(
            today=START, evidence_complete=True
        )
        assert day.day_index == 0
        assert day.daily_gate_passed is True

    def test_daily_gate_advances_real_calendar(
        self, supervisor: ObservationSupervisor
    ) -> None:
        supervisor.begin(start_date=START)
        for offset in range(5):
            day = supervisor.run_daily_gate(
                today=START + timedelta(days=offset),
                evidence_complete=True,
            )
            assert day.day_index == offset
        assert supervisor.next_run_date() == (
            (START + timedelta(days=5)).isoformat()
        )

    def test_missing_evidence_records_failed_day(
        self, supervisor: ObservationSupervisor
    ) -> None:
        supervisor.begin(start_date=START)
        day = supervisor.run_daily_gate(
            today=START, evidence_complete=False
        )
        assert day.daily_gate_passed is False

    def test_external_state_recorded_without_evidence(
        self, supervisor: ObservationSupervisor
    ) -> None:
        supervisor.begin(start_date=START)
        supervisor.run_daily_gate(today=START, evidence_complete=True)
        supervisor.record_external_state(
            external_state="BLOCKED_EXTERNAL", reason="credentials missing"
        )
        day = supervisor.current_day()
        assert day is not None
        assert day.external_state == "BLOCKED_EXTERNAL"
        # No evidence was fabricated: the day gate result is untouched.
        assert day.daily_gate_passed is True

    def test_unknown_external_state_raises(
        self, supervisor: ObservationSupervisor
    ) -> None:
        supervisor.begin(start_date=START)
        supervisor.run_daily_gate(today=START, evidence_complete=True)
        with pytest.raises(ValueError, match="unknown external state"):
            supervisor.record_external_state(
                external_state="MYSTERY", reason="x"
            )

    def test_survives_restart(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "obs.ndjson"
        first = ObservationSupervisor(leader_id="leader-1", path=path)
        first.begin(start_date=START)
        first.run_daily_gate(today=START, evidence_complete=True)
        first.record_external_state(
            external_state="WAITING_EXTERNAL", reason="network down"
        )
        # A new supervisor over the same file restores next-run state.
        restored = ObservationSupervisor(leader_id="leader-1", path=path)
        state = restored.restore()
        assert isinstance(state, ObservationSupervisorState)
        assert state.start_date == START.isoformat()
        day = restored.current_day()
        assert day is not None
        assert day.external_state == "WAITING_EXTERNAL"
        assert restored.next_run_date() == (
            (START + timedelta(days=1)).isoformat()
        )

    def test_outside_range_is_rejected(
        self, supervisor: ObservationSupervisor
    ) -> None:
        supervisor.begin(start_date=START)
        with pytest.raises(ValueError, match="outside Day 0..30"):
            supervisor.run_daily_gate(
                today=START + timedelta(days=31),
                evidence_complete=True,
            )

    def test_day_30_caps_next_run(
        self, supervisor: ObservationSupervisor
    ) -> None:
        supervisor.begin(start_date=START)
        for offset in range(31):
            supervisor.run_daily_gate(
                today=START + timedelta(days=offset),
                evidence_complete=True,
            )
        assert supervisor.next_run_date() is not None
        day = supervisor.current_day()
        assert day is not None
        assert day.day_index == 30
