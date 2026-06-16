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
# PaperStore tests
# ---------------------------------------------------------------------------

from alphabrief_api.db.paper import PaperStore  # noqa: E402


@pytest.fixture
def paper_store(tmp_path: Path) -> Generator[PaperStore, None, None]:
    db_path = tmp_path / "test_paper.db"
    s = PaperStore(db_path=str(db_path))
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_paper_store_creates_tables_on_init(paper_store: PaperStore) -> None:
    tables = paper_store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {row[0] for row in tables}
    assert "audit_events" in table_names
    assert "portfolio_snapshot" in table_names


# ---------------------------------------------------------------------------
# save_audit_event / get_audit_events
# ---------------------------------------------------------------------------


def test_save_audit_event_returns_id(paper_store: PaperStore) -> None:
    eid = paper_store.save_audit_event(
        event_type="order_created",
        symbol="BTC-USD",
        details={"order_id": "order_001"},
    )
    assert eid.startswith("audit_")
    assert len(eid) == 18


def test_get_audit_events_empty(paper_store: PaperStore) -> None:
    assert paper_store.get_audit_events() == []


def test_save_and_get_audit_events(paper_store: PaperStore) -> None:
    eid1 = paper_store.save_audit_event(
        event_type="order_created",
        symbol="BTC-USD",
        details={"order_id": "order_001", "message": "Order created"},
    )
    eid2 = paper_store.save_audit_event(
        event_type="fill_created",
        symbol="BTC-USD",
        details={"fill_id": "fill_001", "order_id": "order_001"},
    )
    events = paper_store.get_audit_events()
    assert len(events) == 2
    assert events[0]["id"] == eid2  # newest first
    assert events[1]["id"] == eid1
    assert events[0]["event_type"] == "fill_created"
    assert events[1]["details"]["order_id"] == "order_001"


def test_get_audit_events_filtered(paper_store: PaperStore) -> None:
    paper_store.save_audit_event(event_type="order_created", symbol="BTC")
    paper_store.save_audit_event(event_type="fill_created", symbol="BTC")
    paper_store.save_audit_event(event_type="order_created", symbol="ETH")

    orders = paper_store.get_audit_events(event_type="order_created")
    assert len(orders) == 2
    for e in orders:
        assert e["event_type"] == "order_created"


# ---------------------------------------------------------------------------
# save_portfolio_snapshot / get_latest_portfolio_snapshot
# ---------------------------------------------------------------------------


def test_save_portfolio_snapshot_returns_id(paper_store: PaperStore) -> None:
    sid = paper_store.save_portfolio_snapshot(
        cash="100000",
        realized_pnl="0",
        total_value="100000",
        positions={},
    )
    assert sid.startswith("psnap_")
    assert len(sid) == 18


def test_get_latest_portfolio_snapshot_none_when_empty(
    paper_store: PaperStore,
) -> None:
    assert paper_store.get_latest_portfolio_snapshot() is None


def test_save_and_get_latest_portfolio_snapshot(
    paper_store: PaperStore,
) -> None:
    positions = {
        "BTC-USD": {"symbol": "BTC-USD", "quantity": "1", "average_price": "50000"}
    }
    paper_store.save_portfolio_snapshot(
        cash="50000", realized_pnl="1000", total_value="100000", positions=positions
    )

    snap = paper_store.get_latest_portfolio_snapshot()
    assert snap is not None
    assert snap["cash"] == "50000"
    assert snap["realized_pnl"] == "1000"
    assert snap["total_value"] == "100000"
    assert "BTC-USD" in snap["positions"]
    assert snap["positions"]["BTC-USD"]["quantity"] == "1"


def test_list_portfolio_snapshots_ordered(paper_store: PaperStore) -> None:
    paper_store.save_portfolio_snapshot(
        cash="100000", realized_pnl="0", total_value="100000", positions={}
    )
    import time

    time.sleep(0.1)
    paper_store.save_portfolio_snapshot(
        cash="90000", realized_pnl="500", total_value="95000", positions={}
    )

    snaps = paper_store.list_portfolio_snapshots(limit=5)
    assert len(snaps) == 2
    assert snaps[0]["cash"] == "90000"
    assert snaps[1]["cash"] == "100000"


# ---------------------------------------------------------------------------
# save_order / get_orders
# ---------------------------------------------------------------------------


