"""Tests for the AlphaBrief API server."""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_api.main import app
from alphabrief_api.routes.data import _clear_store
from alphabrief_data import ParquetBarLoader
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_data_store() -> None:
    """Clear the in-memory data store before every test."""
    _clear_store()


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
    assert bar["close"] == "105.0"


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
