"""CLI smoke tests for the ``alphabrief scheduler`` subcommand group.

The CLI proxies through the API when one is running and falls back to
the local ``HeartbeatStore`` / ``BrokerReconStore`` otherwise. These
tests run with ``ALPHABRIEF_DATA_DIR`` set so the local-fallback path
is taken. ``scheduler run`` is exercised in isolation with a
``subprocess.Popen`` + SIGINT pair to confirm the foreground process
honors the stop signal.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.operations.scheduler import HeartbeatStore


def _run_cli(
    args: list[str], *, env: dict[str, str], timeout: float = 20.0
) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI as a subprocess (installed entry point)."""
    full_env = dict(os.environ)
    full_env.update(env)
    venv_bin = str(Path(sys.executable).parent)
    if venv_bin not in full_env.get("PATH", "").split(":"):
        full_env["PATH"] = venv_bin + ":" + full_env.get("PATH", "")
    return subprocess.run(
        ["alphabrief", *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
        timeout=timeout,
    )


@pytest.fixture
def isolated_data_dir(tmp_path: Path) -> dict[str, str]:
    return {"ALPHABRIEF_DATA_DIR": str(tmp_path)}


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def test_cli_help_lists_scheduler_subcommand() -> None:
    result = _run_cli(["scheduler", "--help"], env={})
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    for cmd in ("status", "heartbeats", "alerts", "tasks", "freezes", "run"):
        assert cmd in combined


# ---------------------------------------------------------------------------
# status / heartbeats / alerts / tasks / freezes (offline)
# ---------------------------------------------------------------------------


def test_cli_status_command_offline_prints_counts(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    result = _run_cli(["scheduler", "status"], env=isolated_data_dir)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "heartbeat_count": 0,
        "open_freeze_count": 0,
        "alerts_total": 0,
        "running": False,
    }


def test_cli_heartbeats_command_offline_prints_empty(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    result = _run_cli(["scheduler", "heartbeats"], env=isolated_data_dir)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"heartbeats": []}


def test_cli_heartbeats_command_offline_reflects_local_store(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    store = HeartbeatStore(db_path=tmp_path / "alphabrief.db")
    store.record_run(task_name="reconcile", status="ok", error=None)
    store.close()

    result = _run_cli(["scheduler", "heartbeats"], env=isolated_data_dir)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["heartbeats"]) == 1
    assert payload["heartbeats"][0]["task_name"] == "reconcile"


def test_cli_alerts_command_offline_prints_empty(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    result = _run_cli(["scheduler", "alerts"], env=isolated_data_dir)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"alerts": []}


def test_cli_tasks_command_offline_returns_default_task_shape(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    result = _run_cli(["scheduler", "tasks"], env=isolated_data_dir)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["tasks"]) == 1
    task = payload["tasks"][0]
    assert task["name"] == "reconcile"
    assert task["interval_seconds"] == 300.0
    assert task["enabled"] is True


def test_cli_freezes_command_offline_lists_open_freeze(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    recon = BrokerReconStore(db_path=tmp_path / "alphabrief.db")
    recon.raise_freeze(reason="offline test", source="t")
    recon.close()

    result = _run_cli(["scheduler", "freezes"], env=isolated_data_dir)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["open_freezes"]) == 1
    assert payload["open_freezes"][0]["reason"] == "offline test"


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_cli_run_command_starts_and_stops_on_sigint(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    """``scheduler run`` should respond to SIGINT and exit 0.

    DuckDB is single-writer, so the parent test process cannot open
    the same DB while the scheduler child holds the lock. We wait a
    fixed window (long enough for one reconcile cycle) and then send
    SIGINT; the heartbeat-availability check is delegated to a
    separate CLI invocation (which also acquires the lock) issued
    *after* the scheduler has exited.
    """
    env = dict(os.environ)
    env.update(isolated_data_dir)
    env.setdefault("PATH", str(Path(sys.executable).parent) + ":" + env.get("PATH", ""))
    cmd = [
        "alphabrief",
        "scheduler",
        "run",
        "--reconcile-interval",
        "1.0",
        "--max-failures",
        "5",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    # Give the scheduler at least one full cycle to run.
    time.sleep(2.5)
    if proc.poll() is not None:
        stdout, stderr = proc.communicate()
        pytest.fail(
            f"scheduler exited early code={proc.returncode}: "
            f"stdout={stdout!r} stderr={stderr!r}"
        )
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("scheduler did not exit within 10s of SIGINT")
    assert proc.returncode == 0, (
        f"expected exit code 0 after SIGINT, got {proc.returncode}; "
        f"stderr={proc.stderr.read() if proc.stderr else ''}"
    )
    # Now the lock is released: confirm the heartbeat was persisted.
    check = _run_cli(
        ["scheduler", "heartbeats"],
        env=isolated_data_dir,
        timeout=10.0,
    )
    assert check.returncode == 0, check.stderr
    payload = json.loads(check.stdout)
    assert any(row["task_name"] == "reconcile" for row in payload["heartbeats"])


def test_cli_run_command_refuses_when_live_trading_unlocked(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    env = dict(isolated_data_dir)
    env["ALPHABRIEF_LIVE_TRADING_ENABLED"] = "true"
    result = _run_cli(["scheduler", "run"], env=env, timeout=10.0)
    assert result.returncode == 3
    combined = result.stdout + result.stderr
    assert "ALPHABRIEF_LIVE_TRADING_ENABLED" in combined
