"""M06-W04: account summary and account changes operations.

Covers:
- account summary and account changes match exact request and response
  fixtures (AC-M06-W04-01);
- balance, NAV, unrealized PnL, margins, open counts, and broker
  transaction IDs stay distinct and Decimal-safe; the durable
  ``sinceTransactionID`` cursor is passed through exactly
  (AC-M06-W04-02);
- missing, malformed, or invalid cursors fail closed and no local state
  is fabricated (AC-M06-W04-03).
"""

from __future__ import annotations

import json
from decimal import Decimal
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.account_ops import (
    DEFAULT_SINCE_TRANSACTION_ID,
    AccountChangesResult,
    AccountOperationError,
    AccountOpsClient,
    AccountSummaryResult,
)
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig

ACCOUNT_ID = "101-004-1234567-001"


def _account_payload() -> dict[str, Any]:
    return {
        "id": ACCOUNT_ID,
        "currency": "USD",
        "balance": "100000.00",
        "NAV": "100050.00",
        "unrealizedPL": "50.00",
        "marginUsed": "1000.00",
        "marginAvailable": "99000.00",
        "openOrderCount": 1,
        "openTradeCount": 2,
        "openPositionCount": 1,
        "lastTransactionID": "2047",
    }


def _changes_payload(since: str) -> dict[str, Any]:
    return {
        "changes": {
            "ordersCreated": [{"id": "2001"}],
            "ordersCancelled": [{"id": "2002"}],
            "ordersFilled": [{"id": "2003"}, {"id": "2004"}],
            "ordersTriggered": [{"id": "2005"}],
            "tradesOpened": [{"id": "2006"}],
            "tradesReduced": [{"id": "2007"}],
            "tradesClosed": [{"id": "2008"}],
            "positionsClosed": [{"id": "2009"}],
            "positionsReduced": [{"id": "2010"}],
            "transactions": [
                {"id": "2003", "type": "ORDER_FILL"},
                {"id": "2008", "type": "TRADE_CLOSE"},
                {"id": "2011", "type": "DAILY_FINANCING"},
            ],
        },
        "state": {
            "account": {
                "balance": "99988.71",
                "NAV": "100120.00",
                "unrealizedPL": "131.29",
            }
        },
        "lastTransactionID": "2011",
    }


class _FakeAccountBroker:
    """A deterministic in-memory OANDA account for the mock transport."""

    def __init__(self) -> None:
        self.captured: list[dict[str, Any]] = []
        self.fail_summary = False
        self.fail_changes = False

    def handle(self, request: Request) -> bytes:
        method = request.method
        url = request.full_url
        raw = request.data
        body = json.loads(raw.decode("utf-8")) if isinstance(raw, bytes) else {}
        self.captured.append({"method": method, "url": url, "body": body})
        path, _, query = url.partition("?")
        if method == "GET" and path.endswith("/summary"):
            if self.fail_summary:
                raise HTTPError(url, 404, "not found", Message(), None)
            return json.dumps({"account": _account_payload()}).encode("utf-8")
        if method == "GET" and path.endswith("/changes"):
            if self.fail_changes:
                raise HTTPError(url, 422, "invalid since", Message(), None)
            params = dict(piece.split("=", 1) for piece in query.split("&") if piece)
            since = params.get("sinceTransactionID", "")
            return json.dumps(_changes_payload(since)).encode("utf-8")
        raise HTTPError(url, 405, "method not allowed", Message(), None)


def _client(broker: _FakeAccountBroker) -> AccountOpsClient:
    http = OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=lambda request, timeout: broker.handle(request),
        token="t",
        account_id=ACCOUNT_ID,
    )
    return AccountOpsClient(http)


# ---------------------------------------------------------------------------
# AC-M06-W04-01: summary and changes match exact fixtures
# ---------------------------------------------------------------------------


def test_account_summary_exact_fixture() -> None:
    broker = _FakeAccountBroker()
    accounts = _client(broker)
    summary: AccountSummaryResult = accounts.account_summary()
    assert summary.account_id == ACCOUNT_ID
    assert summary.currency == "USD"
    assert summary.balance == Decimal("100000.00")
    assert summary.nav == Decimal("100050.00")
    assert summary.unrealized_pl == Decimal("50.00")
    assert summary.margin_used == Decimal("1000.00")
    assert summary.margin_available == Decimal("99000.00")
    assert summary.open_order_count == 1
    assert summary.open_trade_count == 2
    assert summary.open_position_count == 1
    assert summary.last_transaction_id == "2047"
    assert summary.request_id == "summary"


def test_account_changes_exact_fixture() -> None:
    broker = _FakeAccountBroker()
    accounts = _client(broker)
    changes: AccountChangesResult = accounts.account_changes("2000")
    assert changes.since_transaction_id == "2000"
    assert changes.last_transaction_id == "2011"
    assert changes.orders_created == 1
    assert changes.orders_cancelled == 1
    assert changes.orders_filled == 2
    assert changes.orders_triggered == 1
    assert changes.trades_opened == 1
    assert changes.trades_reduced == 1
    assert changes.trades_closed == 1
    assert changes.positions_closed == 1
    assert changes.positions_reduced == 1
    assert changes.transactions == 3
    assert changes.balance == Decimal("99988.71")
    assert changes.nav == Decimal("100120.00")
    assert changes.unrealized_pl == Decimal("131.29")


def test_changes_default_cursor_is_zero() -> None:
    broker = _FakeAccountBroker()
    accounts = _client(broker)
    changes = accounts.account_changes()
    assert changes.since_transaction_id == DEFAULT_SINCE_TRANSACTION_ID
    assert changes.since_transaction_id == "0"
    assert changes.last_transaction_id == "2011"


def test_changes_empty_page() -> None:
    class _EmptyBroker(_FakeAccountBroker):
        def handle(self, request: Request) -> bytes:
            path, _, _ = request.full_url.partition("?")
            if request.method == "GET" and path.endswith("/changes"):
                return json.dumps(
                    {
                        "changes": {
                            "ordersCreated": [],
                            "ordersCancelled": [],
                            "ordersFilled": [],
                            "ordersTriggered": [],
                            "tradesOpened": [],
                            "tradesReduced": [],
                            "tradesClosed": [],
                            "positionsClosed": [],
                            "positionsReduced": [],
                            "transactions": [],
                        },
                        "state": {"account": _account_payload()},
                        "lastTransactionID": "2047",
                    }
                ).encode("utf-8")
            raise HTTPError(request.full_url, 405, "not allowed", Message(), None)

    empty = _client(_EmptyBroker())
    changes = empty.account_changes("2047")
    assert changes.last_transaction_id == "2047"
    assert changes.transactions == 0
    assert changes.orders_filled == 0


# ---------------------------------------------------------------------------
# AC-M06-W04-02: cursor and Decimal-safety
# ---------------------------------------------------------------------------


def test_since_transaction_id_passes_through_exactly() -> None:
    broker = _FakeAccountBroker()
    accounts = _client(broker)
    accounts.account_changes("123456789")
    params = broker.captured[0]["url"].split("?")[1]
    assert "sinceTransactionID=123456789" in params


def test_broker_transaction_ids_stay_distinct() -> None:
    broker = _FakeAccountBroker()
    accounts = _client(broker)
    changes = accounts.account_changes("2000")
    # The cursor and the latest broker transaction ID are separate
    # values; the consumer must never conflate them.
    assert changes.since_transaction_id != changes.last_transaction_id
    assert changes.last_transaction_id.isdigit()
    assert changes.orders_filled + changes.orders_cancelled == 3


def test_decimal_values_never_floats() -> None:
    broker = _FakeAccountBroker()
    accounts = _client(broker)
    summary = accounts.account_summary()
    for value in (
        summary.balance,
        summary.nav,
        summary.unrealized_pl,
        summary.margin_used,
        summary.margin_available,
    ):
        assert isinstance(value, Decimal)
    changes = accounts.account_changes("2000")
    for value in (changes.balance, changes.nav, changes.unrealized_pl):
        assert isinstance(value, Decimal)


# ---------------------------------------------------------------------------
# AC-M06-W04-03: fail-closed
# ---------------------------------------------------------------------------


def test_invalid_cursor_fails_closed() -> None:
    broker = _FakeAccountBroker()
    accounts = _client(broker)
    with pytest.raises(AccountOperationError) as excinfo:
        accounts.account_changes("not-a-cursor")
    assert excinfo.value.kind == "invalid_cursor"
    # No request reached the broker.
    assert broker.captured == []


def test_missing_summary_fails_closed() -> None:
    broker = _FakeAccountBroker()
    broker.fail_summary = True
    accounts = _client(broker)
    with pytest.raises(AccountOperationError) as excinfo:
        accounts.account_summary()
    assert excinfo.value.kind == "account_not_found"


def test_rejected_changes_fail_closed() -> None:
    broker = _FakeAccountBroker()
    broker.fail_changes = True
    accounts = _client(broker)
    with pytest.raises(AccountOperationError) as excinfo:
        accounts.account_changes("2000")
    assert excinfo.value.kind == "rejected"


def test_malformed_changes_fail_closed() -> None:
    class _MalformedBroker(_FakeAccountBroker):
        def handle(self, request: Request) -> bytes:
            return b"not json"

    accounts = _client(_MalformedBroker())
    with pytest.raises(AccountOperationError) as excinfo:
        accounts.account_changes("2000")
    assert excinfo.value.kind == "protocol_error"


def test_every_response_carries_request_correlation() -> None:
    broker = _FakeAccountBroker()
    accounts = _client(broker)
    assert accounts.account_summary(request_id="manual-1").request_id == "manual-1"
    assert (
        accounts.account_changes("2000", request_id="manual-2").request_id
        == "manual-2"
    )
