"""Tests for alphabrief service commands (PROJECT_GUIDE S5)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from alphabrief_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def mock_launch_agents_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    agents_dir = tmp_path / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "alphabrief_cli.service_commands._launch_agents_dir", lambda: agents_dir
    )
    return agents_dir


def test_service_status_uninstalled(mock_launch_agents_dir: Path) -> None:
    with patch("platform.system", return_value="Darwin"):
        res = runner.invoke(app, ["service", "status", "--compact"])
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert data["label"] == "ai.alphabrief.backend"
        assert data["installed"] is False
        assert data["loaded"] is False


def test_service_install_and_uninstall(mock_launch_agents_dir: Path) -> None:
    mock_launchctl = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["launchctl"],
            returncode=0,
            stdout="12345\t0\tai.alphabrief.backend\n",
            stderr="",
        )
    )

    with (
        patch("platform.system", return_value="Darwin"),
        patch("alphabrief_cli.service_commands._launchctl", mock_launchctl),
        patch(
            "alphabrief_cli.service_commands._service_loaded",
            return_value=(True, 12345),
        ),
    ):
        # Install
        res_install = runner.invoke(
            app,
            [
                "service",
                "install",
                "--trading-mode",
                "off",
                "--port",
                "8123",
                "--compact",
            ],
        )
        assert res_install.exit_code == 0, res_install.output
        install_data = json.loads(res_install.output)
        assert install_data["installed"] is True
        assert install_data["loaded"] is True
        assert install_data["port"] == 8123

        plist_file = mock_launch_agents_dir / "ai.alphabrief.backend.plist"
        assert plist_file.exists()

        # Status
        res_status = runner.invoke(app, ["service", "status", "--compact"])
        assert res_status.exit_code == 0
        status_data = json.loads(res_status.output)
        assert status_data["installed"] is True
        assert status_data["loaded"] is True
        assert status_data["pid"] == 12345

        # Uninstall
        res_uninstall = runner.invoke(app, ["service", "uninstall", "--compact"])
        assert res_uninstall.exit_code == 0
        uninstall_data = json.loads(res_uninstall.output)
        assert uninstall_data["installed"] is False
        assert not plist_file.exists()


def test_service_start_and_stop(mock_launch_agents_dir: Path) -> None:
    plist_file = mock_launch_agents_dir / "ai.alphabrief.backend.plist"
    plist_file.write_text("<plist></plist>")

    mock_launchctl = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["launchctl"], returncode=0, stdout="", stderr=""
        )
    )

    with (
        patch("platform.system", return_value="Darwin"),
        patch("alphabrief_cli.service_commands._launchctl", mock_launchctl),
        patch(
            "alphabrief_cli.service_commands._service_loaded", return_value=(True, 9999)
        ),
    ):
        res_start = runner.invoke(app, ["service", "start", "--compact"])
        assert res_start.exit_code == 0
        assert json.loads(res_start.output)["started"] is True

        res_stop = runner.invoke(app, ["service", "stop", "--compact"])
        assert res_stop.exit_code == 0
        assert json.loads(res_stop.output)["stopped"] is True
