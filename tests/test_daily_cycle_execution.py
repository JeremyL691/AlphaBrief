"""M11-W06: proposal → risk → execution with at-most-once submission.

Covers AC-M11-W06-01/02: submit occurs only when the proposal,
OrderIntent, broker-fresh inputs, immutable RiskDecision, execution
enablement, and idempotency mapping share one correlation chain;
approved, rejected, no-trade, and broker-rejected fixtures produce the
correct terminal cycle state and exactly zero or one broker submit call.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from _helpers import FakeExecutionBackend
from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.cycle_execution import IdempotencyMap
from alphabrief_trader.cycle_state import CycleStateMachine
from alphabrief_trader.daily_cycle import DurableDailyCycle
from alphabrief_trader.db_store import AiTradingStore, CycleStateStore
from alphabrief_trader.execution_backend import ExecutionBackendResult
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
    "target_position_pct": "0.10",
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


class _CountingBackend(FakeExecutionBackend):
    """Deterministic backend that counts submit calls."""

    def __init__(self) -> None:
        super().__init__()
        self.submit_calls = 0

    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        reference_price: Decimal,
        now: datetime,
        estimated_quantity: Decimal | None,
    ) -> ExecutionBackendResult:
        self.submit_calls += 1
        return super().submit(
            intent,
            decision,
            reference_price=reference_price,
            now=now,
            estimated_quantity=estimated_quantity,
        )


def _build_cycle(
    store: AiTradingStore,
    state_store: CycleStateStore,
    runtime_store: RuntimeTruthStore,
    idempotency_map: IdempotencyMap,
    backend: _CountingBackend,
    *,
    committee: TradingCommittee,
    facts: PreflightFacts | None = None,
) -> DurableDailyCycle:
    return DurableDailyCycle(
        committee=committee,
        risk_gate=RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True, symbol_allowlist=frozenset({"SPY"})
            )
        ),
        store=store,
        state_store=state_store,
        runtime_store=runtime_store,
        execution_backend=backend,
        snapshot_loader=lambda s: MarketSnapshot(
            symbol=s,
            reference_price=Decimal("100"),
            data_version="v1",
            captured_at=_FIXED_NOW,
        ),
        enabled=True,
        clock=lambda: _FIXED_NOW,
        preflight_facts_provider=lambda: facts or PreflightFacts(),
        idempotency_map=idempotency_map,
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


@pytest.fixture
def idem(tmp_path: Path) -> Iterator[IdempotencyMap]:
    store = IdempotencyMap(db_path=tmp_path / "trader.db")
    try:
        yield store
    finally:
        store.close()


def _chain(store: CycleStateStore, cycle_id: str) -> dict[str, object]:
    machine = CycleStateMachine(store)
    execute = next(
        t for t in machine.transitions(cycle_id) if t.prior_phase == "execute"
    )
    import json
    from typing import cast

    return cast(
        dict[str, object],
        json.loads(str(execute.output_ids["correlation_chain"])),
    )


class TestExecutionChain:
    def test_approved_fixture_submits_exactly_once(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        backend = _CountingBackend()
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            backend,
            committee=_committee(_BULLISH_PAYLOAD),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-approved")

        assert record.outcome == "executed"
        assert backend.submit_calls == 1
        chain = _chain(state_store, record.cycle_id)
        assert chain["proposal_ids"]
        assert chain["intent_ids"]
        assert chain["decision_ids"]
        assert chain["client_order_ids"]
        assert chain["broker_order_ids"]

    def test_risk_rejected_fixture_never_submits(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        backend = _CountingBackend()
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            backend,
            committee=_committee(_BULLISH_PAYLOAD),
        )
        # A kill-switched risk gate rejects every intent.
        cycle._trading._risk_gate.kill_switch.activate("test")
        record = cycle.run(["SPY"], cycle_key="cyc-rejected")

        assert record.outcome == "blocked_risk_gate"
        assert backend.submit_calls == 0

    def test_no_trade_fixture_never_submits(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        backend = _CountingBackend()
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            backend,
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
        assert backend.submit_calls == 0

    def test_broker_rejected_fixture_submits_once_and_terminates(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores

        class _RejectingBroker(_CountingBackend):
            def submit(
                self,
                intent: OrderIntent,
                decision: RiskDecision,
                *,
                reference_price: Decimal,
                now: datetime,
                estimated_quantity: Decimal | None,
            ) -> ExecutionBackendResult:
                from alphabrief_trader.execution_backend import (
                    ExecutionBackendError,
                )

                self.submit_calls += 1
                raise ExecutionBackendError("broker rejected the order")

        rejecting = _RejectingBroker()
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            rejecting,
            committee=_committee(_BULLISH_PAYLOAD),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-broker-rejected")

        assert record.outcome == "error"
        assert rejecting.submit_calls == 1

    def test_at_most_once_across_restart(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        backend = _CountingBackend()
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            backend,
            committee=_committee(_BULLISH_PAYLOAD),
        )
        first = cycle.run(["SPY"], cycle_key="cyc-once")
        assert backend.submit_calls == 1

        # A restarted cycle with the same key reuses the idempotency
        # mapping: the completed cycle is returned, zero new submits.
        second = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            backend,
            committee=_committee(_BULLISH_PAYLOAD),
        )
        resumed = second.run(["SPY"], cycle_key="cyc-once")
        assert resumed.cycle_id == first.cycle_id
        assert backend.submit_calls == 1

    def test_blocked_execution_never_submits(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        backend = _CountingBackend()
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            backend,
            committee=_committee(_BULLISH_PAYLOAD),
            facts=PreflightFacts(credentials_present=False),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-gate-blocked")

        assert record.outcome == "blocked_risk_gate"
        assert backend.submit_calls == 0
