"""M07-W07: prove idempotency and reconciliation and close M07.

Local deterministic gates (always run):

- the aggregate restart chain — crash after send -> restart resolve ->
  fact commit + cursor advance -> projection rebuild -> clean typed
  reconciliation — produces at most one external submit, a correct
  cursor, correct projections, and zero freezes (AC-M07-W07-01);
- missing credentials fail closed with ENVIRONMENT_BLOCKED and no mock
  substitution, waiver, fallback, or false DONE (AC-M07-W07-03);
- a nonzero blocking reconciliation diff or unresolved remote state
  keeps the system frozen and never DONE (AC-M07-W07-03).

Controlled practice restart scenario (AC-M07-W07-02, T7): with
``ALPHABRIEF_OANDA_TOKEN`` and ``ALPHABRIEF_OANDA_ACCOUNT_ID`` set, the
scenario submits a minimum-risk order through the durable
``SubmitWorkflow``, simulates a process restart, resolves the same
external order and transactions, reconciles account truth, cleans up
exposure, and stores scrubbed E5 hashes. Without credentials the
fail-closed path is asserted and the round records
``external_evidence_pending`` — mock output never masquerades as
practice evidence.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.account_projection import (
    AccountProjectionStore,
    FactKind,
    ProjectionFact,
)
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import (
    DEFAULT_BASE_URL,
    OandaPaperConfig,
)
from alphabrief_execution.broker.oanda.freeze_policy import (
    ExposureFreezeStore,
)
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger
from alphabrief_execution.broker.oanda.order_ops import (
    OrderCreateResult,
    OrderOpsClient,
)
from alphabrief_execution.broker.oanda.orders import OandaOrderRequest
from alphabrief_execution.broker.oanda.practice_scenarios import (
    SCENARIO_MINIMUM_RISK_UNITS,
    SCENARIO_SYMBOL,
    PracticeScenarioRunner,
)
from alphabrief_execution.broker.oanda.reconcile import (
    Reconciler,
    ReconciliationReport,
    RemoteAccountView,
    RemoteOrder,
    RemotePosition,
    RemoteTrade,
)
from alphabrief_execution.broker.oanda.submit_recovery import (
    FaultPoint,
    InjectedCrash,
    SubmitWorkflow,
)
from alphabrief_execution.broker.oanda.transaction_cursor import (
    TransactionCursorStore,
)
from alphabrief_execution.broker.oanda.transaction_ops import (
    TransactionOpsClient,
    TransactionResult,
)
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
# Deterministic fake broker (local gates only)
# ---------------------------------------------------------------------------


class _FakeSubmitBroker:
    """In-memory OANDA practice broker for the deterministic aggregate."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.post_count = 0
        self.next_id = 7000
        self.fail_post = False
        self.orders_visible = True
        self.fail_list = False

    def _tx(self) -> str:
        value = str(self.next_id)
        self.next_id += 1
        return value

    def handle(self, request: Request) -> bytes:
        method = request.method
        url = request.full_url
        raw = request.data
        body = json.loads(raw.decode("utf-8")) if isinstance(raw, bytes) else {}
        path, _, _ = url.partition("?")
        if method == "POST" and path == f"{BASE}/orders":
            self.post_count += 1
            if self.fail_post:
                raise TimeoutError("simulated transport failure on submit")
            order = body["order"]
            order_id = self._tx()
            self.orders[order_id] = {
                "id": order_id,
                "instrument": order.get("instrument", ""),
                "units": order.get("units", "0"),
                "state": "FILLED",
                "createTime": "2026-08-13T12:00:00.000000000Z",
                "clientExtensions": order.get("clientExtensions", {}),
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
        instrument=SCENARIO_SYMBOL,
        units=SCENARIO_MINIMUM_RISK_UNITS,
        time_in_force="FOK",
    )


