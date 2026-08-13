"""M14-W06: 30-Day Observation workspace.

Covers AC-M14-W06-01: Observation displays qualified day, weekly gate,
incident, blocker, and evidence completeness from one runtime
authority.
"""

from __future__ import annotations

from alphabrief_api.dashboard.operations import build_observation_view


def _gates() -> list[dict[str, object]]:
    return [
        {"week": "2026-W33", "passed": True, "detail": "all checks ok"},
        {"week": "2026-W32", "passed": False,
         "detail": "reconciliation diff unresolved"},
    ]


class TestObservationView:
    def test_displays_qualified_days_and_completeness(self) -> None:
        view = build_observation_view(
            {"qualified_days": 12, "evidence_completeness": "0.4"},
            weekly_gates=_gates(),
        )
        assert view.qualified_days == 12
        assert view.required_days == 30
        assert view.evidence_completeness == "0.4"

    def test_weekly_gates_are_carried_with_detail(self) -> None:
        view = build_observation_view(weekly_gates=_gates())
        assert len(view.weekly_gates) == 2
        assert view.weekly_gates[0].week == "2026-W33"
        assert view.weekly_gates[0].passed is True
        assert view.weekly_gates[1].passed is False
        assert view.weekly_gates[1].detail == (
            "reconciliation diff unresolved"
        )

    def test_incidents_and_blockers_are_never_hidden(self) -> None:
        view = build_observation_view(
            incidents=["cycle failed 2026-08-12"],
            blockers=["freeze active"],
        )
        assert view.incidents == ("cycle failed 2026-08-12",)
        assert view.blockers == ("freeze active",)

    def test_missing_truth_is_explicit_null(self) -> None:
        view = build_observation_view(None)
        assert view.qualified_days is None
        assert view.weekly_gates == ()
        assert view.incidents == ()
        assert view.blockers == ()

    def test_deterministic(self) -> None:
        first = build_observation_view(
            {"qualified_days": 12}, weekly_gates=_gates()
        )
        second = build_observation_view(
            {"qualified_days": 12}, weekly_gates=_gates()
        )
        assert first.model_dump() == second.model_dump()
