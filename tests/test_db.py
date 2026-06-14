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


# ---------------------------------------------------------------------------
# BacktestReportStore tests
# ---------------------------------------------------------------------------

from alphabrief_api.db.backtest_reports import BacktestReportStore  # noqa: E402


def _make_report_json(
    symbol: str = "BTC",
    strategy_name: str = "MA Trend",
) -> dict[str, object]:
    return {
        "strategy_id": "ma_trend",
        "strategy_version": "0.0.0",
        "symbol": symbol,
        "data_version": "0.0.0",
        "initial_cash": "10000",
        "final_value": "10500",
        "fee_bps": "5",
        "slippage_bps": "5",
        "metrics": {
            "total_return": "0.05",
            "max_drawdown": "0.02",
            "trade_count": 3,
            "win_rate": "0.6666666666666666",
        },
        "equity_curve": [],
        "trades": [],
    }


@pytest.fixture
def report_store(tmp_path: Path) -> Generator[BacktestReportStore, None, None]:
    db_path = tmp_path / "test_reports.db"
    s = BacktestReportStore(db_path=str(db_path))
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_report_store_creates_tables_on_init(
    report_store: BacktestReportStore,
) -> None:
    tables = report_store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {row[0] for row in tables}
    assert "backtest_reports" in table_names


# ---------------------------------------------------------------------------
# save_report
# ---------------------------------------------------------------------------


def test_save_report_returns_id(report_store: BacktestReportStore) -> None:
    report_json = _make_report_json()
    rid = report_store.save_report(
        report_json, symbol="BTC", strategy_name="MA Trend"
    )
    assert rid.startswith("backtest_")
    assert len(rid) == 21


def test_save_report_stores_multiple(report_store: BacktestReportStore) -> None:
    rid1 = report_store.save_report(
        _make_report_json(symbol="BTC"), symbol="BTC", strategy_name="MA Trend"
    )
    rid2 = report_store.save_report(
        _make_report_json(symbol="ETH"), symbol="ETH", strategy_name="MA Cross"
    )
    assert rid1 != rid2
    reports = report_store.list_reports()
    assert len(reports) == 2


# ---------------------------------------------------------------------------
# get_report
# ---------------------------------------------------------------------------


def test_get_report_returns_stored_report(
    report_store: BacktestReportStore,
) -> None:
    report_json = _make_report_json(symbol="BTC")
    rid = report_store.save_report(
        report_json, symbol="BTC", strategy_name="MA Trend"
    )

    result = report_store.get_report(rid)
    assert result is not None
    assert result["id"] == rid
    assert result["symbol"] == "BTC"
    assert result["strategy_name"] == "MA Trend"
    assert "created_at" in result
    assert isinstance(result["report"], dict)
    assert result["report"]["symbol"] == "BTC"


def test_get_report_nonexistent_returns_none(
    report_store: BacktestReportStore,
) -> None:
    assert report_store.get_report("backtest_nonexistent") is None


# ---------------------------------------------------------------------------
# list_reports
# ---------------------------------------------------------------------------


def test_list_reports_empty(report_store: BacktestReportStore) -> None:
    assert report_store.list_reports() == []


def test_list_reports_ordered_by_created_at(
    report_store: BacktestReportStore,
) -> None:
    report_store.save_report(
        _make_report_json(symbol="BTC"), symbol="BTC", strategy_name="First"
    )
    import time

    time.sleep(0.1)
    report_store.save_report(
        _make_report_json(symbol="ETH"), symbol="ETH", strategy_name="Second"
    )

    reports = report_store.list_reports()
    assert len(reports) == 2
    assert reports[0]["strategy_name"] == "Second"
    assert reports[1]["strategy_name"] == "First"


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_report_clear_removes_all_data(
    report_store: BacktestReportStore,
) -> None:
    report_store.save_report(
        _make_report_json(), symbol="BTC", strategy_name="MA Trend"
    )
    assert len(report_store.list_reports()) == 1

    report_store.clear()
    assert report_store.list_reports() == []
    assert report_store.get_report("backtest_any") is None


# ---------------------------------------------------------------------------
# close / reopen
# ---------------------------------------------------------------------------


def test_report_close_then_reopen(tmp_path: Path) -> None:
    db_path = str(tmp_path / "reopen_reports.db")
    store1 = BacktestReportStore(db_path=db_path)
    rid = store1.save_report(
        _make_report_json(symbol="BTC"), symbol="BTC", strategy_name="MA Trend"
    )
    store1.close()

    store2 = BacktestReportStore(db_path=db_path)
    result = store2.get_report(rid)
    assert result is not None
    assert result["report"]["symbol"] == "BTC"
    store2.close()


# ---------------------------------------------------------------------------
# BriefStore tests
# ---------------------------------------------------------------------------

from alphabrief_api.db.briefs import BriefStore  # noqa: E402


