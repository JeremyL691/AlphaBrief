"""M07-W06: restart recovery across every submit and reconciliation transition.

Covers:
- crash injection before reserve, after reserve, before send, after send,
  after response, during fact commit, during cursor advance, and during
  reconciliation recovers deterministically without a second external
  order (AC-M07-W06-01);
- 100 same-cycle replays across fresh processes produce at most one
  external submit identity and one explainable terminal ledger chain
  (AC-M07-W06-02);
- startup sync resolves in-flight submits by query, restores the durable
  submit mapping, and freezes unresolved outcomes (REQ-EXEC-011);
- send failures and unresolved queries freeze instead of re-submitting
  (REQ-EXEC-005), and blocking reconciliation differences freeze new
  exposure while the immutable submit stays complete.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.account_projection import (
    AccountSnapshot,
)
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.freeze_policy import (
    ExposureFreezeStore,
)
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
from alphabrief_execution.broker.oanda.order_ledger import (
    LedgerTransitionError,
    OrderLedger,
)
from alphabrief_execution.broker.oanda.order_ops import (
    OrderCreateResult,
    OrderOpsClient,
)
from alphabrief_execution.broker.oanda.orders import OandaOrderRequest
from alphabrief_execution.broker.oanda.reconcile import (
    Reconciler,
    ReconciliationReport,
    RemoteAccountView,
    RemoteOrder,
)
from alphabrief_execution.broker.oanda.submit_recovery import (
    FAULT_POINTS,
    FaultPoint,
    InjectedCrash,
    StartupSyncService,
    SubmitWorkflow,
    SubmitWorkflowResult,
)
from alphabrief_execution.broker.oanda.transaction_cursor import (
    AdvanceResult,
    TransactionCursorStore,
)
from alphabrief_execution.broker.oanda.transaction_ops import TransactionResult
from alphabrief_execution.broker.oanda.unknown_outcome import (
    UnknownOutcomeResolver,
)

ACCOUNT = "101-004-1234567-001"
BASE = f"http://oanda.test/v3/accounts/{ACCOUNT}"
CYCLE = "cycle-2026-08-13"
INTENT = "intent-42"
OWNER = "daily-runner"
DECISION = "risk-1"
PAYLOAD = "sha256:abc123"
T0 = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Deterministic fake broker
# ---------------------------------------------------------------------------


class _FakeSubmitBroker:
    """In-memory OANDA practice broker for submit/recovery tests."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.post_count = 0
        self.next_id = 5000
        self.fail_post = False
        self.orders_visible = True
        self.fail_list = False
        self.captured: list[dict[str, Any]] = []

    def _tx(self) -> str:
        value = str(self.next_id)
        self.next_id += 1
        return value

    def handle(self, request: Request) -> bytes:
        method = request.method
        url = request.full_url
        raw = request.data
        body = json.loads(raw.decode("utf-8")) if isinstance(raw, bytes) else {}
        self.captured.append({"method": method, "url": url, "body": body})
        path, _, _ = url.partition("?")

        if method == "POST" and path == f"{BASE}/orders":
            self.post_count += 1
            if self.fail_post:
                raise TimeoutError("simulated transport failure on submit")
            order = body["order"]
            order_id = self._tx()
            extensions = order.get("clientExtensions", {})
            self.orders[order_id] = {
                "id": order_id,
                "instrument": order.get("instrument", ""),
                "units": order.get("units", "0"),
                "state": "FILLED",
                "createTime": "2026-08-13T12:00:00.000000000Z",
                "clientExtensions": extensions,
            }
            return json.dumps(
                {
                    "orderCreateTransaction": {"id": order_id},
                    "orderFillTransaction": {"id": self._tx()},
                }
            ).encode("utf-8")
        if method == "GET" and path == f"{BASE}/orders":
            if self.fail_list:
                raise TimeoutError("simulated transport failure on list")
            if not self.orders_visible:
                return json.dumps({"orders": []}).encode("utf-8")
            return json.dumps({"orders": list(self.orders.values())}).encode("utf-8")
        raise AssertionError(f"unexpected request: {method} {path}")


def _client(broker: _FakeSubmitBroker) -> OandaHttpClient:
    def _send(request: Request, timeout_seconds: float) -> bytes:
        return broker.handle(request)

    return OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=_send,
        token="t",
        account_id=ACCOUNT,
    )


def _request() -> OandaOrderRequest:
    return OandaOrderRequest(
        type="MARKET",
        instrument="EUR_USD",
        units=Decimal("1000"),
        time_in_force="FOK",
    )


