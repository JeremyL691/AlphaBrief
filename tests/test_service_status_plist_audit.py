"""`service status` must surface an unsafe already-installed plist.

An operator who upgrades the CLI does not automatically rewrite the
plist that is already loaded in launchctl. If that older plist carries a
plaintext OANDA token or is world readable, nothing in the new code fixes
it until someone reinstalls. The status command therefore audits the
installed file and says so, instead of reporting a green "installed".
"""

from __future__ import annotations

import json
import os
import plistlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from alphabrief_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def agents_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "LaunchAgents"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "alphabrief_cli.service_commands._launch_agents_dir", lambda: directory
    )
    return directory


def _write_plist(directory: Path, env: dict[str, str], mode: int) -> Path:
    target = directory / "ai.alphabrief.backend.plist"
    target.write_bytes(
        plistlib.dumps({"Label": "ai.alphabrief.backend", "EnvironmentVariables": env})
    )
    os.chmod(target, mode)
    return target


def _status() -> dict[str, Any]:
    with (
        patch("platform.system", return_value="Darwin"),
        patch(
            "alphabrief_cli.service_commands._service_loaded",
            return_value=(False, None),
        ),
    ):
        res = runner.invoke(app, ["service", "status", "--compact"])
    assert res.exit_code == 0, res.output
    payload: dict[str, Any] = json.loads(res.output)
    return payload


def test_status_flags_a_plist_that_still_holds_credentials(
    agents_dir: Path,
) -> None:
    _write_plist(
        agents_dir,
        {"ALPHABRIEF_OANDA_TOKEN": "a" * 64, "PATH": "/usr/bin"},
        mode=0o644,
    )

    audit = _status()["plist_audit"]

    assert audit["credential_keys"] == ["ALPHABRIEF_OANDA_TOKEN"]
    assert audit["world_readable"] is True
    assert audit["mode"] == "0o644"


def test_status_reports_a_clean_plist_as_clean(agents_dir: Path) -> None:
    _write_plist(agents_dir, {"PATH": "/usr/bin"}, mode=0o600)

    audit = _status()["plist_audit"]

    assert audit["credential_keys"] == []
    assert audit["world_readable"] is False
    assert audit["mode"] == "0o600"


def test_status_has_no_audit_when_nothing_is_installed(agents_dir: Path) -> None:
    status = _status()

    assert status["installed"] is False
    assert status["plist_audit"] is None


def test_audit_never_echoes_a_credential_value(agents_dir: Path) -> None:
    """The audit names the key, never its value (invariant 8)."""
    token = "b" * 64
    _write_plist(agents_dir, {"ALPHABRIEF_OANDA_TOKEN": token}, mode=0o600)

    raw = json.dumps(_status())

    assert token not in raw
    assert "ALPHABRIEF_OANDA_TOKEN" in raw
