"""Reconciliation runner tests.

Driven by an in-memory fake broker adapter so the tests do not need
a real Alpaca server. Covers:

- startup reconciliation raises a freeze on diff
- cycle reconciliation also freezes on diff
- eod reconciliation records but does not freeze
- recon store exposes has_open_freeze / clear_freeze correctly
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.broker.reconciliation import (
    ALLOWED_SCOPES,
    ReconcilerConfig,
    ReconciliationRunner,
)


class FakeAdapter(BrokerAdapter):
    """Configurable in-memory adapter for reconciliation tests."""

    def __init__(self) -> None:
        self.orders: list[OrderState] = []
        self.positions: list[Position] = []
        self.account = AccountSnapshot(
            account_id="acct-fake",
            cash=Decimal("1000"),
            equity=Decimal("1000"),
            buying_power=Decimal("2000"),
            currency="USD",
            captured_at=datetime(2026, 6, 20, tzinfo=UTC),
        )
        self.fail_with: Exception | None = None

    async def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=True, detail="ok", checked_at=datetime(2026, 6, 20, tzinfo=UTC)
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        order = OrderState(
            broker_order_id=f"b-{client_order_id}",
            client_order_id=client_order_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            filled_quantity=Decimal("0"),
            limit_price=request.limit_price,
            status=BrokerOrderStatus.NEW,
            submitted_at=datetime(2026, 6, 20, tzinfo=UTC),
            updated_at=datetime(2026, 6, 20, tzinfo=UTC),
        )
        self.orders.append(order)
        return SubmitResult(
            broker_order_id=order.broker_order_id,
            client_order_id=client_order_id,
            status=BrokerOrderStatus.NEW,
            accepted_at=order.submitted_at,
        )

    async def cancel(self, broker_order_id: str) -> CancelResult:
        for o in self.orders:
            if o.broker_order_id == broker_order_id:
                o.status = BrokerOrderStatus.CANCELLED
                return CancelResult(
                    broker_order_id=broker_order_id,
                    status=BrokerOrderStatus.CANCELLED,
                    cancelled_at=datetime(2026, 6, 20, tzinfo=UTC),
                )
        raise ValueError("unknown")

    async def get_order(self, broker_order_id: str) -> OrderState:
        for o in self.orders:
            if o.broker_order_id == broker_order_id:
                return o
        raise ValueError("unknown")

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        if self.fail_with is not None:
            raise self.fail_with
        return list(self.orders)

    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        return []

    async def get_positions(self) -> list[Position]:
        return list(self.positions)

    async def get_account(self) -> AccountSnapshot:
        return self.account


@pytest.fixture
def store(tmp_path: Any) -> BrokerReconStore:
    s = BrokerReconStore(db_path=tmp_path / "recon.db")
    yield s
    s.close()


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_unknown_scope_rejected(store: BrokerReconStore) -> None:
    adapter = FakeAdapter()
    runner = ReconciliationRunner(adapter=adapter, store=store)
    with pytest.raises(ValueError, match="unknown reconciliation scope"):
        _run(runner.reconcile(scope="not-a-scope"))


def test_startup_with_no_diff_records_clean_snapshot(store: BrokerReconStore) -> None:
    adapter = FakeAdapter()
    runner = ReconciliationRunner(adapter=adapter, store=store)
    result = _run(runner.reconcile(scope="startup"))
    assert result.snapshot.all_match is True
    assert result.freeze_raised is False
    assert store.has_open_freeze() is False


def test_unknown_broker_order_raises_freeze_on_startup(store: BrokerReconStore) -> None:
    adapter = FakeAdapter()
    adapter.orders.append(
        OrderState(
            broker_order_id="orphan",
            client_order_id="orphan-cli",
            symbol="SPY",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("1"),
            filled_quantity=Decimal("0"),
            status=BrokerOrderStatus.NEW,
            submitted_at=datetime(2026, 6, 20, tzinfo=UTC),
            updated_at=datetime(2026, 6, 20, tzinfo=UTC),
        )
    )
    runner = ReconciliationRunner(adapter=adapter, store=store)
    result = _run(runner.reconcile(scope="startup"))
    assert result.snapshot.all_match is False
    assert result.freeze_raised is True
    assert store.has_open_freeze() is True


def test_eod_with_diff_records_but_does_not_freeze(store: BrokerReconStore) -> None:
    adapter = FakeAdapter()
    adapter.orders.append(
        OrderState(
            broker_order_id="orphan",
            client_order_id="orphan-cli",
            symbol="SPY",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("1"),
            filled_quantity=Decimal("0"),
            status=BrokerOrderStatus.NEW,
            submitted_at=datetime(2026, 6, 20, tzinfo=UTC),
            updated_at=datetime(2026, 6, 20, tzinfo=UTC),
        )
    )
    runner = ReconciliationRunner(adapter=adapter, store=store)
    result = _run(runner.reconcile(scope="eod"))
    assert result.snapshot.all_match is False
    assert result.freeze_raised is False
    assert store.has_open_freeze() is False


def test_failed_recon_pass_raises_freeze(store: BrokerReconStore) -> None:
    adapter = FakeAdapter()
    adapter.fail_with = RuntimeError("adapter offline")
    runner = ReconciliationRunner(adapter=adapter, store=store)
    result = _run(runner.reconcile(scope="startup"))
    assert result.snapshot.all_match is False
    assert result.freeze_raised is True


def test_clear_freeze_resets_open_state(store: BrokerReconStore) -> None:
    store.raise_freeze(reason="manual", source="test")
    assert store.has_open_freeze() is True
    event = store.list_freezes(only_open=True)[0]
    store.clear_freeze(event_id=event.event_id, reason="manual unfreeze")
    assert store.has_open_freeze() is False


def test_clear_unknown_freeze_raises(store: BrokerReconStore) -> None:
    with pytest.raises(ValueError, match="unknown freeze event_id"):
        store.clear_freeze(event_id="not-an-event")


def test_snapshot_listing_returns_recent_first(store: BrokerReconStore) -> None:
    for scope in ("startup", "cycle", "eod"):
        store.record_snapshot(
            scope=scope,
            orders_match=True,
            fills_match=True,
            cash_match=True,
            positions_match=True,
        )
    snapshots = store.list_snapshots()
    assert len(snapshots) == 3
    assert snapshots[0].scope == "eod"


def test_allowed_scopes_constant_is_complete() -> None:
    assert ALLOWED_SCOPES == frozenset({"startup", "cycle", "eod"})


def test_reconciler_config_rejects_unknown_scope() -> None:
    config = ReconcilerConfig()
    snapshot = type("S", (), {"all_match": True})()
    with pytest.raises(ValueError, match="unknown reconciliation scope"):
        config.should_freeze("garbage", snapshot)  # type: ignore[arg-type]
