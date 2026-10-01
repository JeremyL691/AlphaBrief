"""Sync OANDA practice candles and quotes into the local store.

The market data in v1 comes from the same practice account that trades:
``GET /v3/accounts/{id}/instruments/{instrument}/candles`` for the
decision timeframes and ``GET /v3/accounts/{id}/pricing`` for the live
quote snapshot. Both are read-only.

The module is transport-agnostic: it takes an
:class:`~alphabrief_execution.broker.oanda.client.OandaHttpClient` and a
``store`` implementing ``insert_bars`` / ``record_quote`` so the same
code serves the CLI, the backend scheduler, and tests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from alphabrief_core import Bar

from alphabrief_execution.broker.oanda.candles import (
    CandleRequest,
    OandaCandle,
    fetch_candles,
)
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.pricing import (
    OandaPrice,
    PricingRequest,
    fetch_pricing,
)

#: Practice-account source tag stored with every bar.
BAR_SOURCE = "oanda_practice"

#: Data version for ingested candles; bump when parsing semantics change.
CANDLE_DATA_VERSION = "oanda-candles-v1"

#: Decision timeframes and how many completed candles each needs
#: (PROJECT_GUIDE 5.3).
TIMEFRAMES: tuple[tuple[str, int], ...] = (
    ("M15", 96),
    ("H1", 120),
    ("H4", 60),
    ("D", 60),
)


class MarketSyncError(RuntimeError):
    """Raised when a market-data sync cannot complete."""


class BarSink(Protocol):
    """Minimal store contract for bars."""

    def insert_bars(self, bars: list[Bar], source: str, data_version: str) -> int: ...


@dataclass
class SyncReport:
    """Outcome of one market-data sync."""

    bars_by_granularity: dict[str, int]
    quotes: int
    errors: dict[str, str]

    @property
    def total_bars(self) -> int:
        return sum(self.bars_by_granularity.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "bars_by_granularity": dict(self.bars_by_granularity),
            "total_bars": self.total_bars,
            "quotes": self.quotes,
            "errors": dict(self.errors),
        }


def to_bar(candle: OandaCandle, *, granularity: str) -> Bar:
    """Convert one OANDA candle into a core :class:`Bar`.

    The data version records the component and timeframe so bars from
    different series never collide in the store.
    """
    return Bar(
        symbol=candle.symbol,
        timestamp=candle.time,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
        source=BAR_SOURCE,
        data_version=f"{CANDLE_DATA_VERSION}:{candle.component}:{granularity}",
    )


def candles_to_bars(
    candles: Iterable[OandaCandle], *, granularity: str
) -> list[Bar]:
    """Convert completed candles into bars (incomplete ones are skipped)."""
    return [
        to_bar(candle, granularity=granularity)
        for candle in candles
        if candle.complete
    ]


def sync_bars(
    client: OandaHttpClient,
    *,
    instruments: Sequence[str],
    store: BarSink,
    timeframes: Sequence[tuple[str, int]] = TIMEFRAMES,
    component: Literal["M", "B", "A"] = "M",
) -> tuple[dict[str, int], dict[str, str]]:
    """Fetch and persist candles for every instrument and timeframe.

    A failure on one instrument/timeframe is recorded and does not abort
    the rest: the caller decides whether partial data is acceptable
    (risk evaluation treats missing data as stale, never as fresh).
    """
    counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for instrument in instruments:
        for granularity, count in timeframes:
            key = f"{instrument}:{granularity}"
            try:
                page = fetch_candles(
                    client,
                    request=CandleRequest(
                        symbol=instrument,
                        granularity=granularity,  # type: ignore[arg-type]
                        count=count,
                        components=(component,),
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - reported per key
                errors[key] = f"{type(exc).__name__}"
                continue
            bars = candles_to_bars(page.candles, granularity=granularity)
            if not bars:
                counts[key] = 0
                continue
            data_version = bars[0].data_version
            counts[key] = store.insert_bars(
                bars, source=BAR_SOURCE, data_version=data_version
            )
    return counts, errors


def sync_quotes(
    client: OandaHttpClient,
    *,
    instruments: Sequence[str],
) -> tuple[dict[str, Decimal], dict[str, str]]:
    """Fetch bid/ask/spread plus home-currency conversion per instrument."""
    if not instruments:
        return {}, {}
    try:
        batch = fetch_pricing(
            client,
            request=PricingRequest(symbols=tuple(instruments)),
            request_id="market-sync",
        )
    except Exception as exc:  # noqa: BLE001 - reported per instrument
        return {}, {instrument: type(exc).__name__ for instrument in instruments}

    quotes: dict[str, Decimal] = {}
    errors: dict[str, str] = {}
    by_symbol: dict[str, OandaPrice] = {price.symbol: price for price in batch.prices}
    for instrument in instruments:
        price = by_symbol.get(instrument)
        if price is None:
            # The batch publishes explicit coverage, so a missing or
            # malformed row is reported rather than substituted.
            failed = instrument in batch.coverage.failed
            errors[instrument] = "price_failed" if failed else "missing_price"
            continue
        quotes[instrument] = (price.bids[0].price + price.asks[0].price) / Decimal(2)
    return quotes, errors


def sync_market_data(
    client: OandaHttpClient,
    *,
    instruments: Sequence[str],
    store: BarSink,
    timeframes: Sequence[tuple[str, int]] = TIMEFRAMES,
    clock: Callable[[], datetime] | None = None,
) -> SyncReport:
    """Run one bars+quotes sync and return a structured report."""
    del clock  # reserved for future incremental windows
    counts, bar_errors = sync_bars(
        client,
        instruments=instruments,
        store=store,
        timeframes=timeframes,
    )
    quotes, quote_errors = sync_quotes(client, instruments=instruments)
    errors = {**bar_errors, **quote_errors}
    return SyncReport(
        bars_by_granularity=counts,
        quotes=len(quotes),
        errors=errors,
    )


def utc_now() -> datetime:
    """Return the current UTC time (single place for sync timestamps)."""
    return datetime.now(UTC)


__all__ = [
    "BAR_SOURCE",
    "CANDLE_DATA_VERSION",
    "TIMEFRAMES",
    "BarSink",
    "MarketSyncError",
    "SyncReport",
    "candles_to_bars",
    "sync_bars",
    "sync_market_data",
    "sync_quotes",
    "to_bar",
    "utc_now",
]
