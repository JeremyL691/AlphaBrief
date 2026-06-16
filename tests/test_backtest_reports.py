from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from alphabrief_api.db.backtest_reports import BacktestReportStore
from alphabrief_gym import (
    EnvV2AssetMetrics,
    EnvV2CostBreakdown,
    EnvV2Report,
    env_v2_report_to_dict,
)


def _make_legacy_report(
    *,
    symbol: str = "BTC",
    strategy_id: str = "ma_trend",
) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
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


def _make_env_v2_report(*, report_id: str = "envv2_test_001") -> dict[str, Any]:
    report = EnvV2Report(
        report_id=report_id,
        environment="alphabrief_gym_v2",
        steps=12,
        initial_value=Decimal("10000"),
        final_value=Decimal("10125.50"),
        total_return=Decimal("0.01255"),
        max_drawdown=Decimal("0.018"),
        trade_count=4,
        final_leverage=Decimal("1.25"),
        costs=EnvV2CostBreakdown(
            slippage_cost=Decimal("1.20"),
            market_impact_cost=Decimal("0.80"),
            borrow_cost=Decimal("0.10"),
            total_cost=Decimal("2.10"),
        ),
        assets=[
            EnvV2AssetMetrics(
                symbol="BTC-USD",
                final_position=Decimal("0.15"),
                realized_pnl=Decimal("125.50"),
                trade_count=4,
            )
        ],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
    )
    return env_v2_report_to_dict(report)


@pytest.fixture
def report_store(tmp_path: Path) -> Generator[BacktestReportStore, None, None]:
    db_path = tmp_path / "test_backtest_reports.db"
    store = BacktestReportStore(db_path=str(db_path))
    yield store
    store.close()


def _stored_report(result: dict[str, Any]) -> dict[str, object]:
    report = result["report"]
    assert isinstance(report, dict)
    return cast("dict[str, object]", report)


def test_legacy_report_round_trip(report_store: BacktestReportStore) -> None:
    report = _make_legacy_report()

    report_id = report_store.save_report(report, symbol="BTC", strategy_name="MA")

    result = report_store.get_report(report_id)
    assert result is not None
    assert result["report_engine"] == "legacy"
    stored_report = _stored_report(result)
    for key, value in report.items():
        assert stored_report[key] == value


def test_env_v2_report_round_trip(report_store: BacktestReportStore) -> None:
    report = _make_env_v2_report()

    report_id = report_store.save_env_v2_report(
        report,
        symbol="BTC-USD",
        strategy_name="env_v2_policy",
    )

    result = report_store.get_report(report_id)
    assert result is not None
    assert result["report_engine"] == "env_v2"
    stored_report = _stored_report(result)
    assert stored_report["report_id"] == report["report_id"]
    assert stored_report["environment"] == report["environment"]
    assert stored_report["steps"] == report["steps"]


def test_mixed_legacy_and_env_v2_reports(report_store: BacktestReportStore) -> None:
    report_store.save_report(
        _make_legacy_report(),
        symbol="BTC",
        strategy_name="MA",
    )
    report_store.save_env_v2_report(
        _make_env_v2_report(),
        symbol="BTC-USD",
        strategy_name="env_v2_policy",
    )

    reports = report_store.list_reports()

    assert len(reports) == 2
    assert {report["report_engine"] for report in reports} == {"legacy", "env_v2"}


def test_list_reports_by_engine_filter(report_store: BacktestReportStore) -> None:
    legacy_id_1 = report_store.save_report(
        _make_legacy_report(symbol="BTC", strategy_id="ma_btc"),
        symbol="BTC",
        strategy_name="MA BTC",
    )
    legacy_id_2 = report_store.save_report(
        _make_legacy_report(symbol="ETH", strategy_id="ma_eth"),
        symbol="ETH",
        strategy_name="MA ETH",
    )
    env_v2_id = report_store.save_env_v2_report(
        _make_env_v2_report(report_id="envv2_filter_001"),
        symbol="BTC-USD",
        strategy_name="env_v2_policy",
    )

    legacy_reports = report_store.list_reports_by_engine("legacy")
    env_v2_reports = report_store.list_reports_by_engine("env_v2")

    assert {report["id"] for report in legacy_reports} == {legacy_id_1, legacy_id_2}
    assert [report["report_engine"] for report in legacy_reports] == [
        "legacy",
        "legacy",
    ]
    assert [report["id"] for report in env_v2_reports] == [env_v2_id]
    assert [report["report_engine"] for report in env_v2_reports] == ["env_v2"]
    assert report_store.list_reports_by_engine("unknown") == []


def test_list_reports_empty_store(report_store: BacktestReportStore) -> None:
    assert report_store.list_reports() == []


def test_clear_removes_all_reports(report_store: BacktestReportStore) -> None:
    report_id = report_store.save_report(
        _make_legacy_report(),
        symbol="BTC",
        strategy_name="MA",
    )
    assert len(report_store.list_reports()) == 1

    report_store.clear()

    assert report_store.list_reports() == []
    assert report_store.get_report(report_id) is None


def test_legacy_call_without_engine_defaults_to_legacy(
    report_store: BacktestReportStore,
) -> None:
    report_id = report_store.save_report(
        _make_legacy_report(),
        symbol="BTC",
        strategy_name="MA",
    )

    result = report_store.get_report(report_id)

    assert result is not None
    assert result["report_engine"] == "legacy"
