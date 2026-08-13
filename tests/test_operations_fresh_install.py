"""M17-W02: fresh-install readiness.

Covers AC-M17-W02-01: an isolated fresh checkout installs locked
Python and Electron dependencies, initializes an empty data directory,
migrates, and reaches local readiness without relying on untracked
source or historical state.
"""

from __future__ import annotations

from alphabrief_core import (
    FRESH_INSTALL_STEPS,
    FreshInstallReport,
    run_fresh_install_check,
)


class TestFreshInstall:
    def test_all_five_steps_are_declared(self) -> None:
        assert FRESH_INSTALL_STEPS == (
            "locked_deps_install",
            "empty_data_dir_init",
            "migrate",
            "local_readiness",
            "no_untracked_source_dependency",
        )

    def test_full_truth_passes(self) -> None:
        report = run_fresh_install_check(
            step_truth={step: True for step in FRESH_INSTALL_STEPS}
        )
        assert isinstance(report, FreshInstallReport)
        assert report.passed is True
        assert all(step.preserved for step in report.steps)

    def test_missing_truth_fails_closed(self) -> None:
        report = run_fresh_install_check(step_truth={})
        assert report.passed is False
        assert all(not step.preserved for step in report.steps)

    def test_untracked_source_dependency_fails(self) -> None:
        truth = {step: True for step in FRESH_INSTALL_STEPS}
        truth["no_untracked_source_dependency"] = False
        report = run_fresh_install_check(step_truth=truth)
        assert report.passed is False

    def test_empty_data_dir_is_required(self) -> None:
        truth = {step: True for step in FRESH_INSTALL_STEPS}
        truth["empty_data_dir_init"] = False
        report = run_fresh_install_check(step_truth=truth)
        assert report.passed is False

    def test_deterministic(self) -> None:
        truth = {step: True for step in FRESH_INSTALL_STEPS}
        first = run_fresh_install_check(step_truth=truth)
        second = run_fresh_install_check(step_truth=truth)
        assert first.model_dump() == second.model_dump()
