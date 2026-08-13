"""M14-W06: Scheduler workspace.

Covers AC-M14-W06-01: Scheduler displays leader, running, heartbeat,
last and next run, and phase from one runtime authority.
"""

from __future__ import annotations

from alphabrief_api.dashboard.operations import build_scheduler_view


def _truth() -> dict[str, object]:
    return {
        "leader_id": "leader-1",
        "running": True,
        "heartbeat_at": "2026-08-14T00:00:00+00:00",
        "last_run_at": "2026-08-14T00:00:00+00:00",
        "next_run_at": "2026-08-15T00:00:00+00:00",
        "phase": "reconcile",
    }


class TestSchedulerView:
    def test_displays_runtime_truth_fields(self) -> None:
        view = build_scheduler_view(_truth())
        assert view.leader_id == "leader-1"
        assert view.running is True
        assert view.heartbeat_at == "2026-08-14T00:00:00+00:00"
        assert view.last_run_at == "2026-08-14T00:00:00+00:00"
        assert view.next_run_at == "2026-08-15T00:00:00+00:00"
        assert view.phase == "reconcile"

    def test_missing_truth_is_explicit_null(self) -> None:
        view = build_scheduler_view(None)
        assert view.leader_id is None
        assert view.running is None
        assert view.phase is None

    def test_unknown_phase_is_preserved_verbatim(self) -> None:
        view = build_scheduler_view({"phase": "unknown-phase"})
        assert view.phase == "unknown-phase"

    def test_deterministic(self) -> None:
        first = build_scheduler_view(_truth())
        second = build_scheduler_view(_truth())
        assert first.model_dump() == second.model_dump()
