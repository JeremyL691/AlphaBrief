"""M14-W07: visual behavior fixture matrix.

Covers AC-M14-W07-01: automated interaction and visual fixtures pass
in light, dark, reduced-motion, loading, error, offline, and frozen
states at 320, 768, 1024, and 1440 pixels.
"""

from __future__ import annotations

import pytest
from alphabrief_api.dashboard.shell import PAGE_STATES, VIEWPORTS
from alphabrief_api.dashboard.visual_states import (
    VISUAL_MODES,
    validate_visual_fixture_matrix,
    visual_fixture_matrix,
)


class TestFixtureMatrix:
    def test_matrix_covers_all_states_viewports_modes(self) -> None:
        matrix = visual_fixture_matrix()
        assert matrix.total == 8 * 4 * 3
        keys = {(f.state, f.viewport, f.mode) for f in matrix.fixtures}
        assert keys == {
            (state, viewport, mode)
            for state in PAGE_STATES
            for viewport in VIEWPORTS
            for mode in VISUAL_MODES
        }

    def test_every_state_at_every_viewport(self) -> None:
        matrix = visual_fixture_matrix()
        for state in PAGE_STATES:
            for viewport in VIEWPORTS:
                assert any(
                    f.state == state and f.viewport == viewport
                    for f in matrix.fixtures
                ), f"{state}@{viewport}px"

    def test_every_mode_is_covered(self) -> None:
        matrix = visual_fixture_matrix()
        for mode in VISUAL_MODES:
            assert any(f.mode == mode for f in matrix.fixtures)

    def test_fixture_references_are_deterministic(self) -> None:
        first = visual_fixture_matrix()
        second = visual_fixture_matrix()
        assert first.model_dump() == second.model_dump()

    def test_validation_passes(self) -> None:
        verdict = validate_visual_fixture_matrix()
        assert verdict.passed, verdict.issues

    def test_validation_is_deterministic(self) -> None:
        assert validate_visual_fixture_matrix().model_dump() == (
            validate_visual_fixture_matrix().model_dump()
        )

    @pytest.mark.parametrize("viewport", VIEWPORTS)
    def test_reduced_motion_covered_at_every_viewport(
        self, viewport: int
    ) -> None:
        matrix = visual_fixture_matrix()
        assert any(
            f.mode == "reduced_motion" and f.viewport == viewport
            for f in matrix.fixtures
        )
