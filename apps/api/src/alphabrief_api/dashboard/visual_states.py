"""Visual behavior fixture matrix (M14-W07).

Every interaction and visual fixture is declared for the Soft
dashboard across the eight page states and the four required
viewports, in light, dark, and reduced-motion modes.
``validate_visual_fixture_matrix`` is a deterministic completeness
check (REQ-UI-003, REQ-UI-008).
"""

from __future__ import annotations

from alphabrief_api.dashboard.shell import PAGE_STATES, VIEWPORTS
from pydantic import BaseModel, ConfigDict, Field

#: Visual modes every fixture must cover.
VISUAL_MODES: tuple[str, ...] = ("light", "dark", "reduced_motion")


class VisualFixture(BaseModel):
    """One declared visual fixture cell."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: str = Field(min_length=1)
    viewport: int = Field(ge=1)
    mode: str = Field(min_length=1)
    reference: str = Field(min_length=1)


class VisualFixtureMatrix(BaseModel):
    """The complete declared fixture matrix."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixtures: tuple[VisualFixture, ...]
    total: int


class VisualMatrixVerdict(BaseModel):
    """One deterministic matrix validation result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    issues: tuple[str, ...]


def visual_fixture_matrix() -> VisualFixtureMatrix:
    """The full (state x viewport x mode) fixture matrix.

    Every fixture references a deterministic state payload plus the
    shell CSS at that viewport and mode; nothing is invented here.
    """
    fixtures: list[VisualFixture] = []
    for state in PAGE_STATES:
        for viewport in VIEWPORTS:
            for mode in VISUAL_MODES:
                fixtures.append(
                    VisualFixture(
                        state=state,
                        viewport=viewport,
                        mode=mode,
                        reference=(
                            f"state:{state}:{mode}:{viewport}px"
                        ),
                    )
                )
    return VisualFixtureMatrix(
        fixtures=tuple(fixtures),
        total=len(fixtures),
    )


def validate_visual_fixture_matrix() -> VisualMatrixVerdict:
    """Deterministic completeness check over the fixture matrix."""
    issues: list[str] = []
    matrix = visual_fixture_matrix()
    expected = len(PAGE_STATES) * len(VIEWPORTS) * len(VISUAL_MODES)
    if matrix.total != expected:
        issues.append(
            f"matrix has {matrix.total} fixtures, expected {expected}"
        )
    seen: set[tuple[str, int, str]] = set()
    for fixture in matrix.fixtures:
        key = (fixture.state, fixture.viewport, fixture.mode)
        if key in seen:
            issues.append(f"duplicate fixture {key}")
        seen.add(key)
        if fixture.state not in PAGE_STATES:
            issues.append(f"unknown state {fixture.state!r}")
        if fixture.viewport not in VIEWPORTS:
            issues.append(f"unknown viewport {fixture.viewport}")
        if fixture.mode not in VISUAL_MODES:
            issues.append(f"unknown mode {fixture.mode!r}")
    return VisualMatrixVerdict(
        passed=not issues,
        issues=tuple(issues),
    )


__all__ = [
    "VISUAL_MODES",
    "VisualFixture",
    "VisualFixtureMatrix",
    "VisualMatrixVerdict",
    "validate_visual_fixture_matrix",
    "visual_fixture_matrix",
]