def _instrument() -> InstrumentMetadata:
    return InstrumentMetadata(
        name="EUR_USD",
        display_name="EUR/USD",
        raw_type="CURRENCY",
        display_precision=5,
        trade_units_precision=0,
        minimum_trade_size=Decimal("1"),
        maximum_order_units=Decimal("0"),
        maximum_position_size=Decimal("0"),
        margin_rate=Decimal("0.05"),
        pip_location=-4,
    )


def _submit_fn(
    orders: OrderOpsClient, submit_id: str
) -> Callable[[], OrderCreateResult]:
    return lambda: orders.create_order(
        _request(), _instrument(), client_order_id=submit_id
    )


def _facts() -> list[TransactionResult]:
    return [
        TransactionResult(
            transaction_id="6001",
            transaction_type="ORDER_FILL",
            time=T0,
            instrument="EUR_USD",
            units=Decimal("1000"),
            price=Decimal("1.10500"),
            realized_pl=Decimal("0"),
            financing=Decimal("0"),
            request_id="range-6001-6001",
        )
    ]


def _commit_facts(cursor: TransactionCursorStore) -> Callable[[], AdvanceResult]:
    return lambda: cursor.advance(ACCOUNT, _facts(), owner=OWNER)


def _clean_snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        account_id=ACCOUNT,
        last_transaction_id="0",
        balance=Decimal("1000"),
        nav=Decimal("1000"),
        unrealized_pl=Decimal("0"),
        margin_used=Decimal("0"),
        margin_available=Decimal("1000"),
        realized_pl=Decimal("0"),
        financing_total=Decimal("0"),
        open_trade_count=0,
        open_position_count=0,
        orders=(),
        trades=(),
        positions=(),
        fills=(),
        rebuilt_at=T0,
    )


def _clean_report(ledger: OrderLedger) -> ReconciliationReport:
    remote = RemoteAccountView(
        account_id=ACCOUNT, balance=Decimal("1000"), nav=Decimal("1000")
    )
    return Reconciler().reconcile(_clean_snapshot(), remote, ledger=ledger)


def _blocking_report(ledger: OrderLedger) -> ReconciliationReport:
    """One report with a CRITICAL unknown-client-identity remote order."""
    remote = RemoteAccountView(
        account_id=ACCOUNT,
        balance=Decimal("1000"),
        nav=Decimal("1000"),
        orders=(
            RemoteOrder(
                broker_order_id="o-9",
                state="PENDING",
                units=Decimal("100"),
                client_order_id="ext-unknown",
            ),
        ),
    )
    return Reconciler().reconcile(_clean_snapshot(), remote, ledger=ledger)


def _raise_at(point: FaultPoint) -> Callable[[FaultPoint], None]:
    def _fault(actual: FaultPoint) -> None:
        if actual == point:
            raise InjectedCrash(point)

    return _fault


# ---------------------------------------------------------------------------
# Workflow harness (fresh process per run, same durable files)
# ---------------------------------------------------------------------------


def _new_handles(
    tmp_path: Path,
    broker: _FakeSubmitBroker,
    *,
    fault: Callable[[FaultPoint], None] | None = None,
    ledger_db: str = "ledger.db",
) -> dict[str, Any]:
    """One fresh-process component set over the same durable files."""
    ledger = OrderLedger(db_path=tmp_path / ledger_db)
    cursor = TransactionCursorStore(db_path=tmp_path / "cursor.db")
    freeze = ExposureFreezeStore(db_path=tmp_path / "freeze.db")
    orders = OrderOpsClient(_client(broker))
    workflow = SubmitWorkflow(
        ledger=ledger,
        account_id=ACCOUNT,
        owner=OWNER,
        resolve=UnknownOutcomeResolver(orders),
        freeze_store=freeze,
        fault=fault,
    )
    return {
        "ledger": ledger,
        "cursor": cursor,
        "freeze": freeze,
        "orders": orders,
        "workflow": workflow,
    }


def _run(
    handles: dict[str, Any],
    *,
    commit_facts: bool = True,
    reconcile: bool = True,
) -> SubmitWorkflowResult:
    workflow = handles["workflow"]
    assert isinstance(workflow, SubmitWorkflow)
    return workflow.run(
        cycle_id=CYCLE,
        intent_id=INTENT,
        decision_id=DECISION,
        payload_hash=PAYLOAD,
        submit=_submit_fn(handles["orders"], f"{CYCLE}:{INTENT}"),
        commit_facts=_commit_facts(handles["cursor"]) if commit_facts else None,
        reconcile=(lambda: _clean_report(handles["ledger"])) if reconcile else None,
    )


