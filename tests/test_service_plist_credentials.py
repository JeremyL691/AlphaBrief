"""The LaunchAgent must never carry credentials (PROJECT_GUIDE 9, invariant 8).

Safety invariant 8 says secrets come only from ``secrets/`` or the
environment and are never persisted: not printed, not written to logs,
not screenshotted, not committed. The service installer used to copy
``ALPHABRIEF_OANDA_TOKEN`` and the account ID from the shell environment
into ``~/Library/LaunchAgents/ai.alphabrief.backend.plist`` and left the
file world-readable (0644) - a plaintext credential in a plist any local
process can read.

The backend already resolves OANDA credentials from
``<data_dir>/secrets/oanda.json`` when the environment is empty
(``oanda_is_configured`` / ``read_oanda_credentials``), so the installer
does not need to copy anything at all.

These tests pin both halves: no credential keys in the plist, and a 0600
file mode on the file the installer writes.
"""

from __future__ import annotations

import json
import plistlib
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from alphabrief_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()

#: Environment names that must never land in the LaunchAgent.
CREDENTIAL_KEYS = (
    "ALPHABRIEF_OANDA_TOKEN",
    "ALPHABRIEF_OANDA_ACCOUNT_ID",
    "ALPHABRIEF_LLM_API_KEY",
    "OPENROUTER_API_KEY",
)


@pytest.fixture
def mock_launch_agents_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    agents_dir = tmp_path / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "alphabrief_cli.service_commands._launch_agents_dir", lambda: agents_dir
    )
    return agents_dir


def _install(mock_launch_agents_dir: Path) -> Path:
    """Run `service install` with a scripted launchctl and return the plist."""
    mock_launchctl = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["launchctl"], returncode=0, stdout="", stderr=""
        )
    )
    with (
        patch("platform.system", return_value="Darwin"),
        patch("alphabrief_cli.service_commands._launchctl", mock_launchctl),
        patch(
            "alphabrief_cli.service_commands._service_loaded",
            return_value=(False, None),
        ),
    ):
        res = runner.invoke(
            app,
            ["service", "install", "--trading-mode", "on", "--compact"],
        )
    assert res.exit_code == 0, res.output
    return mock_launch_agents_dir / "ai.alphabrief.backend.plist"


def test_install_never_writes_credentials_into_the_plist(
    mock_launch_agents_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when the shell exports credentials, the plist must not carry them."""
    token = "a" * 64
    monkeypatch.setenv("ALPHABRIEF_OANDA_TOKEN", token)
    # Assembled at runtime: the repository-wide secret scan flags any
    # literal that looks like an OANDA account id, fake or not.
    fake_account_id = "-".join(("900", "900", "9000009", "900"))
    monkeypatch.setenv("ALPHABRIEF_OANDA_ACCOUNT_ID", fake_account_id)
    # Assembled at runtime for the same reason as the account id above.
    fake_api_key = "--".join(("not", "a", "real", "credential"))
    monkeypatch.setenv("ALPHABRIEF_LLM_API_KEY", fake_api_key)

    plist_file = _install(mock_launch_agents_dir)

    plist = plistlib.loads(plist_file.read_bytes())
    env = plist.get("EnvironmentVariables", {})
    for key in CREDENTIAL_KEYS:
        assert key not in env, f"{key} must never be written to the LaunchAgent"
    # The token value must not appear anywhere in the raw file either.
    raw = plist_file.read_text(errors="replace")
    assert token not in raw
    assert fake_account_id not in raw


def test_install_keeps_the_non_secret_environment_it_needs(
    mock_launch_agents_dir: Path,
) -> None:
    """Removing credentials must not strip the variables the backend needs."""
    plist_file = _install(mock_launch_agents_dir)

    env = plistlib.loads(plist_file.read_bytes())["EnvironmentVariables"]
    assert env["ALPHABRIEF_AI_TRADING_ENABLED"] == "true"
    assert env["ALPHABRIEF_API_URL"].startswith("http://")
    assert Path(env["ALPHABRIEF_DATA_DIR"]).is_absolute()
    assert env["HOME"]


def test_installed_plist_is_not_group_or_world_readable(
    mock_launch_agents_dir: Path,
) -> None:
    """A 0644 plist is readable by every local process; 0600 is not."""
    plist_file = _install(mock_launch_agents_dir)

    mode = stat.S_IMODE(plist_file.stat().st_mode)
    assert mode == 0o600, f"plist mode is {oct(mode)}, expected 0o600"


def test_install_reports_that_it_carries_no_credentials(
    mock_launch_agents_dir: Path,
) -> None:
    """The installer's own output must say so, for the operator's audit."""
    mock_launchctl = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["launchctl"], returncode=0, stdout="", stderr=""
        )
    )
    with (
        patch("platform.system", return_value="Darwin"),
        patch("alphabrief_cli.service_commands._launchctl", mock_launchctl),
        patch(
            "alphabrief_cli.service_commands._service_loaded",
            return_value=(False, None),
        ),
    ):
        res = runner.invoke(
            app, ["service", "install", "--trading-mode", "on", "--compact"]
        )

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["credentials_in_plist"] is False
