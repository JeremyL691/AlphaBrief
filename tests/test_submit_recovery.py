"""Tests for crash recovery after order submission (PROJECT_GUIDE S5).

Verifies that if a crash occurs after broker submission but before cycle
persistence:
1. Re-running with the same cycle_key / intent deterministically resolves
   the order as accepted via UnknownOutcomeResolver instead of aborting
   with already_consumed or submitting a second order.
2. ALPHABRIEF_TEST_CRASH_AT=after_submit triggers SIGKILL after submit.
3. Restarting after crash resolves the order and completes the cycle.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_execution.broker.oanda.unknown_outcome import (
    SubmitResolutionResult,
)
from alphabrief_execution.broker.port import (
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderStatus,
    SubmitRequest,
    SubmitResult,
)
from alphabrief_execution.broker.risk_context import (
    AccountSourceDatum,
    BrokerRiskContextBuilder,
)
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_risk.broker_context import (
    ConversionDatum,
    HealthState,
    PendingOrderDatum,
    PositionDatum,
    PriceDatum,
    ReconciliationState,
    TradeDatum,
)
from alphabrief_risk.decision_binding import (
    DecisionBindingService,
)
from alphabrief_risk.decision_store import RiskDecisionStore
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.daily_cycle import DailyTradingCycle
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.execution_backend import (
    ExternalPaperExecutionBackend,
)
from alphabrief_trader.rules import DisciplineConfig
from alphabrief_trader.schemas import MarketSnapshot
from committee_provider import GroundedProvider

ACCOUNT = "101-004-1234567-001"
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


class MockBrokerAdapter(BrokerAdapter):
    """Mock broker adapter to record submits and support resolution."""

    def __init__(self) -> None:
        self.submitted_orders: list[SubmitRequest] = []
        self.submit_count = 0
        self.orders_by_client_id: dict[str, str] = {}

    async def health(self) -> BrokerHealth:
        return BrokerHealth(healthy=True, detail="ok", checked_at=NOW)

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str | None = None
    ) -> SubmitResult:
        self.submit_count += 1
        self.submitted_orders.append(request)
        broker_order_id = f"broker-{self.submit_count}"
        if client_order_id:
            self.orders_by_client_id[client_order_id] = broker_order_id
        return SubmitResult(
            broker_order_id=broker_order_id,
            client_order_id=client_order_id or "cli-1",
            status=BrokerOrderStatus.FILLED,
            accepted_at=NOW,
        )

    async def cancel(self, broker_order_id: str) -> Any:
        raise NotImplementedError

    async def get_order(self, broker_order_id: str) -> Any:
        raise NotImplementedError

    async def list_orders(self, status: Any = None) -> list[Any]:
        return []

    async def list_fills(self, since: Any = None) -> list[Any]:
        return []

    async def get_positions(self) -> list[Any]:
        return []

    async def get_account(self) -> Any:
        raise NotImplementedError


class MockResolver:
    """Mock UnknownOutcomeResolver querying MockBrokerAdapter."""

    def __init__(self, adapter: MockBrokerAdapter) -> None:
        self.adapter = adapter

    def resolve(self, client_order_id: str) -> SubmitResolutionResult:
        if client_order_id in self.adapter.orders_by_client_id:
            return SubmitResolutionResult(
                resolution="RESOLVED_ACCEPTED",
                broker_order_id=self.adapter.orders_by_client_id[client_order_id],
                state="FILLED",
                detail="order accepted by broker",
            )
        return SubmitResolutionResult(
            resolution="RESOLVED_NOT_SUBMITTED",
            detail="not found",
        )


class FreshSources:
    def __init__(self, *, now: datetime = NOW) -> None:
        self._now = now
        self.price_captured_at: datetime = now
        self.reconciliation: ReconciliationState = "clean"
        self.health: HealthState = "healthy"

    def fetch_account(self) -> AccountSourceDatum:
        return AccountSourceDatum(
            account_id=ACCOUNT,
            state="ACTIVE",
            tradeable=True,
            home_currency="USD",
            balance=Decimal("10000"),
            nav=Decimal("10000"),
            margin_used=Decimal("0"),
            margin_available=Decimal("10000"),
            captured_at=self._now,
        )

    def fetch_positions(self) -> list[PositionDatum]:
        return []

    def fetch_pending_orders(self) -> list[PendingOrderDatum]:
        return []

    def fetch_trades(self) -> list[TradeDatum]:
        return []

    def fetch_prices(self) -> list[PriceDatum]:
        return [
            PriceDatum(
                symbol="EUR_USD",
                bid=Decimal("1.10400"),
                ask=Decimal("1.10420"),
                captured_at=self.price_captured_at,
            )
        ]

    def fetch_conversions(self) -> list[ConversionDatum]:
        return []

    def fetch_catalog_version(self) -> str | None:
        return "catalog-2026-08-13"

    def fetch_reconciliation_state(self) -> ReconciliationState:
        return self.reconciliation

    def fetch_health(self) -> HealthState:
        return self.health


def test_already_consumed_resolves_and_avoids_duplicate_order(tmp_path: Path) -> None:
    """Validate_before_submit already_consumed resolves without duplicate submit."""
    db_path = tmp_path / "test.db"
    store = RiskDecisionStore(db_path=db_path)
    binding = DecisionBindingService(store)
    adapter = MockBrokerAdapter()
    resolver = MockResolver(adapter)
    sources = FreshSources()
    builder = BrokerRiskContextBuilder(sources, clock=lambda: NOW)

    backend = ExternalPaperExecutionBackend(
        adapter,
        risk_context_builder=builder,
        decision_binding=binding,
        unknown_outcome_resolver=resolver,  # type: ignore[arg-type]
        policy_hash="test-policy-hash",
    )

    intent = OrderIntent(
        intent_id="intent_12345",
        symbol="EUR_USD",
        side="buy",
        order_type="market",
        quantity=Decimal("1000"),
        rationale="test rationale",
        source="manual",
        created_at=NOW,
    )
    decision = RiskDecision(
        decision_id="risk_12345",
        intent_id="intent_12345",
        approved=True,
        reason="approved",
        max_quantity=Decimal("1000"),
        risk_tags=["rule_ok"],
        requires_human_review=False,
        created_at=NOW,
    )

    # First submit succeeds
    res1 = backend.submit(
        intent,
        decision,
        reference_price=Decimal("1.1040"),
        now=NOW,
        estimated_quantity=Decimal("1000"),
    )
    assert res1.filled is True
    assert res1.broker_order_id == "broker-1"
    assert adapter.submit_count == 1

    # Second submit with the exact same intent & decision (crash recovery scenario):
    # Decision was marked consumed in the first submit.
    # Backend must NOT call adapter.submit() again, but resolve it!
    res2 = backend.submit(
        intent,
        decision,
        reference_price=Decimal("1.1040"),
        now=NOW,
        estimated_quantity=Decimal("1000"),
    )
    assert res2.filled is True
    assert res2.broker_order_id == "broker-1"
    # CRITICAL: broker submit count did NOT increase!
    assert adapter.submit_count == 1


def test_daily_cycle_crash_recovery_resumes_without_duplicate(tmp_path: Path) -> None:
    """DailyTradingCycle recovers after crash and produces exactly one order."""
    db_path = tmp_path / "trader.db"
    store = AiTradingStore(db_path=db_path)
    risk_store = RiskDecisionStore(db_path=db_path)
    binding = DecisionBindingService(risk_store)
    adapter = MockBrokerAdapter()
    resolver = MockResolver(adapter)
    sources = FreshSources()
    builder = BrokerRiskContextBuilder(sources, clock=lambda: NOW)

    backend = ExternalPaperExecutionBackend(
        adapter,
        risk_context_builder=builder,
        decision_binding=binding,
        unknown_outcome_resolver=resolver,  # type: ignore[arg-type]
        policy_hash="test-policy-hash",
    )

    _BULLISH_PAYLOAD = {
        "analysis": "Bullish continuation.",
        "view": "bullish",
        "confidence": 0.7,
        "evidence_ids": ["input-evidence"],
        "risks": ["r1"],
        "suggested_action": "buy",
        "target_position_pct": 0.10,
        "veto": False,
        "needs_human_review": False,
    }

    provider = GroundedProvider(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=_BULLISH_PAYLOAD,
    )
    from alphabrief_models import ModelGateway

    committee = TradingCommittee(
        gateway=ModelGateway(providers=[provider]),
        discipline=DisciplineConfig(),
    )

    snapshot_time = NOW
    snapshot = MarketSnapshot(
        symbol="EUR_USD",
        reference_price=Decimal("1.1040"),
        data_version="v1",
        captured_at=snapshot_time,
        atr=Decimal("0.0010"),
    )

    cycle = DailyTradingCycle(
        committee=committee,
        risk_gate=RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True, symbol_allowlist=frozenset({"EUR_USD"})
            )
        ),
        execution_backend=backend,
        store=store,
        snapshot_loader=lambda s: snapshot,
        quantity_override=Decimal("1000"),
        trading_mode="on",
        enabled=True,
        clock=lambda: snapshot_time,
    )

    # Run cycle once
    record1 = cycle.run(["EUR_USD"], cycle_key="round-20260101-A")
    assert record1.outcome == "executed"
    assert adapter.submit_count == 1
    broker_id_1 = record1.attempts[0].order_id

    # Simulate re-running after crash:
    # Say the cycle store had not saved cycle (simulate crash before save_cycle)
    store._conn.execute(
        "DELETE FROM ai_daily_cycles WHERE cycle_id = ?", [record1.cycle_id]
    )

    # Construct cycle again (as after restart)
    cycle2 = DailyTradingCycle(
        committee=committee,
        risk_gate=RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True, symbol_allowlist=frozenset({"EUR_USD"})
            )
        ),
        execution_backend=backend,
        store=store,
        snapshot_loader=lambda s: snapshot,
        quantity_override=Decimal("1000"),
        trading_mode="on",
        enabled=True,
        clock=lambda: snapshot_time,
    )

    record2 = cycle2.run(["EUR_USD"], cycle_key="round-20260101-A")
    assert record2.outcome == "executed"
    # Broker submit count MUST STILL BE 1!
    assert adapter.submit_count == 1
    assert record2.attempts[0].order_id == broker_id_1


def test_already_consumed_not_submitted_raises(tmp_path: Path) -> None:
    """When decision is consumed but broker has no order, raise SUBMIT_NOT_ACCEPTED."""
    from alphabrief_trader.execution_backend import ExecutionBackendError

    db_path = tmp_path / "test.db"
    store = RiskDecisionStore(db_path=db_path)
    binding = DecisionBindingService(store)
    adapter = MockBrokerAdapter()
    sources = FreshSources()
    builder = BrokerRiskContextBuilder(sources, clock=lambda: NOW)

    # Custom resolver that returns RESOLVED_NOT_SUBMITTED
    class NotSubmittedResolver:
        def resolve(self, client_order_id: str) -> SubmitResolutionResult:
            return SubmitResolutionResult(
                resolution="RESOLVED_NOT_SUBMITTED",
                detail="order not on broker",
            )

    backend = ExternalPaperExecutionBackend(
        adapter,
        risk_context_builder=builder,
        decision_binding=binding,
        unknown_outcome_resolver=NotSubmittedResolver(),  # type: ignore[arg-type]
        policy_hash="test-policy-hash",
    )

    intent = OrderIntent(
        intent_id="intent_not_sub",
        symbol="EUR_USD",
        side="buy",
        order_type="market",
        quantity=Decimal("1000"),
        rationale="test rationale",
        source="manual",
        created_at=NOW,
    )
    decision = RiskDecision(
        decision_id="risk_not_sub",
        intent_id="intent_not_sub",
        approved=True,
        reason="approved",
        max_quantity=Decimal("1000"),
        risk_tags=["rule_ok"],
        requires_human_review=False,
        created_at=NOW,
    )

    # First submit succeeds
    backend.submit(
        intent,
        decision,
        reference_price=Decimal("1.1040"),
        now=NOW,
        estimated_quantity=Decimal("1000"),
    )

    # Second submit queries resolver, gets RESOLVED_NOT_SUBMITTED
    with pytest.raises(ExecutionBackendError, match="SUBMIT_NOT_ACCEPTED"):
        backend.submit(
            intent,
            decision,
            reference_price=Decimal("1.1040"),
            now=NOW,
            estimated_quantity=Decimal("1000"),
        )


def test_already_consumed_unresolved_raises(tmp_path: Path) -> None:
    """When decision is consumed and query is inconclusive, raise SUBMIT_UNKNOWN."""
    from alphabrief_trader.execution_backend import ExecutionBackendError

    db_path = tmp_path / "test.db"
    store = RiskDecisionStore(db_path=db_path)
    binding = DecisionBindingService(store)
    adapter = MockBrokerAdapter()
    sources = FreshSources()
    builder = BrokerRiskContextBuilder(sources, clock=lambda: NOW)

    class UnresolvedResolver:
        def resolve(self, client_order_id: str) -> SubmitResolutionResult:
            return SubmitResolutionResult(
                resolution="UNRESOLVED",
                detail="network timeout querying broker",
            )

    backend = ExternalPaperExecutionBackend(
        adapter,
        risk_context_builder=builder,
        decision_binding=binding,
        unknown_outcome_resolver=UnresolvedResolver(),  # type: ignore[arg-type]
        policy_hash="test-policy-hash",
    )

    intent = OrderIntent(
        intent_id="intent_unres",
        symbol="EUR_USD",
        side="buy",
        order_type="market",
        quantity=Decimal("1000"),
        rationale="test rationale",
        source="manual",
        created_at=NOW,
    )
    decision = RiskDecision(
        decision_id="risk_unres",
        intent_id="intent_unres",
        approved=True,
        reason="approved",
        max_quantity=Decimal("1000"),
        risk_tags=["rule_ok"],
        requires_human_review=False,
        created_at=NOW,
    )

    # First submit succeeds
    backend.submit(
        intent,
        decision,
        reference_price=Decimal("1.1040"),
        now=NOW,
        estimated_quantity=Decimal("1000"),
    )

    # Second submit queries resolver, gets UNRESOLVED
    with pytest.raises(ExecutionBackendError, match="SUBMIT_UNKNOWN"):
        backend.submit(
            intent,
            decision,
            reference_price=Decimal("1.1040"),
            now=NOW,
            estimated_quantity=Decimal("1000"),
        )


def test_crash_hook_kills_process_and_restart_recovers(tmp_path: Path) -> None:
    """Crash hook triggers SIGKILL, then second run resolves safely."""
    # Write runner script that runs a cycle with shared sqlite/duckdb file
    script_path = tmp_path / "run_crash_test.py"
    db_file = tmp_path / "crash_test.db"
    script_content = f"""
