"""Tests for macOS desktop notifications (PROJECT_GUIDE S5)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from alphabrief_core.notifications import notify_macos


def test_notify_macos_on_non_darwin() -> None:
    with patch("platform.system", return_value="Linux"):
        assert notify_macos("Hello Linux") is False


def test_notify_macos_no_osascript() -> None:
    with (
        patch("platform.system", return_value="Darwin"),
        patch("shutil.which", return_value=None),
    ):
        assert notify_macos("Hello") is False


def test_notify_macos_success() -> None:
    mock_run = MagicMock(
        return_value=subprocess.CompletedProcess(args=["osascript"], returncode=0)
    )
    with (
        patch("platform.system", return_value="Darwin"),
        patch("shutil.which", return_value="/usr/bin/osascript"),
        patch("subprocess.run", mock_run),
    ):
        ok = notify_macos(
            "Order filled", title="AlphaBrief", subtitle="EUR_USD", sound="Ping"
        )
        assert ok is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/osascript"
        assert cmd[1] == "-e"
        assert 'display notification "Order filled"' in cmd[2]
        assert 'with title "AlphaBrief"' in cmd[2]
        assert 'subtitle "EUR_USD"' in cmd[2]
        assert 'sound name "Ping"' in cmd[2]


def test_notify_macos_handles_subprocess_error() -> None:
    with (
        patch("platform.system", return_value="Darwin"),
        patch("shutil.which", return_value="/usr/bin/osascript"),
        patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=5),
        ),
    ):
        assert notify_macos("Timeout") is False
