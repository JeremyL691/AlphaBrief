"""Tests for the AlphaBrief API server."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alphabrief_api.broker_adapter import _reset_broker_adapter
from alphabrief_api.main import app
from alphabrief_api.routes.backtest import _clear_report_store
from alphabrief_api.routes.data import _close_store
from alphabrief_api.routes.macro import _clear_store as _clear_macro_store
from alphabrief_api.routes.news import _clear_store as _clear_news_store
from alphabrief_api.routes.review import _clear_review_store
from alphabrief_api.routes.risk import _reset_risk_gate
from alphabrief_data import ParquetBarLoader
from alphabrief_news import MacroIndicator, NewsHeadline
from alphabrief_risk import RiskLimitConfig
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path) -> Iterator[None]:
    """Isolate all module-level stores before every test.

    Sets a temporary DuckDB data directory so tests never write to the
    user's home directory. Closes the store after the test to allow
    ``tmp_path`` cleanup.
    """
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    _close_store()
    _clear_report_store()
    _clear_review_store()
    _clear_news_store()
    _clear_macro_store()
    _reset_risk_gate()
    _reset_broker_adapter()
    yield
    _close_store()





# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

CSV_HEADER = "timestamp,open,high,low,close,volume\n"
CSV_ROW_1 = "2026-06-12T09:30:00,100.0,110.0,95.0,105.0,123.45\n"
CSV_ROW_2 = "2026-06-12T09:31:00,105.0,112.0,101.0,111.0,10.0\n"
CSV_ROW_3 = "2026-06-12T09:32:00,111.0,115.0,108.0,109.0,50.0\n"


def _write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _parquet_patch_rows(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
) -> None:
    def read_rows(
        self: ParquetBarLoader,
        path: Path,
    ) -> tuple[tuple[str, ...], list[dict[str, object]]]:
        return ("timestamp", "open", "high", "low", "close", "volume"), rows

    monkeypatch.setattr(ParquetBarLoader, "_read_rows", read_rows)


# ---------------------------------------------------------------------------
# Existing health / status / data-status tests (updated prefix)
# ---------------------------------------------------------------------------


def test_health_check_returns_200() -> None:
    response = client.get("/health")

    assert response.status_code == 200


def test_health_check_body() -> None:
    response = client.get("/health")

    assert response.json() == {"status": "healthy", "version": "0.0.0"}


def test_api_status_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHABRIEF_ENV", "test")

    response = client.get("/api/status")

    assert response.status_code == 200




def test_data_status_returns_200(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "bars.csv").write_text(CSV_HEADER)
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(data_dir))

    response = client.get("/api/v1/data/status")

    assert response.status_code == 200
    assert response.json()["data_dir_exists"] is True
    assert response.json()["data_dir_has_files"] is True


# ---------------------------------------------------------------------------
# POST /api/v1/data/load — CSV
# ---------------------------------------------------------------------------


def test_load_csv_returns_201_and_bar_count(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "btc.csv", CSV_HEADER + CSV_ROW_1 + CSV_ROW_2)

    response = client.post(
        "/api/v1/data/load",
        json={
            "file_path": str(csv_path),
            "symbol": "BTC-USD",
            "source": "test",
            "data_version": "v1",
            "file_type": "csv",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["symbol"] == "BTC-USD"
    assert body["bar_count"] == 2
    assert body["source"] == "test"
    assert body["data_version"] == "v1"


def test_load_csv_defaults_source_and_version(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "eth.csv", CSV_HEADER + CSV_ROW_1)

    response = client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "ETH-USD"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "local"
    assert body["data_version"] == "0.0.0"


def test_load_csv_missing_file_returns_404(tmp_path: Path) -> None:
    response = client.post(
        "/api/v1/data/load",
        json={
            "file_path": str(tmp_path / "nonexistent.csv"),
            "symbol": "X",
        },
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_load_csv_bad_format_returns_422(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "bad.csv",
        "wrong,col,names\n1,2,3\n",
    )

    response = client.post(
        "/api/v1/data/load",
        json={
            "file_path": str(csv_path),
            "symbol": "BAD",
        },
    )

    assert response.status_code == 422


def test_load_csv_reloading_overwrites(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "btc.csv", CSV_HEADER + CSV_ROW_1)
    csv_path_2 = _write_csv(
        tmp_path / "btc2.csv", CSV_HEADER + CSV_ROW_1 + CSV_ROW_2 + CSV_ROW_3
    )

    r1 = client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "BTC-USD"},
    )
    assert r1.json()["bar_count"] == 1

    r2 = client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path_2), "symbol": "BTC-USD"},
    )
    assert r2.json()["bar_count"] == 3


# ---------------------------------------------------------------------------
# POST /api/v1/data/load — Parquet (patched)
# ---------------------------------------------------------------------------


def test_load_parquet_returns_201(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parquet_path = tmp_path / "bars.parquet"
    parquet_path.write_text("")  # file must exist on disk

    _parquet_patch_rows(
        monkeypatch,
        [
            {
                "timestamp": "2026-06-12T09:30:00",
                "open": "100",
                "high": "110",
                "low": "95",
                "close": "105",
                "volume": "123.45",
            }
        ],
    )

    response = client.post(
        "/api/v1/data/load",
        json={
            "file_path": str(parquet_path),
            "symbol": "BTC-USD",
            "file_type": "parquet",
        },
    )

    assert response.status_code == 201
    assert response.json()["bar_count"] == 1


# ---------------------------------------------------------------------------
# GET /api/v1/data/symbols
# ---------------------------------------------------------------------------


def test_symbols_empty_returns_empty_list() -> None:
    response = client.get("/api/v1/data/symbols")

    assert response.status_code == 200
    assert response.json() == {"symbols": []}


def test_symbols_after_load_returns_summaries(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "btc.csv", CSV_HEADER + CSV_ROW_1 + CSV_ROW_2)
    client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "BTC-USD", "source": "test"},
    )
    csv_path_2 = _write_csv(tmp_path / "eth.csv", CSV_HEADER + CSV_ROW_1)
    client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path_2), "symbol": "ETH-USD", "source": "test"},
    )

    response = client.get("/api/v1/data/symbols")
    body = response.json()

    assert response.status_code == 200
    assert len(body["symbols"]) == 2
    symbols = {s["symbol"] for s in body["symbols"]}
    assert symbols == {"BTC-USD", "ETH-USD"}

    btc = next(s for s in body["symbols"] if s["symbol"] == "BTC-USD")
    assert btc["bar_count"] == 2
    assert btc["source"] == "test"


# ---------------------------------------------------------------------------
# GET /api/v1/data/{symbol}/bars
# ---------------------------------------------------------------------------


def test_bars_returns_ohlcv_data(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "btc.csv", CSV_HEADER + CSV_ROW_1 + CSV_ROW_2)
    client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "BTC-USD", "source": "test"},
    )

    response = client.get("/api/v1/data/BTC-USD/bars")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "BTC-USD"
    assert body["total_count"] == 2
    assert body["offset"] == 0
    assert body["limit"] == 100
    assert len(body["bars"]) == 2

    bar = body["bars"][0]
    assert bar["symbol"] == "BTC-USD"
    assert bar["close"] == "105"


def test_bars_pagination_offset(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "btc.csv", CSV_HEADER + CSV_ROW_1 + CSV_ROW_2 + CSV_ROW_3
    )
    client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "BTC-USD"},
    )

    response = client.get("/api/v1/data/BTC-USD/bars?offset=1&limit=1")

    assert response.status_code == 200
    body = response.json()
    assert body["offset"] == 1
    assert body["limit"] == 1
    assert body["total_count"] == 3
    assert len(body["bars"]) == 1


def test_bars_offset_exceeds_total_returns_416(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "btc.csv", CSV_HEADER + CSV_ROW_1)
    client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "BTC-USD"},
    )

    response = client.get("/api/v1/data/BTC-USD/bars?offset=100")

    assert response.status_code == 416


def test_bars_invalid_limit_returns_422(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "btc.csv", CSV_HEADER + CSV_ROW_1)
    client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "BTC-USD"},
    )

    response = client.get("/api/v1/data/BTC-USD/bars?limit=0")

    assert response.status_code == 422


def test_bars_negative_offset_returns_422(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "btc.csv", CSV_HEADER + CSV_ROW_1)
    client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "BTC-USD"},
    )

    response = client.get("/api/v1/data/BTC-USD/bars?offset=-1")

    assert response.status_code == 422


def test_bars_symbol_not_loaded_returns_404() -> None:
    response = client.get("/api/v1/data/NOSUCH/bars")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/data/{symbol}/info
# ---------------------------------------------------------------------------


def test_info_returns_metadata(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "btc.csv", CSV_HEADER + CSV_ROW_1 + CSV_ROW_2)
    client.post(
        "/api/v1/data/load",
        json={
            "file_path": str(csv_path),
            "symbol": "BTC-USD",
            "source": "test-src",
            "data_version": "v0.1",
        },
    )

    response = client.get("/api/v1/data/BTC-USD/info")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "BTC-USD"
    assert body["bar_count"] == 2
    assert body["source"] == "test-src"
    assert body["data_version"] == "v0.1"
    assert body["time_start"] is not None
    assert body["time_end"] is not None
    assert "2026-06-12" in body["time_start"]


def test_info_time_range_is_sorted(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "btc.csv",
        CSV_HEADER
        + "2026-06-12T09:32:00,111,115,108,109,50\n"
        + "2026-06-12T09:30:00,100,110,95,105,123.45\n",
    )
    client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "BTC-USD"},
    )

    response = client.get("/api/v1/data/BTC-USD/info")
    body = response.json()

    assert body["time_start"].startswith("2026-06-12T09:30:00")
    assert body["time_end"].startswith("2026-06-12T09:32:00")


def test_info_symbol_not_loaded_returns_404() -> None:
    response = client.get("/api/v1/data/NOSUCH/info")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Backtest helpers
# ---------------------------------------------------------------------------

CSV_ROW_4 = "2026-06-12T09:33:00,109.0,116.0,107.0,114.0,50.0\n"
CSV_ROW_5 = "2026-06-12T09:34:00,114.0,118.0,112.0,116.0,40.0\n"

_BT_CSV = CSV_HEADER + CSV_ROW_1 + CSV_ROW_2 + CSV_ROW_3 + CSV_ROW_4 + CSV_ROW_5


def _load_btc_bars(tmp_path: Path) -> None:
    """Load 5 BTC-USD bars into the in-memory data store."""
    csv_path = tmp_path / "btc.csv"
    csv_path.write_text(_BT_CSV, encoding="utf-8")
    client.post(
        "/api/v1/data/load",
        json={
            "file_path": str(csv_path),
            "symbol": "BTC-USD",
            "source": "test",
            "data_version": "v1",
        },
    )


# ---------------------------------------------------------------------------
# POST /api/v1/backtest/run
# ---------------------------------------------------------------------------


def test_backtest_run_returns_201(tmp_path: Path) -> None:
    _load_btc_bars(tmp_path)

    response = client.post(
        "/api/v1/backtest/run",
        json={"symbol": "BTC-USD", "sma_window": 3},
    )

    assert response.status_code == 201
    body = response.json()
    assert "report_id" in body
    assert body["symbol"] == "BTC-USD"
    assert body["strategy_id"] == "ma_trend"
    assert body["initial_cash"] == 10000.0
    assert "metrics" in body
    assert "trades" in body
    assert "equity_curve" in body
    assert body["data_version"] == "v1"


def test_backtest_run_with_custom_params(tmp_path: Path) -> None:
    _load_btc_bars(tmp_path)

    response = client.post(
        "/api/v1/backtest/run",
        json={
            "symbol": "BTC-USD",
            "strategy_id": "custom_ma",
            "strategy_name": "Custom MA",
            "strategy_version": "1.0.0",
            "sma_window": 2,
            "max_position_pct": "0.5",
            "fee_bps": "10",
            "slippage_bps": "10",
            "initial_cash": "20000",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["strategy_id"] == "custom_ma"
    assert body["strategy_version"] == "1.0.0"
    assert body["initial_cash"] == 20000.0
    assert body["fee_bps"] == 10.0
    assert body["slippage_bps"] == 10.0


def test_backtest_run_symbol_not_loaded_returns_404() -> None:
    response = client.post(
        "/api/v1/backtest/run",
        json={"symbol": "NOSUCH"},
    )

    assert response.status_code == 404


def test_backtest_run_insufficient_bars_returns_422(tmp_path: Path) -> None:
    csv_path = tmp_path / "short.csv"
    csv_path.write_text(CSV_HEADER + CSV_ROW_1, encoding="utf-8")
    client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "SHORT"},
    )

    response = client.post(
        "/api/v1/backtest/run",
        json={"symbol": "SHORT", "sma_window": 3},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/backtest/reports
# ---------------------------------------------------------------------------


def test_backtest_reports_empty_returns_empty_list() -> None:
    response = client.get("/api/v1/backtest/reports")

    assert response.status_code == 200
    assert response.json() == {"reports": []}


def test_backtest_reports_after_run_returns_summaries(tmp_path: Path) -> None:
    _load_btc_bars(tmp_path)
    client.post(
        "/api/v1/backtest/run",
        json={"symbol": "BTC-USD", "sma_window": 2},
    )
    client.post(
        "/api/v1/backtest/run",
        json={"symbol": "BTC-USD", "sma_window": 3},
    )

    response = client.get("/api/v1/backtest/reports")
    assert response.status_code == 200
    body = response.json()
    assert len(body["reports"]) == 2
    ids = {r["report_id"] for r in body["reports"]}
    assert len(ids) == 2  # unique report IDs


# ---------------------------------------------------------------------------
# GET /api/v1/backtest/report/{report_id}
# ---------------------------------------------------------------------------


def test_backtest_get_report_returns_full_report(tmp_path: Path) -> None:
    _load_btc_bars(tmp_path)
    run_resp = client.post(
        "/api/v1/backtest/run",
        json={"symbol": "BTC-USD", "sma_window": 3},
    )
    report_id = run_resp.json()["report_id"]

    response = client.get(f"/api/v1/backtest/report/{report_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["report_id"] == report_id
    assert body["symbol"] == "BTC-USD"
    assert len(body["equity_curve"]) == 5  # 5 bars loaded


def test_backtest_get_report_not_found_returns_404() -> None:
    response = client.get("/api/v1/backtest/report/nonexistent")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/brief/generate
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# GET /api/v1/brief/history
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# GET /api/v1/brief/{brief_id}
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# GET /api/v1/paper/portfolio
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# GET /api/v1/paper/orders
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# POST /api/v1/paper/orders
# ---------------------------------------------------------------------------


def _load_spy_bars(tmp_path: Path, close: str = "90.0") -> None:
    """Load a minimal SPY bar set so the paper route can resolve a mark price.

    R21.1: the paper order route fails closed with ``missing_mark_price``
    when no bars are stored for the symbol, so any test that submits a SPY
    order must first seed stored bars. The OHLC values scale from the
    chosen close so the ``Bar`` validator (low <= open/high/close) holds.
    The default close ($90) sits under the $100/order policy cap so the
    order-value check passes and downstream limits (human review, total
    exposure) are the ones exercised.
    """
    c = Decimal(close)
    csv_path = _write_csv(
        tmp_path / "spy.csv",
        (
            "timestamp,open,high,low,close,volume\n"
            f"2026-06-12T09:30:00,{c},{c + Decimal('5')},{c - Decimal('2')},"
            f"{c},1000.0\n"
        ),
    )
    resp = client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "SPY", "source": "test"},
    )
    assert resp.status_code == 201, resp.text


def _load_eur_usd_bars(tmp_path: Path, close: str = "1.14") -> None:
    """Load a minimal EUR_USD bar set for OANDA-default paper-order tests."""
    c = Decimal(close)
    csv_path = _write_csv(
        tmp_path / "eur_usd.csv",
        (
            "timestamp,open,high,low,close,volume\n"
            f"2026-06-12T09:30:00,{c},{c + Decimal('0.01')},"
            f"{c - Decimal('0.01')},{c},1000.0\n"
        ),
    )
    resp = client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "EUR_USD", "source": "test"},
    )
    assert resp.status_code == 201, resp.text








# ---------------------------------------------------------------------------
# GET /api/v1/paper/audit
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# GET /api/v1/risk/config
# ---------------------------------------------------------------------------


def test_risk_config_returns_200() -> None:
    response = client.get("/api/v1/risk/config")

    assert response.status_code == 200
    body = response.json()
    assert body["trading_enabled"] is True
    assert body["live_trading_enabled"] is False
    assert body["enabled_strategies"] == []
    # The reviewed boundary is the five FX majors the practice account
    # can actually trade; signal-only symbols are never orderable.
    assert body["symbol_allowlist"] == sorted([
        "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD",
    ])
    # Caps are USD notional; auto-execution is enabled.
    assert body["max_order_value"] == "2000"
    # Phase 19: the runtime account-exposure cap from PaperExecutionPolicy.
    assert body["max_total_exposure"] == "20000"
    assert body["require_human_review"] is False
    # Phase 21 R21.2/R21.3 fields are surfaced with paper defaults.
    assert body["max_symbol_exposure"] == "20000"
    assert body["max_concentration_pct"] == "1.0"
    assert body["max_leverage"] == "1.0"
    assert body["max_price_deviation_pct"] == "0.05"
    assert body["max_signal_age_seconds"] == 300
    assert body["require_market_open"] is False
    assert body["duplicate_order_window_seconds"] == 30
    assert body["duplicate_order_max_count"] == 1
    assert body["max_daily_loss_pct"] == "0.05"
    assert body["max_drawdown_floor_pct"] == "0.10"


# ---------------------------------------------------------------------------
# GET /api/v1/risk/dashboard
# ---------------------------------------------------------------------------


def test_risk_dashboard_returns_200() -> None:
    response = client.get("/api/v1/risk/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert "kill_switch_active" in body
    assert "config" in body
    assert body["kill_switch_active"] is False
    assert body["config"]["trading_enabled"] is True


# ---------------------------------------------------------------------------
# GET /api/v1/risk/context
# ---------------------------------------------------------------------------


def _seed_negative_news(symbol: str = "AAPL") -> None:
    """Helper: insert a single negative-sentiment headline."""
    from alphabrief_api.routes.news import _get_store as news_store

    store = news_store()
    store.insert_headlines(
        [
            NewsHeadline(
                headline_id="h_neg_1",
                published_at=datetime(2026, 6, 14, 9, 0, tzinfo=UTC),
                symbols=[symbol],
                category="earnings",
                source="unit-test",
                title=f"{symbol} faces lawsuit",
                sentiment="negative",
                data_version="news-v1",
            ),
            NewsHeadline(
                headline_id="h_neg_2",
                published_at=datetime(2026, 6, 14, 10, 0, tzinfo=UTC),
                symbols=[symbol],
                category="earnings",
                source="unit-test",
                title=f"{symbol} misses estimates",
                sentiment="negative",
                data_version="news-v1",
            ),
        ],
    )


def _seed_high_macro_indicators(count: int = 6) -> None:
    """Helper: insert many macro indicators to trigger the high-macro rule."""
    from alphabrief_api.routes.macro import _get_store as macro_store

    store = macro_store()
    indicators = [
        MacroIndicator(
            indicator_id=f"fred:I{i}",
            name=f"Indicator {i}",
            country="US",
            released_at=datetime(2026, 6, 14, 9, 0, tzinfo=UTC),
            period="2026-05",
            value=Decimal("1"),
            unit="index",
            source="unit-test",
            data_version="macro-v1",
        )
        for i in range(count)
    ]
    store.insert_indicators(indicators)


def test_risk_context_empty_stores_returns_neutral_decision() -> None:
    response = client.get("/api/v1/risk/context")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["headline_count"] == 0
    assert body["summary"]["untrusted"] is True
    assert body["decision"]["requires_human_review"] is False
    assert body["decision"]["risk_tags"] == []
    assert body["decision"]["suggested_max_position_multiplier"] == 1.0
    assert body["decision"]["source_summary_untrusted"] is True
    assert "gate" in body
    assert body["kill_switch_active"] is False
    assert "query" in body


def test_risk_context_with_negative_news_flips_human_review() -> None:
    _seed_negative_news()

    response = client.get(
        "/api/v1/risk/context?symbols=AAPL&decision_id=rctx_api_neg",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["headline_count"] == 2
    assert body["summary"]["negative_count"] == 2
    assert body["decision"]["requires_human_review"] is True
    assert "negative_news_context" in body["decision"]["risk_tags"]
    assert "requires_human_review" in body["decision"]["risk_tags"]
    assert body["decision"]["decision_id"] == "rctx_api_neg"


def test_risk_context_with_high_macro_suggests_position_reduction() -> None:
    _seed_high_macro_indicators(count=6)

    single_response = client.get(
        "/api/v1/risk/context?macro_indicators=fred:I0&decision_id=rctx_api_macro",
    )
    assert single_response.status_code == 200
    single_body = single_response.json()
    assert "macro_high_risk" not in single_body["decision"]["risk_tags"]

    all_response = client.get(
        "/api/v1/risk/context?macro_indicators=fred:I0,fred:I1,fred:I2,"
        "fred:I3,fred:I4,fred:I5&decision_id=rctx_api_macro_all",
    )
    assert all_response.status_code == 200
    all_body = all_response.json()
    assert "decision" in all_body
    assert all_body["query"]["macro_indicators"] == [
        "fred:I0",
        "fred:I1",
        "fred:I2",
        "fred:I3",
        "fred:I4",
        "fred:I5",
    ]


def test_risk_context_rejects_inverted_window() -> None:
    response = client.get(
        "/api/v1/risk/context?start=2026-06-15T00:00:00Z&end=2026-06-14T00:00:00Z",
    )

    assert response.status_code == 422
    assert "start" in response.json()["detail"]


def test_risk_context_limit_too_large_returns_422() -> None:
    response = client.get("/api/v1/risk/context?limit=999")

    assert response.status_code == 422


def test_risk_context_echoes_query_for_audit() -> None:
    response = client.get(
        "/api/v1/risk/context?symbols=AAPL,MSFT&limit=10&decision_id=rctx_echo",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"]["symbols"] == ["AAPL", "MSFT"]
    assert body["query"]["limit"] == 10
    assert body["query"]["decision_id"] == "rctx_echo"


def test_risk_context_does_not_modify_risk_gate() -> None:
    before = client.get("/api/v1/risk/config").json()
    client.get("/api/v1/risk/context")
    after = client.get("/api/v1/risk/config").json()

    assert before == after


# ---------------------------------------------------------------------------
# GET /api/v1/review/snapshot
# ---------------------------------------------------------------------------


def test_review_snapshot_returns_200() -> None:
    response = client.get("/api/v1/review/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert "snapshot_id" in body
    assert "strategies" in body
    assert "backtests" in body
    assert "daily_briefs" in body
    assert "paper_portfolio" in body
    assert "risk_dashboard" in body


# ---------------------------------------------------------------------------
# GET /api/v1/review/journal
# ---------------------------------------------------------------------------


def test_review_journal_returns_200() -> None:
    response = client.get("/api/v1/review/journal")

    assert response.status_code == 200
    body = response.json()
    assert "entries" in body
    assert isinstance(body["entries"], list)


# ---------------------------------------------------------------------------
# GET /api/v1/review/journal/daily
# ---------------------------------------------------------------------------


def test_review_journal_daily_returns_200() -> None:
    response = client.get("/api/v1/review/journal/daily?trading_day=2026-06-14")

    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "daily"
    assert "title" in body
    assert "summary" in body
    assert "highlights" in body


def test_review_journal_daily_invalid_date_returns_422() -> None:
    response = client.get("/api/v1/review/journal/daily?trading_day=not-a-date")

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/review/journal/weekly
# ---------------------------------------------------------------------------


def test_review_journal_weekly_returns_200() -> None:
    response = client.get("/api/v1/review/journal/weekly?week_start=2026-06-08")

    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "weekly"
    assert "title" in body
    assert "summary" in body
    assert "highlights" in body


def test_review_journal_weekly_invalid_date_returns_422() -> None:
    response = client.get("/api/v1/review/journal/weekly?week_start=bad-date")

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Static dashboard and dashboard redirect (PROJECT_GUIDE 4.7)
# ---------------------------------------------------------------------------


def test_static_dashboard_returns_200_and_html() -> None:
    response = client.get("/")
    assert response.status_code == 200
    content = response.text
    assert "<!DOCTYPE html>" in content
    assert "AlphaBrief" in content
    assert "design-tokens.css" in content
    assert "app.js" in content


def test_dashboard_redirects_to_static() -> None:
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code in (307, 302)
    assert response.headers["location"] == "/"

    response_news = client.get("/dashboard/news", follow_redirects=False)
    assert response_news.status_code in (307, 302)
    assert response_news.headers["location"] == "/#news"


def test_evaluation_scoreboard_endpoint_returns_200() -> None:
    response = client.get("/api/v1/evaluation/scoreboard")
    assert response.status_code == 200
    assert "scoreboard" in response.json()


def test_settings_overview_endpoint_returns_200() -> None:
    response = client.get("/api/v1/settings/overview")
    assert response.status_code == 200
    body = response.json()
    assert "credentials" in body
    assert "service" in body
    assert "paths" in body


def test_doctor_run_endpoint_returns_200() -> None:
    response = client.get("/api/v1/doctor/run?offline=true")
    assert response.status_code == 200
    body = response.json()
    assert "ok" in body
    assert "results" in body






def test_api_docs_accessible() -> None:
    response = client.get("/docs")

    assert response.status_code == 200


def test_redoc_accessible() -> None:
    response = client.get("/redoc")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/research/debate
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# GET /api/v1/research/debate
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# GET /api/v1/research/debate/{debate_id}
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# POST /api/v1/data/fetch — Phase 9 real market data providers
# ---------------------------------------------------------------------------




















# ---------------------------------------------------------------------------
# News routes
# ---------------------------------------------------------------------------




def test_news_fetch_rss_with_injected_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    xml = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel><title>Injected</title>
    <item>
      <title>Injected headline</title>
      <description>desc</description>
      <pubDate>Mon, 03 Jun 2024 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

    def fake_get(request: Any, timeout: float) -> bytes:
        return xml

    import alphabrief_news.providers.rss as rss_mod

    monkeypatch.setattr(rss_mod, "_default_http_get", fake_get)

    response = client.post(
        "/api/v1/news/fetch",
        json={
            "source": "rss",
            "symbols": ["marketwatch-rss"],
            "start": "2024-06-01T00:00:00",
            "end": "2024-06-05T00:00:00",
        },
    )
    assert response.status_code == 201
    assert response.json()["headline_count"] == 1


def test_news_fetch_unknown_source() -> None:
    response = client.post(
        "/api/v1/news/fetch",
        json={
            "source": "unknown",
            "symbols": ["AAPL"],
            "start": "2024-06-01T00:00:00",
            "end": "2024-06-02T00:00:00",
        },
    )
    assert response.status_code == 422










def test_news_get_headline_not_found() -> None:
    response = client.get("/api/v1/news/headlines/does-not-exist")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Macro routes
# ---------------------------------------------------------------------------




def test_macro_fetch_fred_with_explicit_api_key() -> None:

    previous = os.environ.pop("FRED_API_KEY", None)
    try:
        response = client.post(
            "/api/v1/macro/fetch",
            json={
                "source": "fred",
                "indicators": ["CPIAUCSL"],
                "start": "2024-06-01T00:00:00",
                "end": "2024-06-30T00:00:00",
            },
        )
        assert response.status_code == 422
    finally:
        if previous is not None:
            os.environ["FRED_API_KEY"] = previous


def test_macro_fetch_fred_returns_no_api_key() -> None:
    response = client.post(
        "/api/v1/macro/fetch",
        json={
            "source": "fred",
            "indicators": ["CPIAUCSL"],
            "start": "2024-06-01T00:00:00",
            "end": "2024-06-30T00:00:00",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "no_api_key"








def test_macro_get_indicator_not_found() -> None:
    response = client.get("/api/v1/macro/indicators/NOSUCH")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Phase 19 — account-level total-exposure enforcement (API path)
# ---------------------------------------------------------------------------


def _relaxed_exposure_gate(max_total_exposure: Decimal) -> None:
    """Reset the module-level risk gate to enforce the cap WITHOUT the
    default human-review block, so the exposure check is reachable on
    the auto-execution paper path.
    """
    _reset_risk_gate(
        RiskLimitConfig(
            trading_enabled=True,
            live_trading_enabled=False,
            symbol_allowlist=frozenset({"SPY"}),
            enabled_strategies=frozenset(),
            max_order_value=Decimal("200"),
            max_order_quantity=Decimal("10"),
            max_total_exposure=max_total_exposure,
            require_data_quality_passed=False,
            require_human_review=False,
        )
    )






def test_risk_check_enforces_cap_with_account_context() -> None:
    # The /risk/check endpoint accepts account_context and enforces the
    # runtime cap without needing the paper broker.
    _reset_risk_gate(
        RiskLimitConfig(
            trading_enabled=True,
            live_trading_enabled=False,
            symbol_allowlist=frozenset({"SPY"}),
            enabled_strategies=frozenset(),
            max_order_value=Decimal("200"),
            max_order_quantity=Decimal("10"),
            max_total_exposure=Decimal("300"),
            require_data_quality_passed=False,
            require_human_review=False,
        )
    )
    intent = {
        "intent_id": "intent_over",
        "source": "manual",
        "symbol": "SPY",
        "side": "buy",
        "order_type": "market",
        "quantity": "2",  # 2 * 100 = 200 new notional
        "rationale": "over cap",
        "created_at": "2026-06-23T10:00:00+00:00",
    }
    account_ctx = {
        "current_total_exposure": "200",  # existing 200 + 200 = 400 > 300
        "exposure_by_symbol": {"SPY": "200"},
        "cash": "800",
        "account_id": "acct_test",
        "captured_at": "2026-06-23T10:00:00+00:00",
    }
    response = client.post(
        "/api/v1/risk/check",
        json={
            "intent": intent,
            "estimated_price": "100",
            "account_context": account_ctx,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is False
    assert "max_total_exposure" in body["risk_tags"]


def test_risk_check_fail_closed_when_account_context_omitted() -> None:
    # max_total_exposure is configured (via _default_limits = $300) but
    # no account_context is supplied -> the gate fails closed.
    response = client.post(
        "/api/v1/risk/check",
        json={
            "intent": {
                "intent_id": "intent_no_ctx",
                "source": "manual",
                "symbol": "SPY",
                "side": "buy",
                "order_type": "market",
                "quantity": "1",
                "rationale": "no ctx",
                "created_at": "2026-06-23T10:00:00+00:00",
            },
            "estimated_price": "100",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is False
    assert "account_context_required" in body["risk_tags"]


# ---------------------------------------------------------------------------
# POST /api/v1/risk/check — Phase 21 R21.x account_context fields
# ---------------------------------------------------------------------------


def _r21_intent(symbol: str = "SPY") -> dict[str, object]:
    return {
        "intent_id": "intent_r21",
        "source": "manual",
        "symbol": symbol,
        "side": "buy",
        "order_type": "market",
        "quantity": "1",
        "rationale": "r21.x risk check",
        "created_at": "2026-06-23T10:00:00+00:00",
    }


def _r21_base_account_ctx() -> dict[str, object]:
    return {
        "current_total_exposure": "0",
        "exposure_by_symbol": {},
        "cash": "1000",
        "account_id": "acct_r21_api",
        "captured_at": "2026-06-23T10:00:00+00:00",
    }


def test_risk_check_accepts_equity_in_account_context() -> None:
    """``equity`` is part of ``AccountExposureContext`` and is
    transported end-to-end through the API without coercion to float."""
    response = client.post(
        "/api/v1/risk/check",
        json={
            "intent": _r21_intent(),
            "estimated_price": "100",
            "account_context": {
                **_r21_base_account_ctx(),
                "equity": "1000",
            },
        },
    )
    assert response.status_code == 200


def test_risk_check_accepts_reference_mark_prices_in_account_context() -> None:
    """``reference_mark_prices`` carries live marks for the
    price-deviation check; transported as a dict of Decimal strings."""
    response = client.post(
        "/api/v1/risk/check",
        json={
            "intent": _r21_intent(),
            "estimated_price": "100",
            "account_context": {
                **_r21_base_account_ctx(),
                "reference_mark_prices": {"SPY": "100"},
            },
        },
    )
    assert response.status_code == 200


def test_risk_check_accepts_equity_hwm_in_account_context() -> None:
    response = client.post(
        "/api/v1/risk/check",
        json={
            "intent": _r21_intent(),
            "estimated_price": "100",
            "account_context": {
                **_r21_base_account_ctx(),
                "equity": "1000",
                "equity_high_water_mark": "1200",
            },
        },
    )
    assert response.status_code == 200


def test_risk_check_accepts_day_start_equity_in_account_context() -> None:
    response = client.post(
        "/api/v1/risk/check",
        json={
            "intent": _r21_intent(),
            "estimated_price": "100",
            "account_context": {
                **_r21_base_account_ctx(),
                "equity": "950",
                "day_start_equity": "1000",
            },
        },
    )
    assert response.status_code == 200


def test_risk_check_account_context_rejects_float_equity() -> None:
    """``AccountExposureContext`` rejects ``float`` decimal inputs at
    the Pydantic boundary; the API must surface this as a 422."""
    response = client.post(
        "/api/v1/risk/check",
        json={
            "intent": _r21_intent(),
            "estimated_price": "100",
            "account_context": {
                **_r21_base_account_ctx(),
                "equity": 1000.0,
            },
        },
    )
    assert response.status_code == 422