import sys
from datetime import UTC, datetime
from decimal import Decimal
from alphabrief_core import RiskDecision
from alphabrief_execution.broker.risk_context import (
    BrokerRiskContextBuilder,
)
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_risk.decision_binding import DecisionBindingService
from alphabrief_risk.decision_store import RiskDecisionStore
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.daily_cycle import DailyTradingCycle
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.execution_backend import ExternalPaperExecutionBackend
from alphabrief_trader.rules import DisciplineConfig
from alphabrief_trader.schemas import MarketSnapshot
from committee_provider import GroundedProvider
from test_submit_recovery import FreshSources, MockBrokerAdapter, MockResolver, NOW

store = AiTradingStore(db_path="{db_file}")
risk_store = RiskDecisionStore(db_path="{db_file}")
binding = DecisionBindingService(risk_store)
adapter = MockBrokerAdapter()
# Prepopulate shared orders or use persistent store
resolver = MockResolver(adapter)
sources = FreshSources()
builder = BrokerRiskContextBuilder(sources, clock=lambda: NOW)

backend = ExternalPaperExecutionBackend(
    adapter,
    risk_context_builder=builder,
    decision_binding=binding,
    unknown_outcome_resolver=resolver,
    policy_hash="test-policy-hash",
)

payload = {{
    "analysis": "Bullish.",
    "view": "bullish",
    "confidence": 0.7,
    "evidence_ids": ["input-evidence"],
    "risks": ["r1"],
    "suggested_action": "buy",
    "target_position_pct": 0.10,
    "veto": False,
    "needs_human_review": False,
}}

