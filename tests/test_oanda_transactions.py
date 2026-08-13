"""M06-W05: transaction details, ranges, and cursor primitives.

Covers:
- detail, ID-range, paginated-range, and since-ID requests preserve
  OANDA transaction IDs as the cursor authority and never substitute
  local timestamps (AC-M06-W05-01);
- empty pages, overlapping pages, duplicate IDs, out-of-order IDs,
  declared page ranges, and missing ranges produce deterministic
  normalized output and explicit gap signals (AC-M06-W05-02);
- cursor candidates are returned separately from durable advancement so
  a failed consumer cannot acknowledge unseen transactions
  (AC-M06-W05-03).
"""

from __future__ import annotations

import json
from decimal import Decimal
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.transaction_ops import (
    TransactionOperationError,
    TransactionOpsClient,
)

ACCOUNT_ID = "101-004-1234567-001"
BASE = f"http://oanda.test/v3/accounts/{ACCOUNT_ID}"


def _order_fill(
    transaction_id: str,
    *,
    instrument: str = "EUR_USD",
    units: str = "1000",
    price: str = "1.10500",
    pl: str = "12.34",
    financing: str = "-0.05",
) -> dict[str, Any]:
    return {
        "id": transaction_id,
        "type": "ORDER_FILL",
        "time": "2026-08-04T12:00:00.000000000Z",
        "instrument": instrument,
        "units": units,
        "price": price,
        "pl": pl,
        "financing": financing,
    }


