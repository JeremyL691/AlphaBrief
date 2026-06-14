"""Tests for the DuckDB-backed MarketDataStore."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db.market_data import MarketDataStore
from alphabrief_core.domain import Bar


def _make_bar(
    symbol: str = "BTC",
    timestamp: datetime | None = None,
) -> Bar:
    if timestamp is None:
        timestamp = datetime(2026, 6, 12, 9, 30, tzinfo=UTC)
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("95"),
        close=Decimal("105"),
        volume=Decimal("1000"),
        source="test",
        data_version="0.0.0",
    )


def _make_bars(
    count: int = 3,
    symbol: str = "BTC",
    base_time: datetime | None = None,
) -> list[Bar]:
    if base_time is None:
        base_time = datetime(2026, 6, 12, 9, 30, tzinfo=UTC)
    return [
        _make_bar(symbol=symbol, timestamp=base_time + timedelta(minutes=i))
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Generator[MarketDataStore, None, None]:
    db_path = tmp_path / "test.db"
    s = MarketDataStore(db_path=str(db_path))
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_store_creates_tables_on_init(store: MarketDataStore) -> None:
    tables = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {row[0] for row in tables}
    assert "symbols" in table_names
    assert "bars" in table_names


# ---------------------------------------------------------------------------
# insert_bars
# ---------------------------------------------------------------------------


def test_insert_bars_stores_and_returns_count(store: MarketDataStore) -> None:
    bars = _make_bars(3)
    count = store.insert_bars(bars, source="test", data_version="0.0.0")
    assert count == 3
    assert store.symbol_exists("BTC")


def test_insert_bars_empty_list(store: MarketDataStore) -> None:
    count = store.insert_bars([], source="test", data_version="0.0.0")
    assert count == 0


def test_insert_bars_overwrites_existing(store: MarketDataStore) -> None:
    bars1 = _make_bars(2)
    store.insert_bars(bars1, source="v1", data_version="1.0")
    assert store.get_bar_count("BTC") == 2

    bars2 = _make_bars(3)
    store.insert_bars(bars2, source="v2", data_version="2.0")
    assert store.get_bar_count("BTC") == 3


def test_insert_bars_records_symbol_meta(store: MarketDataStore) -> None:
    base = datetime(2026, 6, 12, 9, 30, tzinfo=UTC)
    bars = [
        _make_bar(symbol="ETH", timestamp=base + timedelta(hours=i))
        for i in range(5)
    ]
    store.insert_bars(bars, source="local", data_version="1.2.3")

    info = store.get_symbol_info("ETH")
    assert info is not None
    assert info["symbol"] == "ETH"
    assert info["bar_count"] == 5
    assert info["source"] == "local"
    assert info["data_version"] == "1.2.3"
    assert info["time_start"] is not None
    assert info["time_end"] is not None


# ---------------------------------------------------------------------------
# get_symbols
# ---------------------------------------------------------------------------


def test_get_symbols_empty(store: MarketDataStore) -> None:
    assert store.get_symbols() == []


def test_get_symbols_returns_all(store: MarketDataStore) -> None:
    store.insert_bars(_make_bars(2, symbol="BTC"), source="s1", data_version="v1")
    store.insert_bars(_make_bars(1, symbol="ETH"), source="s2", data_version="v2")

    symbols = store.get_symbols()
    assert len(symbols) == 2
    sym_names = {s["symbol"] for s in symbols}
    assert sym_names == {"BTC", "ETH"}


# ---------------------------------------------------------------------------
# get_bars
# ---------------------------------------------------------------------------


def test_get_bars_pagination(store: MarketDataStore) -> None:
    base = datetime(2026, 6, 12, 9, 30, tzinfo=UTC)
    bars = [
        _make_bar(symbol="BTC", timestamp=base + timedelta(minutes=i))
        for i in range(10)
    ]
    store.insert_bars(bars, source="test", data_version="0.0.0")

    page = store.get_bars("BTC", limit=3, offset=2)
    assert len(page) == 3
    assert page[0]["timestamp"] == (base + timedelta(minutes=2)).isoformat()
    assert page[2]["timestamp"] == (base + timedelta(minutes=4)).isoformat()


def test_get_bars_returns_ordered_by_timestamp(store: MarketDataStore) -> None:
    base = datetime(2026, 6, 12, 9, 30, tzinfo=UTC)
    bars = [
        _make_bar(symbol="BTC", timestamp=base + timedelta(minutes=i))
        for i in [3, 0, 5, 1, 4]
    ]
    store.insert_bars(bars, source="test", data_version="0.0.0")

    result = store.get_bars("BTC", limit=5, offset=0)
    timestamps: list[str] = [str(r["timestamp"]) for r in result]
    assert timestamps == sorted(timestamps)


def test_get_bars_empty_result(store: MarketDataStore) -> None:
    result = store.get_bars("NOPE", limit=10, offset=0)
    assert result == []


def test_get_bars_offset_beyond_range(store: MarketDataStore) -> None:
    store.insert_bars(_make_bars(3), source="test", data_version="0.0.0")
    result = store.get_bars("BTC", limit=10, offset=100)
    assert result == []


# ---------------------------------------------------------------------------
# get_bar_count / symbol_exists
# ---------------------------------------------------------------------------


def test_get_bar_count_zero_when_no_symbol(store: MarketDataStore) -> None:
    assert store.get_bar_count("MISSING") == 0


def test_symbol_exists_false_when_missing(store: MarketDataStore) -> None:
    assert not store.symbol_exists("MISSING")


def test_symbol_exists_true_when_present(store: MarketDataStore) -> None:
    store.insert_bars(_make_bars(1), source="test", data_version="0.0.0")
    assert store.symbol_exists("BTC")


# ---------------------------------------------------------------------------
# get_symbol_info
# ---------------------------------------------------------------------------


def test_get_symbol_info_none_when_missing(store: MarketDataStore) -> None:
    assert store.get_symbol_info("MISSING") is None


def test_get_symbol_info_time_range(store: MarketDataStore) -> None:
    base = datetime(2026, 6, 12, 9, 30, tzinfo=UTC)
    bars = [
        _make_bar(symbol="BTC", timestamp=base + timedelta(days=i))
        for i in range(3)
    ]
    store.insert_bars(bars, source="test", data_version="0.0.0")

    info = store.get_symbol_info("BTC")
    assert info is not None
    assert info["time_start"] == base.isoformat()
    assert info["time_end"] == (base + timedelta(days=2)).isoformat()


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_clear_removes_all_data(store: MarketDataStore) -> None:
    store.insert_bars(_make_bars(3), source="test", data_version="0.0.0")
    assert store.get_bar_count("BTC") == 3
    assert store.get_symbols() != []

    store.clear()
    assert store.get_bar_count("BTC") == 0
    assert store.get_symbols() == []
    assert not store.symbol_exists("BTC")


def test_clear_then_insert(store: MarketDataStore) -> None:
    store.insert_bars(_make_bars(3), source="v1", data_version="1.0")
    store.clear()
    store.insert_bars(_make_bars(5), source="v2", data_version="2.0")
    assert store.get_bar_count("BTC") == 5
    info = store.get_symbol_info("BTC")
    assert info is not None
    assert info["source"] == "v2"


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def test_close_then_reopen(tmp_path: Path) -> None:
    db_path = str(tmp_path / "reopen.db")
    store1 = MarketDataStore(db_path=db_path)
    store1.insert_bars(_make_bars(3), source="test", data_version="0.0.0")
    store1.close()

    store2 = MarketDataStore(db_path=db_path)
    assert store2.get_bar_count("BTC") == 3
    store2.close()


# ---------------------------------------------------------------------------
# Multiple symbol insertion
# ---------------------------------------------------------------------------


def test_multiple_symbols_independent(store: MarketDataStore) -> None:
    store.insert_bars(_make_bars(3, symbol="BTC"), source="s1", data_version="v1")
    store.insert_bars(_make_bars(5, symbol="ETH"), source="s2", data_version="v2")

    assert store.get_bar_count("BTC") == 3
    assert store.get_bar_count("ETH") == 5
    assert len(store.get_symbols()) == 2

    btc_info = store.get_symbol_info("BTC")
    assert btc_info is not None
    assert btc_info["source"] == "s1"

    eth_info = store.get_symbol_info("ETH")
    assert eth_info is not None
    assert eth_info["source"] == "s2"
