"""Tests for the CLI environment guard (PROJECT_GUIDE 4.3).

A relative data directory is a configuration error: it must be reported
as one actionable line with exit code 2, never as a traceback, and
``--help`` must keep working regardless of the environment.
"""

from __future__ import annotations

import json
from pathlib import Path

from alphabrief_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def test_relative_data_dir_exits_with_a_clear_message(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["model", "status"],
        env={"ALPHABRIEF_DATA_DIR": "data/local"},
    )

    assert result.exit_code == 2
    assert "must be an absolute path" in result.output
    assert "Traceback" not in result.output


def test_absolute_data_dir_is_accepted(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["model", "status", "--compact"],
        env={"ALPHABRIEF_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_help_works_even_with_a_relative_data_dir() -> None:
    result = runner.invoke(
        app, ["--help"], env={"ALPHABRIEF_DATA_DIR": "data/local"}
    )

    assert result.exit_code == 0
    assert "Usage" in result.output


def test_home_variable_also_requires_an_absolute_path(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["model", "status"],
        env={"ALPHABRIEF_HOME": "relative/home"},
    )

    assert result.exit_code == 2
    assert "must be an absolute path" in result.output