class _FakeTransactionBroker:
    """A deterministic in-memory OANDA transaction store."""

    def __init__(self) -> None:
        self.transactions: dict[str, dict[str, Any]] = {}
        self.page_size_override: int | None = None
        self.scramble = False
        self.duplicate_ids: list[str] = []
        self.infinite_pages = False

    def add(self, transaction: dict[str, Any]) -> None:
        self.transactions[str(transaction["id"])] = transaction

    def _serve(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if self.scramble:
            rows = list(reversed(rows))
        duplicates: list[dict[str, Any]] = []
        for transaction_id in self.duplicate_ids:
            found = self.transactions.get(transaction_id)
            if found is not None:
                duplicates.append(found)
        return {
            "transactions": rows + duplicates,
            "lastTransactionID": str(
                max(int(t["id"]) for t in self.transactions.values())
            ),
        }

    def handle(self, request: Request) -> bytes:
        method = request.method
        url = request.full_url
        path, _, query = url.partition("?")
        params = dict(piece.split("=", 1) for piece in query.split("&") if piece)

        is_detail = (
            "/transactions/" in path
            and "/idrange" not in path
            and "/sinceid" not in path
        )
        if method == "GET" and is_detail:
            transaction_id = path.split("/transactions/", 1)[1]
            found = self.transactions.get(transaction_id)
            if found is None:
                raise HTTPError(url, 404, "not found", Message(), None)
            return json.dumps({"transaction": found}).encode("utf-8")
        if method == "GET" and path.endswith("/transactions/sinceid"):
            since = int(params["id"])
            rows = [
                t for t in self.transactions.values() if int(t["id"]) > since
            ]
            return json.dumps(self._serve(rows)).encode("utf-8")
        if method == "GET" and path.endswith("/transactions/idrange"):
            from_id = int(params["from"])
            to_id = int(params["to"])
            page_size = int(params.get("pageSize", "100"))
            page = int(params.get("page", "1"))
            rows = [
                t
                for t in self.transactions.values()
                if from_id <= int(t["id"]) <= to_id
            ]
            rows.sort(key=lambda t: int(t["id"]))
            total_pages = max(1, -(-len(rows) // page_size))
            if self.infinite_pages:
                total_pages = 10**9
            start = (page - 1) * page_size
            page_rows = rows[start : start + page_size]
            payload = self._serve(page_rows)
            if page < total_pages:
                next_page = (
                    f"{BASE}/transactions/idrange?from={params['from']}"
                    f"&to={params['to']}&pageSize={page_size}&page={page + 1}"
                )
                payload["pages"] = [next_page]
            else:
                payload["pages"] = []
            return json.dumps(payload).encode("utf-8")
        raise HTTPError(url, 405, "method not allowed", Message(), None)


def _client(
    broker: _FakeTransactionBroker, captured: list[dict[str, Any]] | None = None
) -> TransactionOpsClient:
    log = captured if captured is not None else []

    def _send(request: Request, timeout_seconds: float) -> bytes:
        log.append({"method": request.method, "url": request.full_url})
        return broker.handle(request)

    http = OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=_send,
        token="t",
        account_id=ACCOUNT_ID,
    )
    return TransactionOpsClient(http)


def _seed(broker: _FakeTransactionBroker, ids: list[int]) -> None:
    for transaction_id in ids:
        broker.add(
            _order_fill(
                str(transaction_id),
                units="1000",
                price="1.10500",
                pl="12.34",
                financing="-0.05",
            )
        )


# ---------------------------------------------------------------------------
# AC-M06-W05-01: broker IDs are the cursor authority
# ---------------------------------------------------------------------------


def test_get_transaction_preserves_broker_fields() -> None:
    broker = _FakeTransactionBroker()
    broker.add(_order_fill("2048"))
    transactions = _client(broker)
    detail = transactions.get_transaction("2048")
    assert detail.transaction_id == "2048"
    assert detail.transaction_type == "ORDER_FILL"
    assert detail.time is not None
    assert detail.instrument == "EUR_USD"
    assert detail.units == Decimal("1000")
    assert detail.price == Decimal("1.10500")
    assert detail.realized_pl == Decimal("12.34")
    assert detail.financing == Decimal("-0.05")


def test_range_and_since_pass_exact_broker_ids() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [100, 101])
    captured: list[dict[str, Any]] = []
    transactions = _client(broker, captured)
    transactions.transaction_range("100", "101")
    transactions.transactions_since("100")
    urls = [entry["url"] for entry in captured]
    assert any("idrange?from=100&to=101" in url for url in urls)
    assert any("/transactions/sinceid?id=100" in url for url in urls)


def test_local_timestamps_are_never_accepted_as_cursor() -> None:
    broker = _FakeTransactionBroker()
    transactions = _client(broker)
    with pytest.raises(TransactionOperationError) as excinfo:
        transactions.get_transaction("2026-08-04T12:00:00Z")
    assert excinfo.value.kind == "invalid_cursor"
    with pytest.raises(TransactionOperationError) as excinfo:
        transactions.transaction_range("2026-08-04T12:00:00Z", "2000")
    assert excinfo.value.kind == "invalid_cursor"
    with pytest.raises(TransactionOperationError) as excinfo:
        transactions.transactions_since("2026-08-04T12:00:00Z")
    assert excinfo.value.kind == "invalid_cursor"


def test_reversed_range_and_bad_page_size_fail_closed() -> None:
    broker = _FakeTransactionBroker()
    transactions = _client(broker)
    with pytest.raises(TransactionOperationError) as excinfo:
        transactions.transaction_range("2000", "1000")
    assert excinfo.value.kind == "invalid_range"
    with pytest.raises(TransactionOperationError) as excinfo:
        transactions.transaction_range("1000", "2000", page_size=0)
    assert excinfo.value.kind == "invalid_page_size"
    with pytest.raises(TransactionOperationError) as excinfo:
        transactions.transaction_range("1000", "2000", page_size=1001)
    assert excinfo.value.kind == "invalid_page_size"


def test_unknown_transaction_fails_closed() -> None:
    broker = _FakeTransactionBroker()
    transactions = _client(broker)
    with pytest.raises(TransactionOperationError) as excinfo:
        transactions.get_transaction("9999")
    assert excinfo.value.kind == "transaction_not_found"


# ---------------------------------------------------------------------------
# AC-M06-W05-02: deterministic normalized output and explicit gap signals
# ---------------------------------------------------------------------------


def test_range_normalizes_out_of_order_and_duplicates() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [100, 101, 102])
    broker.scramble = True
    broker.duplicate_ids = ["101"]
    transactions = _client(broker)
    result = transactions.transaction_range("100", "102")
    ids = [t.transaction_id for t in result.transactions]
    assert ids == ["100", "101", "102"]
    assert result.duplicate_count == 1


def test_range_signals_missing_ids() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [100, 101, 103, 105])
    transactions = _client(broker)
    result = transactions.transaction_range("100", "106")
    assert result.declared_from == "100"
    assert result.declared_to == "106"
    gaps = [(g.gap_from, g.gap_to) for g in result.gaps]
    assert gaps == [("102", "102"), ("104", "104"), ("106", "106")]


def test_empty_declared_range_signals_whole_range() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [200])
    transactions = _client(broker)
    result = transactions.transaction_range("300", "305")
    assert result.transactions == ()
    assert result.cursor_candidate is None
    assert [(g.gap_from, g.gap_to) for g in result.gaps] == [("300", "305")]


