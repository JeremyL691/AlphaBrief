"""Tests for soak CLI commands (alphabrief soak, alphabrief report soak)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from alphabrief_cli.main import app
from alphabrief_trader.soak_evaluator import SoakStatus
from alphabrief_trader.soak_report import SoakReportData
from typer.testing import CliRunner

runner = CliRunner()


def test_cli_soak_status_not_started(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"
    with patch("alphabrief_core.paths.db_path", return_value=db):
        res = runner.invoke(app, ["soak", "status"])
        assert res.exit_code == 0
        data = json.loads(res.stdout)
        assert data["soak_started"] is False
        assert data["qualified_days"] == 0
        assert data["target_days"] == 14


def test_cli_soak_start_and_status(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"
    with (
        patch("alphabrief_core.paths.db_path", return_value=db),
        patch("alphabrief_cli.api_client.is_api_running", return_value=False),
    ):
        res_start = runner.invoke(app, ["soak", "start"])
        assert res_start.exit_code == 0
        start_payload = json.loads(res_start.stdout)
        assert start_payload["action"] == "started"
        assert start_payload["run"]["run_index"] == 0
        assert start_payload["run"]["state"] == "active"

        # Now check soak status
        res_status = runner.invoke(app, ["soak", "status"])
        assert res_status.exit_code == 0
        status_payload = json.loads(res_status.stdout)
        assert status_payload["soak_started"] is True
        assert status_payload["run_index"] == 0


def test_cli_report_soak(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"
    out_file = tmp_path / "my-soak-report.md"

    with (
        patch("alphabrief_core.paths.db_path", return_value=db),
        patch("alphabrief_cli.api_client.is_api_running", return_value=False),
    ):
        # Start soak so there's an active run
        runner.invoke(app, ["soak", "start"])

        res = runner.invoke(app, ["report", "soak", "--out-file", str(out_file)])
        assert res.exit_code == 0
        payload = json.loads(res.stdout)
        assert payload["final"] is False
        assert payload["markdown"] == str(out_file)
        assert out_file.is_file()
        content = out_file.read_text(encoding="utf-8")
        assert "# AlphaBrief v" in content
        assert "## Period & Qualification" in content


def test_cli_report_soak_final_refuses_an_incomplete_soak(tmp_path: Path) -> None:
    """The final report is a release artifact: incomplete soak fails loudly."""
    db = tmp_path / "test.duckdb"

    with (
        patch("alphabrief_core.paths.db_path", return_value=db),
        patch("alphabrief_cli.api_client.is_api_running", return_value=False),
        patch("alphabrief_trader.soak_report.project_root", return_value=tmp_path),
    ):
        # Start soak
        runner.invoke(app, ["soak", "start"])

        res = runner.invoke(app, ["report", "soak", "--final"])
        assert res.exit_code == 1
        payload = json.loads(res.stdout)
        assert payload["final"] is True
        assert "qualified days" in payload["error"]
        assert not (tmp_path / "reports").exists()


def test_cli_report_soak_final_writes_when_complete(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"

    complete = SoakStatus(
        soak_started=True,
        run_index=0,
        started_at=datetime(2026, 10, 4, 4, 0, tzinfo=UTC),
        state="completed",
        qualified_days=14,
        extension_days=0,
        target_days=14,
        is_complete=True,
        days=[],
        extensions=[],
        resets=[],
    )
    data = SoakReportData(
        status=complete,
        generated_at=datetime(2026, 10, 18, 4, 0, tzinfo=UTC),
        masked_account_id="...0001",
        equity_metrics={},
        order_metrics={},
        risk_metrics={},
        model_metrics={},
        shadow_metrics={},
        safety_metrics={"invariants": []},
        hotfixes=[],
        version="1.0.0",
    )

    with (
        patch("alphabrief_core.paths.db_path", return_value=db),
        patch("alphabrief_cli.api_client.is_api_running", return_value=False),
        patch("alphabrief_trader.soak_report.project_root", return_value=tmp_path),
        patch(
            "alphabrief_trader.soak_report.generate_soak_report_data",
            return_value=data,
        ),
    ):
        res = runner.invoke(app, ["report", "soak", "--final"])
        assert res.exit_code == 0
        payload = json.loads(res.stdout)
        assert payload["final"] is True
        assert Path(payload["markdown"]).is_file()
        assert Path(payload["json"]).is_file()