def _close(handles: dict[str, Any]) -> None:
    for handle in handles.values():
        if hasattr(handle, "close"):
            handle.close()


# ---------------------------------------------------------------------------
# AC-M07-W06-01: crash injection at every external submission transition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("point", FAULT_POINTS)
def test_crash_at_every_transition_recovers_without_second_order(
    tmp_path: Path, point: FaultPoint
) -> None:
    broker = _FakeSubmitBroker()

    # First process crashes at the named transition boundary.
    first = _new_handles(tmp_path, broker, fault=_raise_at(point))
    try:
        with pytest.raises(InjectedCrash):
            _run(first)
    finally:
        _close(first)

    # Restart in a fresh process on the same durable files.
    second = _new_handles(tmp_path, broker)
    try:
        result = _run(second)
        assert result.state == "COMPLETED"
        assert result.submit_id == f"{CYCLE}:{INTENT}"
        assert result.broker_order_id is not None
        # At most one external submit identity.
        assert broker.post_count == 1
        assert len(broker.orders) == 1
        ledger = second["ledger"]
        assert ledger.reservation_count() == 1
        assert ledger.status(result.submit_id) == "COMPLETED"
        # One explainable terminal ledger chain.
        chain = [event["kind"] for event in ledger.events(result.submit_id)]
        assert chain == ["RESERVED", "BIND", "SUBMIT_ATTEMPT", "BROKER_RESULT"]
        # Facts committed and cursor advanced exactly once (idempotently).
        assert second["cursor"].cursor(ACCOUNT) == "6001"
        assert second["cursor"].fact_count(ACCOUNT) == 1
        # No freeze remains after a clean recovery.
        assert second["freeze"].active_freezes(ACCOUNT) == []
    finally:
        _close(second)


def test_crash_after_send_resolves_accepted_order_by_query(
    tmp_path: Path,
) -> None:
    """An after-send crash keeps the order at the broker; restart resolves
    it by query and completes — the order is never re-submitted."""
    broker = _FakeSubmitBroker()
    first = _new_handles(tmp_path, broker, fault=_raise_at("after_send"))
    try:
        with pytest.raises(InjectedCrash):
            _run(first)
    finally:
        _close(first)
    assert broker.post_count == 1

    second = _new_handles(tmp_path, broker)
    try:
        result = _run(second)
        assert result.state == "COMPLETED"
        assert result.broker_order_id is not None
        assert broker.post_count == 1
        assert second["ledger"].status(result.submit_id) == "COMPLETED"
        # The resolution was a query against the persisted client identity.
        assert broker.captured[-1]["method"] == "GET"
    finally:
        _close(second)


def test_send_failure_with_order_never_received_freezes(
    tmp_path: Path,
) -> None:
    broker = _FakeSubmitBroker()
    broker.fail_post = True
    broker.orders_visible = False  # the order never reached the broker

    handles = _new_handles(tmp_path, broker)
    try:
        result = _run(handles)
        assert result.state == "FROZEN"
        # One failed attempt; the outcome was settled by query, not by a
        # blind re-submit.
        assert broker.post_count == 1
        assert broker.captured[-1]["method"] == "GET"
        assert handles["ledger"].status(result.submit_id) == "FROZEN"
        assert handles["freeze"].active_freezes(ACCOUNT)
    finally:
        _close(handles)

    # A later restart stays frozen and never creates a second order.
    handles = _new_handles(tmp_path, broker)
    try:
        result = _run(handles)
        assert result.state == "FROZEN"
        assert broker.post_count == 1
        assert handles["ledger"].status(result.submit_id) == "FROZEN"
    finally:
        _close(handles)


def test_unresolved_query_freezes_both_ledger_and_exposure(
    tmp_path: Path,
) -> None:
    broker = _FakeSubmitBroker()
    broker.fail_post = True
    broker.fail_list = True  # the resolution query also fails

    handles = _new_handles(tmp_path, broker)
    try:
        result = _run(handles)
        assert result.state == "FROZEN"
        assert broker.post_count == 1
        assert handles["ledger"].status(result.submit_id) == "FROZEN"
        active = handles["freeze"].active_freezes(ACCOUNT)
        assert active
        assert active[0]["reason"] == "unresolved_gap"
    finally:
        _close(handles)