def _make_brief_data(
    brief_id: str = "brief_test_001",
    headline: str = "Market outlook is positive",
) -> dict[str, object]:
    return {
        "brief_id": brief_id,
        "generated_at": "2026-06-14T09:30:00+00:00",
        "trading_day": "2026-06-14",
        "headline": headline,
        "executive_summary": "Markets show strength across key sectors.",
        "market_brief": {
            "brief_id": "mkt_sample",
            "generated_at": "2026-06-14T09:30:00+00:00",
            "trading_day": "2026-06-14",
            "regime": "bullish",
            "summary": "Bullish momentum continues.",
            "confidence": 0.85,
            "key_factors": ["Earnings", "Rate outlook"],
        },
        "symbol_briefs": [
            {
                "brief_id": "sym_sample",
                "symbol": "SPY",
                "generated_at": "2026-06-14T09:30:00+00:00",
                "horizon": "1d",
                "verdict": {
                    "direction": "bullish",
                    "confidence": 0.8,
                    "rationale": "Positive momentum.",
                },
                "catalysts": ["Earnings beat"],
                "risks": ["Valuation concern"],
            }
        ],
        "watchlist": ["SPY", "QQQ"],
        "risk_notes": ["Monitor volatility"],
    }


@pytest.fixture
def brief_store(tmp_path: Path) -> Generator[BriefStore, None, None]:
    db_path = tmp_path / "test_briefs.db"
    s = BriefStore(db_path=str(db_path))
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_brief_store_creates_tables_on_init(brief_store: BriefStore) -> None:
    tables = brief_store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {row[0] for row in tables}
    assert "briefs" in table_names


# ---------------------------------------------------------------------------
# save_brief
# ---------------------------------------------------------------------------


def test_save_brief_returns_id(brief_store: BriefStore) -> None:
    brief_data = _make_brief_data()
    bid = brief_store.save_brief(brief_data)
    assert bid.startswith("brief_")
    assert len(bid) == 18  # "brief_" (6) + 12 hex chars


def test_save_brief_stores_multiple(brief_store: BriefStore) -> None:
    bid1 = brief_store.save_brief(_make_brief_data(headline="First brief"))
    bid2 = brief_store.save_brief(_make_brief_data(headline="Second brief"))
    assert bid1 != bid2
    briefs = brief_store.list_briefs()
    assert len(briefs) == 2


# ---------------------------------------------------------------------------
# get_brief
# ---------------------------------------------------------------------------


def test_get_brief_returns_stored_brief(brief_store: BriefStore) -> None:
    brief_data = _make_brief_data(headline="Test headline")
    bid = brief_store.save_brief(brief_data)

    result = brief_store.get_brief(bid)
    assert result is not None
    assert result["id"] == bid
    assert "created_at" in result
    assert isinstance(result["brief"], dict)
    assert result["brief"]["headline"] == "Test headline"
    assert result["brief"]["trading_day"] == "2026-06-14"


def test_get_brief_nonexistent_returns_none(brief_store: BriefStore) -> None:
    assert brief_store.get_brief("brief_nonexistent") is None


# ---------------------------------------------------------------------------
# list_briefs
# ---------------------------------------------------------------------------


def test_list_briefs_empty(brief_store: BriefStore) -> None:
    assert brief_store.list_briefs() == []


def test_list_briefs_ordered_by_created_at(brief_store: BriefStore) -> None:
    brief_store.save_brief(_make_brief_data(headline="First"))
    import time

    time.sleep(0.1)
    brief_store.save_brief(_make_brief_data(headline="Second"))

    briefs = brief_store.list_briefs()
    assert len(briefs) == 2
    assert briefs[0]["headline"] == "Second"
    assert briefs[1]["headline"] == "First"


def test_list_briefs_summary_fields(brief_store: BriefStore) -> None:
    brief_store.save_brief(_make_brief_data(headline="Test summary"))

    briefs = brief_store.list_briefs()
    assert len(briefs) == 1
    s = briefs[0]
    assert s["id"].startswith("brief_")
    assert "created_at" in s
    assert s["headline"] == "Test summary"
    assert s["trading_day"] == "2026-06-14"


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_brief_clear_removes_all_data(brief_store: BriefStore) -> None:
    brief_store.save_brief(_make_brief_data())
    assert len(brief_store.list_briefs()) == 1

    brief_store.clear()
    assert brief_store.list_briefs() == []
    assert brief_store.get_brief("brief_any") is None


# ---------------------------------------------------------------------------
# close / reopen
# ---------------------------------------------------------------------------


def test_brief_close_then_reopen(tmp_path: Path) -> None:
    db_path = str(tmp_path / "reopen_briefs.db")
    store1 = BriefStore(db_path=db_path)
    bid = store1.save_brief(_make_brief_data(headline="Persistent"))
    store1.close()

    store2 = BriefStore(db_path=db_path)
    result = store2.get_brief(bid)
    assert result is not None
    assert result["brief"]["headline"] == "Persistent"
    store2.close()
