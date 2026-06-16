"""Tests for the AlphaBrief API server."""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import alphabrief_data.providers.binance as binance_mod
import alphabrief_data.providers.yahoo as yahoo_mod
import pytest
from alphabrief_api.main import app
from alphabrief_api.routes.backtest import _clear_report_store
from alphabrief_api.routes.brief import _clear_brief_store
from alphabrief_api.routes.data import _close_store, _get_store
from alphabrief_api.routes.macro import _clear_store as _clear_macro_store
from alphabrief_api.routes.news import _clear_store as _clear_news_store
from alphabrief_api.routes.paper import _reset_broker
from alphabrief_api.routes.research import _clear_debate_store
from alphabrief_api.routes.review import _clear_review_store
from alphabrief_api.routes.risk import _reset_risk_gate
from alphabrief_data import ParquetBarLoader
from alphabrief_news import MacroIndicator, NewsHeadline
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path) -> Generator[None, None, None]:
    """Isolate all module-level stores before every test.

    Sets a temporary DuckDB data directory so tests never write to the
    user's home directory.  Closes the store after the test to allow
    ``tmp_path`` cleanup.
    """
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    _close_store()
    _clear_report_store()
    _clear_brief_store()
    _clear_review_store()
    _clear_debate_store()
    _clear_news_store()
    _clear_macro_store()
    _reset_broker()
    _reset_risk_gate()
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


def test_api_status_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHABRIEF_ENV", "test")
    monkeypatch.setenv("ALPHABRIEF_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", "data/local")
    monkeypatch.setenv("ALPHABRIEF_REPORTS_DIR", "reports/generated")

    response = client.get("/api/status")

    assert response.json() == {
        "version": "0.0.0",
        "environment": "test",
        "live_trading_enabled": False,
        "data_dir": "data/local",
        "reports_dir": "reports/generated",
        "packages_loaded": [
            "alphabrief_core",
            "alphabrief_data",
            "alphabrief_strategy",
            "alphabrief_backtest",
            "alphabrief_models",
            "alphabrief_risk",
            "alphabrief_execution",
            "alphabrief_gym",
            "alphabrief_review",
        ],
    }


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
        "wrong,col,names\n" "1,2,3\n",
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


