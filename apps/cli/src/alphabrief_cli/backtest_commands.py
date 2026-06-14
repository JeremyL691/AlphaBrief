"""CLI subcommands for the backtest module."""

from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import typer
from alphabrief_backtest import VectorizedBacktester, write_backtest_report
from alphabrief_data import generate_basic_features, load_ohlcv_csv
from alphabrief_strategy import (
    MovingAverageTrendStrategy,
    StrategySpec,
)

backtest_app = typer.Typer(help="Run deterministic backtests on strategies.")


@backtest_app.command("run")
def run_cmd(
    data: Path = typer.Option(..., "--data", help="Path to OHLCV CSV file."),
    spec: Path = typer.Option(..., "--spec", help="Path to StrategySpec JSON file."),
    output: Path | None = typer.Option(
        None, "--output", help="Optional path to write the backtest report JSON."
    ),
    cash: str = typer.Option(
        "10000", "--cash", help="Initial cash as a decimal string."
    ),
) -> None:
    """Run a backtest for a given strategy spec and dataset."""
    try:
        initial_cash = Decimal(cash)
    except InvalidOperation as exc:
        print(f"error: invalid --cash value {cash!r}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        spec_payload = spec.read_text()
    except OSError as exc:
        print(f"error: could not read spec file {spec}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        strategy_spec = StrategySpec.model_validate_json(spec_payload)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {spec}: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"error: invalid StrategySpec in {spec}: {exc}", file=sys.stderr)
        sys.exit(1)

    symbol = strategy_spec.universe.symbols[0]

    try:
        bars = load_ohlcv_csv(
            data,
            symbol=symbol,
            source="local-csv",
            data_version="v1",
        )
    except (OSError, ValueError) as exc:
        print(f"error: could not load CSV {data}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        features = generate_basic_features(bars)
    except ValueError as exc:
        print(f"error: could not generate features: {exc}", file=sys.stderr)
        sys.exit(1)

    strategy = MovingAverageTrendStrategy()
    backtester = VectorizedBacktester(initial_cash=initial_cash)
    try:
        report = backtester.run(
            strategy, spec=strategy_spec, bars=bars, features=features
        )
    except Exception as exc:
        print(f"error: backtest run failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"strategy_id: {report.strategy_id}")
    print(f"symbol: {report.symbol}")
    print(f"initial_cash: {report.initial_cash}")
    print(f"final_value: {report.final_value}")
    print(f"total_return: {report.metrics.total_return}")
    print(f"trade_count: {report.metrics.trade_count}")
    print(f"win_rate: {report.metrics.win_rate}")

    if output is not None:
        try:
            write_backtest_report(report, output)
        except OSError as exc:
            print(f"error: could not write report to {output}: {exc}", file=sys.stderr)
            sys.exit(1)


__all__ = ["backtest_app"]
