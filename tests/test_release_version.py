"""Release version consistency and the CLI ``--version`` contract.

The version must agree across ``pyproject.toml``,
``alphabrief_core/version.py``, and ``electron/package.json``;
``scripts/build_release.sh`` refuses to build otherwise, and this test
keeps CI enforcing the same invariant.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from alphabrief_cli.main import app
from alphabrief_core.version import __version__
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]

runner = CliRunner()


def test_declared_versions_agree() -> None:
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    electron = json.loads(
        (ROOT / "electron" / "package.json").read_text(encoding="utf-8")
    )
    assert pyproject["project"]["version"] == __version__
    assert electron["version"] == __version__


def test_cli_version_flag_prints_release_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
    assert "AlphaBrief" in result.output
