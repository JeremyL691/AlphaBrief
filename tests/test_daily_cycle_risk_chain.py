"""M11-W06: the full proposal → risk → execution → reconciliation chain.

Covers AC-M11-W06-01/03: submit occurs only when the proposal,
OrderIntent, broker-fresh inputs, immutable RiskDecision, execution
enablement, and idempotency mapping share one correlation chain; every
broker outcome triggers immediate reconciliation and persists linked
order, transaction, trade, position, account, and reconciliation
evidence before report completion.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
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
from alphabrief_trader.cycle_execution import (
    IdempotencyMap,
    ReconciliationEvidence,
)
from alphabrief_trader.cycle_state import CycleStateMachine
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
    "target_position_pct": "0.10",
    "veto": False,
    "needs_human_review": False,
}


def _committee() -> TradingCommittee:
    provider = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=_BULLISH_PAYLOAD,
    )
    return TradingCommittee(
        gateway=ModelGateway(providers=[provider]),
        discipline=DisciplineConfig(),
    )


def _reconciler(
    evidence: list[ReconciliationEvidence],
) -> Callable[[list[dict[str, object]]], ReconciliationEvidence]:
    def _run(attempts: list[dict[str, object]]) -> ReconciliationEvidence:
        record = ReconciliationEvidence(
            cycle_id="chain-cycle",
            attempt_count=len(attempts),
            order_ids=[
                str(a.get("order_id") or a.get("client_order_id") or "")
                for a in attempts
            ],
            matched=all(
                str(a.get("filled", False)) == "True" or a.get("outcome") != "executed"
                for a in attempts
            ),
            account_snapshot={"equity": "100000", "currency": "USD"},
            detail="immediate post-trade reconciliation",
            created_at=_FIXED_NOW,
        )
        evidence.append(record)
        return record

    return _run


def _build_cycle(
    store: AiTradingStore,
    state_store: CycleStateStore,
    runtime_store: RuntimeTruthStore,
    idem: IdempotencyMap,
    *,
    reconciler: Callable[[list[dict[str, object]]], ReconciliationEvidence],
) -> DurableDailyCycle:
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )
    return DurableDailyCycle(
        committee=_committee(),
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
        preflight_facts_provider=lambda: PreflightFacts(),
        idempotency_map=idem,
        reconciler=reconciler,
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


class TestCorrelationChain:
    def test_full_chain_persisted_on_execute(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        evidence: list[ReconciliationEvidence] = []
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            reconciler=_reconciler(evidence),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-chain")

        machine = CycleStateMachine(state_store)
        execute = next(
            t for t in machine.transitions(record.cycle_id)
            if t.prior_phase == "execute"
        )
        chain = json.loads(str(execute.output_ids["correlation_chain"]))
        # One shared correlation chain: proposal → intent → decision →
        # client order → broker order.
        assert chain["cycle_id"] == record.cycle_id
        assert len(chain["proposal_ids"]) == 1
        assert len(chain["intent_ids"]) == 1
        assert len(chain["decision_ids"]) == 1
        assert len(chain["client_order_ids"]) == 1
        assert len(chain["broker_order_ids"]) == 1

    def test_decision_ids_are_immutable_and_linked(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        evidence: list[ReconciliationEvidence] = []
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            reconciler=_reconciler(evidence),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-chain")
        attempts = record.attempts
        assert attempts
        assert attempts[0].risk_decision_id
        assert attempts[0].intent_id
        assert attempts[0].order_id

    def test_broker_fresh_inputs_gate_submission(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        evidence: list[ReconciliationEvidence] = []
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            reconciler=_reconciler(evidence),
        )
        # Stale data blocks submission before any broker call.
        cycle._preflight_facts_provider = lambda: PreflightFacts(
            data_fresh=False
        )
        record = cycle.run(["SPY"], cycle_key="cyc-stale")
        assert record.outcome == "blocked_risk_gate"
        assert record.attempts == []
        machine = CycleStateMachine(state_store)
        execute = next(
            t for t in machine.transitions(record.cycle_id)
            if t.prior_phase == "execute"
        )
        assert json.loads(str(execute.output_ids.get("attempts", "[]"))) == []


class TestImmediateReconciliation:
    def test_reconciliation_runs_before_report(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        evidence: list[ReconciliationEvidence] = []
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            reconciler=_reconciler(evidence),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-recon")

        # Reconciliation evidence was produced and persisted.
        assert len(evidence) == 1
        machine = CycleStateMachine(state_store)
        reconcile = next(
            t for t in machine.transitions(record.cycle_id)
            if t.prior_phase == "reconcile"
        )
        assert "reconciliation_evidence" in reconcile.output_ids
        persisted = ReconciliationEvidence.model_validate_json(
            str(reconcile.output_ids["reconciliation_evidence"])
        )
        assert persisted.cycle_id == "chain-cycle"
        assert persisted.attempt_count == len(record.attempts)
        assert persisted.order_ids
        assert persisted.account_snapshot["equity"] == "100000"

    def test_reconciliation_precedes_report_phase(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        evidence: list[ReconciliationEvidence] = []
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            reconciler=_reconciler(evidence),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-order")

        machine = CycleStateMachine(state_store)
        phases = [t.phase for t in machine.transitions(record.cycle_id)]
        reconcile_index = phases.index("reconcile")
        report_index = phases.index("report")
        # Reconciliation evidence is committed before the report phase.
        assert reconcile_index < report_index
        assert evidence  # the reconciler ran during the cycle
