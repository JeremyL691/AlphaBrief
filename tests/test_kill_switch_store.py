"""Tests for the durable kill switch (PROJECT_GUIDE 5.7 rule 1)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import OrderIntent
from alphabrief_risk import KillSwitch, KillSwitchStore, RiskGate, RiskLimitConfig

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _intent() -> OrderIntent:
    return OrderIntent(
        intent_id="intent_1",
        source="manual",
        symbol="EUR_USD",
        side="buy",
        order_type="market",
        quantity=Decimal("1000"),
        rationale="kill switch test",
        created_at=NOW,
    )


def _gate(switch: KillSwitch) -> RiskGate:
    return RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True, symbol_allowlist=frozenset({"EUR_USD"})
        ),
        kill_switch=switch,
        clock=lambda: NOW,
    )


class TestStore:
    def test_unset_switch_defaults_to_inactive(self, tmp_path: Path) -> None:
        store = KillSwitchStore(db_path=tmp_path / "state.duckdb")
        try:
            assert store.load() is None
            assert KillSwitch.from_store(store).active is False
        finally:
            store.close()

    def test_activation_is_persisted_across_processes(self, tmp_path: Path) -> None:
        path = tmp_path / "state.duckdb"
        first = KillSwitchStore(db_path=path)
        try:
            state = first.activate(reason="manual halt")
            assert state["active"] is True
        finally:
            first.close()

        second = KillSwitchStore(db_path=path)
        try:
            loaded = KillSwitch.from_store(second)
            assert loaded.active is True
            assert loaded.reason == "manual halt"
        finally:
            second.close()

    def test_blank_reason_is_refused(self, tmp_path: Path) -> None:
        store = KillSwitchStore(db_path=tmp_path / "state.duckdb")
        try:
            with pytest.raises(ValueError, match="must not be blank"):
                store.activate(reason="   ")
        finally:
            store.close()

    def test_deactivation_records_the_reason(self, tmp_path: Path) -> None:
        store = KillSwitchStore(db_path=tmp_path / "state.duckdb")
        try:
            store.activate(reason="manual halt")
            state = store.deactivate(reason="incident closed")
            assert state["active"] is False
            assert state["reason"] == "incident closed"
        finally:
            store.close()


class TestGate:
    def test_active_switch_rejects_every_order(self) -> None:
        gate = _gate(KillSwitch(active=True, reason="manual halt"))

        decision = gate.evaluate(_intent(), estimated_price=Decimal("1.13"))

        assert decision.approved is False
        assert "kill_switch" in decision.risk_tags
        assert "manual halt" in decision.reason

    def test_active_switch_also_blocks_a_close(self) -> None:
        """Rule 1 is the one rule a reduce-only order cannot bypass."""
        gate = _gate(KillSwitch(active=True, reason="manual halt"))
        close = _intent().model_copy(update={"reduce_only": True, "side": "sell"})

        decision = gate.evaluate(close, estimated_price=Decimal("1.13"))

        assert decision.approved is False
        assert "kill_switch" in decision.risk_tags

    def test_inactive_switch_allows_the_order(self) -> None:
        gate = _gate(KillSwitch())

        decision = gate.evaluate(_intent(), estimated_price=Decimal("1.13"))

        assert decision.approved is True
