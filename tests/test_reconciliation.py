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
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.account_projection import AccountProjectionStore
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.live_reconciliation import (
    ALLOWED_SCOPES,
    LiveReconciler,
    ReconcilerConfig,
    record_broker_not_configured,
)
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger
from alphabrief_execution.broker.oanda.transaction_cursor import (
    TransactionCursorStore,
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

        # ORDER_FILL and DAILY_FINANCING move the account and are folded;
        # the protective-order transaction is recognised but not folded.
        assert result.facts_applied == 2
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
