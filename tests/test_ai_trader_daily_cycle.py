"""Tests for the daily AI trading cycle."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
)
from alphabrief_models import (
    FakeProviderAdapter,
    ModelGateway,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
)
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.daily_cycle import (
    DailyTradingCycle,
    SnapshotLoader,
    is_ai_trading_enabled,
    is_live_trading_unlocked,
)
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.rules import DisciplineConfig
from alphabrief_trader.schemas import MarketSnapshot

_BULLISH_PAYLOAD = {
    "analysis": "Bullish continuation.",
    "view": "bullish",
    "confidence": 0.7,
    "evidence": ["e1"],
    "risks": ["r1"],
    "suggested_action": "buy",
    "target_position_pct": 0.10,
    "veto": False,
    "needs_human_review": False,
}

_HOLD_PAYLOAD = {
    "analysis": "Insufficient data.",
    "view": "neutral",
    "confidence": 0.5,
    "evidence": [],
    "risks": [],
    "suggested_action": "hold",
    "target_position_pct": 0.0,
    "veto": False,
    "needs_human_review": True,
}


def _snapshot(symbol: str) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        reference_price=Decimal("100"),
        data_version="test-v1",
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _build_committee(payload: dict[str, object]) -> TradingCommittee:
    provider = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=payload,
    )
    gateway = ModelGateway(providers=[provider])

    return TradingCommittee(gateway=gateway, discipline=DisciplineConfig())


def _build_broker() -> PaperBroker:
    return PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )


def _build_risk_gate(
    symbols: list[str], *, kill: bool = False
) -> RiskGate:
    gate = RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True,
            symbol_allowlist=frozenset(symbols),
        )
    )
    if kill:
        gate.kill_switch.activate("test")
    return gate


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AiTradingStore]:
    s = AiTradingStore(db_path=tmp_path / "trader.db")
    try:
        yield s
    finally:
        s.close()


class TestDailyTradingCycle:
    def test_disabled_records_blocked_disabled(
        self,
        store: AiTradingStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ALPHABRIEF_AI_TRADING_ENABLED", raising=False)
        cycle = DailyTradingCycle(
            committee=_build_committee(_BULLISH_PAYLOAD),
            risk_gate=_build_risk_gate(["SPY"]),
            broker=_build_broker(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s),
            enabled=False,
        )
        record = cycle.run(["SPY"])
        assert record.outcome == "blocked_disabled"
        assert record.enabled is False
        # Saved in store
        assert store.get_cycle(record.cycle_id) is not None

    def test_live_trading_unlocked_blocks(
        self,
        store: AiTradingStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_LIVE_TRADING_ENABLED", "true")
        cycle = DailyTradingCycle(
            committee=_build_committee(_BULLISH_PAYLOAD),
            risk_gate=_build_risk_gate(["SPY"]),
            broker=_build_broker(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s),
            enabled=True,
        )
        record = cycle.run(["SPY"])
        assert record.outcome == "blocked_live_trading"
        assert record.live_trading_enabled is True
        assert len(record.attempts) == 0

    def test_buy_plan_executes(self, store: AiTradingStore) -> None:
        cycle = DailyTradingCycle(
            committee=_build_committee(_BULLISH_PAYLOAD),
            risk_gate=_build_risk_gate(["SPY"]),
            broker=_build_broker(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s),
            enabled=True,
        )
        record = cycle.run(["SPY"])
        assert record.outcome == "executed"
        assert len(record.attempts) == 1
        attempt = record.attempts[0]
        assert attempt.filled is True
        assert attempt.outcome == "executed"
        assert attempt.approved is True
        assert attempt.fill_price is not None
        assert attempt.fill_quantity is not None

    def test_hold_action_skips(self, store: AiTradingStore) -> None:
        cycle = DailyTradingCycle(
            committee=_build_committee(_HOLD_PAYLOAD),
            risk_gate=_build_risk_gate(["SPY"]),
            broker=_build_broker(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s),
            enabled=True,
        )
        record = cycle.run(["SPY"])
        # Hold action synthesizes a zero-target plan → no intent → no attempt
        assert record.outcome == "skipped_no_intent"
        assert len(record.attempts) == 0

    def test_kill_switch_blocks_order(
        self, store: AiTradingStore
    ) -> None:
        cycle = DailyTradingCycle(
            committee=_build_committee(_BULLISH_PAYLOAD),
            risk_gate=_build_risk_gate(["SPY"], kill=True),
            broker=_build_broker(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s),
            enabled=True,
        )
        record = cycle.run(["SPY"])
        # RiskGate rejects when kill switch is on → no fill
        assert len(record.attempts) == 1
        attempt = record.attempts[0]
        assert attempt.approved is False
        assert attempt.filled is False
        assert attempt.outcome == "blocked_risk_gate"

    def test_snapshot_loader_none_skips_symbol(
        self, store: AiTradingStore
    ) -> None:
        cycle = DailyTradingCycle(
            committee=_build_committee(_BULLISH_PAYLOAD),
            risk_gate=_build_risk_gate(["SPY", "QQQ"]),
            broker=_build_broker(),
            store=store,
            snapshot_loader=lambda s: None,
            enabled=True,
        )
        record = cycle.run(["SPY", "QQQ"])
        # No snapshots → no votes → no plans → skipped_no_consensus
        assert record.outcome == "skipped_no_consensus"
        assert record.plans == []

    def test_multi_symbol_loop(self, store: AiTradingStore) -> None:
        cycle = DailyTradingCycle(
            committee=_build_committee(_BULLISH_PAYLOAD),
            risk_gate=_build_risk_gate(["SPY", "QQQ"]),
            broker=_build_broker(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s),
            enabled=True,
        )
        record = cycle.run(["SPY", "QQQ"])
        # Both symbols should have produced attempts.
        assert len(record.attempts) == 2
        assert {a.order_intent_json["symbol"] for a in record.attempts} == {
            "SPY",
            "QQQ",
        }

    def test_all_provider_failures_record_provider_error(
        self, store: AiTradingStore
    ) -> None:
        # Every role call fails at the gateway → the cycle must record a
        # visible provider_error outcome instead of a misleading
        # skipped_no_consensus.
        provider = FakeProviderAdapter(
            provider_name="fake",
            model_name="fake-1",
            capabilities=["structured_output"],
            fail=True,
        )
        committee = TradingCommittee(
            gateway=ModelGateway(providers=[provider]),
            discipline=DisciplineConfig(),
        )
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=_build_risk_gate(["SPY"]),
            broker=_build_broker(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s),
            enabled=True,
        )
        record = cycle.run(["SPY"])
        assert record.outcome == "provider_error"
        assert record.votes == []
        assert record.plans == []
        assert "provider_call_failed" in record.summary
        assert "technical" in record.summary
        # The record is persisted so dashboards/exports can surface it.
        saved = store.get_cycle(record.cycle_id)
        assert saved is not None
        assert saved["outcome"] == "provider_error"

    def test_partial_role_failure_does_not_mask_outcome(
        self, store: AiTradingStore
    ) -> None:
        # One role fails but the rest vote → normal synthesis continues
        # and the outcome reflects the plan, not provider_error.
        class _PartialFailProvider(FakeProviderAdapter):
            def __init__(self, payload: dict[str, object]) -> None:
                super().__init__(
                    provider_name="fake",
                    model_name="fake-1",
                    capabilities=["structured_output"],
                    structured_output=payload,
                )

            def call(self, request: ModelRequest) -> ModelResponse:
                if request.metadata.get("committee_role") == "technical":
                    raise ModelProviderError("technical down")
                return super().call(request)

        committee = TradingCommittee(
            gateway=ModelGateway(providers=[_PartialFailProvider(_BULLISH_PAYLOAD)]),
            discipline=DisciplineConfig(),
        )
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=_build_risk_gate(["SPY"]),
            broker=_build_broker(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s),
            enabled=True,
        )
        record = cycle.run(["SPY"])
        assert record.outcome == "executed"
        # Five roles total; one analyst fails → four votes remain.
        assert len(record.votes) == 4
        assert "provider_error" not in record.summary

    def test_constructor_requires_all_dependencies(self) -> None:
        with pytest.raises(TypeError):
            DailyTradingCycle(
                committee=cast(TradingCommittee, None),
                risk_gate=cast(RiskGate, None),
                broker=cast(PaperBroker, None),
                store=cast(AiTradingStore, None),
                snapshot_loader=cast(SnapshotLoader, None),
            )


class TestEnvHelpers:
    def test_ai_trading_enabled_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ALPHABRIEF_AI_TRADING_ENABLED", raising=False)
        assert is_ai_trading_enabled() is False
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        assert is_ai_trading_enabled() is True

    def test_live_trading_unlocked_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ALPHABRIEF_LIVE_TRADING_ENABLED", raising=False)
        assert is_live_trading_unlocked() is False
        monkeypatch.setenv("ALPHABRIEF_LIVE_TRADING_ENABLED", "1")
        assert is_live_trading_unlocked() is True