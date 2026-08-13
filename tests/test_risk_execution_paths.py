"""M08-W01: AI and manual paper execution paths resolve the same context service.

Covers:
- the AI external backend and the manual paper API path build their
  pre-risk context through the same broker-fresh context service with
  the same context and policy versions (AC-M08-W01-02);
- a missing, stale, or frozen context rejects before submit with no
  order reaching the broker — no synthesized defaults, no fallback
  account, no review bypass (AC-M08-W01-03, REQ-RISK-010).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderStatus,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)
from alphabrief_execution.broker.risk_context import (
    AccountSourceDatum,
    BrokerRiskContextBuilder,
)
from alphabrief_risk.broker_context import (
    DEFAULT_CONTEXT_VERSION,
    DEFAULT_POLICY_VERSION,
    ConversionDatum,
    HealthState,
    PendingOrderDatum,
    PositionDatum,
    PriceDatum,
    ReconciliationState,
    TradeDatum,
)
from alphabrief_trader import ExternalPaperExecutionBackend
from alphabrief_trader.execution_backend import ExecutionBackendError

ACCOUNT = "101-004-1234567-001"
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

class _FakeAdapter(BrokerAdapter):
    """Records submits; used only to prove the order never reaches it."""

    def __init__(self) -> None:
        self.requests: list[SubmitRequest] = []

    async def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=True, detail="ok", checked_at=NOW
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        self.requests.append(request)
        return SubmitResult(
            broker_order_id=f"broker-{client_order_id}",
            client_order_id=client_order_id,
            status=BrokerOrderStatus.NEW,
            accepted_at=NOW,
        )

    async def cancel(self, broker_order_id: str) -> CancelResult:
        raise NotImplementedError

    async def get_order(self, broker_order_id: str) -> OrderState:
        raise NotImplementedError

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        return []

    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        return []

    async def get_positions(self) -> list[Position]:
        return []

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id=ACCOUNT,
            cash=Decimal("10000"),
            equity=Decimal("10000"),
            buying_power=Decimal("10000"),
            currency="USD",
            captured_at=datetime.now(UTC),
        )


class _FreshSources:
    """Complete, fresh venue sources; configurable for fail-closed cases."""

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


def _intent() -> OrderIntent:
    return OrderIntent(
        intent_id="ai_test",
        source="model",
        symbol="EUR_USD",
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        rationale="test",
        created_at=NOW,
    )


def _decision() -> RiskDecision:
    return RiskDecision(
        decision_id="risk_test",
        intent_id="ai_test",
        approved=True,
        reason="approved",
        max_quantity=Decimal("2"),
        risk_tags=["approved"],
        requires_human_review=False,
        source_module="test",
        created_at=NOW,
    )


def _backend_with(
    adapter: _FakeAdapter,
    sources: _FreshSources,
) -> ExternalPaperExecutionBackend:
    return ExternalPaperExecutionBackend(
        adapter,
        risk_context_builder=BrokerRiskContextBuilder(
            sources, clock=lambda: NOW
        ),
    )


# ---------------------------------------------------------------------------
# AC-M08-W01-02: both paths resolve the same builder and versions
# ---------------------------------------------------------------------------


def test_ai_backend_submits_with_fresh_context() -> None:
    adapter = _FakeAdapter()
    backend = ExternalPaperExecutionBackend(adapter)

    result = backend.submit(
        _intent(),
        _decision(),
        reference_price=Decimal("1.10"),
        now=NOW,
        estimated_quantity=Decimal("1"),
    )

    assert len(adapter.requests) == 1
    # The backend's default builder composes its venue sources from the
    # adapter through the one shared context service.
    assert result.risk_context_version == DEFAULT_CONTEXT_VERSION


def test_manual_paper_path_uses_same_service_and_versions() -> None:
    from alphabrief_api.routes.paper import build_paper_risk_context
    from alphabrief_execution import (
        ExecutionAuditLog,
        FillSimulator,
        PaperBroker,
        PortfolioState,
    )
    from alphabrief_execution.broker.risk_context import (
        project_risk_context_to_exposure,
    )

    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        fill_simulator=FillSimulator(),
        audit_log=ExecutionAuditLog(),
    )
    context = build_paper_risk_context(
        broker,
        symbol="EUR_USD",
        reference_price=Decimal("1.10000"),
        now=NOW,
        clock=lambda: NOW,
    )
    # The manual path goes through the same broker-fresh service with the
    # same shared version stamps (AC-M08-W01-02).
    assert context.context_version == DEFAULT_CONTEXT_VERSION
    assert context.policy_version == DEFAULT_POLICY_VERSION
    assert context.account.account_id == "paper_local"
    assert context.balance == Decimal("100000")
    assert context.health_state == "healthy"
    assert context.internally_consistent is True

    exposure = project_risk_context_to_exposure(
        context, mark_prices={"EUR_USD": Decimal("1.10")}
    )
    assert exposure.account_id == "paper_local"
    assert exposure.cash == Decimal("100000")
    assert exposure.current_total_exposure == Decimal("0")


# ---------------------------------------------------------------------------
# AC-M08-W01-03: missing/stale/frozen context rejects before submit
# ---------------------------------------------------------------------------


def test_ai_backend_rejects_when_adapter_unavailable() -> None:
    """The default adapter-derived context fails closed when the broker
    itself is unreachable (account source missing -> no submit)."""
    adapter = _FakeAdapter()

    async def _fail() -> AccountSnapshot:
        raise TimeoutError("broker unreachable")

    adapter.get_account = _fail  # type: ignore[method-assign]
    backend = ExternalPaperExecutionBackend(adapter)
    with pytest.raises(ExecutionBackendError, match="risk context"):
        backend.submit(
            _intent(),
            _decision(),
            reference_price=Decimal("1.10"),
            now=NOW,
            estimated_quantity=Decimal("1"),
        )
    assert adapter.requests == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda sources: setattr(
            sources, "price_captured_at", NOW - timedelta(seconds=300)
        ),
        lambda sources: setattr(sources, "reconciliation", "frozen"),
        lambda sources: setattr(sources, "health", "unhealthy"),
    ],
    ids=["stale", "frozen", "unhealthy"],
)
def test_ai_backend_rejects_defective_context_before_submit(
    mutate: Any,
) -> None:
    """A stale, frozen, or unhealthy context rejects before submit with no
    order reaching the broker (AC-M08-W01-03)."""
    sources = _FreshSources()
    mutate(sources)
    adapter = _FakeAdapter()
    backend = _backend_with(adapter, sources)
    with pytest.raises(ExecutionBackendError, match="risk context"):
        backend.submit(
            _intent(),
            _decision(),
            reference_price=Decimal("1.10"),
            now=NOW,
            estimated_quantity=Decimal("1"),
        )
    assert adapter.requests == []
