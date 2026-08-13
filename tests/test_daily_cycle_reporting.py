"""M11-W07: reproducible daily cycle reports from immutable IDs.

Covers AC-M11-W07-01/02: each completed cycle references a daily brief,
transcript or legal skip, proposal or no-trade, risk result, broker
outcome, reconciliation, portfolio snapshot, alerts, and data-quality
summary; rebuilding a report from immutable IDs produces byte-equivalent
normalized content and cannot substitute newer evidence.
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
from alphabrief_trader.cycle_execution import (
    IdempotencyMap,
    ReconciliationEvidence,
)
from alphabrief_trader.cycle_report import (
    DailyCycleReport,
    build_cycle_report,
    rebuild_cycle_report,
)
from alphabrief_trader.cycle_state import CycleStateMachine, CycleTransition
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


def _reconciler(attempts: list[dict[str, object]]) -> ReconciliationEvidence:
    return ReconciliationEvidence(
        cycle_id="report-cycle",
        attempt_count=len(attempts),
        order_ids=[str(a.get("order_id") or "") for a in attempts],
        matched=True,
        account_snapshot={"equity": "100000", "currency": "USD"},
        detail="immediate post-trade reconciliation",
        created_at=_FIXED_NOW,
    )


def _build_cycle(
    store: AiTradingStore,
    state_store: CycleStateStore,
    runtime_store: RuntimeTruthStore,
    idem: IdempotencyMap,
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
        reconciler=_reconciler,
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


def _report_from_cycle(
    store: CycleStateStore, cycle_id: str
) -> DailyCycleReport:
    machine = CycleStateMachine(store)
    return build_cycle_report(
        cycle_id=cycle_id,
        trading_date="2026-08-13",
        transitions=machine.transitions(cycle_id),
        portfolio_snapshot={"equity": "100000", "currency": "USD"},
        alert_summary={"open": 0},
        data_quality_summary={"verdict": "acceptable"},
        clock=lambda: _FIXED_NOW,
    )


class TestCompleteCycleReport:
    def test_completed_cycle_references_all_evidence(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(store, state_store, runtime_store, idem)
        record = cycle.run(["SPY"], cycle_key="cyc-report")

        report = _report_from_cycle(state_store, record.cycle_id)
        assert report.cycle_id == record.cycle_id
        assert report.scheduler_outcome == record.outcome
        # Proposal or no-trade is always present.
        assert report.proposal_ids or report.no_trade_reason
        # Decision chain and broker outcome.
        assert report.decision_ids
        assert report.broker_order_ids
        # Reconciliation, portfolio, alerts, data quality.
        assert report.reconciliation_id is not None
        assert report.portfolio_snapshot["equity"] == "100000"
        assert report.alert_summary["open"] == 0
        assert report.data_quality_summary["verdict"] == "acceptable"
        # Transcript or legal skip.
        assert report.transcript_id is not None or report.transcript_skip_reason

    def test_no_trade_cycle_references_no_trade_reason(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(store, state_store, runtime_store, idem)
        cycle._preflight_facts_provider = lambda: PreflightFacts(
            data_fresh=False
        )
        record = cycle.run(["SPY"], cycle_key="cyc-no-trade-report")

        report = _report_from_cycle(state_store, record.cycle_id)
        assert report.scheduler_outcome == "blocked_risk_gate"
        assert report.no_trade_reason is not None
        assert report.broker_order_ids == []

    def test_report_id_is_deterministic(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(store, state_store, runtime_store, idem)
        record = cycle.run(["SPY"], cycle_key="cyc-deterministic")

        first = _report_from_cycle(state_store, record.cycle_id)
        second = _report_from_cycle(state_store, record.cycle_id)
        assert first.report_id == second.report_id
        assert first.normalized_json() == second.normalized_json()


class TestRebuildEquivalence:
    def _transitions(
        self, cycle_id: str, machine: CycleStateMachine
    ) -> list[CycleTransition]:
        return machine.transitions(cycle_id)

    def test_rebuild_is_byte_equivalent(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(store, state_store, runtime_store, idem)
        record = cycle.run(["SPY"], cycle_key="cyc-rebuild")

        machine = CycleStateMachine(state_store)
        transitions = self._transitions(record.cycle_id, machine)
        original = build_cycle_report(
            cycle_id=record.cycle_id,
            trading_date="2026-08-13",
            transitions=transitions,
            portfolio_snapshot={"equity": "100000"},
            alert_summary={"open": 0},
            data_quality_summary={"verdict": "acceptable"},
            clock=lambda: _FIXED_NOW,
        )
        from datetime import timedelta

        rebuilt = rebuild_cycle_report(
            original,
            transitions,
            clock=lambda: _FIXED_NOW + timedelta(hours=1),
        )
        assert rebuilt.report_id == original.report_id
        assert rebuilt.normalized_json() == original.normalized_json()
        assert rebuilt.scheduler_outcome == original.scheduler_outcome
        assert rebuilt.broker_order_ids == original.broker_order_ids

    def test_newer_evidence_cannot_substitute(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(store, state_store, runtime_store, idem)
        record = cycle.run(["SPY"], cycle_key="cyc-frozen")

        machine = CycleStateMachine(state_store)
        original = build_cycle_report(
            cycle_id=record.cycle_id,
            trading_date="2026-08-13",
            transitions=machine.transitions(record.cycle_id),
            clock=lambda: _FIXED_NOW,
        )
        # A later cycle with newer evidence must not change the old report.
        later = cycle.run(["SPY"], cycle_key="cyc-later")
        assert later.cycle_id != record.cycle_id
        frozen = build_cycle_report(
            cycle_id=record.cycle_id,
            trading_date="2026-08-13",
            transitions=machine.transitions(record.cycle_id),
            clock=lambda: _FIXED_NOW,
        )
        assert frozen.report_id == original.report_id
        assert frozen.normalized_json() == original.normalized_json()