def test_save_order_stores_as_audit_event(paper_store: PaperStore) -> None:
    oid = paper_store.save_order(
        {"symbol": "BTC-USD", "order_id": "order_001", "status": "created"}
    )
    assert oid.startswith("audit_")

    orders = paper_store.get_orders()
    assert len(orders) == 1
    assert orders[0]["event_type"] == "order_created"


def test_get_orders_filtered_by_status(paper_store: PaperStore) -> None:
    paper_store.save_order(
        {"symbol": "BTC", "order_id": "o1", "status": "created"}
    )
    paper_store.save_order(
        {"symbol": "ETH", "order_id": "o2", "status": "filled"}
    )

    created = paper_store.get_orders(status="created")
    assert len(created) == 1
    assert created[0]["details"]["order_id"] == "o1"


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_paper_clear_removes_all_data(paper_store: PaperStore) -> None:
    paper_store.save_audit_event(event_type="test", symbol="BTC")
    paper_store.save_portfolio_snapshot(
        cash="100", realized_pnl="0", total_value="100", positions={}
    )
    assert len(paper_store.get_audit_events()) == 1
    assert paper_store.get_latest_portfolio_snapshot() is not None

    paper_store.clear()
    assert paper_store.get_audit_events() == []
    assert paper_store.get_latest_portfolio_snapshot() is None


# ---------------------------------------------------------------------------
# close / reopen
# ---------------------------------------------------------------------------


def test_paper_close_then_reopen(tmp_path: Path) -> None:
    db_path = str(tmp_path / "reopen_paper.db")
    store1 = PaperStore(db_path=db_path)
    eid = store1.save_audit_event(event_type="order_created", symbol="BTC")
    store1.close()

    store2 = PaperStore(db_path=db_path)
    events = store2.get_audit_events()
    assert len(events) == 1
    assert events[0]["id"] == eid
    assert events[0]["symbol"] == "BTC"
    store2.close()


# ---------------------------------------------------------------------------
# ReviewStore tests
# ---------------------------------------------------------------------------

from alphabrief_api.db.review import ReviewStore  # noqa: E402


def _make_snapshot_data(
    snapshot_id: str = "snapshot_test_001",
    headline: str = "Review snapshot headline",
) -> dict[str, object]:
    return {
        "snapshot_id": snapshot_id,
        "generated_at": "2026-06-15T09:30:00+00:00",
        "headline": headline,
        "strategies": [],
        "backtests": [],
        "daily_briefs": [],
        "model_calls": [],
        "paper_portfolio": {
            "cash": "100000",
            "total_value": "100000",
            "realized_pnl": "0",
            "open_positions": {},
            "updated_at": "2026-06-15T09:30:00+00:00",
        },
        "order_audit_log": [],
        "risk_dashboard": {
            "total_decisions": 0,
            "approved_decisions": 0,
            "rejected_decisions": 0,
            "kill_switch_active": False,
            "latest_risk_tags": [],
            "updated_at": "2026-06-15T09:30:00+00:00",
        },
        "review_journal": [],
    }


@pytest.fixture
def review_store(tmp_path: Path) -> Generator[ReviewStore, None, None]:
    db_path = tmp_path / "test_review.db"
    s = ReviewStore(db_path=str(db_path))
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_review_store_creates_tables_on_init(
    review_store: ReviewStore,
) -> None:
    tables = review_store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {row[0] for row in tables}
    assert "review_snapshots" in table_names


# ---------------------------------------------------------------------------
# save_snapshot
# ---------------------------------------------------------------------------


def test_review_save_snapshot_returns_id(review_store: ReviewStore) -> None:
    data = _make_snapshot_data()
    sid = review_store.save_snapshot(data)
    assert sid.startswith("snapshot_")
    assert len(sid) == 21


def test_review_save_snapshot_stores_multiple(
    review_store: ReviewStore,
) -> None:
    sid1 = review_store.save_snapshot(
        _make_snapshot_data(headline="First snapshot")
    )
    sid2 = review_store.save_snapshot(
        _make_snapshot_data(headline="Second snapshot")
    )
    assert sid1 != sid2
    snapshots = review_store.list_snapshots()
    assert len(snapshots) == 2


# ---------------------------------------------------------------------------
# get_snapshot
# ---------------------------------------------------------------------------


def test_review_get_snapshot_returns_stored(
    review_store: ReviewStore,
) -> None:
    data = _make_snapshot_data(headline="Test headline")
    sid = review_store.save_snapshot(data)

    result = review_store.get_snapshot(sid)
    assert result is not None
    assert result["id"] == sid
    assert "created_at" in result
    assert isinstance(result["snapshot"], dict)
    assert result["snapshot"]["headline"] == "Test headline"


