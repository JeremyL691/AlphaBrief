"""Tests for the paper trading CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from alphabrief_cli.paper_commands import paper_app  # type: ignore[import-not-found]
from typer.testing import CliRunner

runner = CliRunner()


def _make_csv(path: Path, symbol: str = "BTC-USD") -> None:
    lines = [
        "timestamp,open,high,low,close,volume",
        "2026-06-14T10:00:00+00:00,100,105,95,100,1000",
        "2026-06-14T11:00:00+00:00,101,106,96,101,1100",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _make_spec(path: Path, symbol: str = "BTC-USD") -> None:
    spec = {
        "strategy_id": "test-strat",
        "name": "Test Strategy",
        "version": "1.0.0",
        "universe": {"symbols": [symbol]},
        "timeframe": "1h",
        "entry": {"condition": "close > open"},
        "exit": {"condition": "close < open"},
        "risk": {
            "max_position_pct": "0.5",
            "stop_loss": "5%",
        },
        "costs": {
            "fee_bps": "10",
            "slippage_bps": "20",
        },
        "evaluation": {
            "train_period": {
                "start": "2026-01-01",
                "end": "2026-03-31",
            },
            "test_period": {
                "start": "2026-04-01",
                "end": "2026-06-30",
            },
        },
    }
    path.write_text(json.dumps(spec), encoding="utf-8")


def test_paper_status_prints_placeholder() -> None:
    result = runner.invoke(paper_app, ["status"])
    assert result.exit_code == 0
    assert "Paper portfolio status not yet persisted" in result.output


def test_paper_run_success(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    spec_path = tmp_path / "spec.json"
    _make_csv(csv_path)
    _make_spec(spec_path)

    result = runner.invoke(
        paper_app,
        [
            "run",
            "--data",
            str(csv_path),
            "--spec",
            str(spec_path),
            "--price",
            "100",
        ],
    )
    assert result.exit_code == 0
    assert "Symbol: BTC-USD" in result.output
    assert "Side: buy" in result.output
    assert "Quantity: 1" in result.output
    assert "Portfolio Cash:" in result.output
    assert "Portfolio Position (BTC-USD): 1" in result.output


def test_paper_run_missing_data_option() -> None:
    result = runner.invoke(paper_app, ["run", "--spec", "foo.json"])
    assert result.exit_code != 0


def test_paper_run_missing_spec_option() -> None:
    result = runner.invoke(paper_app, ["run", "--data", "foo.csv"])
    assert result.exit_code != 0


def test_paper_run_invalid_json_spec(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    spec_path = tmp_path / "spec.json"
    _make_csv(csv_path)
    spec_path.write_text("not json", encoding="utf-8")

    result = runner.invoke(
        paper_app,
        [
            "run",
            "--data",
            str(csv_path),
            "--spec",
            str(spec_path),
            "--price",
            "100",
        ],
    )
    assert result.exit_code == 1
    assert "invalid JSON" in result.output


def test_paper_run_invalid_strategy_spec(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    spec_path = tmp_path / "spec.json"
    _make_csv(csv_path)
    spec_path.write_text(json.dumps({"bad": "spec"}), encoding="utf-8")

    result = runner.invoke(
        paper_app,
        [
            "run",
            "--data",
            str(csv_path),
            "--spec",
            str(spec_path),
            "--price",
            "100",
        ],
    )
    assert result.exit_code == 1
    assert "invalid strategy spec" in result.output


def test_paper_run_invalid_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    spec_path = tmp_path / "spec.json"
    csv_path.write_text("bad,header\n1,2\n", encoding="utf-8")
    _make_spec(spec_path)

    result = runner.invoke(
        paper_app,
        [
            "run",
            "--data",
            str(csv_path),
            "--spec",
            str(spec_path),
            "--price",
            "100",
        ],
    )
    assert result.exit_code == 1
    assert "failed to load market data" in result.output


def test_paper_run_invalid_price(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    spec_path = tmp_path / "spec.json"
    _make_csv(csv_path)
    _make_spec(spec_path)

    result = runner.invoke(
        paper_app,
        [
            "run",
            "--data",
            str(csv_path),
            "--spec",
            str(spec_path),
            "--price",
            "abc",
        ],
    )
    assert result.exit_code == 1
    assert "invalid price value" in result.output
