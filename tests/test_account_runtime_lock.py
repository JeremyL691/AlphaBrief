"""Trading ownership must survive data-directory changes and crash recovery."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import typer
from alphabrief_cli import scheduler_commands
from alphabrief_core import (
    RuntimeLock,
    RuntimeLockError,
    account_runtime_lock,
    lock_status,
    paths,
)


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "_DEFAULT_HOME", tmp_path / "application-support")
    monkeypatch.delenv("ALPHABRIEF_HOME", raising=False)
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path / "data-a"))
    monkeypatch.setenv("ALPHABRIEF_OANDA_TOKEN", "test-token")
    monkeypatch.setenv("ALPHABRIEF_OANDA_ACCOUNT_ID", "test-practice-account")
    monkeypatch.setenv("ALPHABRIEF_TRADING_MODE", "on")


def test_same_account_conflicts_across_data_directory_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, directory = scheduler_commands._acquire_runtime_ownership()
    with first:
        monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path / "data-b"))
        with pytest.raises(typer.Exit) as exc:
            scheduler_commands._acquire_runtime_ownership()
        assert exc.value.exit_code == 2
        assert directory.held
        # A failed account claim releases its already-acquired directory lock.
        with RuntimeLock():
            pass
    second, _ = scheduler_commands._acquire_runtime_ownership()
    second.close()


def test_different_accounts_have_independent_ownership() -> None:
    with account_runtime_lock("account-a"), account_runtime_lock("account-b"):
        with pytest.raises(RuntimeLockError):
            account_runtime_lock("account-a").acquire()


def test_lock_path_and_metadata_do_not_disclose_account() -> None:
    account = "sensitive-test-account"
    lock = account_runtime_lock(account)
    with lock:
        assert account not in str(lock.path)
        assert account not in lock.path.read_text()
        assert lock_status(lock.path) is not None
    assert lock_status(lock.path) is None


def test_empty_account_is_rejected() -> None:
    with pytest.raises(paths.PathConfigError, match="account is required"):
        account_runtime_lock("  ")


def test_missing_credentials_prevent_trading_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN")
    with pytest.raises(typer.Exit) as exc:
        scheduler_commands._acquire_runtime_ownership()
    assert exc.value.exit_code == 2
    assert lock_status() is None
    assert not (paths._DEFAULT_HOME / "account-locks").exists()


def test_trading_off_does_not_claim_account_or_require_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with account_runtime_lock("test-practice-account"):
        monkeypatch.setenv("ALPHABRIEF_TRADING_MODE", "off")
        monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN")
        ownership, directory = scheduler_commands._acquire_runtime_ownership()
        with ownership:
            assert directory.held
    assert not directory.held


def test_kernel_releases_account_ownership_after_kill(tmp_path: Path) -> None:
    # Child uses the same fixed support root, with no broker or model calls.
    script = """
import sys
from pathlib import Path
from alphabrief_core import account_runtime_lock, paths
paths._DEFAULT_HOME = Path(sys.argv[1])
lock = account_runtime_lock('crash-account')
lock.acquire()
print('locked', flush=True)
sys.stdin.read()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(paths._DEFAULT_HOME)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=os.environ.copy(),
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(RuntimeLockError):
            account_runtime_lock("crash-account").acquire()
        child.kill()
        child.wait(timeout=10)
        with account_runtime_lock("crash-account"):
            pass
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)


@pytest.mark.parametrize("entrypoint", ["runtime", "scheduler"])
def test_cli_refuses_account_conflict_before_starting_services(
    entrypoint: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_cli.main import app
    from typer.testing import CliRunner

    command = "run" if entrypoint == "runtime" else "scheduler"
    with account_runtime_lock("test-practice-account"):
        result = CliRunner().invoke(app, [command, "run"])
    assert result.exit_code == 2
    assert "Could not set lock" in result.output
    assert "test-practice-account" not in result.output
    assert lock_status() is None


def test_runtime_constructor_failure_releases_both_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_cli import run_commands
    from alphabrief_cli.main import app
    from typer.testing import CliRunner

    def fail_runtime(**kwargs: object) -> None:
        raise RuntimeError("constructor failed")

    monkeypatch.setattr(run_commands, "Runtime", fail_runtime)
    result = CliRunner().invoke(app, ["run", "run"])
    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert str(result.exception) == "constructor failed"
    assert lock_status() is None
    with account_runtime_lock("test-practice-account"):
        pass


def test_trading_off_close_out_cannot_call_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_cli.run_commands import close_out_once
    from alphabrief_execution.broker import runtime

    def unexpected_client() -> None:
        pytest.fail("trading-off runtime attempted a broker call")

    monkeypatch.setenv("ALPHABRIEF_TRADING_MODE", "off")
    monkeypatch.setattr(runtime, "build_oanda_paper_client", unexpected_client)
    assert close_out_once(reason="friday_close") == 0


def test_trading_on_close_out_fails_closed_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_cli.run_commands import close_out_once
    from alphabrief_execution.broker.errors import BrokerAuthError

    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN")
    with pytest.raises(BrokerAuthError, match="credentials are required"):
        close_out_once(reason="friday_close")
