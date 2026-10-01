"""Tests for the single-instance lock and ``alphabrief doctor`` (GUIDE 4.1/4.9)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alphabrief_cli.doctor_commands import (
    CheckResult,
    DoctorReport,
    check_data_dir,
    check_disk_space,
    check_market_data,
    check_quote_samples,
    check_reconciliation,
    check_single_instance_lock,
    check_sleep_assertion,
    run_checks,
)
from alphabrief_core import RuntimeLock, RuntimeLockError, lock_status
from alphabrief_core import paths as _paths


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))


class TestRuntimeLock:
    def test_second_acquire_is_refused_immediately(self, tmp_path: Path) -> None:
        lock = RuntimeLock(tmp_path / "runtime.lock")
        with lock:
            with pytest.raises(RuntimeLockError, match="Could not set lock"):
                RuntimeLock(tmp_path / "runtime.lock").acquire()

    def test_lock_records_the_holder(self, tmp_path: Path) -> None:
        path = tmp_path / "runtime.lock"
        with RuntimeLock(path):
            status = lock_status(path)

        assert status is not None
        assert status["pid"].isdigit()
        assert status["started_at"]

    def test_lock_is_free_after_release(self, tmp_path: Path) -> None:
        path = tmp_path / "runtime.lock"
        lock = RuntimeLock(path)
        lock.acquire()
        lock.release()

        assert lock.held is False
        assert lock_status(path) is None

    def test_missing_lock_file_reports_free(self, tmp_path: Path) -> None:
        assert lock_status(tmp_path / "absent.lock") is None


class TestChecks:
    def test_data_dir_is_writable(self, tmp_path: Path) -> None:
        result = check_data_dir()

        assert result.status == "PASS"
        assert str(tmp_path) in result.detail

    def test_free_lock_is_a_pass_unless_a_daemon_is_expected(self) -> None:
        assert check_single_instance_lock().status == "PASS"
        assert check_single_instance_lock(expect_daemon=True).status == "WARN"

    def test_held_lock_warns_outside_a_daemon_run(self, tmp_path: Path) -> None:
        lock = RuntimeLock(_paths.runtime_lock_path())
        lock.acquire()
        try:
            assert check_single_instance_lock().status == "WARN"
            assert check_single_instance_lock(expect_daemon=True).status == "PASS"
        finally:
            lock.release()

    def test_disk_space_reports_free_bytes(self) -> None:
        result = check_disk_space()

        assert result.status in {"PASS", "WARN", "FAIL"}
        assert "MiB free" in result.detail

    def test_sleep_assertion_is_never_a_failure(self) -> None:
        # The check reads the system settings and never modifies them, so
        # an enabled sleep is the operator's decision (WARN), not a FAIL.
        result = check_sleep_assertion()

        assert result.status in {"PASS", "WARN"}
        assert result.check_id == "sleep_assertion"

    def test_market_data_fails_closed_without_bars(self) -> None:
        result = check_market_data(("EUR_USD",))

        assert result.status == "FAIL"
        assert "no stored bars" in result.detail

    def test_quote_samples_warn_until_history_exists(self) -> None:
        result = check_quote_samples(("EUR_USD",))

        assert result.status == "WARN"
        assert "rule 4 fails closed" in result.detail

    def test_reconciliation_warns_without_a_snapshot(self) -> None:
        result = check_reconciliation()

        assert result.status == "WARN"
        assert "no reconciliation snapshot" in result.detail


class TestReport:
    def test_report_summary_and_exit_semantics(self) -> None:
        report = DoctorReport(
            checked_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
        report.results.extend(
            [
                CheckResult("a", "PASS", "fine"),
                CheckResult("b", "WARN", "watch"),
            ]
        )

        assert report.ok is True
        assert "1 PASS, 1 WARN, 0 FAIL" in report.summary()
        assert report.to_dict()["ok"] is True

    def test_offline_run_has_no_network_checks(self) -> None:
        report = run_checks(symbols=("EUR_USD",), include_network=False)

        check_ids = {result.check_id for result in report.results}
        assert "oanda_read_only" not in check_ids
        assert "model_channel" not in check_ids
        assert "news_sources" not in check_ids
        assert "data_dir" in check_ids
        # Exit code semantics: only FAILs make the report unhealthy.
        assert report.ok is (not report.failed)