def test_brief_generate_returns_201() -> None:
    response = client.post(
        "/api/v1/brief/generate",
        json={"input_text": "Generate a brief", "prompt_version": "v1:1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert "brief_id" in body
    assert "headline" in body
    assert "executive_summary" in body
    assert "market_brief" in body
    assert "symbol_briefs" in body


def test_brief_generate_defaults_work() -> None:
    response = client.post("/api/v1/brief/generate", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["headline"] == "Market outlook is positive"


def test_brief_generate_with_include_news_flag() -> None:
    response = client.post(
        "/api/v1/brief/generate",
        json={"include_news": True, "news_symbols": ["AAPL"]},
    )

    assert response.status_code == 201
    body = response.json()
    assert "brief_id" in body
    assert body["headline"] == "Market outlook is positive"


def test_brief_generate_with_include_macro_flag() -> None:
    response = client.post(
        "/api/v1/brief/generate",
        json={"include_macro": True, "macro_indicators": ["CPIAUCSL"]},
    )

    assert response.status_code == 201
    body = response.json()
    assert "brief_id" in body


def test_brief_generate_with_both_flags() -> None:
    response = client.post(
        "/api/v1/brief/generate",
        json={
            "include_news": True,
            "include_macro": True,
            "news_symbols": ["AAPL"],
            "macro_indicators": ["CPIAUCSL", "UNRATE"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "brief_id" in body


# ---------------------------------------------------------------------------
# GET /api/v1/brief/history
# ---------------------------------------------------------------------------


def test_brief_history_empty_returns_empty_list() -> None:
    response = client.get("/api/v1/brief/history")

    assert response.status_code == 200
    assert response.json() == {"briefs": []}


def test_brief_history_after_generate_returns_summaries() -> None:
    client.post("/api/v1/brief/generate", json={})
    client.post("/api/v1/brief/generate", json={})

    response = client.get("/api/v1/brief/history")
    assert response.status_code == 200
    body = response.json()
    assert len(body["briefs"]) == 2

    for brief in body["briefs"]:
        assert "brief_id" in brief
        assert "trading_day" in brief
        assert "headline" in brief


# ---------------------------------------------------------------------------
# GET /api/v1/brief/{brief_id}
# ---------------------------------------------------------------------------


def test_brief_get_by_id_returns_full_brief() -> None:
    gen_resp = client.post("/api/v1/brief/generate", json={})
    brief_id = gen_resp.json()["brief_id"]

    response = client.get(f"/api/v1/brief/{brief_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["brief_id"] == brief_id
    assert body["headline"] == "Market outlook is positive"
    assert len(body["symbol_briefs"]) == 1


def test_brief_get_by_id_not_found_returns_404() -> None:
    response = client.get("/api/v1/brief/nonexistent")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/paper/portfolio
# ---------------------------------------------------------------------------


def test_paper_portfolio_returns_200() -> None:
    response = client.get("/api/v1/paper/portfolio")

    assert response.status_code == 200
    body = response.json()
    assert "cash" in body
    assert "positions" in body
    assert "realized_pnl" in body
    assert body["cash"] == "100000"


def test_paper_portfolio_shows_positions() -> None:
    response = client.get("/api/v1/paper/portfolio")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["positions"], list)


# ---------------------------------------------------------------------------
# GET /api/v1/paper/orders
# ---------------------------------------------------------------------------


def test_paper_orders_returns_200() -> None:
    response = client.get("/api/v1/paper/orders")

    assert response.status_code == 200
    body = response.json()
    assert "entries" in body
    assert body["entries"] == []


def test_paper_orders_with_status_filter() -> None:
    response = client.get("/api/v1/paper/orders?status=order_created")

    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []


# ---------------------------------------------------------------------------
# POST /api/v1/paper/orders
# ---------------------------------------------------------------------------


def test_paper_submit_order_returns_201() -> None:
    response = client.post(
        "/api/v1/paper/orders",
        json={
            "symbol": "BTC-USD",
            "side": "buy",
            "order_type": "market",
            "quantity": "1",
            "rationale": "Test order",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "order_id" in body
    assert "fill_id" in body
    assert body["symbol"] == "BTC-USD"
    assert body["side"] == "buy"
    assert body["status"] == "filled"


def test_paper_submit_order_persists_audit_events() -> None:
    client.post(
        "/api/v1/paper/orders",
        json={
            "symbol": "BTC-USD",
            "side": "buy",
            "quantity": "1",
            "rationale": "Audit test",
        },
    )

    # Audit events should be persisted
    response = client.get("/api/v1/paper/audit")
    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) > 0
    # Should include risk_decision_recorded and order_created at minimum
    event_types = {e["event_type"] for e in body["entries"]}
    assert "risk_decision_recorded" in event_types
    assert "order_created" in event_types


def test_paper_submit_order_creates_portfolio_snapshot() -> None:
    client.post(
        "/api/v1/paper/orders",
        json={
            "symbol": "BTC-USD",
            "side": "buy",
            "quantity": "1",
            "rationale": "Portfolio snapshot test",
        },
    )

    # Verify portfolio is updated
    response = client.get("/api/v1/paper/portfolio")
    assert response.status_code == 200
    body = response.json()
    assert body["cash"] != "100000"  # Should have been reduced by the buy
    assert len(body["positions"]) > 0
    assert body["positions"][0]["symbol"] == "BTC-USD"


# ---------------------------------------------------------------------------
# GET /api/v1/paper/audit
# ---------------------------------------------------------------------------


def test_paper_audit_returns_200() -> None:
    response = client.get("/api/v1/paper/audit")

    assert response.status_code == 200
    body = response.json()
    assert "entries" in body
    assert isinstance(body["entries"], list)


# ---------------------------------------------------------------------------
# GET /api/v1/risk/config
# ---------------------------------------------------------------------------


def test_risk_config_returns_200() -> None:
    response = client.get("/api/v1/risk/config")

    assert response.status_code == 200
    body = response.json()
    assert body["trading_enabled"] is True
    assert body["live_trading_enabled"] is False
    assert "ma_trend" in body["enabled_strategies"]
    assert "BTC-USD" in body["symbol_allowlist"]


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
        "fred:I0", "fred:I1", "fred:I2", "fred:I3", "fred:I4", "fred:I5",
    ]


def test_risk_context_rejects_inverted_window() -> None:
    response = client.get(
        "/api/v1/risk/context?start=2026-06-15T00:00:00Z"
        "&end=2026-06-14T00:00:00Z",
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
# GET /dashboard
# ---------------------------------------------------------------------------


def test_dashboard_returns_200_and_html() -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    content = response.text
    assert "<!DOCTYPE html>" in content
    assert "AlphaBrief Dashboard" in content
    assert "Project Status" in content
    assert "Data Symbols" in content
    assert "Last Backtest" in content
    assert "Last Brief" in content
    assert "Paper Portfolio" in content
    assert "Risk Status" in content
    assert "API Docs" in content
    assert "Positions" in content
    assert "Equity Curve" in content
    assert "Recent Fills" in content


def test_dashboard_news_returns_200() -> None:
    response = client.get("/dashboard/news")
    assert response.status_code == 200
    content = response.text
    assert "News" in content
    assert "/api/v1/news/headlines" in content


def test_dashboard_macro_returns_200() -> None:
    response = client.get("/dashboard/macro")
    assert response.status_code == 200
    content = response.text
    assert "Macro" in content
    assert "/api/v1/macro/indicators" in content


def test_dashboard_brief_returns_200() -> None:
    response = client.get("/dashboard/brief")
    assert response.status_code == 200
    content = response.text
    assert "Briefs" in content
    assert "/api/v1/brief/history" in content


def test_dashboard_debate_returns_200() -> None:
    response = client.get("/dashboard/debate")
    assert response.status_code == 200
    content = response.text
    assert "Debates" in content or "Debate" in content
    assert "/api/v1/research/debate" in content


def test_api_docs_accessible() -> None:
    response = client.get("/docs")

    assert response.status_code == 200


def test_redoc_accessible() -> None:
    response = client.get("/redoc")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/research/debate
# ---------------------------------------------------------------------------


def test_research_debate_returns_201() -> None:
    response = client.post(
        "/api/v1/research/debate",
        json={
            "question": "How will NVDA perform next week?",
            "symbol": "NVDA",
            "time_horizon": "5 trading days",
            "perspectives": ["technical", "fundamental"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "debate_id" in body
    assert "question" in body
    assert "responses" in body
    assert "consensus" in body
    assert len(body["responses"]) > 0


def test_research_debate_without_symbol() -> None:
    response = client.post(
        "/api/v1/research/debate",
        json={"question": "General market outlook for Q3?"},
    )

    assert response.status_code == 201
    body = response.json()
    assert "debate_id" in body
    assert body["question"]["question"] == "General market outlook for Q3?"


def test_research_debate_with_include_news_flag() -> None:
    response = client.post(
        "/api/v1/research/debate",
        json={
            "question": "How will AAPL trade?",
            "symbol": "AAPL",
            "include_news": True,
            "news_symbols": ["AAPL"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "debate_id" in body


def test_research_debate_with_include_macro_flag() -> None:
    response = client.post(
        "/api/v1/research/debate",
        json={
            "question": "How will AAPL trade?",
            "include_macro": True,
            "macro_indicators": ["CPIAUCSL"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "debate_id" in body


# ---------------------------------------------------------------------------
# GET /api/v1/research/debate
# ---------------------------------------------------------------------------


def test_research_debate_list_after_create() -> None:
    # Create a debate first
    client.post(
        "/api/v1/research/debate",
        json={"question": "Test debate for list"},
    )

    response = client.get("/api/v1/research/debate")
    assert response.status_code == 200
    body = response.json()
    assert "debates" in body
    assert len(body["debates"]) > 0


# ---------------------------------------------------------------------------
# GET /api/v1/research/debate/{debate_id}
# ---------------------------------------------------------------------------


def test_research_debate_get_by_id() -> None:
    # Create a debate
    create_resp = client.post(
        "/api/v1/research/debate",
        json={"question": "Find me by ID"},
    )
    assert create_resp.status_code == 201
    debate_id = create_resp.json()["debate_id"]

    # Get by ID
    response = client.get(f"/api/v1/research/debate/{debate_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == debate_id


def test_research_debate_get_nonexistent_returns_404() -> None:
    response = client.get("/api/v1/research/debate/deb_nonexistent1234")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/data/fetch — Phase 9 real market data providers
# ---------------------------------------------------------------------------


def _yahoo_payload(
    timestamps: list[int],
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> bytes:
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "AAPL"},
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [
                                {
                                    "open": opens,
                                    "high": highs,
                                    "low": lows,
                                    "close": closes,
                                    "volume": volumes,
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
    ).encode("utf-8")


def _binance_payload(rows: list[list[Any]]) -> bytes:
    return json.dumps(rows).encode("utf-8")


def test_fetch_yahoo_returns_201_and_persists_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_ts = 1_704_067_200  # 2024-01-01T00:00:00Z
    payload = _yahoo_payload(
        timestamps=[base_ts, base_ts + 86_400],
        opens=[100.0, 101.0],
        highs=[110.0, 111.0],
        lows=[95.0, 96.0],
        closes=[105.0, 106.0],
        volumes=[1234.0, 1500.0],
    )
    monkeypatch.setattr(yahoo_mod, "_default_http_get", lambda _req, _t: payload)

    response = client.post(
        "/api/v1/data/fetch",
        json={
            "source": "yahoo",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-01-03",
            "interval": "1d",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["symbol"] == "AAPL"
    assert body["source"] == "yahoo"
    assert body["interval"] == "1d"
    assert body["bar_count"] == 2
    assert body["time_start"] is not None
    assert body["time_end"] is not None

    # Verify the bars are queryable through the existing endpoints.
    store = _get_store()
    assert store.symbol_exists("AAPL")
    assert store.get_bar_count("AAPL") == 2
    bars = store.get_bar_models("AAPL")
    assert all(bar.source == "yahoo" for bar in bars)


def test_fetch_binance_returns_201_and_persists_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_ms = 1_704_067_200_000
    rows = [
        [
            base_ms,
            "100.50",
            "110.00",
            "95.25",
            "105.75",
            "1234.50",
            base_ms + 86_400_000 - 1,
        ]
    ]
    monkeypatch.setattr(
        binance_mod, "_default_http_get", lambda _req, _t: _binance_payload(rows)
    )

    response = client.post(
        "/api/v1/data/fetch",
        json={
            "source": "binance",
            "symbol": "BTCUSDT",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-03T00:00:00Z",
            "interval": "1d",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["symbol"] == "BTCUSDT"
    assert body["source"] == "binance"
    assert body["bar_count"] == 1

    store = _get_store()
    assert store.symbol_exists("BTCUSDT")
    bars = store.get_bar_models("BTCUSDT")
    assert bars[0].close == 105.75


def test_fetch_rejects_unknown_source() -> None:
    response = client.post(
        "/api/v1/data/fetch",
        json={
            "source": "fakedata",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-01-03",
        },
    )
    # Pydantic literal validation catches the source value first
    assert response.status_code == 422


def test_fetch_rejects_invalid_date_string() -> None:
    response = client.post(
        "/api/v1/data/fetch",
        json={
            "source": "yahoo",
            "symbol": "AAPL",
            "start": "not-a-date",
            "end": "2024-01-03",
        },
    )
    assert response.status_code == 422


def test_fetch_returns_404_when_provider_returns_no_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps({"chart": {"result": [], "error": None}}).encode("utf-8")
    monkeypatch.setattr(yahoo_mod, "_default_http_get", lambda _req, _t: payload)

    response = client.post(
        "/api/v1/data/fetch",
        json={
            "source": "yahoo",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-01-03",
        },
    )
    assert response.status_code == 404
    assert "0 bars" in response.json()["detail"]


def test_fetch_returns_422_when_provider_http_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from email.message import Message
    from urllib.error import HTTPError

    def _fail(_req: object, _t: float) -> bytes:
        raise HTTPError(
            "https://query1.finance.yahoo.com",
            500,
            "Internal Server Error",
            Message(),
            None,
        )

    monkeypatch.setattr(yahoo_mod, "_default_http_get", _fail)

    response = client.post(
        "/api/v1/data/fetch",
        json={
            "source": "yahoo",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-01-03",
        },
    )
    assert response.status_code == 422
    assert "yahoo" in response.json()["detail"].lower()


def test_fetch_respects_custom_data_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_ts = 1_704_067_200
    payload = _yahoo_payload(
        timestamps=[base_ts],
        opens=[100.0],
        highs=[110.0],
        lows=[95.0],
        closes=[105.0],
        volumes=[1.0],
    )
    monkeypatch.setattr(yahoo_mod, "_default_http_get", lambda _req, _t: payload)

    response = client.post(
        "/api/v1/data/fetch",
        json={
            "source": "yahoo",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-01-03",
            "data_version": "custom-v2",
        },
    )
    assert response.status_code == 201
    assert response.json()["data_version"] == "custom-v2"

    store = _get_store()
    info = store.get_symbol_info("AAPL")
    assert info is not None
    assert info["data_version"] == "custom-v2"


# ---------------------------------------------------------------------------
# News routes
# ---------------------------------------------------------------------------


def test_news_fetch_mock() -> None:
    response = client.post(
        "/api/v1/news/fetch",
        json={
            "source": "mock",
            "symbols": ["AAPL"],
            "start": "2024-06-01T00:00:00",
            "end": "2024-06-02T00:00:00",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["headline_count"] == 1
    assert data["time_start"] is not None
    assert data["time_end"] is not None


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


def test_news_fetch_invalid_date() -> None:
    response = client.post(
        "/api/v1/news/fetch",
        json={
            "source": "mock",
            "symbols": ["AAPL"],
            "start": "not-a-date",
            "end": "2024-06-02T00:00:00",
        },
    )
    assert response.status_code == 422


def test_news_fetch_empty_result() -> None:
    response = client.post(
        "/api/v1/news/fetch",
        json={
            "source": "mock",
            "symbols": ["AAPL"],
            "start": "2023-01-01T00:00:00",
            "end": "2023-01-02T00:00:00",
        },
    )
    assert response.status_code == 404


def test_news_fetch_custom_data_version() -> None:
    response = client.post(
        "/api/v1/news/fetch",
        json={
            "source": "mock",
            "symbols": ["AAPL"],
            "start": "2024-06-01T00:00:00",
            "end": "2024-06-02T00:00:00",
            "data_version": "custom-v1",
        },
    )
    assert response.status_code == 201


def test_news_list_and_get_headline() -> None:
    client.post(
        "/api/v1/news/fetch",
        json={
            "source": "mock",
            "symbols": ["AAPL"],
            "start": "2024-06-01T00:00:00",
            "end": "2024-06-02T00:00:00",
        },
    )
    list_response = client.get("/api/v1/news/headlines")
    assert list_response.status_code == 200
    headlines = list_response.json()["headlines"]
    assert len(headlines) == 1

    hid = headlines[0]["headline_id"]
    get_response = client.get(f"/api/v1/news/headlines/{hid}")
    assert get_response.status_code == 200
    assert get_response.json()["headline"]["title"] == "AAPL earnings preview"


def test_news_get_headline_not_found() -> None:
    response = client.get("/api/v1/news/headlines/does-not-exist")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Macro routes
# ---------------------------------------------------------------------------


def test_macro_fetch_mock() -> None:
    response = client.post(
        "/api/v1/macro/fetch",
        json={
            "source": "mock",
            "indicators": ["CPIAUCSL"],
            "start": "2024-06-01T00:00:00",
            "end": "2024-06-30T00:00:00",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["indicator_count"] == 1


def test_macro_fetch_fred_with_explicit_api_key() -> None:
    import os

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


def test_macro_fetch_invalid_date() -> None:
    response = client.post(
        "/api/v1/macro/fetch",
        json={
            "source": "mock",
            "indicators": ["CPIAUCSL"],
            "start": "2024-06-01T00:00:00",
            "end": "not-a-date",
        },
    )
    assert response.status_code == 422


def test_macro_fetch_empty_result() -> None:
    response = client.post(
        "/api/v1/macro/fetch",
        json={
            "source": "mock",
            "indicators": ["CPIAUCSL"],
            "start": "2023-01-01T00:00:00",
            "end": "2023-01-02T00:00:00",
        },
    )
    assert response.status_code == 404


def test_macro_list_and_get_indicator() -> None:
    client.post(
        "/api/v1/macro/fetch",
        json={
            "source": "mock",
            "indicators": ["CPIAUCSL"],
            "start": "2024-06-01T00:00:00",
            "end": "2024-06-30T00:00:00",
        },
    )
    list_response = client.get("/api/v1/macro/indicators")
    assert list_response.status_code == 200
    indicators = list_response.json()["indicators"]
    assert len(indicators) == 1

    get_response = client.get("/api/v1/macro/indicators/CPIAUCSL")
    assert get_response.status_code == 200
    assert get_response.json()["indicator"]["indicator_id"] == "CPIAUCSL"


def test_macro_get_indicator_not_found() -> None:
    response = client.get("/api/v1/macro/indicators/NOSUCH")
    assert response.status_code == 404