def test_paginated_range_fetches_all_pages_deterministically() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [100, 101, 102, 103, 104])
    transactions = _client(broker)
    result = transactions.transaction_range("100", "104", page_size=2)
    assert [t.transaction_id for t in result.transactions] == [
        "100",
        "101",
        "102",
        "103",
        "104",
    ]
    assert result.gaps == ()
    assert result.duplicate_count == 0


def test_overlapping_calls_are_idempotent_and_deterministic() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [100, 101, 102, 103])
    transactions = _client(broker)
    first = transactions.transaction_range("100", "103")
    second = transactions.transaction_range("101", "104")
    # Each window is normalized against its own declared range.
    assert [t.transaction_id for t in first.transactions] == [
        "100",
        "101",
        "102",
        "103",
    ]
    assert [t.transaction_id for t in second.transactions] == [
        "101",
        "102",
        "103",
    ]
    assert [(g.gap_from, g.gap_to) for g in second.gaps] == [("104", "104")]


def test_since_mode_signals_internal_gaps() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [500, 501, 503, 504])
    transactions = _client(broker)
    result = transactions.transactions_since("500")
    assert [t.transaction_id for t in result.transactions] == [
        "501",
        "503",
        "504",
    ]
    assert [(g.gap_from, g.gap_to) for g in result.gaps] == [("502", "502")]


def test_since_mode_with_nothing_new() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [500, 501])
    transactions = _client(broker)
    result = transactions.transactions_since("501")
    assert result.transactions == ()
    assert result.gaps == ()
    assert result.cursor_candidate is None


def test_pagination_limit_fails_closed() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [100, 101])
    broker.infinite_pages = True
    transactions = _client(broker)
    with pytest.raises(TransactionOperationError) as excinfo:
        transactions.transaction_range("100", "101", page_size=1)
    assert excinfo.value.kind == "pagination_limit_exceeded"


# ---------------------------------------------------------------------------
# AC-M06-W05-03: cursor candidates are separate from durable advancement
# ---------------------------------------------------------------------------


def test_cursor_candidate_is_the_contiguous_prefix() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [100, 101, 103])
    transactions = _client(broker)
    result = transactions.transaction_range("100", "105")
    assert result.cursor_candidate == "101"
    # The candidate never advances past the first hole.
    assert [(g.gap_from, g.gap_to) for g in result.gaps] == [
        ("102", "102"),
        ("104", "105"),
    ]


def test_since_candidate_stops_at_first_hole() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [500, 502, 503])
    transactions = _client(broker)
    result = transactions.transactions_since("500")
    # 501 is missing, so no ID after 500 is fully contiguous: the
    # candidate cannot advance and stays unacknowledged.
    assert result.cursor_candidate is None
    assert [(g.gap_from, g.gap_to) for g in result.gaps] == [("501", "501")]
    contiguous = transactions.transactions_since("501")
    assert contiguous.cursor_candidate == "503"


def test_port_holds_no_durable_cursor() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [500, 501, 502])
    transactions = _client(broker)
    # Repeated fetches with the same cursor return identical windows: the
    # port never advances implicitly.
    first = transactions.transactions_since("500")
    second = transactions.transactions_since("500")
    assert first == second
    # There is no advance primitive on the port itself.
    assert not hasattr(transactions, "advance")
    assert not hasattr(transactions, "durable_cursor")


def test_failed_consumer_never_acknowledges_unseen_transactions() -> None:
    broker = _FakeTransactionBroker()
    _seed(broker, [500, 501, 502, 503])
    transactions = _client(broker)
    result = transactions.transactions_since("500")
    assert result.cursor_candidate == "503"
    # The consumer fails after seeing the candidate but before persisting
    # it: the retry sees the same window because nothing advanced.
    try:
        _persist_cursor_failingly(result.cursor_candidate)
    except _ConsumerCrash:
        pass
    retry = transactions.transactions_since("500")
    assert retry.cursor_candidate == "503"
    assert [t.transaction_id for t in retry.transactions] == [
        "501",
        "502",
        "503",
    ]


class _ConsumerCrash(RuntimeError):
    pass


def _persist_cursor_failingly(candidate: str | None) -> None:
    if candidate is None:
        raise _ConsumerCrash("nothing to persist")
    raise _ConsumerCrash("persist failed before commit")
