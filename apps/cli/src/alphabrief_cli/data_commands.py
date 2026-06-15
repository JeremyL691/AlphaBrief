"""CLI subcommands for the data module."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import typer
from alphabrief_core import Bar
from alphabrief_data import (
    BinanceProvider,
    MarketDataLoadError,
    MarketDataProvider,
    MarketDataProviderError,
    YahooFinanceProvider,
    check_bar_quality,
    load_ohlcv_csv,
    load_ohlcv_parquet,
)

data_app = typer.Typer(help="Manage market data ingestion and quality checks.")

ProviderSource = Literal["yahoo", "binance"]


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


def _build_provider(source: str) -> MarketDataProvider:
    """Build a market data provider for the given *source* name.

    Exposed as a module-level helper so tests can verify provider
    selection without invoking the full CLI command.
    """
    if source == "yahoo":
        return YahooFinanceProvider()
    if source == "binance":
        return BinanceProvider()
    raise MarketDataProviderError(
        f"data fetch: unknown source {source!r}; expected 'yahoo' or 'binance'",
        code="invalid_source",
    )


def _parse_iso_date(value: str, *, field_name: str) -> datetime:
    """Parse an ISO-8601 date or datetime string into a UTC datetime.

    Accepts either ``YYYY-MM-DD`` (interpreted as midnight UTC) or a
    full ISO-8601 timestamp. Naive inputs are anchored to UTC; aware
    inputs are converted to UTC.
    """
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise MarketDataProviderError(
            f"data fetch: invalid {field_name} {value!r}: {exc}",
            code="invalid_date_range",
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


@data_app.command("fetch")
def fetch_cmd(
    source: str = typer.Option(
        ...,
        "--source",
        help="Market data source: 'yahoo' or 'binance'.",
    ),
    symbol: str = typer.Option(..., "--symbol", help="Market symbol identifier."),
    start: str = typer.Option(
        ...,
        "--start",
        help="Start date or datetime (ISO-8601).",
    ),
    end: str = typer.Option(
        ...,
        "--end",
        help="End date or datetime (ISO-8601, exclusive).",
    ),
    interval: str = typer.Option(
        "1d",
        "--interval",
        help=(
            "Bar interval. Yahoo: 1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo. "
            "Binance: 1m, 3m, 5m, 15m, 30m, 1h, 1d, 1w, 1M."
        ),
    ),
    data_version: str = typer.Option(
        "fetch-v1",
        "--data-version",
        help="Data version tag stored alongside the bars.",
    ),
) -> None:
    """Download OHLCV bars from a free public data provider and persist them.

    Bars are written to the AlphaBrief DuckDB store under
    ``ALPHABRIEF_DATA_DIR/alphabrief.db``. The same symbol can be
    re-fetched; existing rows for ``(symbol, timestamp)`` pairs are
    replaced in place.
    """
    from alphabrief_api.db.market_data import MarketDataStore

    try:
        provider = _build_provider(source)
        start_dt = _parse_iso_date(start, field_name="--start")
        end_dt = _parse_iso_date(end, field_name="--end")
    except MarketDataProviderError as exc:
        print(f"data fetch failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        bars = provider.fetch_ohlcv(
            symbol=symbol, start=start_dt, end=end_dt, interval=interval
        )
    except MarketDataProviderError as exc:
        print(f"data fetch failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not bars:
        print(
            f"data fetch: provider {provider.provider_name!r} returned "
            f"0 bars for {symbol} in [{start}, {end}) at interval "
            f"{interval!r}.",
            file=sys.stderr,
        )
        sys.exit(1)

    store = MarketDataStore()
    try:
        inserted = store.insert_bars(
            bars, source=provider.provider_name, data_version=data_version
        )
    finally:
        store.close()

    print(
        f"Fetched and stored {inserted} bars for {symbol} from "
        f"{provider.provider_name} (v{data_version}) "
        f"interval={interval} range=[{start}, {end})"
    )


__all__ = ["data_app"]
