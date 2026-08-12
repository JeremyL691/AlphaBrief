"""M06-W02: OANDA order operations port.

Covers:
- create, get, list (paginated), cancel, and replace produce exact typed
  responses and correct state transitions (AC-M06-W02-01);
- invalid request IDs, unknown orders, race conditions, and stale
  replaces fail closed with classified errors (AC-M06-W02-02);
- request correlation is preserved on every response and retries never
  duplicate orders — create is idempotent on clientExtensions.id
  (AC-M06-W02-03).
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
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
from alphabrief_execution.broker.oanda.order_ops import (
    OrderOperationError,
    OrderOpsClient,
    OrderStateResult,
)
from alphabrief_execution.broker.oanda.orders import OandaOrderRequest

ACCOUNT_ID = "101-004-1234567-001"


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
        raw_payload={"guaranteedStopLossOrderMode": "ENABLED"},
    )


def _order_request() -> OandaOrderRequest:
    return OandaOrderRequest(
        type="MARKET",
        instrument="EUR_USD",
        units=Decimal("1000"),
        time_in_force="GTC",
    )


class _FakeBroker:
    """A deterministic in-memory OANDA order store for the mock transport."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.next_id = 1
        self.requests: list[dict[str, Any]] = []

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        order_id = str(self.next_id)
        self.next_id += 1
        order: dict[str, Any] = {
            "id": order_id,
            "instrument": payload.get("instrument", ""),
            "units": payload.get("units", "0"),
            "state": "PENDING",
            "createTime": "2026-08-04T12:00:00.000000000Z",
            "clientExtensions": payload.get("clientExtensions", {}),
        }
        if "price" in payload:
            order["price"] = payload["price"]
        self.orders[order_id] = order
        return order

    def order_payload(self, order_id: str) -> dict[str, Any]:
        return self.orders[order_id]


def _send_factory(broker: _FakeBroker, captured: list[dict[str, Any]]) -> Any:
    def _send(request: Request, timeout_seconds: float) -> bytes:
        method = request.method
        url = request.full_url
        raw = request.data
        body = json.loads(raw.decode("utf-8")) if isinstance(raw, bytes) else {}
        captured.append({"method": method, "url": url, "body": body})
        path = url.split(f"/v3/accounts/{ACCOUNT_ID}", 1)[1]

        if method == "POST" and path == "/orders":
            order = broker.create(body["order"])
            return json.dumps(
                {
                    "orderCreateTransaction": {
                        "id": order["id"],
                        "time": order["createTime"],
                    },
                    "orderFillTransaction": None,
                }
            ).encode("utf-8")
        if method == "GET" and path.startswith("/orders/") and "/cancel" not in path:
            order_id = path.split("/orders/", 1)[1].split("?", 1)[0]
            found = broker.orders.get(order_id)
            if found is None:
                raise HTTPError(url, 404, "not found", Message(), None)
            return json.dumps({"order": found}).encode("utf-8")
        if method == "GET" and path.startswith("/orders"):
            ordered: list[dict[str, Any]] = [
                broker.orders[oid]
                for oid in sorted(broker.orders, key=lambda o: int(o))
            ]
            return json.dumps({"orders": ordered}).encode("utf-8")
        if method == "PUT" and path.endswith("/cancel"):
            order_id = path.split("/orders/", 1)[1].split("/", 1)[0]
            found = broker.orders.get(order_id)
            if found is None:
                raise HTTPError(url, 404, "not found", Message(), None)
            found["state"] = "CANCELLED"
            return json.dumps({}).encode("utf-8")
        if method == "PUT" and "/orders/" in path:
            order_id = path.split("/orders/", 1)[1].split("?", 1)[0]
            found = broker.orders.get(order_id)
            if found is None:
                raise HTTPError(url, 404, "not found", Message(), None)
            replacement = broker.create(body["order"])
            replacement["state"] = "PENDING"
            broker.orders[str(replacement["id"])] = replacement
            return json.dumps(
                {"orderReplaceTransaction": {"id": replacement["id"]}}
            ).encode("utf-8")
        raise HTTPError(url, 405, "method not allowed", Message(), None)

    return _send


def _client(broker: _FakeBroker, captured: list[dict[str, Any]]) -> OrderOpsClient:
    http = OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=_send_factory(broker, captured),
        token="t",
        account_id=ACCOUNT_ID,
    )
    return OrderOpsClient(http)


# ---------------------------------------------------------------------------
# AC-M06-W02-01: typed responses and state transitions
# ---------------------------------------------------------------------------