def test_send_failure_without_resolver_freezes(tmp_path: Path) -> None:
    broker = _FakeSubmitBroker()
    broker.fail_post = True
    broker.orders_visible = False

    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
    freeze = ExposureFreezeStore(db_path=tmp_path / "freeze.db")
    orders = OrderOpsClient(_client(broker))
    workflow = SubmitWorkflow(
        ledger=ledger, account_id=ACCOUNT, owner=OWNER, freeze_store=freeze
    )
    try:
        result = workflow.run(
            cycle_id=CYCLE,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            submit=_submit_fn(orders, f"{CYCLE}:{INTENT}"),
        )
        assert result.state == "FROZEN"
        assert ledger.status(result.submit_id) == "FROZEN"
        assert freeze.active_freezes(ACCOUNT)
    finally:
        ledger.close()
        freeze.close()


def test_blocking_reconciliation_difference_freezes_exposure(
    tmp_path: Path,
) -> None:
    broker = _FakeSubmitBroker()
    handles = _new_handles(tmp_path, broker)
    try:
        result = handles["workflow"].run(
            cycle_id=CYCLE,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            submit=_submit_fn(handles["orders"], f"{CYCLE}:{INTENT}"),
            commit_facts=_commit_facts(handles["cursor"]),
            reconcile=lambda: _blocking_report(handles["ledger"]),
        )
        assert result.state == "FROZEN"
        assert result.broker_order_id is not None
        # The external submit itself is an immutable terminal fact.
        assert handles["ledger"].status(result.submit_id) == "COMPLETED"
        chain = [
            event["kind"] for event in handles["ledger"].events(result.submit_id)
        ]
        assert chain == ["RESERVED", "BIND", "SUBMIT_ATTEMPT", "BROKER_RESULT"]
        active = handles["freeze"].active_freezes(ACCOUNT)
        assert active
        assert active[0]["reason"] == "blocking_diff"
        assert active[0]["evidence_refs"] == (f"ledger:{result.submit_id}",)
    finally:
        _close(handles)


def test_workflow_rejects_identity_collision(tmp_path: Path) -> None:
    broker = _FakeSubmitBroker()
    handles = _new_handles(tmp_path, broker)
    try:
        result = _run(handles)
        assert result.state == "COMPLETED"
        assert broker.post_count == 1
    finally:
        _close(handles)

    # A replay with a different approved decision is an identity collision
    # and freezes instead of overwriting or creating a second order.
    handles = _new_handles(tmp_path, broker)
    try:
        with pytest.raises(LedgerTransitionError) as excinfo:
            handles["workflow"].run(
                cycle_id=CYCLE,
                intent_id=INTENT,
                decision_id="risk-2",
                payload_hash=PAYLOAD,
                submit=_submit_fn(handles["orders"], f"{CYCLE}:{INTENT}"),
            )
        assert excinfo.value.kind == "identity_collision"
        assert broker.post_count == 1
        assert handles["ledger"].status(f"{CYCLE}:{INTENT}") == "COMPLETED"
    finally:
        _close(handles)


# ---------------------------------------------------------------------------
# AC-M07-W06-02: 100 same-cycle replays across fresh processes
# ---------------------------------------------------------------------------


def test_100_same_cycle_replays_across_fresh_processes(tmp_path: Path) -> None:
    broker = _FakeSubmitBroker()
    for iteration in range(100):
        handles = _new_handles(tmp_path, broker)
        try:
            result = _run(handles)
            assert result.state == "COMPLETED"
            assert result.submit_id == f"{CYCLE}:{INTENT}"
            if iteration == 0:
                assert result.reused is False
            else:
                assert result.reused is True
        finally:
            _close(handles)

    # At most one external submit identity across all 100 processes.
    assert broker.post_count == 1
    assert len(broker.orders) == 1
    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
    try:
        assert ledger.reservation_count() == 1
        submit_id = f"{CYCLE}:{INTENT}"
        assert ledger.status(submit_id) == "COMPLETED"
        # One explainable terminal ledger chain.
        chain = [event["kind"] for event in ledger.events(submit_id)]
        assert chain == ["RESERVED", "BIND", "SUBMIT_ATTEMPT", "BROKER_RESULT"]
        # The durable mapping resolves to the single broker order.
        assert ledger.completed_mappings() == {
            submit_id: next(iter(broker.orders))
        }
    finally:
        ledger.close()


# ---------------------------------------------------------------------------
# Startup sync (REQ-EXEC-011, REQ-OPS-006)
# ---------------------------------------------------------------------------


