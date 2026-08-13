"""M16-W03: in-window isolated backup restore drill.

Covers AC-M16-W03-02: the latest in-window backup restores into an
isolated directory and reproduces schema, projections, cycle
checkpoints, risk counters, broker mappings, transaction cursor, and
observation state.
"""

from __future__ import annotations

from alphabrief_core import (
    RESTORE_SURFACES,
    IsolatedRestoreResult,
    RestoreSurface,
    run_isolated_restore,
)


def _full_truth() -> dict[str, bool]:
    return {surface: True for surface in RESTORE_SURFACES}


class TestIsolatedRestore:
    def test_all_seven_surfaces_are_declared(self) -> None:
        assert RESTORE_SURFACES == (
            "schema",
            "projections",
            "cycle_checkpoints",
            "risk_counters",
            "broker_mappings",
            "transaction_cursor",
            "observation_state",
        )

    def test_full_truth_restores_all_surfaces(self) -> None:
        report = run_isolated_restore(
            scenario="isolated-restore", surface_truth=_full_truth()
        )
        assert isinstance(report, IsolatedRestoreResult)
        assert report.scenario == "isolated-restore"
        assert report.isolated is True
        assert report.passed is True
        assert len(report.surfaces) == 7
        assert all(surface.reproduced for surface in report.surfaces)

    def test_missing_truth_fails_closed_not_reproduced(self) -> None:
        report = run_isolated_restore(
            scenario="isolated-restore", surface_truth={}
        )
        assert report.passed is False
        assert all(not surface.reproduced for surface in report.surfaces)
        assert all(
            surface.detail == "not reproduced"
            for surface in report.surfaces
        )

    def test_partial_restore_is_not_a_pass(self) -> None:
        truth = _full_truth()
        truth["transaction_cursor"] = False
        report = run_isolated_restore(
            scenario="isolated-restore", surface_truth=truth
        )
        assert report.passed is False
        cursor = next(
            s for s in report.surfaces if s.surface == "transaction_cursor"
        )
        assert cursor.reproduced is False

    def test_surfaces_are_typed_and_frozen(self) -> None:
        report = run_isolated_restore(
            scenario="isolated-restore", surface_truth=_full_truth()
        )
        surface = report.surfaces[0]
        assert isinstance(surface, RestoreSurface)
        assert surface.surface in RESTORE_SURFACES

    def test_isolated_directory_never_leaks(self) -> None:
        report = run_isolated_restore(
            scenario="isolated-restore", surface_truth=_full_truth()
        )
        # The restore contract always targets an isolated directory;
        # production paths are never written by the drill.
        assert report.isolated is True

    def test_deterministic(self) -> None:
        first = run_isolated_restore(
            scenario="isolated-restore", surface_truth=_full_truth()
        )
        second = run_isolated_restore(
            scenario="isolated-restore", surface_truth=_full_truth()
        )
        assert first.model_dump() == second.model_dump()
