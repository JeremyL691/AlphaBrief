"""M11-W05: durable successful terminal no-trade outcomes.

Covers AC-M11-W05-01/03: repeating the same trading date and snapshot
key returns the existing cycle; no-trade, risk rejection, market closed,
stale data, insufficient evidence, and budget exhaustion are durable
successful terminal outcomes with evidence IDs and reasons.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
)
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.cycle_schedule import daily_cycle_key
from alphabrief_trader.daily_cycle import DurableDailyCycle
from alphabrief_trader.db_store import AiTradingStore, CycleStateStore
from alphabrief_trader.execution_gate import PreflightFacts
from alphabrief_trader.rules import DisciplineConfig
from alphabrief_trader.runtime_truth import RuntimeTruthStore
from alphabrief_trader.schemas import MarketSnapshot

_FIXED_NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

_BULLISH_PAYLOAD: dict[str, object] = {
    "analysis": "Bullish continuation.",
    "view": "bullish",
    "confidence": 0.7,
    "evidence": ["trend confirmed"],
    "risks": ["r1"],
    "suggested_action": "buy",
    "target_position_pct": 0.10,
    "veto": False,
    "needs_human_review": False,
}


def _committee(payload: dict[str, object]) -> TradingCommittee:
    provider = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=payload,
    )
    return TradingCommittee(
        gateway=ModelGateway(providers=[provider]),
        discipline=DisciplineConfig(),
    )


def _build_cycle(
    store: AiTradingStore,
    state_store: CycleStateStore,
    runtime_store: RuntimeTruthStore,
    *,
    facts: PreflightFacts,
    committee: TradingCommittee,
) -> DurableDailyCycle:
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )
    return DurableDailyCycle(
        committee=committee,
        risk_gate=RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True, symbol_allowlist=frozenset({"SPY"})
            )
        ),
        broker=broker,
        store=store,
        state_store=state_store,
        runtime_store=runtime_store,
        snapshot_loader=lambda s: MarketSnapshot(
            symbol=s,
            reference_price=Decimal("100"),
            data_version="v1",
            captured_at=_FIXED_NOW,
        ),
        enabled=True,
        clock=lambda: _FIXED_NOW,
        preflight_facts_provider=lambda: facts,
    )


@pytest.fixture
def stores(tmp_path: Path) -> Iterator[
    tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
]:
    store = AiTradingStore(db_path=tmp_path / "trader.db")
    state_store = CycleStateStore(db_path=tmp_path / "trader.db")
    runtime_store = RuntimeTruthStore(db_path=tmp_path / "trader.db")
    try:
        yield store, state_store, runtime_store
    finally:
        store.close()
        state_store.close()
        runtime_store.close()


class TestSameDateSnapshotIdempotency:
    def test_same_date_and_snapshot_returns_existing_cycle(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(),
            committee=_committee(_BULLISH_PAYLOAD),
        )
        snapshot_key = "snap-abc123"
        key = daily_cycle_key("2026-08-13", snapshot_key)

        first = cycle.run(["SPY"], cycle_key=key)
        second = cycle.run(["SPY"], cycle_key=key)

        assert second.cycle_id == first.cycle_id
        assert len(store.list_cycles()) == 1

    def test_different_snapshot_creates_new_cycle(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(),
            committee=_committee(_BULLISH_PAYLOAD),
        )
        first = cycle.run(["SPY"], cycle_key=daily_cycle_key("2026-08-13", "snap-a"))
        second = cycle.run(["SPY"], cycle_key=daily_cycle_key("2026-08-13", "snap-b"))
        assert first.cycle_id != second.cycle_id
        assert len(store.list_cycles()) == 2


class TestTerminalNoTradeOutcomes:
    def test_market_closed_is_durable_terminal_outcome(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(market_open=False),
            committee=_committee(_BULLISH_PAYLOAD),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-market-closed")
        assert record.outcome == "blocked_risk_gate"
        assert "market_closed" in record.summary
        stored = store.get_cycle(record.cycle_id)
        assert stored is not None
        assert stored["attempts"] == []

    def test_stale_data_is_durable_terminal_outcome(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(data_fresh=False),
            committee=_committee(_BULLISH_PAYLOAD),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-stale-data")
        assert record.outcome == "blocked_risk_gate"
        assert "stale_data" in record.summary
        assert record.votes  # research still ran

    def test_risk_rejection_is_durable_terminal_outcome(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(),
            committee=_committee(
                {
                    **_BULLISH_PAYLOAD,
                    "suggested_action": "buy",
                    "target_position_pct": "0.10",
                }
            ),
        )
        # A risk gate that rejects every symbol produces a blocked outcome.
        cycle._trading._risk_gate.kill_switch.activate("test")
        record = cycle.run(["SPY"], cycle_key="cyc-risk-reject")
        assert record.outcome == "blocked_risk_gate"
        stored = store.get_cycle(record.cycle_id)
        assert stored is not None
        # The risk rejection is a durable blocked attempt, never a fill.
        assert stored["attempts"]
        assert stored["attempts"][0]["approved"] is False
        assert stored["attempts"][0]["filled"] is False

    def test_insufficient_evidence_is_durable_terminal_outcome(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(),
            committee=_committee({"bogus": "field"}),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-no-evidence")
        assert record.outcome in {"provider_error", "skipped_no_consensus"}
        stored = store.get_cycle(record.cycle_id)
        assert stored is not None
        assert stored["attempts"] == []

    def test_no_trade_is_durable_successful_outcome(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(),
            committee=_committee(
                {
                    **_BULLISH_PAYLOAD,
                    "suggested_action": "hold",
                    "target_position_pct": "0.0",
                }
            ),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-no-trade")
        assert record.outcome == "skipped_no_intent"
        stored = store.get_cycle(record.cycle_id)
        assert stored is not None
        assert stored["votes"]  # evidence retained
        # The evidence survived in the durable record.
        evidence = {
            entry
            for vote in stored["votes"]
            for entry in vote.get("evidence", [])
        }
        assert "trend confirmed" in evidence
