"""M05-W01: OANDA candles contract fixtures.

Covers:
- fixtures cover every supported granularity, M/B/A component
  combinations, count and time ranges, daily and weekly alignment,
  pagination boundaries, and UTC timestamps (AC-M05-W01-01);
- bid/ask/mid OHLC plus volume and complete flags are Decimal-safe and
  retained without collapsing components or overwriting another source
  version (AC-M05-W01-02);
- pagination is bounded and duplicate-free and incomplete candles
  remain queryable raw facts but are excluded from completed decision
  inputs (AC-M05-W01-03).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.candles import (
    CANDLE_SOURCE_VERSION,
    MAX_CANDLES_PER_REQUEST,
    CandleRequest,
    OandaCandle,
    completed_only,
    fetch_candles,
    parse_candles_response,
)
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig

ACCOUNT_ID = "101-004-1234567-001"


def _row(
    time: str = "2026-08-01T12:00:00.000000000Z",
    *,
    complete: bool = True,
    volume: str = "1000",
    mid: dict[str, str] | None = None,
    bid: dict[str, str] | None = None,
    ask: dict[str, str] | None = None,
) -> dict[str, Any]:
    default = {"o": "1.10000", "h": "1.11000", "l": "1.09000", "c": "1.10500"}
    row: dict[str, Any] = {
        "time": time,
        "volume": volume,
        "complete": complete,
    }
    if mid is not None:
        row["mid"] = mid
    if bid is not None:
        row["bid"] = bid
    if ask is not None:
        row["ask"] = ask
    if "mid" not in row and "bid" not in row and "ask" not in row:
        row["mid"] = default
    return row


def _body(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"candles": list(rows)}


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
# AC-M05-W01-01: fixture coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "granularity",
    [
        "S5", "S10", "S15", "S30", "M1", "M2", "M4", "M5", "M10", "M15", "M30",
        "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D", "W", "M",
    ],
)
def test_all_granularities_parse(granularity: str) -> None:
    page = parse_candles_response(
        _body(_row()),
        symbol="EUR_USD",
        granularity=granularity,  # type: ignore[arg-type]
        components=("M",),
    )
    assert page.granularity == granularity
    assert len(page.candles) == 1


def test_mid_bid_ask_components_all_retained() -> None:
    page = parse_candles_response(
        _body(
            _row(
                mid={"o": "1.10", "h": "1.11", "l": "1.09", "c": "1.105"},
                bid={"o": "1.09", "h": "1.10", "l": "1.08", "c": "1.095"},
                ask={"o": "1.11", "h": "1.12", "l": "1.10", "c": "1.115"},
            )
        ),
        symbol="EUR_USD",
        granularity="M5",
        components=("M", "B", "A"),
    )
    assert len(page.candles) == 3
    components = {candle.component for candle in page.candles}
    assert components == {"M", "B", "A"}
    for candle in page.candles:
        assert candle.open < candle.high
        assert candle.low < candle.close


def test_count_and_time_ranges_are_passed_through() -> None:
    captured: dict[str, Any] = {}
    request = CandleRequest(
        symbol="EUR_USD",
        granularity="H1",
        components=("M",),
        count=250,
        from_time=datetime(2026, 8, 1, tzinfo=UTC),
        to_time=datetime(2026, 8, 2, tzinfo=UTC),
        daily_alignment=17,
        weekly_alignment="M",
    )
    fetch_candles(_client(_body(_row()), captured), request=request)
    assert "count=250" in captured["url"]
    assert "from=" in captured["url"]
    assert "to=" in captured["url"]
    assert "dailyAlignment=17" in captured["url"]
    assert "weeklyAlignment=M" in captured["url"]


def test_utc_timestamps_are_normalized() -> None:
    page = parse_candles_response(
        _body(_row(time="2026-08-01T12:00:00.000000000Z")),
        symbol="EUR_USD",
        granularity="M5",
        components=("M",),
    )
    candle = page.candles[0]
    assert candle.time.tzinfo is not None
    assert candle.time.hour == 12
    assert page.next_from_time is not None
    assert page.next_from_time.tzinfo is not None


# ---------------------------------------------------------------------------
# AC-M05-W01-02: Decimal-safe, no collapsing, no overwrite
# ---------------------------------------------------------------------------


def test_ohlc_and_volume_are_decimal_safe() -> None:
    page = parse_candles_response(
        _body(_row(volume="1234")),
        symbol="EUR_USD",
        granularity="M5",
        components=("M",),
    )
    candle = page.candles[0]
    assert isinstance(candle.open, Decimal)
    assert isinstance(candle.volume, Decimal)
    assert candle.open == Decimal("1.10000")
    assert candle.volume == Decimal("1234")
    # JSON serialization keeps exact values.
    payload = json.loads(candle.model_dump_json())
    assert payload["open"] == "1.10000"


def test_float_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        parse_candles_response(
            _body(
                _row(
                    mid={
                        "o": 1.1,  # type: ignore[dict-item]
                        "h": 1.11,  # type: ignore[dict-item]
                        "l": 1.09,  # type: ignore[dict-item]
                        "c": 1.105,  # type: ignore[dict-item]
                    }
                )
            ),
            symbol="EUR_USD",
            granularity="M5",
            components=("M",),
        )


def test_missing_component_prices_reject() -> None:
    with pytest.raises(ValueError, match="missing A prices"):
        parse_candles_response(
            _body(_row(mid={"o": "1", "h": "2", "l": "0", "c": "1"})),
            symbol="EUR_USD",
            granularity="M5",
            components=("M", "A"),
        )


def test_source_versions_coexist_in_store_without_overwrite(
    tmp_path: Path,
) -> None:
    """Two candle source versions of the same bar coexist in the store."""
    from alphabrief_api.db.market_data import MarketDataStore
    from alphabrief_core import Bar

    store = MarketDataStore(db_path=tmp_path / "candles.db")
    try:
        for version in ("oanda-v20-candles-1", "oanda-v20-candles-2"):
            store.insert_bars(
                [
                    Bar(
                        symbol="EUR_USD",
                        timestamp=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                        open=Decimal("1.10"),
                        high=Decimal("1.11"),
                        low=Decimal("1.09"),
                        close=Decimal("1.105"),
                        volume=Decimal("1000"),
                        source="oanda-mid",
                        data_version=version,
                    )
                ],
                source="oanda-mid",
                data_version=version,
            )
        facts = store.get_bar_facts(
            symbol="EUR_USD", timestamp=datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        )
        assert len(facts) == 2
        assert {fact["data_version"] for fact in facts} == {
            "oanda-v20-candles-1",
            "oanda-v20-candles-2",
        }
    finally:
        store.close()


# ---------------------------------------------------------------------------
# AC-M05-W01-03: bounded, duplicate-free pagination; complete semantics
# ---------------------------------------------------------------------------


def test_request_count_is_bounded() -> None:
    with pytest.raises(ValueError):
        CandleRequest(
            symbol="EUR_USD",
            granularity="M5",
            components=("M",),
            count=MAX_CANDLES_PER_REQUEST + 1,
        )


def test_duplicate_rows_are_rejected_not_merged() -> None:
    with pytest.raises(ValueError, match="duplicate candle row"):
        parse_candles_response(
            _body(_row(), _row()),
            symbol="EUR_USD",
            granularity="M5",
            components=("M",),
        )


def test_incomplete_candles_stay_raw_but_out_of_decision_inputs() -> None:
    page = parse_candles_response(
        _body(
            _row(time="2026-08-01T12:00:00.000000000Z", complete=False),
            _row(time="2026-08-01T12:05:00.000000000Z", complete=True),
        ),
        symbol="EUR_USD",
        granularity="M5",
        components=("M",),
    )
    assert len(page.candles) == 2
    # Both remain queryable raw facts...
    assert {candle.complete for candle in page.candles} == {False, True}
    # ...but completed decision inputs exclude the incomplete one.
    decision = completed_only(page.candles)
    assert len(decision) == 1
    assert decision[0].complete is True


def test_candle_source_version_is_immutable_identity() -> None:
    candle = parse_candles_response(
        _body(_row()),
        symbol="EUR_USD",
        granularity="M5",
        components=("M",),
    ).candles[0]
    assert candle.source_version == CANDLE_SOURCE_VERSION
    assert isinstance(candle, OandaCandle)
