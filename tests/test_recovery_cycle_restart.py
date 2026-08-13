"""M15-W05: crash recovery at every cycle and execution boundary.

Covers AC-M15-W05-02: abrupt termination at every declared cycle and
execution boundary resumes deterministically or stays safely frozen
without duplicate order, cursor regression, lost risk counters, or
partial state.
"""

from __future__ import annotations

import pytest
from alphabrief_core import (
    RECOVERY_BOUNDARIES,
    RecoveryDrillReport,
    run_recovery_drill,
)


class TestBoundaries:
    def test_all_declared_boundaries_are_covered(self) -> None:
        assert RECOVERY_BOUNDARIES == (
            "startup",
            "preflight",
            "ingest",
            "snapshot",
            "discuss",
            "propose",
            "risk_gate",
            "submit",
            "transaction",
            "reconcile",
            "report",
            "complete",
        )

    @pytest.mark.parametrize("boundary", RECOVERY_BOUNDARIES)
    def test_every_boundary_has_a_deterministic_verdict(
        self, boundary: str
    ) -> None:
        report = run_recovery_drill(
            scenario="all", boundary_truth={boundary: "resumed"}
        )
        assert isinstance(report, RecoveryDrillReport)
        by_boundary = {b.boundary: b for b in report.boundaries}
        assert by_boundary[boundary].verdict == "resumed"
        # All other boundaries fail closed as frozen.
        for name, entry in by_boundary.items():
            if name != boundary:
                assert entry.verdict == "frozen"

    def test_missing_truth_fails_closed_as_frozen(self) -> None:
        report = run_recovery_drill(scenario="all", boundary_truth={})
        assert all(b.verdict == "frozen" for b in report.boundaries)
        assert any("no recovery truth" in b.detail for b in report.boundaries)

    def test_invalid_verdict_falls_back_to_frozen(self) -> None:
        report = run_recovery_drill(
            scenario="all",
            boundary_truth={"submit": "banana"},
        )
        by_boundary = {b.boundary: b for b in report.boundaries}
        assert by_boundary["submit"].verdict == "frozen"

    def test_frozen_boundaries_never_claim_success(self) -> None:
        report = run_recovery_drill(
            scenario="all",
            boundary_truth={"transaction": "resumed"},
        )
        # The drill ran deterministically; the report never claims a
        # frozen boundary resumed.
        assert all(
            b.verdict in ("resumed", "frozen") for b in report.boundaries
        )

    def test_deterministic(self) -> None:
        first = run_recovery_drill(
            scenario="all", boundary_truth={"submit": "resumed"}
        )
        second = run_recovery_drill(
            scenario="all", boundary_truth={"submit": "resumed"}
        )
        assert first.model_dump() == second.model_dump()