def test_create_get_list_cancel_replace_flow() -> None:
    broker = _FakeBroker()
    captured: list[dict[str, Any]] = []
    ops = _client(broker, captured)

    created = ops.create_order(
        _order_request(), _instrument(), client_order_id="c1"
    )
    assert created.state == "PENDING"
    assert created.broker_order_id == "1"
    assert created.request_id.startswith("create-")

    state = ops.get_order(created.broker_order_id)
    assert isinstance(state, OrderStateResult)
    assert state.state == "PENDING"
    assert state.symbol == "EUR_USD"
    assert state.units == Decimal("1000")
    assert state.client_order_id == "c1"

    listing = ops.list_orders(page=1, page_size=10)
    assert len(listing.orders) == 1
    assert listing.orders[0].broker_order_id == "1"

    cancelled = ops.cancel_order(created.broker_order_id)
    assert cancelled.cancelled is True
    assert ops.get_order(created.broker_order_id).state == "CANCELLED"


def test_replace_creates_new_order_state() -> None:
    broker = _FakeBroker()
    ops = _client(broker, [])
    created = ops.create_order(
        _order_request(), _instrument(), client_order_id="c1"
    )
    replaced = ops.replace_order(
        created.broker_order_id,
        _order_request().model_copy(update={"units": Decimal("2000")}),
        _instrument(),
    )
    assert replaced.state == "PENDING"
    assert replaced.broker_order_id == "2"


# ---------------------------------------------------------------------------
# AC-M06-W02-02: classified fail-closed errors
# ---------------------------------------------------------------------------


def test_invalid_request_ids_fail_closed() -> None:
    ops = _client(_FakeBroker(), [])
    with pytest.raises(OrderOperationError) as excinfo:
        ops.create_order(_order_request(), _instrument(), client_order_id="  ")
    assert excinfo.value.kind == "invalid_request_id"
    with pytest.raises(OrderOperationError) as excinfo:
        ops.get_order("")
    assert excinfo.value.kind == "invalid_request_id"


def test_unknown_order_fails_closed() -> None:
    ops = _client(_FakeBroker(), [])
    with pytest.raises(OrderOperationError) as excinfo:
        ops.get_order("999")
    assert excinfo.value.kind == "unknown_order"


def test_cancel_of_filled_order_fails_closed() -> None:
    broker = _FakeBroker()
    ops = _client(broker, [])
    created = ops.create_order(
        _order_request(), _instrument(), client_order_id="c1"
    )
    broker.orders[created.broker_order_id]["state"] = "FILLED"
    with pytest.raises(OrderOperationError) as excinfo:
        ops.cancel_order(created.broker_order_id)
    assert excinfo.value.kind == "order_state_invalid"


def test_stale_replace_fails_closed() -> None:
    broker = _FakeBroker()
    ops = _client(broker, [])
    created = ops.create_order(
        _order_request(), _instrument(), client_order_id="c1"
    )
    # The order fills between the read and the replace (race).
    broker.orders[created.broker_order_id]["state"] = "FILLED"
    with pytest.raises(OrderOperationError) as excinfo:
        ops.replace_order(
            created.broker_order_id, _order_request(), _instrument()
        )
    assert excinfo.value.kind == "order_state_invalid"


# ---------------------------------------------------------------------------
# AC-M06-W02-03: correlation and idempotent create
# ---------------------------------------------------------------------------


def test_create_is_idempotent_on_client_order_id() -> None:
    broker = _FakeBroker()
    captured: list[dict[str, Any]] = []
    ops = _client(broker, captured)

    first = ops.create_order(
        _order_request(), _instrument(), client_order_id="c1"
    )
    second = ops.create_order(
        _order_request(), _instrument(), client_order_id="c1"
    )

    assert second.broker_order_id == first.broker_order_id
    assert second.reused is True
    # Only one broker order exists: retries never duplicate.
    assert len(broker.orders) == 1
    assert len(captured) == 1


def test_every_response_carries_request_correlation() -> None:
    broker = _FakeBroker()
    ops = _client(broker, [])
    created = ops.create_order(
        _order_request(), _instrument(), client_order_id="corr-1"
    )
    assert created.request_id == "create-corr-1"
    state = ops.get_order(created.broker_order_id, request_id="manual-1")
    assert state.request_id == "manual-1"
    listing = ops.list_orders(request_id="manual-list")
    assert listing.request_id == "manual-list"
    cancelled = ops.cancel_order(created.broker_order_id, request_id="manual-c")
    assert cancelled.request_id == "manual-c"
