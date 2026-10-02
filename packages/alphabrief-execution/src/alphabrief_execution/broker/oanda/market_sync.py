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

from alphabrief_execution.broker.errors import BrokerNotFoundError
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

SIGNAL_INSTRUMENTS = ("XAU_USD", "SPX500_USD", "BCO_USD")
SIGNAL_TIMEFRAMES: tuple[tuple[Literal["H1", "D"], int], ...] = (("H1", 120), ("D", 60))


class MarketSyncError(RuntimeError):
    """Raised when a market-data sync cannot complete."""


class BarSink(Protocol):
    """Minimal store contract for bars."""

    def insert_bars(self, bars: list[Bar], source: str, data_version: str) -> int: ...


@dataclass(frozen=True)
class SignalCandleObservation:
    """One round's read-only observations; old stored bars never hide fetch failures."""

    series: dict[str, dict[str, list[Bar]]]
    excluded: dict[str, Literal["broker_not_found"]]
    errors: dict[str, str]
    observed_at: datetime


def observe_signal_candles(
    client: OandaHttpClient, *, store: BarSink,
    clock: Callable[[], datetime] | None = None,
) -> SignalCandleObservation:
    """Read the guide's signals without making them eligible for orders.

    A broker 404 proves the signal cannot supply this account's input.
    Authentication, network, parsing and storage failures remain failures,
    not permission to silently remove a required signal.
    """
    series: dict[str, dict[str, list[Bar]]] = {}
    excluded: dict[str, Literal["broker_not_found"]] = {}
    errors: dict[str, str] = {}
    for symbol in SIGNAL_INSTRUMENTS:
        windows: dict[str, list[Bar]] = {}
        for timeframe, count in SIGNAL_TIMEFRAMES:
            try:
                page = fetch_candles(client, request=CandleRequest(
                    symbol=symbol, granularity=timeframe,
                    components=("M",), count=count + 1,
                ))
                bars = sorted(candles_to_bars(page.candles, granularity=timeframe),
                              key=lambda bar: bar.timestamp)[-count:]
            except BrokerNotFoundError:
                excluded[symbol] = "broker_not_found"
                break
            except Exception as exc:  # noqa: BLE001 - safe classification, never exclude
                errors[f"{symbol}:{timeframe}"] = type(exc).__name__
                continue
            try:
                if bars:
                    store.insert_bars(bars, source=BAR_SOURCE,
                                      data_version=bars[0].data_version)
                windows[timeframe] = bars
            except Exception as exc:  # noqa: BLE001 - persistence is part of ingestion
                errors[f"{symbol}:{timeframe}"] = type(exc).__name__
        if symbol not in excluded:
            series[symbol] = windows
    return SignalCandleObservation(
        series=series, excluded=excluded, errors=errors,
        observed_at=(clock or utc_now)(),
    )


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
    require_full_window: bool = False,
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
                        count=count + 1,
                        components=(component,),
                    ),
                )
                bars = sorted(
                    candles_to_bars(page.candles, granularity=granularity),
                    key=lambda bar: bar.timestamp,
                )[-count:]
                if (
                    require_full_window
                    and len({bar.timestamp for bar in bars}) != count
                ):
                    errors[key] = "IncompleteWindow"
                    continue
                if not bars:
                    counts[key] = 0
                    continue
                data_version = bars[0].data_version
                counts[key] = store.insert_bars(
                    bars, source=BAR_SOURCE, data_version=data_version
                )
            except Exception as exc:  # noqa: BLE001 - safe per-window failure classification
                errors[key] = type(exc).__name__
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
    "SIGNAL_INSTRUMENTS",
    "SIGNAL_TIMEFRAMES",
    "SignalCandleObservation",
    "BarSink",
    "MarketSyncError",
    "SyncReport",
    "candles_to_bars",
    "observe_signal_candles",
    "sync_bars",
    "sync_market_data",
    "sync_quotes",
    "to_bar",
    "utc_now",
]
