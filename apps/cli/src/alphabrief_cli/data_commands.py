"""CLI subcommands for the data module."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from alphabrief_core import Bar
from alphabrief_data import (
    MarketDataLoadError,
    check_bar_quality,
    load_ohlcv_csv,
    load_ohlcv_parquet,
)

data_app = typer.Typer(help="Manage market data ingestion and quality checks.")


def _load_bars(
    file_path: Path, symbol: str, source: str, data_version: str
) -> list[Bar]:
    """Load bars from CSV or Parquet based on file extension."""
    suffix = file_path.suffix.lower()
    if suffix == ".parquet":
        return load_ohlcv_parquet(
            file_path,
            symbol=symbol,
            source=source,
            data_version=data_version,
        )
    return load_ohlcv_csv(
        file_path,
        symbol=symbol,
        source=source,
        data_version=data_version,
    )


@data_app.command("import")
def import_cmd(
    file: Path = typer.Option(..., "--file", help="Path to CSV or Parquet file."),
    symbol: str = typer.Option(..., "--symbol", help="Market symbol identifier."),
    source: str = typer.Option(..., "--source", help="Data source name."),
    data_version: str = typer.Option(
        ...,
        "--data-version",
        help="Data version tag (e.g. 'v1', '2024-q1').",
    ),
) -> None:
    """Import raw market data into the local AlphaBrief data directory."""
    try:
        bars = _load_bars(file, symbol, source, data_version)
    except MarketDataLoadError as exc:
        print(f"data import failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded {len(bars)} bars for {symbol} from {source} (v{data_version})")


@data_app.command("check")
def check_cmd(
    file: Path = typer.Option(..., "--file", help="Path to CSV or Parquet file."),
    symbol: str = typer.Option(..., "--symbol", help="Market symbol identifier."),
    source: str = typer.Option(..., "--source", help="Data source name."),
    data_version: str = typer.Option(
        ...,
        "--data-version",
        help="Data version tag (e.g. 'v1', '2024-q1').",
    ),
) -> None:
    """Run quality checks on a market data file."""
    try:
        bars = _load_bars(file, symbol, source, data_version)
        report = check_bar_quality(bars)
    except MarketDataLoadError as exc:
        print(f"data check failed: {exc}", file=sys.stderr)
        sys.exit(1)

    for issue in report.issues:
        ts = f" @ {issue.timestamp.isoformat()}" if issue.timestamp else ""
        print(f"[{issue.severity}] {issue.code}: {issue.message}{ts}")

    if report.passed:
        print("Quality: PASSED")
    else:
        print("Quality: FAILED")


__all__ = ["data_app"]