def test_review_get_snapshot_nonexistent_returns_none(
    review_store: ReviewStore,
) -> None:
    assert review_store.get_snapshot("snapshot_nonexistent") is None


# ---------------------------------------------------------------------------
# get_latest_snapshot
# ---------------------------------------------------------------------------


def test_review_get_latest_snapshot_none_when_empty(
    review_store: ReviewStore,
) -> None:
    assert review_store.get_latest_snapshot() is None


def test_review_get_latest_snapshot_returns_most_recent(
    review_store: ReviewStore,
) -> None:
    review_store.save_snapshot(_make_snapshot_data(headline="First"))
    import time

    time.sleep(0.1)
    review_store.save_snapshot(_make_snapshot_data(headline="Second"))

    latest = review_store.get_latest_snapshot()
    assert latest is not None
    assert latest["snapshot"]["headline"] == "Second"


# ---------------------------------------------------------------------------
# list_snapshots
# ---------------------------------------------------------------------------


def test_review_list_snapshots_empty(review_store: ReviewStore) -> None:
    assert review_store.list_snapshots() == []


def test_review_list_snapshots_ordered(
    review_store: ReviewStore,
) -> None:
    review_store.save_snapshot(_make_snapshot_data(headline="First"))
    import time

    time.sleep(0.1)
    review_store.save_snapshot(_make_snapshot_data(headline="Second"))

    snapshots = review_store.list_snapshots()
    assert len(snapshots) == 2
    assert snapshots[0]["headline"] == "Second"
    assert snapshots[1]["headline"] == "First"


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_review_clear_removes_all_data(review_store: ReviewStore) -> None:
    review_store.save_snapshot(_make_snapshot_data())
    assert len(review_store.list_snapshots()) == 1

    review_store.clear()
    assert review_store.list_snapshots() == []
    assert review_store.get_snapshot("snapshot_any") is None


# ---------------------------------------------------------------------------
# close / reopen
# ---------------------------------------------------------------------------


def test_review_close_then_reopen(tmp_path: Path) -> None:
    db_path = str(tmp_path / "reopen_review.db")
    store1 = ReviewStore(db_path=db_path)
    sid = store1.save_snapshot(
        _make_snapshot_data(headline="Persistent review")
    )
    store1.close()

    store2 = ReviewStore(db_path=db_path)
    result = store2.get_snapshot(sid)
    assert result is not None
    assert result["snapshot"]["headline"] == "Persistent review"
    store2.close()


# ---------------------------------------------------------------------------
# brief close / reopen (preserved from earlier round)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DebateStore tests
# ---------------------------------------------------------------------------

from alphabrief_api.db.debates import DebateStore  # noqa: E402


@pytest.fixture
def debate_store(tmp_path: Path) -> Generator[DebateStore, None, None]:
    db_path = str(tmp_path / "test_debates.db")
    s = DebateStore(db_path=db_path)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_debate_store_creates_tables_on_init(debate_store: DebateStore) -> None:
    tables = debate_store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {row[0] for row in tables}
    assert "debate_records" in table_names


# ---------------------------------------------------------------------------
# save_debate_record / get_debate_record
# ---------------------------------------------------------------------------


def test_save_debate_record_returns_id(debate_store: DebateStore) -> None:
    did = debate_store.save_debate_record(
        question={"question": "Test question"},
        responses=[{"analysis": "test", "view": "neutral", "confidence": 0.5,
            "suggested_action": "watch", "needs_human_review": False,
        }],
        consensus={"num_models": 1, "agreement_level": "high", "avg_confidence": 0.5},
    )
    assert did.startswith("deb_")
    assert len(did) == 16  # "deb_" + 12 hex chars


def test_list_debate_records_empty(debate_store: DebateStore) -> None:
    assert debate_store.list_debate_records() == []


def test_save_and_get_debate_record(debate_store: DebateStore) -> None:
    question = {"question": "Market outlook?", "symbol": "BTC-USD"}
    responses = [
        {
                "analysis": "Bullish", "view": "bullish", "confidence": 0.8,
                "suggested_action": "buy", "needs_human_review": False,
            },
        {
                "analysis": "Bearish", "view": "bearish", "confidence": 0.6,
                "suggested_action": "sell", "needs_human_review": False,
            },
    ]
    consensus = {
        "num_models": 2,
        "agreement_level": "mixed",
        "consensus_view": None,
        "avg_confidence": 0.7,
        "view_distribution": {"bullish": 1, "bearish": 1},
    }

    did = debate_store.save_debate_record(
        question=question,
        responses=responses,
        consensus=consensus,
    )

    record = debate_store.get_debate_record(did)
    assert record is not None
    assert record["id"] == did
    assert record["question"]["question"] == "Market outlook?"
    assert len(record["responses"]) == 2
    assert record["consensus"]["num_models"] == 2


def test_get_debate_record_nonexistent(debate_store: DebateStore) -> None:
    assert debate_store.get_debate_record("deb_nonexistent") is None


def test_list_debate_records_ordered(debate_store: DebateStore) -> None:
    debate_store.save_debate_record(
        question={"question": "First"},
        responses=[],
        consensus={"num_models": 0, "agreement_level": "mixed", "avg_confidence": 0.0},
    )
    debate_store.save_debate_record(
        question={"question": "Second"},
        responses=[],
        consensus={"num_models": 0, "agreement_level": "mixed", "avg_confidence": 0.0},
    )

    records = debate_store.list_debate_records()
    assert len(records) == 2
    # Second should be first (newest)
    assert records[0]["question"]["question"] == "Second"


def test_debate_clear_removes_all_data(debate_store: DebateStore) -> None:
    debate_store.save_debate_record(
        question={"question": "Test"},
        responses=[],
        consensus={"num_models": 0, "agreement_level": "mixed", "avg_confidence": 0.0},
    )
    debate_store.clear()
    assert debate_store.list_debate_records() == []


def test_debate_close_then_reopen(tmp_path: Path) -> None:
    from alphabrief_api.db.debates import DebateStore

    db_path = str(tmp_path / "reopen_debates.db")
    store1 = DebateStore(db_path=db_path)
    did = store1.save_debate_record(
        question={"question": "Persistent test"},
        responses=[],
        consensus={"num_models": 0, "agreement_level": "mixed", "avg_confidence": 0.0},
    )
    store1.close()

    store2 = DebateStore(db_path=db_path)
    record = store2.get_debate_record(did)
    assert record is not None
    assert record["question"]["question"] == "Persistent test"
    store2.close()


# ---------------------------------------------------------------------------
# brief close / reopen (preserved from earlier round)
# ---------------------------------------------------------------------------


def test_brief_close_then_reopen(tmp_path: Path) -> None:
    from alphabrief_api.db.briefs import BriefStore

    db_path = str(tmp_path / "reopen_briefs.db")
    store1 = BriefStore(db_path=db_path)
    bid = store1.save_brief(
        {
            "brief_id": "brief_test_001",
            "generated_at": "2026-06-14T09:30:00+00:00",
            "trading_day": "2026-06-14",
            "headline": "Persistent",
            "executive_summary": "Test",
        }
    )
    store1.close()

    store2 = BriefStore(db_path=db_path)
    result = store2.get_brief(bid)
    assert result is not None
    assert result["brief"]["headline"] == "Persistent"
    store2.close()



# ---------------------------------------------------------------------------
# NewsStore + MacroStore
# ---------------------------------------------------------------------------


def _make_headline(headline_id: str = "h1", symbol: str = "AAPL"):
    from alphabrief_news.types import NewsHeadline
    return NewsHeadline(
        headline_id=headline_id,
        published_at=datetime(2026, 6, 12, 9, 30, tzinfo=UTC),
        symbols=[symbol],
        category="earnings",
        source="test",
        title=f"{symbol} news",
    )


def _make_indicator(indicator_id: str = "CPI", name: str = "CPI"):
    from decimal import Decimal

    from alphabrief_news.types import MacroIndicator
    return MacroIndicator(
        indicator_id=indicator_id,
        name=name,
        country="US",
        released_at=datetime(2026, 6, 12, 8, 30, tzinfo=UTC),
        period="2026-05",
        value=Decimal("300.0"),
        unit="index",
        source="test",
    )


def test_news_store_inserts_and_gets(tmp_path: Path) -> None:
    from alphabrief_api.db.news import NewsStore

    db_path = str(tmp_path / "news.db")
    store = NewsStore(db_path=db_path)
    headline = _make_headline()
    store.insert_headlines([headline])

    fetched = store.get_headline("h1")
    assert fetched is not None
    assert fetched.title == "AAPL news"
    assert fetched.symbols == ["AAPL"]
    store.close()


