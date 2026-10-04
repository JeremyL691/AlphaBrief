"""Automated tests for S7: Vectorized backtesting on stored OANDA bars.

Verifies:
- VectorizedBacktester runs on OANDA bars with forex cost models
  (spread, integer units, overnight financing).
- alphabrief backtest run persists report to BacktestReportStore.
- Stored reports are exposed via GET /api/v1/backtest/reports.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db import BacktestReportStore, MarketDataStore
from alphabrief_backtest import VectorizedBacktester
from alphabrief_cli.main import app
from alphabrief_core import Bar
from alphabrief_strategy import MomentumStrategy, StrategySpec
from fastapi.testclient import TestClient
from typer.testing import CliRunner

runner = CliRunner()


def _make_spec() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "strategy_id": "momentum",
            "name": "Momentum Baseline",
            "version": "1.0.0",
            "universe": {"symbols": ["EUR_USD"]},
            "timeframe": "1h",
            "entry": {"condition": "close > open"},
            "exit": {"condition": "close < open"},
            "risk": {"max_position_pct": "0.5"},
            "costs": {"fee_bps": "2", "slippage_bps": "2"},
            "evaluation": {
                "train_period": {"start": "2024-01-01", "end": "2024-06-30"},
                "test_period": {"start": "2024-07-01", "end": "2024-12-31"},
            },
        }
    )


def _seed_bars(store: MarketDataStore, symbol: str = "EUR_USD") -> list[Bar]:
    base_time = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    bars: list[Bar] = []
    price = Decimal("1.1000")
    for i in range(50):
        ts = base_time + timedelta(hours=i)
        if i % 2 == 0:
            close = price + Decimal("0.0020")
        else:
            close = price - Decimal("0.0010")
        b = Bar(
            symbol=symbol,
            timestamp=ts,
            open=price,
            high=max(price, close) + Decimal("0.0025"),
            low=min(price, close) - Decimal("0.0015"),
            close=close,
            volume=Decimal("100"),
            source="oanda_practice",
            data_version="oanda-candles-v1:M:H1",
        )
        bars.append(b)
        price = close

    store.insert_bars(
        bars=bars,
        source="oanda_practice",
        data_version="oanda-candles-v1:M:H1",
    )
    return bars


def test_vectorized_backtester_costs_and_integer_units() -> None:
    spec = _make_spec()
    base_time = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    bars = []
    for i in range(30):
        o = Decimal("1.1000") + Decimal(str(i * 0.0005))
        c = o + Decimal("0.0008") if i % 2 == 0 else o - Decimal("0.0004")
        bars.append(
            Bar(
                symbol="EUR_USD",
                timestamp=base_time + timedelta(days=i),
                open=o,
                high=max(o, c) + Decimal("0.0010"),
                low=min(o, c) - Decimal("0.0010"),
                close=c,
                volume=Decimal("1000"),
                source="oanda_practice",
                data_version="oanda-candles-v1:M:D",
            )
        )

    backtester = VectorizedBacktester(
        initial_cash=Decimal("10000"),
        spread_bps=Decimal("2.0"),
        financing_rate_daily=Decimal("0.0001"),
        integer_units=True,
    )
    strategy = MomentumStrategy(window=5)
    report = backtester.run(strategy, spec=spec, bars=bars)

    assert report.spread_bps == Decimal("2.0")
    assert report.financing_rate_daily == Decimal("0.0001")
    assert report.integer_units is True
    assert report.financing_estimated is True

    if report.trades:
        for t in report.trades:
            assert t.quantity == Decimal(int(t.quantity))
            assert t.spread_cost >= Decimal("0")


def test_cli_backtest_run_oanda_persists_to_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "alphabrief_test.duckdb"
    monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
    monkeypatch.setattr("alphabrief_core.paths.db_path", lambda: db_file)

    mstore = MarketDataStore(db_path=db_file)
    try:
        _seed_bars(mstore, "EUR_USD")
    finally:
        mstore.close()

    result = runner.invoke(
        app,
        [
            "backtest",
            "run",
            "--strategy",
            "momentum",
            "--instrument",
            "EUR_USD",
            "--from",
            "2026-07-01",
            "--spread-bps",
            "1.5",
        ],
    )
    assert result.exit_code == 0, f"CLI error: {result.output}"
    assert "report_id:" in result.output
    assert "EUR_USD" in result.output
    assert "spread_cost:" in result.output
    assert "integer_units: True" in result.output

    rstore = BacktestReportStore(db_path=db_file)
    try:
        reports = rstore.list_reports()
        assert len(reports) >= 1
        latest = reports[0]["report"]
        assert latest["symbol"] == "EUR_USD"
        assert latest["strategy_id"] == "momentum"
    finally:
        rstore.close()


def test_api_backtest_reports_includes_oanda_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "alphabrief_test.duckdb"
    monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
    monkeypatch.setattr("alphabrief_core.paths.db_path", lambda: db_file)

    rstore = BacktestReportStore(db_path=db_file)
    try:
        spec = _make_spec()
        base_time = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
        bars = []
        for i in range(25):
            o = Decimal("1.1000") + Decimal(str(i * 0.0002))
            c = o + Decimal("0.0005") if i % 2 == 0 else o - Decimal("0.0003")
            bars.append(
                Bar(
                    symbol="EUR_USD",
                    timestamp=base_time + timedelta(hours=i),
                    open=o,
                    high=max(o, c) + Decimal("0.0008"),
                    low=min(o, c) - Decimal("0.0008"),
                    close=c,
                    volume=Decimal("1000"),
                    source="oanda_practice",
                    data_version="oanda-candles-v1:M:H1",
                )
            )
        bt = VectorizedBacktester(
            initial_cash=Decimal("10000"),
            spread_bps=Decimal("1.5"),
            financing_rate_daily=Decimal("0.0001"),
            integer_units=True,
        )
        report = bt.run(MomentumStrategy(window=5), spec=spec, bars=bars)
        report_id = rstore.save_report(
            report.model_dump(mode="json"),
            symbol="EUR_USD",
            strategy_name="momentum",
        )
    finally:
        rstore.close()

    from alphabrief_api.main import app as fastapi_app
    from alphabrief_api.routes import backtest as backtest_route

    # The route caches a module-level store bound to the first default
    # db_path it sees (a previous test's temporary directory). Rebind it
    # to None so the request rebuilds the store on this test's patched
    # path; monkeypatch restores the previous binding afterwards.
    monkeypatch.setattr(backtest_route, "_report_store", None)
    client = TestClient(fastapi_app)
    response = client.get("/api/v1/backtest/reports")
    assert response.status_code == 200
    data = response.json()
    assert "reports" in data
    found = [r for r in data["reports"] if r["report_id"] == report_id]
    assert len(found) == 1
    assert found[0]["symbol"] == "EUR_USD"
    assert found[0]["strategy_id"] == "momentum"


def test_cli_backtest_uses_requested_granularity_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D bars must not be dropped when another series shares timestamps.

    ``get_bar_models`` without a suffix dedupes by (symbol, timestamp)
    across granularities; the backtest command must query per granularity
    instead so colliding H1 bars cannot shrink the D series.
    """
    db_file = tmp_path / "alphabrief_test.duckdb"
    monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
    monkeypatch.setattr("alphabrief_core.paths.db_path", lambda: db_file)

    mstore = MarketDataStore(db_path=db_file)
    try:
        base_time = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
        d_bars: list[Bar] = []
        price = Decimal("1.1000")
        for i in range(25):
            ts = base_time + timedelta(days=i)
            o = price
            c = o + Decimal("0.0010")
            d_bars.append(
                Bar(
                    symbol="EUR_USD",
                    timestamp=ts,
                    open=o,
                    high=max(o, c) + Decimal("0.0010"),
                    low=min(o, c) - Decimal("0.0010"),
                    close=c,
                    volume=Decimal("1000"),
                    source="oanda_practice",
                    data_version="oanda-candles-v1:M:D",
                )
            )
            # A colliding H1 bar at the same timestamp would win the
            # cross-granularity dedupe and drop the D bar.
            d_bars.append(
                Bar(
                    symbol="EUR_USD",
                    timestamp=ts,
                    open=o,
                    high=max(o, c) + Decimal("0.0010"),
                    low=min(o, c) - Decimal("0.0010"),
                    close=c,
                    volume=Decimal("1000"),
                    source="oanda_practice",
                    data_version="oanda-candles-v1:M:H1",
                )
            )
            price = c
        mstore.insert_bars(
            bars=d_bars, source="oanda_practice", data_version="oanda-candles-v1:M:D"
        )
        mstore.insert_bars(
            bars=d_bars, source="oanda_practice", data_version="oanda-candles-v1:M:H1"
        )
    finally:
        mstore.close()

    result = runner.invoke(
        app,
        [
            "backtest",
            "run",
            "--strategy",
            "momentum",
            "--instrument",
            "EUR_USD",
            "--from",
            "2026-07-01",
            "--granularity",
            "D",
        ],
    )
    assert result.exit_code == 0, f"CLI error: {result.output}"
    assert "bars_count: 25" in result.output
