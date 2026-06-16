"""Tests for the backtest CLI commands.

These tests cover the ``alphabrief backtest run`` subcommand for both the
legacy engine and the env-v2 engine.  Legacy tests use a real CSV file on
disk; env-v2 tests exercise the validation gate that requires --symbols.
"""

from __future__ import annotations

import json
from pathlib import Path

from alphabrief_cli.backtest_commands import backtest_app
from typer.testing import CliRunner

runner = CliRunner()

CSV_HEADER = "timestamp,open,high,low,close,volume\n"
CSV_ROW_1 = "2026-06-12T09:30:00,100,110,95,105,1\n"
CSV_ROW_2 = "2026-06-12T09:31:00,105,112,101,111,2\n"

SPEC_JSON = json.dumps(
    {
        "strategy_id": "test_ma",
        "name": "Test MA",
        "version": "0.1.0",
        "universe": {"symbols": ["TEST"]},
        "timeframe": "1min",
        "entry": {"condition": "close > close_sma_3"},
        "exit": {"condition": "close <= close_sma_3"},
        "risk": {"max_position_pct": "1.0"},
        "costs": {"fee_bps": "5", "slippage_bps": "5"},
        "evaluation": {
            "train_period": {"start": "2024-01-01", "end": "2024-12-31"},
            "test_period": {"start": "2025-01-01", "end": "2025-12-31"},
        },
    }
)


def _write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _write_spec(path: Path, spec: str) -> Path:
    path.write_text(spec, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# env-v2 validation
# ---------------------------------------------------------------------------


def test_cli_backtest_run_env_v2_missing_symbols() -> None:
    """``--engine env-v2`` without ``--symbols`` must exit with an error."""
    result = runner.invoke(
        backtest_app,
        ["--engine", "env-v2"],
    )
    assert result.exit_code != 0
    assert "--symbols is required" in result.output


# ---------------------------------------------------------------------------
# legacy engine regressions
# ---------------------------------------------------------------------------


def test_cli_backtest_run_legacy_still_works(tmp_path: Path) -> None:
    """Default legacy engine with ``--data`` and ``--spec`` produces a report."""
    csv_path = _write_csv(
        tmp_path / "btc.csv", CSV_HEADER + CSV_ROW_1 + CSV_ROW_2
    )
    spec_path = _write_spec(tmp_path / "spec.json", SPEC_JSON)

    result = runner.invoke(
        backtest_app,
        [
            "--data",
            str(csv_path),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "strategy_id:" in result.output
    assert "symbol:" in result.output
    assert "initial_cash:" in result.output