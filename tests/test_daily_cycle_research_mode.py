"""M11-W03: research scheduling runs independently of execution enablement.

Covers AC-M11-W03-01/03: a frozen, disabled, or broker-unready execution
path still completes eligible ingest, snapshot, committee, and report
phases; research-only, execution-disabled, blocked, and executable modes
are persisted as distinct machine-readable states with reasons.
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
from alphabrief_trader.cycle_state import CycleStateMachine
from alphabrief_trader.daily_cycle import DurableDailyCycle
from alphabrief_trader.db_store import AiTradingStore, CycleStateStore
from alphabrief_trader.execution_gate import (
    ExecutionMode,
    PreflightFacts,
)
from alphabrief_trader.rules import DisciplineConfig
from alphabrief_trader.runtime_truth import RuntimeTruthStore
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
    runtime_store: RuntimeTruthStore,
    *,
    facts: PreflightFacts,
    submit_count: list[int] | None = None,
) -> DurableDailyCycle:
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )
    from alphabrief_core import OrderIntent, RiskDecision
    from alphabrief_trader.execution_backend import (
        ExecutionBackendResult,
        LocalPaperExecutionBackend,
    )

    class _CountingBackend(LocalPaperExecutionBackend):
        def submit(
            self,
            intent: OrderIntent,
            decision: RiskDecision,
            *,
            reference_price: Decimal,
            now: datetime,
            estimated_quantity: Decimal | None,
        ) -> ExecutionBackendResult:
            if submit_count is not None:
                submit_count.append(1)
            return super().submit(
                intent,
                decision,
                reference_price=reference_price,
                now=now,
                estimated_quantity=estimated_quantity,
            )

    return DurableDailyCycle(
        committee=_committee(),
        risk_gate=_risk_gate(),
        broker=broker,
        store=store,
        state_store=state_store,
        runtime_store=runtime_store,
        snapshot_loader=lambda s: _snapshot(s),
        execution_backend=_CountingBackend(broker),
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


class TestResearchRunsWhenExecutionBlocked:
    def test_blocked_cycle_completes_research_phases(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        submits: list[int] = []
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(
                credentials_present=False,  # blocks execution
            ),
            submit_count=submits,
        )
        record = cycle.run(["SPY"], cycle_key="cyc-blocked")

        machine = CycleStateMachine(state_store)
        # The full legal phase sequence still completed.
        phases = [t.phase for t in machine.transitions(record.cycle_id)]
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
        # Research artifacts are present; execution produced zero submits.
        discuss = next(
            t for t in machine.transitions(record.cycle_id)
            if t.phase == "propose"
        )
        assert discuss.output_ids["votes"]
        assert submits == []
        assert record.attempts == []

    def test_disabled_cycle_completes_research_phases(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        submits: list[int] = []
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(trading_enabled=False),
            submit_count=submits,
        )
        record = cycle.run(["SPY"], cycle_key="cyc-disabled")

        machine = CycleStateMachine(state_store)
        assert machine.is_complete(record.cycle_id) is True
        assert submits == []
        assert record.votes  # committee research still ran

    def test_research_only_cycle_completes_research_phases(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        submits: list[int] = []
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(research_only=True),
            submit_count=submits,
        )
        record = cycle.run(["SPY"], cycle_key="cyc-research")

        machine = CycleStateMachine(state_store)
        assert machine.is_complete(record.cycle_id) is True
        assert submits == []
        assert record.plans  # proposals still produced

    def test_executable_cycle_can_submit(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        submits: list[int] = []
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(),  # everything passes
            submit_count=submits,
        )
        record = cycle.run(["SPY"], cycle_key="cyc-exec")

        assert record.outcome == "executed"
        assert len(submits) >= 1


class TestModePersistence:
    def test_blocked_mode_persisted_with_reasons(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(
                credentials_present=False,
                backup_ok=False,
            ),
        )
        cycle.run(["SPY"], cycle_key="cyc-blocked")

        mode = runtime_store.get_execution_mode()
        assert mode is not None
        assert mode["mode"] == ExecutionMode.BLOCKED.value
        assert set(mode["reasons"]) == {
            "missing_credentials",
            "backup_failed",
        }

    def test_executable_mode_persisted(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(
            store, state_store, runtime_store, facts=PreflightFacts()
        )
        cycle.run(["SPY"], cycle_key="cyc-exec")

        mode = runtime_store.get_execution_mode()
        assert mode is not None
        assert mode["mode"] == ExecutionMode.EXECUTABLE.value
        assert mode["reasons"] == []

    def test_modes_are_distinct_machine_readable_states(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        seen: set[str] = set()
        for key, facts in (
            ("cyc-a", PreflightFacts()),
            ("cyc-b", PreflightFacts(trading_enabled=False)),
            ("cyc-c", PreflightFacts(research_only=True)),
            ("cyc-d", PreflightFacts(credentials_present=False)),
        ):
            cycle = _build_cycle(
                store, state_store, runtime_store, facts=facts
            )
            cycle.run(["SPY"], cycle_key=key)
            mode = runtime_store.get_execution_mode()
            assert mode is not None
            seen.add(mode["mode"])
        assert seen == {
            ExecutionMode.EXECUTABLE.value,
            ExecutionMode.EXECUTION_DISABLED.value,
            ExecutionMode.RESEARCH_ONLY.value,
            ExecutionMode.BLOCKED.value,
        }

    def test_execute_gate_records_mode_in_transitions(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            facts=PreflightFacts(kill_switch_active=True),
        )
        cycle.run(["SPY"], cycle_key="cyc-kill")

        machine = CycleStateMachine(state_store)
        cycle_id = cycle._cycle_id("cyc-kill", ["SPY"])
        preflight = next(
            t for t in machine.transitions(cycle_id)
            if t.phase == "ingest"
        )
        assert preflight.output_ids["execution_mode"] == "blocked"
        assert "kill_switch_active" in preflight.output_ids["execution_reasons"]