def test_startup_sync_resolves_in_flight_and_restores_mapping(
    tmp_path: Path,
) -> None:
    broker = _FakeSubmitBroker()
    # A prior process crashed after the send: the ledger holds an in-flight
    # SUBMITTED reservation and the broker holds the order.
    first = _new_handles(tmp_path, broker, fault=_raise_at("after_send"))
    try:
        with pytest.raises(InjectedCrash):
            _run(first)
    finally:
        _close(first)
    assert broker.post_count == 1

    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
    cursor = TransactionCursorStore(db_path=tmp_path / "cursor.db")
    freeze = ExposureFreezeStore(db_path=tmp_path / "freeze.db")
    orders = OrderOpsClient(_client(broker))
    restored: dict[str, str] = {}
    service = StartupSyncService(
        ledger=ledger,
        account_id=ACCOUNT,
        resolve=UnknownOutcomeResolver(orders),
        freeze_store=freeze,
        cursor_store=cursor,
    )
    try:
        result = service.sync(restore_mapping=restored.update)
        assert result.in_flight_found == 1
        assert result.completed == (f"{CYCLE}:{INTENT}",)
        assert result.frozen == ()
        assert result.frozen_exposure is False
        assert result.cursor is None  # facts were never committed
        assert ledger.status(f"{CYCLE}:{INTENT}") == "COMPLETED"
        assert freeze.active_freezes(ACCOUNT) == []
        # The durable mapping is restored into the process adapter so a
        # replay can never double-submit.
        assert restored == {f"{CYCLE}:{INTENT}": next(iter(broker.orders))}
    finally:
        ledger.close()
        cursor.close()
        freeze.close()


def _arrange_in_flight(tmp_path: Path) -> None:
    """Drive the ledger to an in-flight SUBMITTED reservation by hand."""
    db = tmp_path / "ledger.db"
    ledger = OrderLedger(db_path=db)
    try:
        outcome = ledger.reserve(
            cycle_id=CYCLE,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            owner=OWNER,
        )
        ledger.bind_decision(
            outcome.submit_id,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            owner=OWNER,
        )
        ledger.record_submit_attempt(
            outcome.submit_id, payload_hash=PAYLOAD, owner=OWNER
        )
        assert ledger.status(outcome.submit_id) == "SUBMITTED"
    finally:
        ledger.close()


def test_startup_sync_freezes_in_flight_without_broker_order(
    tmp_path: Path,
) -> None:
    # Arrange an in-flight SUBMITTED reservation whose order never reached
    # the broker (crash before arrival).
    _arrange_in_flight(tmp_path)

    broker = _FakeSubmitBroker()  # no order ever arrived
    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
    freeze = ExposureFreezeStore(db_path=tmp_path / "freeze.db")
    orders = OrderOpsClient(_client(broker))
    service = StartupSyncService(
        ledger=ledger,
        account_id=ACCOUNT,
        resolve=UnknownOutcomeResolver(orders),
        freeze_store=freeze,
    )
    try:
        result = service.sync()
        assert result.in_flight_found == 1
        assert result.completed == ()
        assert result.frozen == (f"{CYCLE}:{INTENT}",)
        assert result.frozen_exposure is True
        assert ledger.status(f"{CYCLE}:{INTENT}") == "FROZEN"
        assert freeze.active_freezes(ACCOUNT)
        # The resolution was a query; nothing was re-submitted.
        assert broker.post_count == 0
        assert len(broker.orders) == 0
    finally:
        ledger.close()
        freeze.close()


def test_startup_sync_freezes_unresolved_in_flight(tmp_path: Path) -> None:
    _arrange_in_flight(tmp_path)

    broker = _FakeSubmitBroker()
    broker.fail_list = True  # the resolution query fails
    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
    freeze = ExposureFreezeStore(db_path=tmp_path / "freeze.db")
    orders = OrderOpsClient(_client(broker))
    service = StartupSyncService(
        ledger=ledger,
        account_id=ACCOUNT,
        resolve=UnknownOutcomeResolver(orders),
        freeze_store=freeze,
    )
    try:
        result = service.sync()
        assert result.frozen == (f"{CYCLE}:{INTENT}",)
        assert result.frozen_exposure is True
        assert ledger.status(f"{CYCLE}:{INTENT}") == "FROZEN"
        assert freeze.active_freezes(ACCOUNT)
    finally:
        ledger.close()
        freeze.close()