def test_news_store_lists_by_symbol(tmp_path: Path) -> None:
    from alphabrief_api.db.news import NewsStore

    store = NewsStore(db_path=str(tmp_path / "news2.db"))
    store.insert_headlines([
        _make_headline(headline_id="h1", symbol="AAPL"),
        _make_headline(headline_id="h2", symbol="TSLA"),
    ])

    results = store.list_headlines(symbol="AAPL")
    assert len(results) == 1
    assert results[0].headline_id == "h1"
    store.close()


def test_news_store_filters_by_time_window(tmp_path: Path) -> None:
    from alphabrief_api.db.news import NewsStore
    from alphabrief_news.types import NewsHeadline

    store = NewsStore(db_path=str(tmp_path / "news3.db"))
    early = NewsHeadline(
        headline_id="early",
        published_at=datetime(2026, 6, 10, 9, 30, tzinfo=UTC),
        symbols=["AAPL"],
        category="earnings",
        source="test",
        title="early",
    )
    late = NewsHeadline(
        headline_id="late",
        published_at=datetime(2026, 6, 12, 9, 30, tzinfo=UTC),
        symbols=["AAPL"],
        category="earnings",
        source="test",
        title="late",
    )
    store.insert_headlines([early, late])

    results = store.list_headlines(
        start=datetime(2026, 6, 11, tzinfo=UTC),
        end=datetime(2026, 6, 13, tzinfo=UTC),
    )
    assert len(results) == 1
    assert results[0].headline_id == "late"
    store.close()


def test_news_store_clear(tmp_path: Path) -> None:
    from alphabrief_api.db.news import NewsStore

    store = NewsStore(db_path=str(tmp_path / "news4.db"))
    store.insert_headlines([_make_headline()])
    store.clear()
    assert store.get_headline("h1") is None
    store.close()


def test_macro_store_inserts_and_gets(tmp_path: Path) -> None:
    from alphabrief_api.db.macro import MacroStore

    store = MacroStore(db_path=str(tmp_path / "macro.db"))
    indicator = _make_indicator()
    store.insert_indicators([indicator])

    fetched = store.get_indicator("CPI")
    assert fetched is not None
    assert fetched.value == Decimal("300.0")
    store.close()


def test_macro_store_lists_by_indicator_id(tmp_path: Path) -> None:
    from alphabrief_api.db.macro import MacroStore

    store = MacroStore(db_path=str(tmp_path / "macro2.db"))
    store.insert_indicators([
        _make_indicator(indicator_id="CPI", name="CPI"),
        _make_indicator(indicator_id="UNRATE", name="Unemployment"),
    ])

    results = store.list_indicators(indicator_id="CPI")
    assert len(results) == 1
    assert results[0].indicator_id == "CPI"
    store.close()


def test_macro_store_filters_by_time_window(tmp_path: Path) -> None:
    from alphabrief_api.db.macro import MacroStore
    from alphabrief_news.types import MacroIndicator

    store = MacroStore(db_path=str(tmp_path / "macro3.db"))
    early = MacroIndicator(
        indicator_id="CPI",
        name="CPI",
        released_at=datetime(2026, 6, 10, 8, 30, tzinfo=UTC),
        value=Decimal("290.0"),
        source="test",
    )
    late = MacroIndicator(
        indicator_id="CPI",
        name="CPI",
        released_at=datetime(2026, 6, 12, 8, 30, tzinfo=UTC),
        value=Decimal("300.0"),
        source="test",
    )
    store.insert_indicators([early, late])

    results = store.list_indicators(
        indicator_id="CPI",
        start=datetime(2026, 6, 11, tzinfo=UTC),
        end=datetime(2026, 6, 13, tzinfo=UTC),
    )
    assert len(results) == 1
    assert results[0].value == Decimal("300.0")
    store.close()


def test_macro_store_clear(tmp_path: Path) -> None:
    from alphabrief_api.db.macro import MacroStore

    store = MacroStore(db_path=str(tmp_path / "macro4.db"))
    store.insert_indicators([_make_indicator()])
    store.clear()
    assert store.get_indicator("CPI") is None
    store.close()


def test_news_and_macro_tables_exist_after_schema(tmp_path: Path) -> None:
    from alphabrief_api.db.news import NewsStore

    store = NewsStore(db_path=str(tmp_path / "schema.db"))
    tables = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {row[0] for row in tables}
    assert "news_headlines" in names
    assert "macro_indicators" in names
    store.close()
