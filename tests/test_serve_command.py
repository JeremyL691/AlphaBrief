"""Tests for the AlphaBrief API serve CLI command."""

from __future__ import annotations

from alphabrief_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def test_serve_command_registered() -> None:
    result = runner.invoke(app, ["serve", "--help"])

    assert result.exit_code == 0
    assert "serve" in result.output
