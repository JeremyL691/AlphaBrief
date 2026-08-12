"""M05-W02: batch pricing and home-currency conversion evidence.

Covers:
- requests are deterministically chunked within configured limits and
  responses preserve bid/ask ladders, spread, liquidity, tradeable,
  closeout prices, conversion factors, broker timestamp, and request
  correlation (AC-M05-W02-01);
- missing sides, crossed prices, nonpositive conversion factors,
  duplicate instruments, and malformed timestamps fail quality
  validation instead of being silently repaired (AC-M05-W02-02);
- partial broker responses publish explicit per-instrument coverage and
  are never represented as a complete pricing snapshot (AC-M05-W02-03).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from urllib.request import Request

from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.pricing import (
    PRICING_SOURCE_VERSION,
    OandaPrice,
    PricingRequest,
    fetch_pricing,
    parse_pricing_response,
)

ACCOUNT_ID = "101-004-1234567-001"


def _price_row(
    symbol: str = "EUR_USD",
    *,
    bid: str = "1.10000",
    ask: str = "1.10050",
    tradeable: bool = True,
    conversions: dict[str, str] | None = None,
    time: str = "2026-08-01T12:00:00.000000000Z",
    closeout_bid: str | None = None,
    closeout_ask: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "type": "PRICE",
        "instrument": symbol,
        "time": time,
        "tradeable": tradeable,
        "bids": [{"price": bid, "liquidity": 1000000}],
        "asks": [{"price": ask, "liquidity": 1000000}],
        "closeoutBid": closeout_bid or bid,
        "closeoutAsk": closeout_ask or ask,
        "quoteHomeConversionFactors": conversions
        or {"positiveUnits": "1", "negativeUnits": "1"},
    }
    return row


def _body(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"prices": list(rows)}


def _client(
    body: dict[str, Any], captured: dict[str, Any] | None = None
) -> OandaHttpClient:
    def _send(request: Request, timeout_seconds: float) -> bytes:
        if captured is not None:
            captured["url"] = request.full_url
        return json.dumps(body).encode("utf-8")

    return OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=_send,
        token="t",
        account_id=ACCOUNT_ID,
    )


# ---------------------------------------------------------------------------
# AC-M05-W02-01: chunking and field preservation
# ---------------------------------------------------------------------------


def test_requests_are_deterministically_chunked() -> None:
    from urllib.parse import parse_qs, urlparse

    urls: list[str] = []
    symbols = tuple(f"SYM{i:03d}" for i in range(7))

    def _send(request: Request, timeout_seconds: float) -> bytes:
        urls.append(request.full_url)
        query = parse_qs(urlparse(request.full_url).query)
        requested = query["instruments"][0].split(",")
        return json.dumps(
            _body(*[_price_row(symbol=s) for s in requested])
        ).encode("utf-8")

    client = OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=_send,
        token="t",
        account_id=ACCOUNT_ID,
    )
    batch = fetch_pricing(
        client,
        request=PricingRequest(
            symbols=symbols, max_instruments_per_request=3
        ),
        request_id="req-1",
    )
    assert len(urls) == 3  # 7 symbols in chunks of 3 -> 3 requests
    for url in urls:
        chunk = url.split("instruments=")[1].split("&")[0].split(",")
        assert len(chunk) <= 3
    assert len(batch.prices) == 7
    assert batch.coverage.complete is True


def test_price_facts_preserve_all_fields() -> None:
    batch = parse_pricing_response(
        _body(
            _price_row(
                conversions={
                    "positiveUnits": "0.91",
                    "negativeUnits": "0.90",
                }
            )
        ),
        requested=("EUR_USD",),
        request_id="req-7",
    )
    price = batch.prices[0]
    assert isinstance(price, OandaPrice)
    assert price.bids[0].price == Decimal("1.10000")
    assert price.bids[0].liquidity == 1000000
    assert price.asks[0].price == Decimal("1.10050")
    assert price.spread == Decimal("0.00050")
    assert price.tradeable is True
    assert price.closeout_bid == Decimal("1.10000")
    assert price.closeout_ask == Decimal("1.10050")
    assert price.conversion_factor == Decimal("0.91")
    assert price.broker_time.tzinfo is not None
    assert price.request_id == "req-7"
    assert price.source_version == PRICING_SOURCE_VERSION
    assert batch.coverage.complete is True


def test_chunk_correlation_ids_are_distinct() -> None:
    captured: dict[str, Any] = {}

    def _send(request: Request, timeout_seconds: float) -> bytes:
        captured["url"] = request.full_url
        return json.dumps(
            _body(*[_price_row(symbol=s) for s in ("A", "B")])
        ).encode("utf-8")

    client = _client(_body(_price_row()), captured)
    batch = fetch_pricing(
        client,
        request=PricingRequest(symbols=("A", "B"), max_instruments_per_request=1),
        request_id="req-chunk",
    )
    ids = {price.request_id for price in batch.prices}
    assert ids == {"req-chunk-0", "req-chunk-1"}


# ---------------------------------------------------------------------------
# AC-M05-W02-02: quality validation fails closed
# ---------------------------------------------------------------------------


def test_missing_sides_fail_validation() -> None:
    row = _price_row()
    row["asks"] = []
    batch = parse_pricing_response(
        _body(row), requested=("EUR_USD",), request_id="r"
    )
    assert batch.coverage.failed == ("EUR_USD (missing bid or ask side)",)
    assert batch.coverage.complete is False


def test_crossed_prices_fail_validation() -> None:
    batch = parse_pricing_response(
        _body(_price_row(bid="1.10100", ask="1.10050")),
        requested=("EUR_USD",),
        request_id="r",
    )
    assert batch.coverage.failed
    assert batch.coverage.complete is False


def test_nonpositive_conversion_factor_fails_validation() -> None:
    batch = parse_pricing_response(
        _body(
            _price_row(conversions={"positiveUnits": "0", "negativeUnits": "0"})
        ),
        requested=("EUR_USD",),
        request_id="r",
    )
    assert batch.coverage.failed == (
        "EUR_USD (nonpositive conversion factor)",
    )
    assert batch.coverage.complete is False


def test_duplicate_instruments_fail_validation() -> None:
    batch = parse_pricing_response(
        _body(_price_row(), _price_row()),
        requested=("EUR_USD",),
        request_id="r",
    )
    assert batch.coverage.failed == ("EUR_USD (duplicate)",)
    assert batch.coverage.complete is False


def test_malformed_timestamps_fail_validation() -> None:
    batch = parse_pricing_response(
        _body(_price_row(time="not-a-time")),
        requested=("EUR_USD",),
        request_id="r",
    )
    assert batch.coverage.failed
    assert batch.coverage.complete is False


def test_float_values_are_rejected() -> None:
    row = _price_row()
    row["bids"][0]["price"] = 1.1
    batch = parse_pricing_response(
        _body(row), requested=("EUR_USD",), request_id="r"
    )
    assert batch.coverage.failed
    assert batch.coverage.complete is False


# ---------------------------------------------------------------------------
# AC-M05-W02-03: explicit per-instrument coverage
# ---------------------------------------------------------------------------


def test_partial_response_never_represents_complete_snapshot() -> None:
    batch = parse_pricing_response(
        _body(_price_row("EUR_USD")),
        requested=("EUR_USD", "GBP_USD", "USD_JPY"),
        request_id="r",
    )
    assert batch.coverage.requested == ("EUR_USD", "GBP_USD", "USD_JPY")
    assert batch.coverage.returned == ("EUR_USD",)
    assert batch.coverage.missing == ("GBP_USD", "USD_JPY")
    assert batch.coverage.complete is False


def test_complete_coverage_is_explicit() -> None:
    batch = parse_pricing_response(
        _body(_price_row("EUR_USD"), _price_row("GBP_USD")),
        requested=("EUR_USD", "GBP_USD"),
        request_id="r",
    )
    assert batch.coverage.complete is True
    assert batch.coverage.missing == ()
    assert batch.coverage.failed == ()
