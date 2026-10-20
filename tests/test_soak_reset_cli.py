"""`soak reset` must exist and be honest about what it does.

The soak store has had ``record_reset`` since S9, but no CLI reached it.
That left the operator unable to start a new Day 0 after a failed run:
``soak start`` returns the currently active run unchanged, so a backend
that already has an active run can never be re-baselined without
hand-editing the database - exactly the kind of unlogged mutation the
soak integrity rules exist to prevent.

The command must therefore:

* refuse while the resident backend owns the writer (a direct write would
  race it, invariant 12);
* require a reason, because the reset history is the audit trail;
* supersede the old run and open a new one, keeping the old row intact;
* never accept a backdated start, same as ``soak start``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from alphabrief_cli.main import app
from alphabrief_trader.soak_store import SoakStore
from typer.testing import CliRunner

runner = CliRunner()


def _runs(db: Path) -> list[tuple[int, str, str | None, int | None]]:
    store = SoakStore(db_path=db)
    try:
        return [
            (r.run_index, r.state, r.reason, r.superseded_by)
            for r in store.list_runs()
        ]
    finally:
        store.close()


def test_reset_requires_a_reason(tmp_path: Path) -> None:
    """An unexplained reset is indistinguishable from a fabricated one."""
    db = tmp_path / "test.duckdb"
    with patch("alphabrief_core.paths.db_path", return_value=db):
        res = runner.invoke(app, ["soak", "reset"])

    assert res.exit_code != 0


def test_reset_refuses_while_the_backend_owns_the_writer(
    tmp_path: Path,
) -> None:
    """Invariant 12: one writer per account, and the daemon is it."""
    db = tmp_path / "test.duckdb"
    with (
        patch("alphabrief_core.paths.db_path", return_value=db),
        patch("alphabrief_cli.api_client.is_api_running", return_value=True),
    ):
        res = runner.invoke(app, ["soak", "reset", "--reason", "test reset"])

    assert res.exit_code == 3, res.stdout
    assert "backend is running" in (res.stdout + res.stderr)


def test_reset_supersedes_the_active_run_and_keeps_history(
    tmp_path: Path,
) -> None:
    db = tmp_path / "test.duckdb"
    with patch("alphabrief_core.paths.db_path", return_value=db):
        first = json.loads(
            runner.invoke(app, ["soak", "start"]).stdout
        )["run"]
        assert first["run_index"] == 0

        with patch("alphabrief_cli.api_client.is_api_running", return_value=False):
            res = runner.invoke(
                app,
                ["soak", "reset", "--reason", "operator re-baseline"],
            )

    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["action"] == "reset"
    assert payload["previous_run"]["run_index"] == 0
    assert payload["run"]["run_index"] == 1
    assert payload["run"]["state"] == "active"

    runs = {
        index: (state, reason, superseded)
        for index, state, reason, superseded in _runs(db)
    }
    assert runs[0][0] == "reset"
    assert runs[0][1] == "operator re-baseline"
    assert runs[0][2] == 1
    assert runs[1][0] == "active"


def test_reset_keeps_the_backdating_guard(tmp_path: Path) -> None:
    """Days may only come from real elapsed time (invariant 11)."""
    db = tmp_path / "test.duckdb"
    with (
        patch("alphabrief_core.paths.db_path", return_value=db),
        patch("alphabrief_cli.api_client.is_api_running", return_value=False),
    ):
        res = runner.invoke(
            app,
            [
                "soak",
                "reset",
                "--reason",
                "backdated attempt",
                "--started-at",
                "2026-01-01T00:00:00+00:00",
            ],
        )

    assert res.exit_code == 1
    payload = json.loads(res.stdout)
    assert payload["action"] == "refused"


def test_reset_withdraws_the_current_qualified_progress(tmp_path: Path) -> None:
    """After a reset the status must show a fresh run, not the old days."""
    db = tmp_path / "test.duckdb"
    with (
        patch("alphabrief_core.paths.db_path", return_value=db),
        patch("alphabrief_cli.api_client.is_api_running", return_value=False),
    ):
        runner.invoke(app, ["soak", "start"])
        reset = runner.invoke(app, ["soak", "reset", "--reason", "re-baseline"])
        assert reset.exit_code == 0, reset.stdout

        status = json.loads(runner.invoke(app, ["soak", "status"]).stdout)

    assert status["run_index"] == 1
    assert status["state"] == "active"
    assert status["qualified_days"] == 0
    # The superseded run stays in the reset history for the audit trail.
    assert any(r["run_index"] == 0 for r in status["resets"])


def test_reset_without_an_active_run_is_refused(tmp_path: Path) -> None:
    """There is nothing to supersede; silently creating a run would hide that."""
    db = tmp_path / "test.duckdb"
    with (
        patch("alphabrief_core.paths.db_path", return_value=db),
        patch("alphabrief_cli.api_client.is_api_running", return_value=False),
    ):
        res = runner.invoke(app, ["soak", "reset", "--reason", "nothing here"])

    assert res.exit_code == 1
    assert json.loads(res.stdout)["action"] == "refused"
    assert _runs(db) == []
