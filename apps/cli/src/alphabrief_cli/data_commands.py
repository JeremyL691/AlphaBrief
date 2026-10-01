"""CLI subcommands for the data module."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import typer
from alphabrief_core import Bar
from alphabrief_data import (
    MarketDataLoadError,
    MarketDataProviderError,
    check_bar_quality,
    load_ohlcv_csv,
    load_ohlcv_parquet,
)

data_app = typer.Typer(help="Manage market data ingestion and quality checks.")


@data_app.command("catalog")
def catalog_cmd(
    search: str | None = typer.Option(  # noqa: B008
        None,
        "--search",
        help="Case-insensitive name or display-name search.",
    ),
    category: str | None = typer.Option(  # noqa: B008
        None,
        "--category",
        help="Filter by taxonomy category (e.g. CURRENCY, INDEX_CFD, OTHER_CFD).",
    ),
    active_only: bool = typer.Option(  # noqa: B008
        False,
        "--active-only",
        help="Only instruments active in the current projection.",
    ),
    page: int = typer.Option(  # noqa: B008
        1,
        "--page",
        min=1,
        help="Page number (1-based).",
    ),
    page_size: int = typer.Option(  # noqa: B008
        100,
        "--page-size",
        min=1,
        max=10000,
        help="Page size.",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
        help="Pretty-print JSON output.",
    ),
) -> None:
    """Query the persisted account instrument catalog.

    Read-only: the same deterministic query function the API uses, so
    totals, filters, metadata, taxonomy, active state, catalog version,
    and freshness are identical for the same query.
    """
    import json

    from alphabrief_api.db.instrument_catalog import InstrumentCatalogStore

    result = InstrumentCatalogStore().query(
        search=search,
        category=category,
        active_only=active_only,
        page=page,
        page_size=page_size,
    )
    json.dump(
        result.model_dump(mode="json"),
        sys.stdout,
        indent=2 if pretty else None,
        sort_keys=True,
    )
    sys.stdout.write("\n")

ProviderSource = Literal["yahoo", "binance", "alphavantage"]


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



__all__ = ["data_app"]


def _record_quote_samples(client: Any, instruments: tuple[str, ...]) -> int:
    """Append one spread sample per instrument from a live pricing call."""
    from alphabrief_data.quote_samples import QuoteSample, QuoteSampleStore
    from alphabrief_execution.broker.oanda.pricing import (
        PricingRequest,
        fetch_pricing,
    )

    batch = fetch_pricing(
        client,
        request=PricingRequest(symbols=instruments),
        request_id="quote-samples",
    )
    now = datetime.now(UTC)
    store = QuoteSampleStore()
    recorded = 0
    try:
        for price in batch.prices:
            if not price.bids or not price.asks:
                continue
            bid = price.bids[0].price
            ask = price.asks[0].price
            if store.record(
                QuoteSample(
                    symbol=price.symbol,
                    captured_at=now,
                    bid=bid,
                    ask=ask,
                    spread=ask - bid,
                    mid=(bid + ask) / Decimal(2),
                )
            ):
                recorded += 1
    finally:
        store.close()
    return recorded


@data_app.command("sync-oanda")
def sync_oanda_cmd(
    instrument: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--instrument",
        help="OANDA instrument (repeatable). Defaults to the FX majors.",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Sync OANDA practice candles and quotes into the local database.

    Read-only against the practice account. Missing credentials fail
    closed: nothing is written and the command exits non-zero.
    """
    import json

    from alphabrief_api.db.market_data import MarketDataStore
    from alphabrief_execution.broker.oanda.market_sync import sync_market_data

    default_instruments = ("EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD")
    instruments = tuple(instrument or ()) or default_instruments

    from alphabrief_execution.broker.oanda.client import OandaHttpClient
    from alphabrief_execution.broker.oanda.config import (
        load_oanda_paper_config,
        read_oanda_credentials,
    )
    from alphabrief_execution.broker.runtime import oanda_is_configured

    if not oanda_is_configured():
        print(
            "error: OANDA practice credentials are required (set "
            "ALPHABRIEF_OANDA_TOKEN and ALPHABRIEF_OANDA_ACCOUNT_ID)",
            file=sys.stderr,
        )
        sys.exit(1)

    config_path = Path(
        os.environ.get("ALPHABRIEF_OANDA_CONFIG", "config/oanda_paper.yaml")
    )
    try:
        token, account_id = read_oanda_credentials()
        client = OandaHttpClient(
            config=load_oanda_paper_config(config_path),
            token=token,
            account_id=account_id,
        )
    except (OSError, ValueError) as exc:
        print(f"error: OANDA configuration unusable: {exc}", file=sys.stderr)
        sys.exit(1)

    store = MarketDataStore()
    samples = 0
    try:
        report = sync_market_data(client, instruments=instruments, store=store)
        # Every sync also records real quote samples: rule 4 compares the
        # live spread against the same-period median of these rows.
        samples = _record_quote_samples(client, instruments)
    finally:
        store.close()

    payload = report.to_dict()
    payload["spread_samples_recorded"] = samples
    json.dump(payload, sys.stdout, indent=2 if pretty else None, default=str)
    sys.stdout.write("\n")
    if report.errors:
        sys.exit(1)
