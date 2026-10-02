"""Tests for OANDA practice market-data sync.

The transport is injected, so these tests are fully deterministic: no
socket, no credential, no network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest
from alphabrief_core import Bar
from alphabrief_execution.broker.oanda.candles import OandaCandle
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.market_sync import (
    BAR_SOURCE,
    CANDLE_DATA_VERSION,
    candles_to_bars,
    sync_bars,
    sync_market_data,
    sync_quotes,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _candles_payload(
    symbol: str, *, count: int = 2, complete: bool = True
) -> dict[str, Any]:
    return {
        "instrument": symbol,
        "granularity": "H1",
        "candles": [
            {
                "time": f"2026-09-30T{10 + index:02d}:00:00.000000000Z",
                "complete": complete,
                "volume": 100 + index,
                "mid": {
                    "o": "1.1000",
                    "h": "1.1050",
                    "l": "1.0950",
                    "c": "1.1020",
                },
            }
            for index in range(count)
        ],
    }


def _pricing_payload(symbol: str) -> dict[str, Any]:
    if symbol == "XAU_USD":
        # Signal-only symbols may not be priced by an FX-only account.
        return {"prices": []}
    return {
        "homeConversions": [{
            "currency": symbol.split("_")[-1], "positionValue": "1",
            "accountGain": "1", "accountLoss": "1",
        }],
        "prices": [
            {
                "instrument": symbol,
                "time": "2026-09-30T12:00:00.000000000Z",
                "tradeable": True,
                "bids": [{"price": "1.1018", "liquidity": 1000000}],
                "asks": [{"price": "1.1022", "liquidity": 1000000}],
                "closeoutBid": "1.1017",
                "closeoutAsk": "1.1023",
            }
        ]
    }


class _MemoryStore:
    """Minimal bar sink that records what was written."""

    def __init__(self) -> None:
        self.bars: list[Bar] = []
        self.calls: list[tuple[str, str]] = []

    def insert_bars(self, bars: list[Bar], source: str, data_version: str) -> int:
        if source != BAR_SOURCE:
            raise AssertionError(f"unexpected source {source!r}")
        if not data_version.startswith(CANDLE_DATA_VERSION):
            raise AssertionError(f"unexpected data version {data_version!r}")
        self.bars.extend(bars)
        self.calls.append((source, data_version))
        return len(bars)


def _client(*, fail_paths: tuple[str, ...] = ()) -> OandaHttpClient:
    def http_send(request: Request, timeout: float) -> bytes:
        del timeout
        url = request.full_url
        if any(fragment in url for fragment in fail_paths):
            raise OSError("simulated transport failure")
        if "/candles" in url:
            symbol = url.split("/instruments/")[1].split("/")[0]
            return json.dumps(_candles_payload(symbol)).encode()
        if "/pricing" in url:
            symbol = parse_qs(urlparse(url).query)["instruments"][0].split(",")[0]
            return json.dumps(_pricing_payload(symbol)).encode()
        raise AssertionError(f"unexpected request: {url}")

    config = OandaPaperConfig(
        base_url="https://api-fxpractice.oanda.com",
        timeout_seconds=5.0,
        max_retries=0,
        retry_backoff_seconds=0.1,
    )
    return OandaHttpClient(
        config=config,
        http_send=http_send,
        token="test-token",
        account_id="101-004-1234567-001",
    )


class TestCandleConversion:
    def test_completed_candles_become_bars_with_timeframe_version(self) -> None:
        candle: OandaCandle = OandaCandle(
            symbol="EUR_USD",
            time=NOW,
            component="M",
            open=Decimal("1.1"),
            high=Decimal("1.2"),
            low=Decimal("1.0"),
            close=Decimal("1.15"),
            volume=Decimal("10"),
            complete=True,
            source_version="test",
        )

        bars = candles_to_bars([candle], granularity="H1")

        assert len(bars) == 1
        assert bars[0].symbol == "EUR_USD"
        assert bars[0].source == BAR_SOURCE
        assert bars[0].data_version == f"{CANDLE_DATA_VERSION}:M:H1"

    def test_incomplete_candles_are_skipped(self) -> None:
        candle: OandaCandle = OandaCandle(
            symbol="EUR_USD",
            time=NOW,
            component="M",
            open=Decimal("1.1"),
            high=Decimal("1.2"),
            low=Decimal("1.0"),
            close=Decimal("1.15"),
            volume=Decimal("10"),
            complete=False,
            source_version="test",
        )

        assert candles_to_bars([candle], granularity="H1") == []


class TestSyncBars:
    @pytest.mark.parametrize("last_complete", [False, True])
    def test_fetch_extra_candle_and_keep_exact_completed_window(
        self, monkeypatch: pytest.MonkeyPatch, last_complete: bool
    ) -> None:
        from types import SimpleNamespace

        from alphabrief_execution.broker.oanda import market_sync

        requests: list[Any] = []

        def fetch(client: Any, *, request: Any) -> Any:
            requests.append(request)
            return SimpleNamespace(candles=[OandaCandle(
                symbol="EUR_USD", time=NOW + timedelta(hours=i), component="M",
                open=Decimal("1"), high=Decimal("1.1"), low=Decimal("0.9"),
                close=Decimal("1"), volume=Decimal(10),
                complete=i < 3 or last_complete, source_version="test",
            ) for i in range(4)])

        monkeypatch.setattr(market_sync, "fetch_candles", fetch)
        store = _MemoryStore()
        counts, errors = sync_bars(
            _client(), instruments=["EUR_USD"], store=store,
            timeframes=(("H1", 3),),
        )
        assert requests[0].count == 4
        assert counts == {"EUR_USD:H1": 3} and errors == {}
        first = 1 if last_complete else 0
        assert [b.timestamp for b in store.bars] == [
            NOW + timedelta(hours=i) for i in range(first, first + 3)
        ]

    def test_bars_are_written_per_instrument_and_timeframe(self) -> None:
        store = _MemoryStore()

        counts, errors = sync_bars(
            _client(),
            instruments=["EUR_USD", "USD_JPY"],
            store=store,
            timeframes=(("H1", 2), ("H4", 2)),
        )

        assert errors == {}
        assert counts == {
            "EUR_USD:H1": 2,
            "EUR_USD:H4": 2,
            "USD_JPY:H1": 2,
            "USD_JPY:H4": 2,
        }
        assert len(store.bars) == 8
        assert {bar.symbol for bar in store.bars} == {"EUR_USD", "USD_JPY"}

    def test_one_failed_instrument_does_not_abort_the_sync(self) -> None:
        store = _MemoryStore()

        counts, errors = sync_bars(
            _client(fail_paths=("USD_JPY",)),
            instruments=["EUR_USD", "USD_JPY"],
            store=store,
            timeframes=(("H1", 2),),
        )

        assert counts == {"EUR_USD:H1": 2}
        assert set(errors) == {"USD_JPY:H1"}
        assert store.bars  # the healthy instrument still landed


class TestSyncQuotes:
    def test_quote_mid_is_the_average_of_the_touch(self) -> None:
        quotes, errors = sync_quotes(_client(), instruments=["EUR_USD"])

        assert errors == {}
        assert quotes["EUR_USD"] == Decimal("1.1020")

    def test_missing_quote_is_reported_not_faked(self) -> None:
        quotes, errors = sync_quotes(_client(), instruments=["XAU_USD"])

        assert quotes == {}
        assert errors == {"XAU_USD": "missing_price"}

    def test_transport_failure_is_reported_per_instrument(self) -> None:
        quotes, errors = sync_quotes(
            _client(fail_paths=("/pricing",)), instruments=["EUR_USD", "USD_JPY"]
        )

        assert quotes == {}
        assert set(errors) == {"EUR_USD", "USD_JPY"}


class TestSyncMarketData:
    def test_report_summarizes_bars_quotes_and_errors(self) -> None:
        store = _MemoryStore()

        report = sync_market_data(
            _client(fail_paths=("USD_JPY",)),
            instruments=["EUR_USD", "USD_JPY"],
            store=store,
            timeframes=(("H1", 2),),
        )

        payload = report.to_dict()
        assert payload["total_bars"] == 2
        # The pricing batch covers both instruments in one request, so a
        # transport failure fails the whole batch closed (no partial
        # substitution of stale or invented quotes).
        assert payload["quotes"] == 0
        # Transport failures surface as the client's classified error type.
        assert payload["errors"]["EUR_USD"] == "BrokerTransientError"
        assert payload["errors"]["USD_JPY"] == "BrokerTransientError"
        assert payload["errors"]["USD_JPY:H1"] == "BrokerTransientError"
        # EUR_USD candles succeeded, so it has no bar error at all.
        assert "EUR_USD:H1" not in payload["errors"]
