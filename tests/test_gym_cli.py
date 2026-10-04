"""Automated tests for S7: Gym demo CLI on stored OANDA bars.

Verifies:
- alphabrief gym demo runs an episode on stored OANDA bars.
- Zero broker orders placed (offline simulation only).
- Output contains episode metrics.
- Missing bars returns actionable error message.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db import MarketDataStore
from alphabrief_cli.main import app
from alphabrief_core import Bar
from typer.testing import CliRunner

runner = CliRunner()


def _seed_bars(
    store: MarketDataStore, symbol: str = "EUR_USD", count: int = 40
) -> None:
    base_time = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    bars: list[Bar] = []
    price = Decimal("1.1000")
    for i in range(count):
        ts = base_time + timedelta(hours=i)
        close = price + Decimal("0.0005") if i % 2 == 0 else price - Decimal("0.0003")
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=ts,
                open=price,
                high=max(price, close) + Decimal("0.0005"),
                low=min(price, close) - Decimal("0.0005"),
                close=close,
                volume=Decimal("100"),
                source="oanda_practice",
                data_version="oanda-candles-v1:M:H1",
            )
        )
        price = close

    store.insert_bars(
        bars=bars,
        source="oanda_practice",
        data_version="oanda-candles-v1:M:H1",
    )


def test_gym_demo_runs_episode_on_oanda_bars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "alphabrief_test.duckdb"
    monkeypatch.setattr("alphabrief_core.paths.db_path", lambda: db_file)

    mstore = MarketDataStore(db_path=db_file)
    try:
        _seed_bars(mstore, "EUR_USD", count=30)
    finally:
        mstore.close()

    result = runner.invoke(
        app, ["gym", "demo", "--instrument", "EUR_USD", "--granularity", "H1"]
    )
    assert result.exit_code == 0, f"Error: {result.output}"
    data = json.loads(result.output)
    assert data["status"] == "completed"
    assert data["mode"] == "gym_offline_simulation"
    assert data["live_trading"] is False
    assert data["instrument"] == "EUR_USD"
    assert data["bar_count"] == 30
    assert data["steps"] == 29
    assert "total_return" in data
    assert "max_drawdown" in data
    assert "zero broker orders placed" in data["execution_note"]


def test_gym_demo_fails_when_no_bars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "alphabrief_test.duckdb"
    monkeypatch.setattr("alphabrief_core.paths.db_path", lambda: db_file)

    result = runner.invoke(app, ["gym", "demo", "--instrument", "GBP_USD"])
    assert result.exit_code != 0
    assert "No stored OANDA bars found" in result.output
