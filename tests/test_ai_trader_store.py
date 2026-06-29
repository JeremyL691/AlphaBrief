"""Tests for the AI Trading Committee DuckDB store."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.schemas import (
    CommitteeVote,
    DailyCycleRecord,
    OrderAttempt,
    TradePlan,
)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Iterator[AiTradingStore]:
    store = AiTradingStore(db_path=tmp_path / "trader.db")
    try:
        yield store
    finally:
        store.close()


def _vote(**overrides: object) -> CommitteeVote:
    defaults: dict[str, object] = {
        "role": "manager",
        "model_name": "fake-1",
        "analysis": "ok",
        "view": "bullish",
        "confidence": 0.7,
        "evidence": ["e"],
        "risks": ["r"],
        "suggested_action": "buy",
        "target_position_pct": Decimal("0.10"),
        "veto": False,
        "needs_human_review": False,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return CommitteeVote.model_validate(defaults)


def _attempt(**overrides: object) -> OrderAttempt:
    defaults: dict[str, object] = {
        "intent_id": "ai_1",
        "approved": True,
        "reason": "ok",
        "requires_human_review": False,
        "outcome": "executed",
        "order_intent_json": {"intent_id": "ai_1"},
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return OrderAttempt.model_validate(defaults)


def _plan(**overrides: object) -> TradePlan:
    defaults: dict[str, object] = {
        "symbol": "SPY",
        "side": "buy",
        "target_position_pct": Decimal("0.10"),
        "confidence": 0.7,
        "consensus_level": "unanimous",
        "rationale": "ok",
        "needs_human_review": False,
    }
    defaults.update(overrides)
    return TradePlan.model_validate(defaults)


def _record(**overrides: object) -> DailyCycleRecord:
    defaults: dict[str, object] = {
        "cycle_id": "aic_1",
        "trading_day": "2026-01-01",
        "symbols": ["SPY"],
        "plans": [_plan()],
        "votes": [
            _vote(),
            _vote(role="technical"),
            _vote(role="fundamental"),
            _vote(role="risk"),
        ],
        "attempts": [_attempt()],
        "outcome": "executed",
        "enabled": True,
        "live_trading_enabled": False,
        "summary": "ok",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return DailyCycleRecord.model_validate(defaults)


class TestAiTradingStoreSaveCycle:
    def test_round_trip(self, tmp_db: AiTradingStore) -> None:
        record = _record()
        cycle_id = tmp_db.save_cycle(record)
        assert cycle_id == "aic_1"

        loaded = tmp_db.get_cycle(cycle_id)
        assert loaded is not None
        assert loaded["cycle_id"] == "aic_1"
        assert loaded["outcome"] == "executed"
        assert len(loaded["plans"]) == 1
        assert len(loaded["votes"]) == 4
        assert len(loaded["attempts"]) == 1

    def test_get_cycle_missing_returns_none(self, tmp_db: AiTradingStore) -> None:
        assert tmp_db.get_cycle("missing") is None

    def test_list_cycles_orders_newest_first(self, tmp_db: AiTradingStore) -> None:
        tmp_db.save_cycle(_record(cycle_id="aic_1"))
        tmp_db.save_cycle(
            _record(
                cycle_id="aic_2",
                created_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )
        rows = tmp_db.list_cycles(limit=10)
        assert [r.cycle_id for r in rows] == ["aic_2", "aic_1"]

    def test_list_cycles_for_day(self, tmp_db: AiTradingStore) -> None:
        tmp_db.save_cycle(_record(cycle_id="aic_1", trading_day="2026-01-01"))
        tmp_db.save_cycle(
            _record(
                cycle_id="aic_2",
                trading_day="2026-01-01",
                created_at=datetime(2026, 1, 1, 5, tzinfo=UTC),
            )
        )
        rows = tmp_db.list_cycles_for_day("2026-01-01")
        assert len(rows) == 2
        assert tmp_db.list_cycles_for_day("2026-01-02") == []

    def test_list_attempts(self, tmp_db: AiTradingStore) -> None:
        tmp_db.save_cycle(_record(cycle_id="aic_1"))
        rows = tmp_db.list_attempts(limit=10)
        assert len(rows) == 1
        assert rows[0]["intent_id"] == "ai_1"
        assert rows[0]["cycle_id"] == "aic_1"
        assert rows[0]["outcome"] == "executed"

    def test_get_latest_cycle(self, tmp_db: AiTradingStore) -> None:
        assert tmp_db.get_latest_cycle() is None
        tmp_db.save_cycle(_record(cycle_id="aic_1"))
        tmp_db.save_cycle(
            _record(cycle_id="aic_2", created_at=datetime(2026, 1, 2, tzinfo=UTC))
        )
        latest = tmp_db.get_latest_cycle()
        assert latest is not None
        assert latest["cycle_id"] == "aic_2"

    def test_summary_aggregates_outcomes(self, tmp_db: AiTradingStore) -> None:
        tmp_db.save_cycle(
            _record(
                cycle_id="aic_1",
                attempts=[
                    _attempt(intent_id="ai_1", outcome="executed"),
                    _attempt(intent_id="ai_2", outcome="blocked_risk_gate"),
                ],
            )
        )
        rows = tmp_db.list_cycles(limit=1)
        assert rows[0].executed_count == 1
        assert rows[0].blocked_count == 1
        assert rows[0].attempt_count == 2
        assert rows[0].plan_count == 1


class TestAiTradingStoreLifecycle:
    def test_clear_drops_only_ai_tables(
        self, tmp_path: Path
    ) -> None:
        # Use a real DuckDB file that has the full schema applied.
        store = AiTradingStore(db_path=tmp_path / "trader.db")
        store.clear()
        # Re-open after clear.
        store2 = AiTradingStore(db_path=tmp_path / "trader.db")
        try:
            assert store2.get_cycle("anything") is None
        finally:
            store2.close()
        store.close()

    def test_data_dir_env_used(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
        store = AiTradingStore()
        try:
            assert str(tmp_path) in str(store._db_path)  # noqa: SLF001
        finally:
            store.close()


class TestDisciplineSnapshot:
    def test_save_and_get(self, tmp_db: AiTradingStore) -> None:
        config = {
            "max_position_pct": "0.30",
            "no_trade_below_confidence": 0.5,
        }
        snapshot_id = tmp_db.save_discipline_snapshot(config)
        assert snapshot_id.startswith("disc_")

        snap = tmp_db.get_discipline_snapshot()
        assert snap is not None
        assert snap["config"] == config

    def test_get_when_empty(self, tmp_db: AiTradingStore) -> None:
        assert tmp_db.get_discipline_snapshot() is None