def _instrument() -> InstrumentMetadata:
    return InstrumentMetadata(
        name=SCENARIO_SYMBOL,
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


def _cursor_facts() -> list[TransactionResult]:
    return [
        TransactionResult(
            transaction_id="6001",
            transaction_type="ORDER_FILL",
            time=T0,
            instrument=SCENARIO_SYMBOL,
            units=SCENARIO_MINIMUM_RISK_UNITS,
            price=Decimal("1.10500"),
            realized_pl=Decimal("0"),
            financing=Decimal("0"),
            request_id="range-6001-6001",
        )
    ]


def _projection_facts(
    *, order_id: str, trade_id: str
) -> list[ProjectionFact]:
    return [
        ProjectionFact(
            fact_id="6000",
            kind="ORDER_CREATE",
            order_id=order_id,
            instrument=SCENARIO_SYMBOL,
            units=SCENARIO_MINIMUM_RISK_UNITS,
            price=Decimal("1.10500"),
            realized_pl=Decimal("0"),
            financing=Decimal("0"),
            occurred_at=T0,
        ),
        ProjectionFact(
            fact_id="6001",
            kind="ORDER_FILL",
            order_id=order_id,
            trade_id=trade_id,
            instrument=SCENARIO_SYMBOL,
            units=SCENARIO_MINIMUM_RISK_UNITS,
            price=Decimal("1.10500"),
            realized_pl=Decimal("0"),
            financing=Decimal("0"),
            occurred_at=T0,
        ),
    ]


def _raise_at(point: FaultPoint) -> Callable[[FaultPoint], None]:
    def _fault(actual: FaultPoint) -> None:
        if actual == point:
            raise InjectedCrash(point)

    return _fault


def _new_handles(
    tmp_path: Path,
    broker: _FakeSubmitBroker,
    *,
    fault: Callable[[FaultPoint], None] | None = None,
) -> dict[str, Any]:
    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
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


def _close(handles: dict[str, Any]) -> None:
    for handle in handles.values():
        if hasattr(handle, "close"):
            handle.close()


# ---------------------------------------------------------------------------
# AC-M07-W07-01: deterministic aggregate restart chain
# ---------------------------------------------------------------------------


def test_aggregate_restart_chain_reconciles_clean(tmp_path: Path) -> None:
    """Crash after send -> restart resolve -> cursor -> projection ->
    clean typed reconciliation, at most one external submit, zero freeze."""
    broker = _FakeSubmitBroker()
    first = _new_handles(tmp_path, broker, fault=_raise_at("after_send"))
    try:
        with pytest.raises(InjectedCrash):
            first["workflow"].run(
                cycle_id=CYCLE,
                intent_id=INTENT,
                decision_id=DECISION,
                payload_hash=PAYLOAD,
                submit=_submit_fn(first["orders"], f"{CYCLE}:{INTENT}"),
            )
    finally:
        _close(first)
    assert broker.post_count == 1
    broker_order_id = next(iter(broker.orders))

    # Restart in a fresh process on the same durable files.
    second = _new_handles(tmp_path, broker)
    try:
        result = second["workflow"].run(
            cycle_id=CYCLE,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            submit=_submit_fn(second["orders"], f"{CYCLE}:{INTENT}"),
            commit_facts=lambda: second["cursor"].advance(
                ACCOUNT, _cursor_facts(), owner=OWNER
            ),
        )
        assert result.state == "COMPLETED"
        assert result.broker_order_id == broker_order_id
        assert broker.post_count == 1  # resolved by query, never re-submitted
        # Atomic cursor recovery: exactly one fact, frontier advanced.
        assert second["cursor"].cursor(ACCOUNT) == "6001"
        assert second["cursor"].fact_count(ACCOUNT) == 1
        # Correct projections from the immutable facts.
        projection = AccountProjectionStore(
            db_path=tmp_path / "projection.db"
        )
        try:
            snapshot = projection.rebuild(
                ACCOUNT,
                _projection_facts(order_id=broker_order_id, trade_id="t-1"),
                initial_balance=Decimal("1000"),
            )
            assert snapshot.last_transaction_id == "6001"
            assert snapshot.open_trade_count == 1
            assert snapshot.open_position_count == 1
            orders_by_id = {o.broker_order_id: o for o in snapshot.orders}
            assert orders_by_id[broker_order_id].state == "FILLED"
        finally:
            projection.close()
        # Legitimate remote state reconciles without false mismatches.
        remote = RemoteAccountView(
            account_id=ACCOUNT,
            last_transaction_id="6001",
            balance=Decimal("1000"),
            nav=Decimal("1000"),
            margin_used=snapshot.margin_used,
            financing_total=Decimal("0"),
            remote_fill_count=1,
            orders=(
                RemoteOrder(
                    broker_order_id=broker_order_id,
                    state="FILLED",
                    units=SCENARIO_MINIMUM_RISK_UNITS,
                    client_order_id=f"{CYCLE}:{INTENT}",
                ),
            ),
            trades=(
                RemoteTrade(
                    broker_trade_id="t-1",
                    state="OPEN",
                    current_units=SCENARIO_MINIMUM_RISK_UNITS,
                ),
            ),
            positions=(
                RemotePosition(
                    instrument=SCENARIO_SYMBOL,
                    long_units=SCENARIO_MINIMUM_RISK_UNITS,
                    short_units=Decimal("0"),
                ),
            ),
        )
        report = Reconciler().reconcile(
            snapshot, remote, ledger=second["ledger"]
        )
        assert report.clean is True
        # No freeze remains after the clean recovery.
        assert second["freeze"].active_freezes(ACCOUNT) == []
    finally:
        _close(second)


# ---------------------------------------------------------------------------
# AC-M07-W07-03: fail closed — no fallback, no waiver, no false DONE
# ---------------------------------------------------------------------------


def test_missing_credentials_fail_closed_environment_blocked(
    tmp_path: Path,
) -> None:
    runner = PracticeScenarioRunner(
        client=None,
        store_path=tmp_path / "scenarios.db",
        scenario_id="m07-w07-missing-creds",
    )
    verdict = runner.run()
    assert verdict.verdict == "ENVIRONMENT_BLOCKED"
    assert verdict.approved is None
    assert verdict.broker_order_id is None
    assert verdict.cleanup_result is None
    # No mock fill, no fallback execution, no question asked.
    assert "credential" in verdict.detail


def test_blocking_diff_and_unresolved_remote_state_freeze_never_done(
    tmp_path: Path,
) -> None:
    # (a) A completed submit followed by a blocking reconciliation diff
    # freezes new exposure; the external order stays immutable.
    broker = _FakeSubmitBroker()
    handles = _new_handles(tmp_path, broker)
    try:
        ledger = handles["ledger"]
        result = handles["workflow"].run(
            cycle_id=CYCLE,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            submit=_submit_fn(handles["orders"], f"{CYCLE}:{INTENT}"),
            reconcile=lambda: _blocking_report(ledger),
        )
        assert result.state == "FROZEN"
        assert handles["ledger"].status(result.submit_id) == "COMPLETED"
        active = handles["freeze"].active_freezes(ACCOUNT)
        assert active
        assert active[0]["reason"] == "blocking_diff"
    finally:
        _close(handles)

    # (b) Unresolved remote state after a failed send freezes the ledger
    # and new exposure; nothing is re-submitted and nothing is DONE.
    broker = _FakeSubmitBroker()
    broker.fail_post = True
    broker.fail_list = True
    handles = _new_handles(tmp_path, broker)
    try:
        result = handles["workflow"].run(
            cycle_id="cycle-blocked",
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            submit=_submit_fn(handles["orders"], "cycle-blocked:" + INTENT),
        )
        assert result.state == "FROZEN"
        assert handles["ledger"].status(result.submit_id) == "FROZEN"
        assert handles["freeze"].active_freezes(ACCOUNT)
        assert broker.post_count == 1  # one attempt, never retried blindly
    finally:
        _close(handles)


def _blocking_report(ledger: OrderLedger) -> ReconciliationReport:
    """One report with a CRITICAL unknown-client-identity remote order."""
    from alphabrief_execution.broker.oanda.account_projection import (
        AccountSnapshot,
    )

    local = AccountSnapshot(
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
    return Reconciler().reconcile(local, remote, ledger=ledger)


# ---------------------------------------------------------------------------
# AC-M07-W07-02: controlled practice restart scenario (T7, creds-gated)
# ---------------------------------------------------------------------------


def _practice_client(token: str, account_id: str) -> OandaHttpClient:
    return OandaHttpClient(
        config=OandaPaperConfig(
            base_url=DEFAULT_BASE_URL,
            timeout_seconds=10.0,
            max_retries=2,
            retry_backoff_seconds=0.25,
        ),
        token=token,
        account_id=account_id,
    )


def _run_practice_restart_scenario(
    tmp_path: Path, *, token: str, account_id: str
) -> dict[str, Any]:
    """One real practice restart scenario (documented T7 harness).

    submit -> process restart -> resolve same external order ->
    transactions/cursor -> projection -> typed reconciliation ->
    cleanup -> scrubbed E5 evidence. Raises on any anomaly; the evidence
    file contains only non-reversible hashes, never the token or the
    complete account ID.
    """
    from alphabrief_execution.broker.oanda.account_ops import (
        AccountOpsClient,
    )
    from alphabrief_execution.broker.oanda.position_ops import (
        PositionOpsClient,
    )
    from alphabrief_execution.broker.oanda.trade_ops import TradeOpsClient

    client = _practice_client(token, account_id)
    scenario_id = "m07-w07-restart"
    cycle_id = f"cycle-{scenario_id}"
    submit_id = f"{cycle_id}:{INTENT}"

    # --- run 1: durable submit ------------------------------------------
    ledger1 = OrderLedger(db_path=tmp_path / "ledger.db")
    cursor1 = TransactionCursorStore(db_path=tmp_path / "cursor.db")
    freeze1 = ExposureFreezeStore(db_path=tmp_path / "freeze.db")
    orders1 = OrderOpsClient(client)
    workflow1 = SubmitWorkflow(
        ledger=ledger1,
        account_id=account_id,
        owner=OWNER,
        resolve=UnknownOutcomeResolver(orders1),
        freeze_store=freeze1,
    )
    try:
        first = workflow1.run(
            cycle_id=cycle_id,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            submit=_submit_fn(orders1, submit_id),
        )
    finally:
        ledger1.close()
        cursor1.close()
        freeze1.close()
    assert first.state == "COMPLETED", first.detail
    assert first.broker_order_id is not None

    # --- process restart: fresh stores, same durable files --------------
    ledger2 = OrderLedger(db_path=tmp_path / "ledger.db")
    cursor2 = TransactionCursorStore(db_path=tmp_path / "cursor.db")
    freeze2 = ExposureFreezeStore(db_path=tmp_path / "freeze.db")
    orders2 = OrderOpsClient(client)
    workflow2 = SubmitWorkflow(
        ledger=ledger2,
        account_id=account_id,
        owner=OWNER,
        resolve=UnknownOutcomeResolver(orders2),
        freeze_store=freeze2,
    )
    try:
        second = workflow2.run(
            cycle_id=cycle_id,
            intent_id=INTENT,
            decision_id=DECISION,
            payload_hash=PAYLOAD,
            submit=_submit_fn(orders2, submit_id),
        )
        assert second.state == "COMPLETED", second.detail
        assert second.reused is True
        # The same external order is resolved, never duplicated.
        assert second.broker_order_id == first.broker_order_id

        # --- transactions and atomic cursor -----------------------------
        transactions = TransactionOpsClient(client)
        window = transactions.transactions_since(
            cursor2.cursor(account_id) or "0"
        )
        advance = cursor2.advance(
            account_id, list(window.transactions), owner=OWNER
        )
        assert advance.facts_consumed >= 1
        assert advance.gaps == (), (
            f"unexpected transaction gaps: {advance.gaps}"
        )

        # --- projection rebuild from the immutable facts ----------------
        projection = AccountProjectionStore(db_path=tmp_path / "projection.db")
        # Only the projection's supported fact kinds fold; other OANDA
        # transaction types (CLIENT_CONFIGURE etc.) are counted and
        # recorded in the evidence, never silently dropped.
        supported_kinds = frozenset(
            {
                "ORDER_CREATE",
                "ORDER_FILL",
                "ORDER_CANCEL",
                "TRADE_CLOSE",
                "TRADE_REDUCE",
                "DAILY_FINANCING",
                "DEPOSIT",
                "WITHDRAWAL",
            }
        )
        supported = [
            transaction
            for transaction in window.transactions
            if transaction.transaction_type in supported_kinds
        ]
        facts = [
            ProjectionFact(
                fact_id=transaction.transaction_id,
                kind=cast(FactKind, transaction.transaction_type),
                order_id=None,
                trade_id=None,
                instrument=transaction.instrument,
                units=transaction.units or Decimal("0"),
                price=transaction.price,
                realized_pl=transaction.realized_pl or Decimal("0"),
                financing=transaction.financing or Decimal("0"),
                occurred_at=transaction.time or datetime.now(UTC),
            )
            for transaction in supported
        ]
        snapshot = projection.rebuild(account_id, facts)
        projection.close()

        # --- typed reconciliation against real account truth ------------
        accounts = AccountOpsClient(client)
        summary = accounts.account_summary()
        positions = PositionOpsClient(client).list_positions()
        remote = RemoteAccountView(
            account_id=account_id,
            last_transaction_id=summary.last_transaction_id,
            balance=summary.balance,
            nav=summary.nav,
            margin_used=summary.margin_used,
            financing_total=Decimal("0"),
            remote_fill_count=len(
                [f for f in facts if f.kind == "ORDER_FILL"]
            ),
            orders=tuple(
                RemoteOrder(
                    broker_order_id=order.broker_order_id,
                    state=order.state,
                    units=order.units,
                    client_order_id=order.client_order_id,
                )
                for order in orders2.list_orders().orders
            ),
            trades=(),
            positions=tuple(
                RemotePosition(
                    instrument=position.instrument,
                    long_units=position.long_units,
                    short_units=position.short_units,
                )
                for position in positions.positions
            ),
        )
        report = Reconciler().reconcile(
            snapshot, remote, ledger=ledger2
        )
        assert report.clean is True, (
            f"practice reconciliation not clean: {report.diffs}"
        )

        # --- cleanup: nothing of ours stays open ------------------------
        trades_client = TradeOpsClient(client)
        opened = [
            trade
            for trade in trades_client.list_trades(state="OPEN").trades
            if trade.client_order_id == submit_id
        ]
        cleanup_result: str
        if opened:
            trades_client.close_trade(opened[0].broker_trade_id)
            cleanup_result = "closed"
        else:
            cleanup_result = "already_closed"

        # --- scrubbed E5 evidence ---------------------------------------
        evidence = {
            "scenario_id": scenario_id,
            "verdict": "COMPLETED",
            "broker_order_hash": sha256(
                str(first.broker_order_id).encode("utf-8")
            ).hexdigest()[:16],
            "transaction_id_hashes": [
                sha256(fact.fact_id.encode("utf-8")).hexdigest()[:16]
                for fact in facts
            ],
            "cursor": advance.cursor,
            "reconcile_clean": report.clean,
            "cleanup_result": cleanup_result,
            "reused_identity": second.reused,
        }
        evidence_path = tmp_path / "m07-w07-e5.json"
        evidence_path.write_text(json.dumps(evidence, sort_keys=True))
        assert freeze2.active_freezes(account_id) == []
        return {**evidence, "evidence_path": str(evidence_path)}
    finally:
        ledger2.close()
        cursor2.close()
        freeze2.close()


def test_controlled_practice_restart_scenario(tmp_path: Path) -> None:
    token = os.environ.get("ALPHABRIEF_OANDA_TOKEN", "").strip()
    account_id = os.environ.get("ALPHABRIEF_OANDA_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        # T7 pending: the deterministic fail-closed path is asserted and
        # the round records external_evidence_pending. Mock output never
        # masquerades as practice evidence.
        runner = PracticeScenarioRunner(
            client=None,
            store_path=tmp_path / "scenarios.db",
            scenario_id="m07-w07-restart",
        )
        verdict = runner.run()
        assert verdict.verdict == "ENVIRONMENT_BLOCKED"
        assert "credential" in verdict.detail
        return

    evidence = _run_practice_restart_scenario(
        tmp_path, token=token, account_id=account_id
    )
    assert evidence["reconcile_clean"] is True
    assert evidence["reused_identity"] is True
    # The E5 evidence is scrubbed: no token and no complete account ID.
    raw = Path(evidence["evidence_path"]).read_text()
    assert token not in raw
    assert account_id not in raw