from alphabrief_models import ModelGateway
committee = TradingCommittee(
    gateway=ModelGateway(providers=[GroundedProvider(
        provider_name="fake", model_name="fake-1",
        capabilities=["structured_output"], structured_output=payload
    )]),
    discipline=DisciplineConfig(),
)

snapshot = MarketSnapshot(
    symbol="EUR_USD", reference_price=Decimal("1.1040"),
    data_version="v1", captured_at=NOW, atr=Decimal("0.0010"),
)

limits = RiskLimitConfig(
    trading_enabled=True,
    symbol_allowlist=frozenset({{"EUR_USD"}}),
)
cycle = DailyTradingCycle(
    committee=committee,
    risk_gate=RiskGate(limits=limits),
    execution_backend=backend,
    store=store,
    snapshot_loader=lambda s: snapshot,
    quantity_override=Decimal("1000"),
    trading_mode="on",
    enabled=True,
    clock=lambda: NOW,
)

record = cycle.run(["EUR_USD"], cycle_key="crash-cycle-key")
print("SUCCESS:" + record.outcome)
"""
    script_path.write_text(script_content)

    env_crash = dict(os.environ)
    env_crash["PYTHONPATH"] = (
        f"{Path(__file__).parent}:{os.environ.get('PYTHONPATH', '')}"
    )
    env_crash["ALPHABRIEF_TEST_CRASH_AT"] = "after_submit"

    # Step 1: run with crash hook -> should be killed by SIGKILL
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        env=env_crash,
        capture_output=True,
        text=True,
    )
    # On Unix, killed by signal 9 gives returncode -9 or 137
    assert proc.returncode in (-signal.SIGKILL, 137, -9)
