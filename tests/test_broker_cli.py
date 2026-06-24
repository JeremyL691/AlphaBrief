"""CLI smoke tests for the ``alphabrief broker`` subcommand group.

The CLI proxies through the API when one is running and falls back to
the local BrokerReconStore otherwise. These tests run with
``ALPHABRIEF_DATA_DIR`` set so the local-fallback path is taken.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(
    args: list[str], *, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI as a subprocess.

    Uses the installed ``alphabrief`` entry point so we exercise the
    real Typer application graph, not ``python -m``. The PATH is
    inherited from the parent so the venv-installed script is found.
    """
    full_env = dict(os.environ)
    full_env.update(env)
    # Ensure the venv is on PATH so the `alphabrief` script resolves.
    venv_bin = str(Path(sys.executable).parent)
    if venv_bin not in full_env.get("PATH", "").split(":"):
        full_env["PATH"] = venv_bin + ":" + full_env.get("PATH", "")
    return subprocess.run(
        ["alphabrief", *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
        timeout=20,
    )


@pytest.fixture
def isolated_data_dir(tmp_path: Path) -> dict[str, str]:
    return {"ALPHABRIEF_DATA_DIR": str(tmp_path)}


def test_cli_help_lists_broker_subcommand() -> None:
    result = _run_cli(["broker", "--help"], env={})
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "reconcile" in combined
    assert "status" in combined
    assert "freeze" in combined
    assert "unfreeze" in combined
    # Phase 20 read-only live-read commands are locked into the CLI surface.
    assert "positions" in combined
    assert "account" in combined


def test_cli_broker_positions_requires_api(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    # Without a running API the CLI must refuse rather than fabricate data.
    result = _run_cli(["broker", "positions"], env=isolated_data_dir)
    assert result.returncode != 0
    assert "requires the API server to be running" in result.stderr


def test_cli_broker_account_requires_api(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    result = _run_cli(["broker", "account"], env=isolated_data_dir)
    assert result.returncode != 0
    assert "requires the API server to be running" in result.stderr


def test_cli_broker_status_empty_store(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    result = _run_cli(["broker", "status"], env=isolated_data_dir)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["latest_snapshot"] is None
    assert payload["open_freeze_count"] == 0


def test_cli_broker_reconcile_records_snapshot(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    result = _run_cli(["broker", "reconcile", "--scope", "eod"], env=isolated_data_dir)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["scope"] == "eod"
    assert payload["all_match"] is True


def test_cli_broker_reconcile_rejects_invalid_scope(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    result = _run_cli(
        ["broker", "reconcile", "--scope", "garbage"], env=isolated_data_dir
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "scope must be one of" in combined


def test_cli_broker_freeze_and_unfreeze(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    freeze = _run_cli(["broker", "freeze", "--reason", "test"], env=isolated_data_dir)
    assert freeze.returncode == 0, freeze.stderr
    # The CLI emits key: value lines for freeze (mirror risk_commands).
    assert "event_id:" in freeze.stdout
    event_id_line = next(
        line for line in freeze.stdout.splitlines() if line.startswith("event_id:")
    )
    event_id = event_id_line.split(":", 1)[1].strip()
    assert event_id

    status = _run_cli(["broker", "status"], env=isolated_data_dir)
    assert status.returncode == 0
    status_payload = json.loads(status.stdout)
    assert status_payload["open_freeze_count"] == 1

    unfreeze = _run_cli(
        ["broker", "unfreeze", event_id, "--reason", "manual ok"],
        env=isolated_data_dir,
    )
    assert unfreeze.returncode == 0, unfreeze.stderr
    cleared_line = next(
        line for line in unfreeze.stdout.splitlines() if line.startswith("cleared_at:")
    )
    assert cleared_line.split(":", 1)[1].strip()

    final = _run_cli(["broker", "status"], env=isolated_data_dir)
    assert final.returncode == 0
    final_payload = json.loads(final.stdout)
    assert final_payload["open_freeze_count"] == 0


def test_cli_broker_unfreeze_unknown_event_errors(
    tmp_path: Path, isolated_data_dir: dict[str, str]
) -> None:
    result = _run_cli(
        ["broker", "unfreeze", "missing-id", "--reason", "test"],
        env=isolated_data_dir,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "unknown freeze event_id" in combined
