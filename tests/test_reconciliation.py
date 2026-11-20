"""Reconciliation safety tests for the live OANDA reconciler (S3-3).

The old runner treated every remote position and every unregistered order
as a difference, which froze the scheduler on the first real fill. These
tests pin the corrected contract:

* our own orders (client ``tag=alphabrief``), protective-order fills and
  financing are explainable and must never freeze;
* a foreign position freezes new exposure;
* without credentials the verdict is explicitly non-matching, and the
  per-scope freeze policy still applies;
* snapshots and freezes land in the durable recon store.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.account_ops import AccountOpsClient
from alphabrief_execution.broker.oanda.account_projection import AccountProjectionStore
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.live_reconciliation import (
    ALLOWED_SCOPES,
    LiveReconciler,
    ReconcileBusyError,
    ReconcilerConfig,
    record_broker_not_configured,
)
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger
from alphabrief_execution.broker.oanda.transaction_cursor import (
    TransactionCursorStore,
)
from alphabrief_execution.broker.oanda.transaction_ops import (
    TransactionGap,
    TransactionOperationError,
    TransactionOpsClient,
    TransactionResult,
)
from alphabrief_execution.broker.recon_store import BrokerReconStore

ACCOUNT = "101-004-1234567-001"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[BrokerReconStore]:
    recon_store = BrokerReconStore(db_path=tmp_path / "recon.db")
    try:
        yield recon_store
    finally:
        recon_store.close()


def _reconciler(
    store: BrokerReconStore,
    tmp_path: Path,
    *,
    client: OandaHttpClient,
    lock_timeout_seconds: float = 20.0,
) -> LiveReconciler:
    """Build a reconciler whose stores are all inside the test directory.

    The production defaults point at the user's data directory; tests must
    never read or write that.
    """
    database = tmp_path / "recon-state.duckdb"
    return LiveReconciler(
        client=client,
        store=store,
        cursor_store=TransactionCursorStore(db_path=database),
        projection_store=AccountProjectionStore(db_path=database),
        order_ledger=OrderLedger(db_path=database),
        lock_timeout_seconds=lock_timeout_seconds,
    )


def _config() -> OandaPaperConfig:
    return OandaPaperConfig(
        base_url="https://api-fxpractice.oanda.com",
        timeout_seconds=1.0,
        max_retries=0,
        retry_backoff_seconds=0.001,
    )


def _account_summary(*, last_transaction_id: str = "10") -> dict[str, Any]:
    return {
        "account": {
            "id": ACCOUNT,
            "currency": "USD",
            "balance": "100000.0000",
            "NAV": "100000.0000",
            "unrealizedPL": "0.0000",
            "marginUsed": "0.0000",
            "marginAvailable": "100000.0000",
            "openOrderCount": 0,
            "openTradeCount": 0,
            "openPositionCount": 0,
            "lastTransactionID": last_transaction_id,
        }
    }


def _fill(
    *,
    transaction_id: str,
    order_id: str = "7",
    units: str = "1000",
    transaction_type: str = "ORDER_FILL",
) -> dict[str, Any]:
    return {
        "id": transaction_id,
        "type": transaction_type,
        "time": "2026-09-30T10:00:00.000000000Z",
        "instrument": "EUR_USD",
        "units": units,
        "price": "1.10000",
        "pl": "0.0000",
        "financing": "0.0000",
        "orderID": order_id,
    }


def _our_order() -> dict[str, Any]:
    return {
        "id": "7",
        "type": "MARKET",
        "state": "FILLED",
        "instrument": "EUR_USD",
        "units": "1000",
        "timeInForce": "FOK",
        "clientExtensions": {"id": "cli-1", "tag": "alphabrief"},
        "createTime": "2026-09-30T10:00:00.000000000Z",
    }


def _foreign_position() -> dict[str, Any]:
    return {
        "instrument": "EUR_USD",
        "long": {"units": "5000", "averagePrice": "1.10000", "unrealizedPL": "0"},
        "short": {"units": "0"},
    }


def _client(
    *,
    orders: list[dict[str, Any]] | None = None,
    positions: list[dict[str, Any]] | None = None,
    trades: list[dict[str, Any]] | None = None,
    transactions: list[dict[str, Any]] | None = None,
    last_transaction_id: str = "10",
    since_queries: list[str] | None = None,
) -> OandaHttpClient:
    """Client double: summary, orders, positions, trades, transactions."""

    def send(request: Request, timeout: float) -> bytes:
        del timeout
        url = request.full_url
        if "/summary" in url:
            return json.dumps(
                _account_summary(last_transaction_id=last_transaction_id)
            ).encode()
        if "/openPositions" in url or "/positions" in url:
            return json.dumps({"positions": positions or []}).encode()
        if "/openTrades" in url or "/trades" in url:
            return json.dumps({"trades": trades or []}).encode()
        if "/orders" in url:
            return json.dumps({"orders": orders or []}).encode()
        if "/transactions/sinceid" in url or "/transactions/idrange" in url:
            rows = transactions or []
            if "/transactions/sinceid" in url and since_queries is not None:
                since = parse_qs(urlsplit(url).query)["id"][0]
                since_queries.append(since)
                rows = [row for row in rows if int(row["id"]) > int(since)]
            if "/transactions/idrange" in url:
                query = parse_qs(urlsplit(url).query)
                by_id = {int(row["id"]): row for row in rows}
                rows = [
                    by_id.get(tx_id, {"id": str(tx_id), "type": "CREATE"})
                    for tx_id in range(int(query["from"][0]), int(query["to"][0]) + 1)
                ]
            return json.dumps(
                {
                    "transactions": rows,
                    "lastTransactionID": last_transaction_id,
                }
            ).encode()
        raise AssertionError(f"unexpected request: {url}")

    return OandaHttpClient(
        config=_config(), http_send=send, token="test-token", account_id=ACCOUNT
    )


def test_reconcile_serializes_threads_for_the_same_account(
    store: BrokerReconStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(transactions=[_fill(transaction_id="1")], last_transaction_id="1")
    first = _reconciler(store, tmp_path, client=client)
    second = _reconciler(store, tmp_path, client=client)
    holder_entered, release, second_resolved, second_entered = (
        Event(), Event(), Event(), Event()
    )
    original_record = first._record_result
    original_summary = second.account_summary
    original_pass = second._reconcile_account

    def hold_after_record(**kwargs: Any) -> Any:
        result = original_record(**kwargs)
        holder_entered.set()
        assert release.wait(5)
        return result

    def resolve_second() -> Any:
        summary = original_summary()
        second_resolved.set()
        return summary

    def enter_second(*args: Any, **kwargs: Any) -> Any:
        second_entered.set()
        return original_pass(*args, **kwargs)

    monkeypatch.setattr(first, "_record_result", hold_after_record)
    monkeypatch.setattr(second, "account_summary", resolve_second)
    monkeypatch.setattr(second, "_reconcile_account", enter_second)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            holder = pool.submit(first.reconcile, scope="eod")
            try:
                assert holder_entered.wait(5)
                waiter = pool.submit(second.reconcile, scope="eod")
                assert second_resolved.wait(5)
                assert not second_entered.wait(0.1)
                assert not waiter.done()
            finally:
                release.set()
            holder.result(timeout=5)
            waiter.result(timeout=5)
        assert len(store.list_snapshots()) == 2
        snapshot = second._projection_store.snapshot(ACCOUNT)
        assert snapshot is not None
        assert len(snapshot.fills) == 1
        assert snapshot.balance == Decimal("100000")
    finally:
        first.close()
        second.close()


def test_reconcile_lock_timeout_does_not_publish_state(
    store: BrokerReconStore,
    tmp_path: Path,
) -> None:
    first = _reconciler(store, tmp_path, client=_client())
    second = _reconciler(
        store, tmp_path, client=_client(), lock_timeout_seconds=0.05
    )
    try:
        with first._account_lock(ACCOUNT):
            with pytest.raises(ReconcileBusyError, match="busy.*retry later"):
                second.reconcile()
        assert store.list_snapshots() == []
        assert not store.has_open_freeze()
        assert second._projection_store.snapshot(ACCOUNT) is None
        assert second._cursor_store.cursor(ACCOUNT) is None
        second.reconcile(scope="eod")
        assert len(store.list_snapshots()) == 1
    finally:
        first.close()
        second.close()


def test_reconcile_different_accounts_do_not_contend(
    store: BrokerReconStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _reconciler(store, tmp_path, client=_client())
    second = _reconciler(
        store, tmp_path, client=_client(), lock_timeout_seconds=0
    )
    summary = second.account_summary().model_copy(update={"account_id": "account?a"})
    monkeypatch.setattr(second, "account_summary", lambda: summary)
    try:
        with first._account_lock("account/a"):
            result = second.reconcile(scope="eod")
        assert result.report.account_id == "account?a"
        assert len(store.list_snapshots()) == 1
        locks = list(tmp_path.glob("reconcile-*.lock"))
        assert len(locks) == 2
        assert all("/" not in path.name and "?" not in path.name for path in locks)
    finally:
        first.close()
        second.close()


def test_reconcile_lock_releases_after_pass_error(
    store: BrokerReconStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _reconciler(store, tmp_path, client=_client())
    second = _reconciler(
        store, tmp_path, client=_client(), lock_timeout_seconds=0
    )

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("pass failed")

    monkeypatch.setattr(first, "_reconcile_account", fail)
    try:
        with pytest.raises(RuntimeError, match="pass failed"):
            first.reconcile()
        second.reconcile(scope="eod")
        assert len(store.list_snapshots()) == 1
    finally:
        first.close()
        second.close()


def test_overlapping_syncs_apply_the_same_window_once(
    store: BrokerReconStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(
        transactions=[
            {**_fill(transaction_id="11"), "pl": "5"},
            {
                **_fill(transaction_id="12", transaction_type="DAILY_FINANCING"),
                "financing": "-10",
            },
        ],
        since_queries=[],
    )
    first = _reconciler(store, tmp_path, client=client)
    second = _reconciler(store, tmp_path, client=client)
    first._projection_store.rebuild(ACCOUNT, [], initial_balance=Decimal("1000"))
    first._projection_store.advance_cursor(ACCOUNT, "10")
    first._cursor_store.advance(
        ACCOUNT,
        [
            TransactionResult(
                transaction_id="10", transaction_type="CREATE", request_id="test"
            )
        ],
        owner="reconciler",
    )
    original_apply = second._projection_store.apply_changes

    def overlapping_apply(*args: Any, **kwargs: Any) -> Any:
        first.sync(ACCOUNT)
        return original_apply(*args, **kwargs)

    try:
        monkeypatch.setattr(
            second._projection_store, "apply_changes", overlapping_apply
        )
        second.sync(ACCOUNT)
        second.sync(ACCOUNT)
        snapshot = first._projection_store.snapshot(ACCOUNT)
        assert snapshot is not None
        assert snapshot.balance == Decimal("995")
        assert snapshot.realized_pl == Decimal("5")
        assert snapshot.financing_total == Decimal("-10")
        assert len(snapshot.fills) == 1
        assert snapshot.last_transaction_id == "12"
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("failure_stage", ["cursor", "before_apply", "after_apply"])
@pytest.mark.parametrize("separate_stores", [False, True])
def test_sync_recovers_after_interruption_exactly_once(
    store: BrokerReconStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    separate_stores: bool,
) -> None:
    cursor_path = tmp_path / "cursor.db"
    projection_path = tmp_path / "projection.db" if separate_stores else cursor_path
    cursors = TransactionCursorStore(cursor_path)
    projections = AccountProjectionStore(projection_path)
    projections.rebuild(ACCOUNT, [], initial_balance=Decimal("1000"))
    projections.advance_cursor(ACCOUNT, "10")
    cursors.advance(
        ACCOUNT,
        [
            TransactionResult(
                transaction_id="10",
                transaction_type="CREATE",
                request_id="test",
            )
        ],
        owner="reconciler",
    )
    rows = [
        {
            **_fill(transaction_id="11", transaction_type="DAILY_FINANCING"),
            "financing": "-10",
        },
        {"id": "12", "type": "CLIENT_CONFIGURE"},
    ]
    queries: list[str] = []
    client = _client(transactions=rows, since_queries=queries)
    reconciler = LiveReconciler(
        client=client,
        store=store,
        cursor_store=cursors,
        projection_store=projections,
    )
    original_apply = projections.apply_changes

    def interrupted_apply(*args: Any, **kwargs: Any) -> Any:
        if failure_stage == "after_apply":
            original_apply(*args, **kwargs)
        raise RuntimeError("interrupted")

    def interrupted_cursor(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("interrupted")

    try:
        with monkeypatch.context() as patch:
            if failure_stage == "cursor":
                patch.setattr(cursors, "_insert_projection", interrupted_cursor)
            else:
                patch.setattr(projections, "apply_changes", interrupted_apply)
            with pytest.raises(RuntimeError, match="interrupted"):
                reconciler.sync(ACCOUNT)
    finally:
        reconciler.close()

    cursors = TransactionCursorStore(cursor_path)
    projections = AccountProjectionStore(projection_path)
    restarted = LiveReconciler(
        client=client,
        store=store,
        cursor_store=cursors,
        projection_store=projections,
    )
    try:
        result = restarted.sync(ACCOUNT)
        assert result[1] == (0 if failure_stage == "after_apply" else 1)
        for _ in range(3):
            assert restarted.sync(ACCOUNT)[1] == 0
        snapshot = projections.snapshot(ACCOUNT)
        assert snapshot is not None
        assert snapshot.balance == Decimal("990")
        assert snapshot.financing_total == Decimal("-10")
        assert snapshot.last_transaction_id == cursors.cursor(ACCOUNT) == "12"
        assert queries[:2] == ["10", "11" if failure_stage == "after_apply" else "10"]
    finally:
        restarted.close()


@pytest.mark.parametrize("cursor_ahead", [False, True])
def test_sync_waits_for_gap_before_projecting_later_facts(
    store: BrokerReconStore,
    tmp_path: Path,
    cursor_ahead: bool,
) -> None:
    rows = [
        {
            **_fill(transaction_id="12", transaction_type="DAILY_FINANCING"),
            "financing": "-10",
        }
    ]
    reconciler = _reconciler(
        store,
        tmp_path,
        client=_client(transactions=rows, since_queries=[]),
    )
    projections = reconciler._projection_store
    cursors = reconciler._cursor_store
    projections.rebuild(ACCOUNT, [], initial_balance=Decimal("1000"))
    projections.advance_cursor(ACCOUNT, "10")
    cursors.advance(
        ACCOUNT,
        [
            TransactionResult(
                transaction_id="10",
                transaction_type="CREATE",
                request_id="test",
            )
        ],
        owner="reconciler",
    )
    if cursor_ahead:
        cursors.advance(
            ACCOUNT,
            [
                TransactionResult(
                    transaction_id=str(transaction_id),
                    transaction_type="CREATE",
                    request_id="test",
                )
                for transaction_id in (11, 12)
            ],
            owner="reconciler",
        )
    try:
        assert reconciler.sync(ACCOUNT)[1:3] == (0, 1)
        rows.insert(
            0,
            {
                **_fill(transaction_id="11", transaction_type="DAILY_FINANCING"),
                "financing": "-5",
            },
        )
        assert reconciler.sync(ACCOUNT)[1:3] == (2, 0)
        assert reconciler.sync(ACCOUNT)[1] == 0
        snapshot = projections.snapshot(ACCOUNT)
        assert snapshot is not None
        assert snapshot.balance == Decimal("985")
    finally:
        reconciler.close()


def test_first_boot_replays_history_without_double_counting_balance(
    store: BrokerReconStore,
    tmp_path: Path,
) -> None:
    rows = [
        {**_fill(transaction_id="1", transaction_type="DEPOSIT"), "units": "100"},
        {**_fill(transaction_id="2", transaction_type="WITHDRAWAL"), "units": "20"},
        {
            **_fill(transaction_id="3", transaction_type="DAILY_FINANCING"),
            "financing": "-10",
        },
        {**_fill(transaction_id="4", units="0"), "pl": "5"},
    ]
    client = _client(transactions=rows, last_transaction_id="4", since_queries=[])
    reconciler = _reconciler(store, tmp_path, client=client)
    summary = AccountOpsClient(client).account_summary()
    try:
        reconciler._ensure_seeded(summary)
        for _ in range(3):
            assert reconciler.sync(ACCOUNT)[1] == 0
        snapshot = reconciler._projection_store.snapshot(ACCOUNT)
        assert snapshot is not None
        assert snapshot.balance == summary.balance
        assert snapshot.realized_pl == Decimal("5")
        assert snapshot.financing_total == Decimal("-10")
        assert len(snapshot.fills) == 1
        assert snapshot.last_transaction_id == "4"
    finally:
        reconciler.close()


def test_first_boot_empty_history_preserves_balance(
    store: BrokerReconStore,
    tmp_path: Path,
) -> None:
    client = _client(since_queries=[])
    reconciler = _reconciler(store, tmp_path, client=client)
    try:
        for _ in range(3):
            reconciler.reconcile()
        snapshot = reconciler._projection_store.snapshot(ACCOUNT)
        assert snapshot is not None
        assert snapshot.balance == Decimal("100000")
        assert snapshot.fills == ()
    finally:
        reconciler.close()


def test_first_boot_incomplete_history_is_not_published(
    store: BrokerReconStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    reconciler = _reconciler(store, tmp_path, client=client)
    summary = AccountOpsClient(client).account_summary()
    window = TransactionOpsClient(client).transaction_range("1", "10")
    incomplete = window.model_copy(
        update={
            "gaps": (TransactionGap(gap_from="1", gap_to="1"),),
        }
    )

    def incomplete_range(*args: Any, **kwargs: Any) -> Any:
        return incomplete

    try:
        with monkeypatch.context() as patch:
            patch.setattr(TransactionOpsClient, "transaction_range", incomplete_range)
            with pytest.raises(TransactionOperationError, match="incomplete_history"):
                reconciler._ensure_seeded(summary)
        assert reconciler._projection_store.snapshot(ACCOUNT) is None
        reconciler._ensure_seeded(summary)
        reconciler.sync(ACCOUNT)
        snapshot = reconciler._projection_store.snapshot(ACCOUNT)
        assert snapshot is not None
        assert snapshot.balance == summary.balance
    finally:
        reconciler.close()


@pytest.mark.parametrize("scope", ["startup", "cycle", "eod"])
def test_bootstrap_history_gap_records_verdict_and_obeys_freeze_policy(
    store: BrokerReconStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
) -> None:
    client = _client()
    reconciler = _reconciler(store, tmp_path, client=client)
    window = TransactionOpsClient(client).transaction_range("1", "10")
    incomplete = window.model_copy(
        update={"gaps": (TransactionGap(gap_from="1", gap_to="1"),)}
    )

    def incomplete_range(*args: Any, **kwargs: Any) -> Any:
        return incomplete

    monkeypatch.setattr(TransactionOpsClient, "transaction_range", incomplete_range)
    try:
        result = reconciler.reconcile(scope=scope)
        assert not result.clean
        assert result.facts_applied == 0
        assert result.gap_count == 1
        assert result.freeze_raised is (scope != "eod")
        assert store.has_open_freeze() is (scope != "eod")
        diff = result.report.diffs[0]
        assert diff.kind == "cursor_diff"
        assert diff.severity == "CRITICAL"
        assert diff.detail == "bootstrap history incomplete"
        snapshots = store.list_snapshots()
        assert len(snapshots) == 1
        assert not snapshots[0].all_match
        assert snapshots[0].scope == scope
        assert reconciler._projection_store.snapshot(ACCOUNT) is None
        assert reconciler._cursor_store.cursor(ACCOUNT) is None
    finally:
        reconciler.close()


def test_bootstrap_other_transaction_errors_propagate(
    store: BrokerReconStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reconciler = _reconciler(store, tmp_path, client=_client())

    def failed_range(*args: Any, **kwargs: Any) -> Any:
        raise TransactionOperationError("protocol_error", "invalid response")

    monkeypatch.setattr(TransactionOpsClient, "transaction_range", failed_range)
    try:
        with pytest.raises(TransactionOperationError, match="protocol_error"):
            reconciler.reconcile()
        assert store.list_snapshots() == []
        assert reconciler._projection_store.snapshot(ACCOUNT) is None
    finally:
        reconciler.close()


class TestOwnActivityIsExplainable:
    def test_our_filled_order_and_protective_fill_never_freeze(
        self, store: BrokerReconStore, tmp_path: Path
    ) -> None:
        """The regression that mattered: a real fill must not freeze."""
        reconciler = _reconciler(
            store,
            tmp_path,
            client=_client(
                orders=[_our_order()],
                transactions=[
                    _fill(transaction_id="8"),
                    _fill(transaction_id="9", transaction_type="STOP_LOSS_ORDER"),
                    _fill(
                        transaction_id="10",
                        transaction_type="DAILY_FINANCING",
                        units="0",
                    ),
                ],
            ),
        )
        try:
            result = reconciler.reconcile(scope="cycle")
        finally:
            reconciler.close()

        assert result.facts_applied == 0
        assert set(result.warnings) >= {
            "ORDER_FILL",
            "STOP_LOSS_ORDER",
            "DAILY_FINANCING",
        }
        # Own activity is explainable: nothing here may freeze new exposure.
        assert result.freeze_raised is False
        assert store.has_open_freeze() is False

    def test_cursor_advances_and_snapshot_is_recorded(
        self, store: BrokerReconStore, tmp_path: Path
    ) -> None:
        reconciler = _reconciler(
            store, tmp_path, client=_client(transactions=[_fill(transaction_id="8")])
        )
        try:
            result = reconciler.reconcile(scope="cycle")
        finally:
            reconciler.close()

        assert result.cursor is not None
        snapshots = store.list_snapshots()
        assert snapshots and snapshots[0].scope == "cycle"


class TestUnexplainedDifferencesFreeze:
    def test_foreign_position_freezes(
        self, store: BrokerReconStore, tmp_path: Path
    ) -> None:
        reconciler = _reconciler(
            store, tmp_path, client=_client(positions=[_foreign_position()])
        )
        try:
            result = reconciler.reconcile(scope="cycle")
        finally:
            reconciler.close()

        assert result.clean is False
        assert result.freeze_raised is True
        assert store.has_open_freeze() is True

    def test_eod_scope_records_but_does_not_freeze(
        self, store: BrokerReconStore, tmp_path: Path
    ) -> None:
        reconciler = _reconciler(
            store, tmp_path, client=_client(positions=[_foreign_position()])
        )
        try:
            result = reconciler.reconcile(scope="eod")
        finally:
            reconciler.close()

        assert result.clean is False
        assert result.freeze_raised is False
        assert store.has_open_freeze() is False

    def test_unknown_scope_is_rejected(
        self, store: BrokerReconStore, tmp_path: Path
    ) -> None:
        reconciler = _reconciler(store, tmp_path, client=_client())
        try:
            with pytest.raises(ValueError, match="unknown reconciliation scope"):
                reconciler.reconcile(scope="garbage")
        finally:
            reconciler.close()


class TestUnconfiguredBroker:
    def test_records_non_matching_snapshot_and_freezes_startup(
        self, store: BrokerReconStore
    ) -> None:
        result = record_broker_not_configured(store, scope="startup")

        assert result.clean is False
        assert result.freeze_raised is True
        assert store.has_open_freeze() is True
        snapshots = store.list_snapshots()
        assert snapshots[0].all_match is False

    def test_eod_scope_never_freezes_even_when_unconfigured(
        self, store: BrokerReconStore
    ) -> None:
        result = record_broker_not_configured(store, scope="eod")

        assert result.freeze_raised is False
        assert store.has_open_freeze() is False

    def test_unknown_scope_is_rejected(self, store: BrokerReconStore) -> None:
        with pytest.raises(ValueError, match="unknown reconciliation scope"):
            record_broker_not_configured(store, scope="garbage")


class TestScopeAndPolicyConstants:
    def test_allowed_scopes_constant_is_complete(self) -> None:
        assert ALLOWED_SCOPES == frozenset({"startup", "cycle", "eod"})

    def test_reconciler_config_rejects_unknown_scope(self) -> None:
        with pytest.raises(ValueError, match="unknown reconciliation scope"):
            ReconcilerConfig().should_freeze("garbage")

    def test_reconciler_config_defaults_freeze_startup_and_cycle(self) -> None:
        config = ReconcilerConfig()

        assert config.should_freeze("startup") is True
        assert config.should_freeze("cycle") is True
        assert config.should_freeze("eod") is False


class TestFreezeStore:
    def test_clear_freeze_resets_open_state(self, store: BrokerReconStore) -> None:
        store.raise_freeze(reason="manual", source="test")
        assert store.has_open_freeze() is True

        event = store.list_freezes(only_open=True)[0]
        store.clear_freeze(event_id=event.event_id, reason="manual unfreeze")

        assert store.has_open_freeze() is False

    def test_clear_unknown_freeze_raises(self, store: BrokerReconStore) -> None:
        with pytest.raises(ValueError, match="unknown freeze event_id"):
            store.clear_freeze(event_id="not-an-event")

    def test_snapshot_listing_returns_recent_first(
        self, store: BrokerReconStore
    ) -> None:
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


class TestDependentOrdersAndTradeLinks:
    """The shapes a real fill produces (verified against the practice API)."""

    def test_dependent_orders_parse_without_an_instrument(self) -> None:
        """Stop-loss/take-profit rows carry tradeID, no instrument/units."""
        from alphabrief_execution.broker.oanda.order_ops import OrderOpsClient

        def send(request: Request, timeout: float) -> bytes:
            del timeout
            return json.dumps(
                {
                    "orders": [
                        {
                            "id": "7",
                            "type": "STOP_LOSS",
                            "state": "PENDING",
                            "instrument": None,
                            "units": None,
                            "timeInForce": "GTC",
                            "tradeID": "5",
                            "price": "1.13002",
                            "clientExtensions": None,
                        },
                        {
                            "id": "4",
                            "type": "MARKET",
                            "state": "FILLED",
                            "instrument": "EUR_USD",
                            "units": "1000",
                            "timeInForce": "FOK",
                            "clientExtensions": {"id": "ai_1", "tag": "alphabrief"},
                        },
                    ]
                }
            ).encode()

        client = OandaHttpClient(
            config=_config(),
            http_send=send,
            token="test-token",
            account_id=ACCOUNT,
        )

        orders = OrderOpsClient(client).list_orders().orders

        stop, entry = orders
        assert stop.symbol is None
        assert stop.trade_id == "5"
        assert stop.units == Decimal("0")
        assert entry.symbol == "EUR_USD"
        assert entry.client_tag == "alphabrief"

    def test_closing_fill_links_to_the_trade_it_closes(self) -> None:
        """``tradesClosed`` associates a close with its trade."""
        from alphabrief_execution.broker.oanda.transaction_ops import (
            TransactionOpsClient,
        )

        def send(request: Request, timeout: float) -> bytes:
            del timeout
            return json.dumps(
                {
                    "transactions": [
                        {
                            "id": "5",
                            "type": "ORDER_FILL",
                            "time": "2026-09-30T10:00:00.000000000Z",
                            "instrument": "EUR_USD",
                            "units": "1000",
                            "price": "1.13173",
                            "pl": "0.0000",
                            "tradeOpened": {"tradeID": "5", "units": "1000"},
                        },
                        {
                            "id": "9",
                            "type": "ORDER_FILL",
                            "time": "2026-09-30T11:00:00.000000000Z",
                            "instrument": "EUR_USD",
                            "units": "-1000",
                            "price": "1.13165",
                            "pl": "-0.0800",
                            "tradesClosed": [{"tradeID": "5", "units": "-1000"}],
                        },
                    ],
                    "lastTransactionID": "9",
                }
            ).encode()

        client = OandaHttpClient(
            config=_config(),
            http_send=send,
            token="test-token",
            account_id=ACCOUNT,
        )

        window = TransactionOpsClient(client).transactions_since("4", request_id="test")

        assert [tx.trade_id for tx in window.transactions] == ["5", "5"]

    def test_projection_closes_the_trade_on_the_closing_fill(
        self, tmp_path: Path
    ) -> None:
        """A closing fill zeroes the trade and the position it held."""
        from alphabrief_execution.broker.oanda.account_projection import (
            AccountProjectionStore,
        )
        from alphabrief_execution.broker.oanda.live_reconciliation import (
            facts_from_transactions,
        )
        from alphabrief_execution.broker.oanda.transaction_ops import (
            TransactionResult,
        )

        def tx(tx_id: str, units: str, *, trade_id: str) -> TransactionResult:
            return TransactionResult(
                transaction_id=tx_id,
                transaction_type="ORDER_FILL",
                time=datetime(2026, 9, 30, 10, 0, tzinfo=UTC),
                instrument="EUR_USD",
                units=Decimal(units),
                price=Decimal("1.13173"),
                realized_pl=Decimal("0"),
                financing=Decimal("0"),
                trade_id=trade_id,
                request_id="test",
            )

        facts, _ = facts_from_transactions(
            [tx("5", "1000", trade_id="5"), tx("9", "-1000", trade_id="5")]
        )
        store = AccountProjectionStore(db_path=tmp_path / "projection.duckdb")
        try:
            snapshot = store.rebuild(ACCOUNT, facts, initial_balance=Decimal("100000"))
        finally:
            store.close()

        assert [t.state for t in snapshot.trades] == ["CLOSED"]
        assert snapshot.trades[0].current_units == 0
        assert list(snapshot.positions) == []
        assert snapshot.balance == Decimal("100000")
