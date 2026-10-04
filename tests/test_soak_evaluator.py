"""Tests for soak status and day qualification rules (PROJECT_GUIDE S10)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from alphabrief_api.db.ai_trading import AiTradingStore
from alphabrief_api.db.paper import PaperStore
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_trader.schemas import DailyCycleRecord
from alphabrief_trader.soak_evaluator import (
    evaluate_soak_status,
)
from alphabrief_trader.soak_store import SoakStore


def _insert_recon_snapshot(
    recon_store: BrokerReconStore,
    *,
    snapshot_id: str,
    captured_at: str,
    all_match: bool = True,
) -> None:
    recon_store._conn.execute(
        """
        INSERT INTO broker_recon_snapshots (
            snapshot_id, captured_at, scope, orders_match, fills_match,
            cash_match, positions_match, diff_json
        )
        VALUES (?, ?, 'cycle', ?, ?, ?, ?, '{}')
        """,
        [snapshot_id, captured_at, all_match, all_match, all_match, all_match],
    )


def test_evaluator_when_not_started(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"
    status = evaluate_soak_status(db_path=db)
    assert not status.soak_started
    assert status.run_index is None
    assert status.qualified_days == 0
    assert status.extension_days == 0
    assert not status.is_complete


def test_evaluator_day_zero_in_progress(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"
    now = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    soak = SoakStore(db_path=db)
    try:
        soak.start_soak(started_at=datetime(2026, 10, 4, 4, 0, tzinfo=UTC))
    finally:
        soak.close()

    status = evaluate_soak_status(db_path=db, as_of=now)
    assert status.soak_started
    assert status.run_index == 0
    assert status.qualified_days == 0
    assert len(status.days) == 1
    assert status.days[0].date == "2026-10-04"
    assert status.days[0].status == "in_progress"


def test_evaluator_qualified_weekday(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"
    t_start = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)  # Monday
    t_as_of = datetime(2026, 10, 6, 1, 0, tzinfo=UTC)  # Tuesday morning

    soak = SoakStore(db_path=db)
    soak.start_soak(started_at=t_start)
    soak.close()

    # Record 1 cycle for Monday 2026-10-05
    ai_store = AiTradingStore(db_path=db)
    ai_store.save_cycle(
        DailyCycleRecord(
            cycle_id="aic_1",
            trading_day="2026-10-05",
            symbols=["EUR_USD"],
            attempts=[],
            outcome="executed",
            enabled=True,
            summary="test cycle",
            created_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        )
    )
    ai_store.close()

    # Record clean recon at day start and end to avoid downtime gap
    recon_store = BrokerReconStore(db_path=db)
    _insert_recon_snapshot(
        recon_store,
        snapshot_id="rec_start",
        captured_at="2026-10-05T00:05:00+00:00",
        all_match=True,
    )
    _insert_recon_snapshot(
        recon_store,
        snapshot_id="rec_end",
        captured_at="2026-10-05T23:55:00+00:00",
        all_match=True,
    )
    recon_store.close()

    with patch(
        "alphabrief_trader.soak_evaluator._daily_report_exists", return_value=True
    ):
        status = evaluate_soak_status(db_path=db, as_of=t_as_of)

    assert status.soak_started
    assert status.qualified_days == 1
    assert status.extension_days == 0
    assert len(status.days) == 2
    day0 = status.days[0]
    assert day0.date == "2026-10-05"
    assert day0.status == "qualified"
    assert not day0.is_weekend
    assert day0.recon_clean
    assert day0.daily_report_exists


def test_evaluator_weekend_without_cycles_is_qualified(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"
    t_start = datetime(2026, 10, 10, 0, 0, tzinfo=UTC)  # Saturday
    t_as_of = datetime(2026, 10, 11, 1, 0, tzinfo=UTC)  # Sunday

    soak = SoakStore(db_path=db)
    soak.start_soak(started_at=t_start)
    soak.close()

    recon_store = BrokerReconStore(db_path=db)
    _insert_recon_snapshot(
        recon_store,
        snapshot_id="rec_sat_1",
        captured_at="2026-10-10T00:05:00+00:00",
        all_match=True,
    )
    _insert_recon_snapshot(
        recon_store,
        snapshot_id="rec_sat_2",
        captured_at="2026-10-10T23:55:00+00:00",
        all_match=True,
    )
    recon_store.close()

    with patch(
        "alphabrief_trader.soak_evaluator._daily_report_exists", return_value=True
    ):
        status = evaluate_soak_status(db_path=db, as_of=t_as_of)

    day_sat = status.days[0]
    assert day_sat.date == "2026-10-10"
    assert day_sat.is_weekend
    assert day_sat.status == "qualified"
    assert status.qualified_days == 1


def test_evaluator_missing_report_causes_extension(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"
    t_start = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    t_as_of = datetime(2026, 10, 6, 1, 0, tzinfo=UTC)

    soak = SoakStore(db_path=db)
    soak.start_soak(started_at=t_start)
    soak.close()

    ai_store = AiTradingStore(db_path=db)
    ai_store.save_cycle(
        DailyCycleRecord(
            cycle_id="aic_1",
            trading_day="2026-10-05",
            symbols=["EUR_USD"],
            attempts=[],
            outcome="executed",
            enabled=True,
            summary="test cycle",
            created_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        )
    )
    ai_store.close()

    recon_store = BrokerReconStore(db_path=db)
    _insert_recon_snapshot(
        recon_store,
        snapshot_id="rec_1",
        captured_at="2026-10-05T00:05:00+00:00",
        all_match=True,
    )
    _insert_recon_snapshot(
        recon_store,
        snapshot_id="rec_2",
        captured_at="2026-10-05T23:55:00+00:00",
        all_match=True,
    )
    recon_store.close()

    # No daily report
    with patch(
        "alphabrief_trader.soak_evaluator._daily_report_exists", return_value=False
    ):
        status = evaluate_soak_status(db_path=db, as_of=t_as_of)

    day = status.days[0]
    assert day.status == "extension"
    assert "daily report not generated" in day.extension_reasons
    assert status.qualified_days == 0
    assert status.extension_days == 1


def test_evaluator_duplicate_orders_triggers_reset(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"
    t_start = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    t_as_of = datetime(2026, 10, 6, 1, 0, tzinfo=UTC)

    soak = SoakStore(db_path=db)
    soak.start_soak(started_at=t_start)
    soak.close()

    paper = PaperStore(db_path=db)
    paper.save_order(
        {
            "order_id": "ord_1",
            "client_order_id": "dup_cid_123",
            "decision_id": "dec_1",
            "symbol": "EUR_USD",
            "units": 1000,
            "status": "filled",
            "created_at": "2026-10-05T12:00:00+00:00",
        }
    )
    paper.save_order(
        {
            "order_id": "ord_2",
            "client_order_id": "dup_cid_123",  # duplicate!
            "decision_id": "dec_2",
            "symbol": "EUR_USD",
            "units": 1000,
            "status": "filled",
            "created_at": "2026-10-05T12:01:00+00:00",
        }
    )
    paper.close()

    recon_store = BrokerReconStore(db_path=db)
    _insert_recon_snapshot(
        recon_store,
        snapshot_id="rec_1",
        captured_at="2026-10-05T00:05:00+00:00",
        all_match=True,
    )
    _insert_recon_snapshot(
        recon_store,
        snapshot_id="rec_2",
        captured_at="2026-10-05T23:55:00+00:00",
        all_match=True,
    )
    recon_store.close()

    with patch(
        "alphabrief_trader.soak_evaluator._daily_report_exists", return_value=True
    ):
        status = evaluate_soak_status(db_path=db, as_of=t_as_of)

    day = status.days[0]
    assert day.status == "reset"
    assert any("duplicate orders" in r for r in day.reset_reasons)
    assert not status.is_complete


def test_evaluator_order_without_risk_decision_triggers_reset(
    tmp_path: Path,
) -> None:
    db = tmp_path / "test.duckdb"
    t_start = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    t_as_of = datetime(2026, 10, 6, 1, 0, tzinfo=UTC)

    soak = SoakStore(db_path=db)
    soak.start_soak(started_at=t_start)
    soak.close()

    paper = PaperStore(db_path=db)
    paper.save_order(
        {
            "order_id": "ord_1",
            "client_order_id": "cid_valid",
            "decision_id": None,  # Missing RiskDecision!
            "symbol": "EUR_USD",
            "units": 1000,
            "status": "filled",
            "created_at": "2026-10-05T12:00:00+00:00",
        }
    )
    paper.close()

    recon_store = BrokerReconStore(db_path=db)
    _insert_recon_snapshot(
        recon_store,
        snapshot_id="rec_1",
        captured_at="2026-10-05T00:05:00+00:00",
        all_match=True,
    )
    _insert_recon_snapshot(
        recon_store,
        snapshot_id="rec_2",
        captured_at="2026-10-05T23:55:00+00:00",
        all_match=True,
    )
    recon_store.close()

    with patch(
        "alphabrief_trader.soak_evaluator._daily_report_exists", return_value=True
    ):
        status = evaluate_soak_status(db_path=db, as_of=t_as_of)

    day = status.days[0]
    assert day.status == "reset"
    assert any("without persisted RiskDecision" in r for r in day.reset_reasons)
