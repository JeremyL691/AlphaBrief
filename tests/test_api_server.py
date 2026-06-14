"""Tests for the AlphaBrief API server."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.main import app
from alphabrief_api.routes.backtest import _clear_reports
from alphabrief_api.routes.brief import _clear_briefs
from alphabrief_api.routes.data import _close_store
from alphabrief_api.routes.paper import _reset_broker
from alphabrief_api.routes.risk import _reset_risk_gate
from alphabrief_data import ParquetBarLoader
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
    _clear_reports()
    _clear_briefs()
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


def test_api_docs_accessible() -> None:
    response = client.get("/docs")

    assert response.status_code == 200


def test_redoc_accessible() -> None:
    response = client.get("/redoc")

    assert response.status_code == 200
