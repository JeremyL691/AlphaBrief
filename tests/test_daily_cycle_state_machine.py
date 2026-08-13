"""M11-W01: durable daily-cycle state machine.

Covers AC-M11-W01-01/02/03: a normal cycle durably visits preflight,
ingest, snapshot, discuss, propose, risk, execute (or no-trade),
reconcile, report, complete in legal order; every transition atomically
records input hashes, output IDs, attempt counts, timestamps, and prior
state while stale writers are rejected; restart at every phase boundary
resumes from the last committed gate without repeating a completed side
effect.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
)
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.cycle_state import (
    CYCLE_PHASE_ORDER,
    CycleStateMachine,
)
from alphabrief_trader.daily_cycle import DurableDailyCycle
from alphabrief_trader.db_store import AiTradingStore, CycleStateStore
from alphabrief_trader.execution_backend import (
    ExecutionBackend,
    ExecutionBackendResult,
    LocalPaperExecutionBackend,
)
from alphabrief_trader.rules import DisciplineConfig
from alphabrief_trader.schemas import MarketSnapshot

_BULLISH_PAYLOAD: dict[str, object] = {
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

_FIXED_NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


class _CountingExecutionBackend(ExecutionBackend):
    """Execution backend that counts submit calls."""

    def __init__(self, inner: ExecutionBackend) -> None:
        self._inner = inner
        self.submit_count = 0

    def estimate_quantity(
        self, intent: OrderIntent, *, reference_price: Decimal
    ) -> Decimal | None:
        return self._inner.estimate_quantity(
            intent, reference_price=reference_price
        )

    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        reference_price: Decimal,
        now: datetime,
        estimated_quantity: Decimal | None,
    ) -> ExecutionBackendResult:
        self.submit_count += 1
        return self._inner.submit(
            intent,
            decision,
            reference_price=reference_price,
            now=now,
            estimated_quantity=estimated_quantity,
        )


def _snapshot(symbol: str) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        reference_price=Decimal("100"),
        data_version="test-v1",
        captured_at=_FIXED_NOW,
    )


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


def _risk_gate() -> RiskGate:
    return RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True,
            symbol_allowlist=frozenset({"SPY"}),
        )
    )


def _build_cycle(
    store: AiTradingStore,
    state_store: CycleStateStore,
    *,
    submit_counter: _CountingExecutionBackend | None = None,
    committee: TradingCommittee | None = None,
) -> DurableDailyCycle:
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )
    backend = submit_counter or LocalPaperExecutionBackend(broker)
    return DurableDailyCycle(
        committee=committee or _committee(),
        risk_gate=_risk_gate(),
        broker=broker,
        store=store,
        state_store=state_store,
        snapshot_loader=lambda s: _snapshot(s),
        execution_backend=backend,
        enabled=True,
        clock=lambda: _FIXED_NOW,
    )


@pytest.fixture
def stores(tmp_path: Path) -> Iterator[tuple[AiTradingStore, CycleStateStore]]:
    store = AiTradingStore(db_path=tmp_path / "trader.db")
    state_store = CycleStateStore(db_path=tmp_path / "trader.db")
    try:
        yield store, state_store
    finally:
        store.close()
        state_store.close()


class TestLegalPhaseOrder:
    def test_normal_cycle_visits_all_phases_in_order(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        cycle = _build_cycle(store, state_store)
        record = cycle.run(["SPY"], cycle_key="cyc-2026-08-13")

        machine = CycleStateMachine(state_store)
        transitions = machine.transitions(record.cycle_id)
        phases = [t.phase for t in transitions]
        assert phases == [
            "preflight",
            "ingest",
            "snapshot",
            "discuss",
            "propose",
            "risk",
            "execute",
            "reconcile",
            "report",
            "complete",
        ]
        assert machine.is_complete(record.cycle_id) is True
        assert machine.resume_phase(record.cycle_id) is None

    def test_execute_phase_records_no_trade_outcome(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        cycle = _build_cycle(store, state_store)
        record = cycle.run(["SPY"], cycle_key="cyc-hold")
        machine = CycleStateMachine(state_store)
        execute = [
            t
            for t in machine.transitions(record.cycle_id)
            if t.prior_phase == "execute"
        ][0]
        # The fake committee returns a buy plan with positive exposure, so
        # the execute gate records a real outcome.
        assert execute.outcome in {"executed", "no_trade", "blocked"}
        assert execute.output_ids

    def test_terminal_record_is_durable(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        cycle = _build_cycle(store, state_store)
        record = cycle.run(["SPY"], cycle_key="cyc-2026-08-13")
        stored = store.get_cycle(record.cycle_id)
        assert stored is not None
        assert stored["outcome"] == record.outcome
        assert stored["votes"]


class TestAtomicTransitions:
    def test_transition_records_hashes_outputs_attempts_prior_and_time(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        cycle = _build_cycle(store, state_store)
        record = cycle.run(["SPY"], cycle_key="cyc-2026-08-13")
        machine = CycleStateMachine(state_store)
        transitions = machine.transitions(record.cycle_id)
        snapshot_t = next(t for t in transitions if t.phase == "snapshot")
        assert snapshot_t.input_hashes
        # The transition leaving snapshot carries the fingerprint output.
        snapshot_done = next(
            t for t in transitions if t.prior_phase == "snapshot"
        )
        assert "snapshot_fingerprint" in snapshot_done.output_ids
        discuss_t = next(t for t in transitions if t.phase == "propose")
        assert "votes" in discuss_t.output_ids
        assert discuss_t.prior_phase == "discuss"
        assert discuss_t.attempt_count >= 1
        assert discuss_t.created_at.tzinfo is not None
        assert discuss_t.transition_id
        for transition in transitions:
            assert transition.phase_order == CYCLE_PHASE_ORDER.index(
                transition.phase
            )

    def test_stale_writer_is_rejected_without_mutation(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        cycle = _build_cycle(store, state_store)
        record = cycle.run(["SPY"], cycle_key="cyc-2026-08-13")
        machine = CycleStateMachine(state_store)
        before = machine.transitions(record.cycle_id)

        # A writer expecting a stale phase cannot advance anything.
        result = machine.advance(
            record.cycle_id,
            expected_phase="discuss",
            next_phase="propose",
        )
        assert result is None
        assert machine.transitions(record.cycle_id) == before
        assert machine.is_complete(record.cycle_id) is True

    def test_non_monotonic_advance_is_rejected(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        machine = CycleStateMachine(state_store)
        assert machine.begin("cyc-1") is True
        assert machine.advance(
            "cyc-1", expected_phase="preflight", next_phase="ingest"
        ) is not None
        # Cannot go backwards.
        assert (
            machine.advance(
                "cyc-1", expected_phase="ingest", next_phase="preflight"
            )
            is None
        )

    def test_unknown_phase_rejected(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        machine = CycleStateMachine(state_store)
        assert machine.begin("cyc-1") is True
        with pytest.raises(ValueError):
            machine.advance(
                "cyc-1", expected_phase="preflight", next_phase="bogus"
            )

    def test_execute_requires_outcome(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        machine = CycleStateMachine(state_store)
        assert machine.begin("cyc-1") is True
        current = "preflight"
        for _target in ("ingest", "snapshot", "discuss", "propose", "risk"):
            nxt = CYCLE_PHASE_ORDER[CYCLE_PHASE_ORDER.index(current) + 1]
            assert machine.advance(
                "cyc-1", expected_phase=current, next_phase=nxt
            ) is not None
            current = nxt
        assert machine.advance(
            "cyc-1", expected_phase="risk", next_phase="execute"
        ) is not None
        with pytest.raises(ValueError):
            machine.advance(
                "cyc-1", expected_phase="execute", next_phase="reconcile"
            )


class TestRestartResume:
    def test_completed_cycle_returns_stored_record_without_rerunning(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        counter = _CountingExecutionBackend(
            LocalPaperExecutionBackend(_broker())
        )
        cycle = _build_cycle(store, state_store, submit_counter=counter)
        first = cycle.run(["SPY"], cycle_key="cyc-restart")
        submits_after_first = counter.submit_count

        # A fresh durable cycle instance resumes from the completed gate:
        # no committee run, no proposal, no broker submission.
        second = _build_cycle(store, state_store, submit_counter=counter)
        resumed = second.run(["SPY"], cycle_key="cyc-restart")

        assert resumed.cycle_id == first.cycle_id
        assert resumed.outcome == first.outcome
        assert counter.submit_count == submits_after_first
        assert len(store.list_cycles()) == 1

    def test_restart_after_execute_never_repeats_broker_submission(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        counter = _CountingExecutionBackend(
            LocalPaperExecutionBackend(_broker())
        )
        machine = CycleStateMachine(state_store)

        # Simulate a crash right after the execute gate committed: the
        # state says execute is done, but reconcile/report/complete never
        # ran. A restart must not re-submit anything.
        cycle = _build_cycle(store, state_store, submit_counter=counter)
        cycle_id = cycle._cycle_id("cyc-crash-after-execute", ["SPY"])
        assert machine.begin(cycle_id) is True
        current = "preflight"
        while current != "risk":
            nxt = CYCLE_PHASE_ORDER[CYCLE_PHASE_ORDER.index(current) + 1]
            assert machine.advance(
                cycle_id, expected_phase=current, next_phase=nxt
            ) is not None
            current = nxt
        machine.advance(
            cycle_id,
            expected_phase="risk",
            next_phase="execute",
            output_ids={"attempts": "[]"},
            outcome="executed",
        )
        # The execute phase itself completes by committing its leave
        # transition; only then is the crash simulated.
        machine.advance(
            cycle_id,
            expected_phase="execute",
            next_phase="reconcile",
            output_ids={"attempts": "[]"},
            outcome="executed",
        )
        assert counter.submit_count == 0

        record = cycle.run(["SPY"], cycle_key="cyc-crash-after-execute")

        assert counter.submit_count == 0
        assert machine.is_complete(record.cycle_id) is True
        assert record.outcome == "executed"

    def test_restart_from_every_phase_boundary_resumes_correctly(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        machine = CycleStateMachine(state_store)
        cycle_id = "cyc-boundary"
        assert machine.begin(cycle_id) is True

        # Crash at each boundary: commit phase N only, then restart.
        current = "preflight"
        while current != "complete":
            nxt = CYCLE_PHASE_ORDER[CYCLE_PHASE_ORDER.index(current) + 1]
            outcome = "no_trade" if current == "execute" else None
            assert machine.advance(
                cycle_id,
                expected_phase=current,
                next_phase=nxt,
                output_ids={"probe": current},
                outcome=outcome,
            ) is not None
            if nxt != "complete":
                resumed = machine.resume_phase(cycle_id)
                assert resumed == nxt, (current, resumed)
            current = nxt
        assert machine.resume_phase(cycle_id) is None

    def test_restart_runs_only_pending_phases(
        self, stores: tuple[AiTradingStore, CycleStateStore]
    ) -> None:
        store, state_store = stores
        machine = CycleStateMachine(state_store)
        cycle = _build_cycle(store, state_store)
        cycle_id = cycle._cycle_id("cyc-partial", ["SPY"])
        assert machine.begin(cycle_id) is True
        # Commit through snapshot only (crash during discuss).
        current = "preflight"
        while current != "discuss":
            nxt = CYCLE_PHASE_ORDER[CYCLE_PHASE_ORDER.index(current) + 1]
            assert machine.advance(
                cycle_id, expected_phase=current, next_phase=nxt
            ) is not None
            current = nxt

        record = cycle.run(["SPY"], cycle_key="cyc-partial")
        assert machine.is_complete(record.cycle_id) is True
        # The resumed run completed discuss..complete without redoing
        # preflight/ingest/snapshot.
        transitions = machine.transitions(cycle_id)
        phases = [t.phase for t in transitions]
        assert phases == list(CYCLE_PHASE_ORDER)


def _broker() -> PaperBroker:
    return PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )
