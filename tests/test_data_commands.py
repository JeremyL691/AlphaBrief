"""Tests for the data CLI commands.

These tests cover the new ``alphabrief data fetch`` subcommand plus
the existing ``import`` and ``check`` subcommands. The fetch tests
inject fake HTTP callables into the provider modules so no real
network request is made.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import alphabrief_data.providers.binance as binance_mod
import alphabrief_data.providers.yahoo as yahoo_mod
import pytest
from alphabrief_cli.data_commands import data_app
from typer.testing import CliRunner

runner = CliRunner()

CSV_HEADER = "timestamp,open,high,low,close,volume\n"
CSV_ROW_1 = "2026-06-12T09:30:00,100,110,95,105,1\n"
CSV_ROW_2 = "2026-06-12T09:31:00,105,112,101,111,2\n"


def _write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Existing commands (regression coverage)
# ---------------------------------------------------------------------------


def test_data_import_loads_csv(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "btc.csv", CSV_HEADER + CSV_ROW_1 + CSV_ROW_2
    )

    result = runner.invoke(
        data_app,
        [
            "import",
            "--file",
            str(csv_path),
            "--symbol",
            "BTC-USD",
            "--source",
            "csv-test",
            "--data-version",
            "v1",
        ],
    )

    assert result.exit_code == 0
    assert "Loaded 2 bars" in result.output


def test_data_import_missing_file_fails(tmp_path: Path) -> None:
    result = runner.invoke(
        data_app,
        [
            "import",
            "--file",
            str(tmp_path / "missing.csv"),
            "--symbol",
            "BTC-USD",
            "--source",
            "csv-test",
            "--data-version",
            "v1",
        ],
    )
    assert result.exit_code != 0
    assert "failed" in result.output.lower()


def test_data_check_reports_passed_for_valid_csv(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "bars.csv", CSV_HEADER + CSV_ROW_1)

    result = runner.invoke(
        data_app,
        [
            "check",
            "--file",
            str(csv_path),
            "--symbol",
            "BTC-USD",
            "--source",
            "csv-test",
            "--data-version",
            "v1",
        ],
    )

    assert result.exit_code == 0
    assert "PASSED" in result.output


# ---------------------------------------------------------------------------
# `data fetch` — Yahoo
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


@pytest.fixture
def _isolated_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None, None, None]:
    """Point the MarketDataStore at a per-test temp directory."""
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path / "alphabrief_db"))
    yield


def test_data_fetch_yahoo_success(
    monkeypatch: pytest.MonkeyPatch, _isolated_data_dir: None
) -> None:
    base_ts = 1_704_067_200
    payload = _yahoo_payload(
        timestamps=[base_ts, base_ts + 86_400],
        opens=[100.0, 101.0],
        highs=[110.0, 111.0],
        lows=[95.0, 96.0],
        closes=[105.0, 106.0],
        volumes=[1234.0, 1500.0],
    )
    monkeypatch.setattr(yahoo_mod, "_default_http_get", lambda _req, _t: payload)

    result = runner.invoke(
        data_app,
        [
            "fetch",
            "--source",
            "yahoo",
            "--symbol",
            "AAPL",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-03",
            "--interval",
            "1d",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Fetched and stored 2 bars" in result.output
    assert "AAPL" in result.output
    assert "yahoo" in result.output


def test_data_fetch_binance_success(
    monkeypatch: pytest.MonkeyPatch, _isolated_data_dir: None
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

    result = runner.invoke(
        data_app,
        [
            "fetch",
            "--source",
            "binance",
            "--symbol",
            "BTCUSDT",
            "--start",
            "2024-01-01T00:00:00Z",
            "--end",
            "2024-01-03T00:00:00Z",
            "--interval",
            "1d",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Fetched and stored 1 bars" in result.output
    assert "BTCUSDT" in result.output
    assert "binance" in result.output


def test_data_fetch_unknown_source_fails() -> None:
    result = runner.invoke(
        data_app,
        [
            "fetch",
            "--source",
            "fakedata",
            "--symbol",
            "AAPL",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-03",
        ],
    )
    assert result.exit_code != 0
    assert "data fetch failed" in result.output.lower()


def test_data_fetch_invalid_date_fails() -> None:
    result = runner.invoke(
        data_app,
        [
            "fetch",
            "--source",
            "yahoo",
            "--symbol",
            "AAPL",
            "--start",
            "not-a-date",
            "--end",
            "2024-01-03",
        ],
    )
    assert result.exit_code != 0
    assert "data fetch failed" in result.output.lower()


def test_data_fetch_empty_response_fails(
    monkeypatch: pytest.MonkeyPatch, _isolated_data_dir: None
) -> None:
    payload = json.dumps({"chart": {"result": [], "error": None}}).encode("utf-8")
    monkeypatch.setattr(yahoo_mod, "_default_http_get", lambda _req, _t: payload)

    result = runner.invoke(
        data_app,
        [
            "fetch",
            "--source",
            "yahoo",
            "--symbol",
            "AAPL",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-03",
        ],
    )
    assert result.exit_code != 0
    assert "0 bars" in result.output.lower()


def test_data_fetch_lowercase_binance_symbol_fails(
    monkeypatch: pytest.MonkeyPatch, _isolated_data_dir: None
) -> None:
    """Binance requires uppercase symbols — the CLI surfaces this clearly."""
    monkeypatch.setattr(
        binance_mod, "_default_http_get", lambda _req, _t: _binance_payload([])
    )

    result = runner.invoke(
        data_app,
        [
            "fetch",
            "--source",
            "binance",
            "--symbol",
            "btcusdt",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-03",
        ],
    )
    assert result.exit_code != 0
    assert "uppercase" in result.output.lower()


# ---------------------------------------------------------------------------
# `news` CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def _isolated_news_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None, None, None]:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path / "alphabrief_db"))
    yield


def test_news_fetch_mock_success(_isolated_news_dir: None) -> None:
    from alphabrief_cli.news_commands import news_app

    result = runner.invoke(
        news_app,
        [
            "fetch",
            "--source", "mock",
            "--symbol", "AAPL",
            "--start", "2024-06-01T00:00:00",
            "--end", "2024-06-02T00:00:00",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Fetched 1 headlines" in result.output


def test_news_fetch_lowercase_symbol_fails(_isolated_news_dir: None) -> None:
    from alphabrief_cli.news_commands import news_app

    result = runner.invoke(
        news_app,
        [
            "fetch",
            "--source", "mock",
            "--symbol", "aapl",
            "--start", "2024-06-01T00:00:00",
            "--end", "2024-06-02T00:00:00",
        ],
    )
    assert result.exit_code != 0
    assert "uppercase" in result.output.lower()


def test_news_fetch_invalid_date_fails(_isolated_news_dir: None) -> None:
    from alphabrief_cli.news_commands import news_app

    result = runner.invoke(
        news_app,
        [
            "fetch",
            "--source", "mock",
            "--symbol", "AAPL",
            "--start", "not-a-date",
            "--end", "2024-06-02T00:00:00",
        ],
    )
    assert result.exit_code != 0


def test_news_list_after_fetch(_isolated_news_dir: None) -> None:
    from alphabrief_cli.news_commands import news_app

    runner.invoke(
        news_app,
        [
            "fetch",
            "--source", "mock",
            "--symbol", "AAPL",
            "--start", "2024-06-01T00:00:00",
            "--end", "2024-06-02T00:00:00",
        ],
    )
    result = runner.invoke(news_app, ["list"])
    assert result.exit_code == 0
    assert "AAPL" in result.output


def test_news_fetch_empty_window_fails(_isolated_news_dir: None) -> None:
    from alphabrief_cli.news_commands import news_app

    result = runner.invoke(
        news_app,
        [
            "fetch",
            "--source", "mock",
            "--symbol", "AAPL",
            "--start", "2023-01-01T00:00:00",
            "--end", "2023-01-02T00:00:00",
        ],
    )
    assert result.exit_code != 0
    assert "No headlines" in result.output


# ---------------------------------------------------------------------------
# `macro` CLI
# ---------------------------------------------------------------------------


def test_macro_fetch_mock_success(_isolated_news_dir: None) -> None:
    from alphabrief_cli.macro_commands import macro_app

    result = runner.invoke(
        macro_app,
        [
            "fetch",
            "--source", "mock",
            "--indicator", "CPIAUCSL",
            "--start", "2024-06-01T00:00:00",
            "--end", "2024-06-30T00:00:00",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Fetched 1 indicator" in result.output


def test_macro_fetch_fred_fails_with_no_api_key(_isolated_news_dir: None) -> None:
    from alphabrief_cli.macro_commands import macro_app

    result = runner.invoke(
        macro_app,
        [
            "fetch",
            "--source", "fred",
            "--indicator", "CPIAUCSL",
            "--start", "2024-06-01T00:00:00",
            "--end", "2024-06-30T00:00:00",
        ],
    )
    assert result.exit_code != 0
    assert "no_api_key" in result.output


def test_macro_fetch_invalid_date_fails(_isolated_news_dir: None) -> None:
    from alphabrief_cli.macro_commands import macro_app

    result = runner.invoke(
        macro_app,
        [
            "fetch",
            "--source", "mock",
            "--indicator", "CPIAUCSL",
            "--start", "2024-06-01T00:00:00",
            "--end", "bad-date",
        ],
    )
    assert result.exit_code != 0


def test_macro_list_after_fetch(_isolated_news_dir: None) -> None:
    from alphabrief_cli.macro_commands import macro_app

    runner.invoke(
        macro_app,
        [
            "fetch",
            "--source", "mock",
            "--indicator", "CPIAUCSL",
            "--start", "2024-06-01T00:00:00",
            "--end", "2024-06-30T00:00:00",
        ],
    )
    result = runner.invoke(macro_app, ["list"])
    assert result.exit_code == 0
    assert "CPIAUCSL" in result.output
