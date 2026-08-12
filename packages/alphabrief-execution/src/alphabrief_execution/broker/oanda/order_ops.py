"""OANDA order operations port (M06-W02).

Create, get, list (paginated), cancel, and replace orders with exact
typed responses, request correlation on every result, and fail-closed
semantics: invalid request IDs, unknown orders, race conditions, and
stale replaces raise classified errors. Create is idempotent on
``clientExtensions.id`` — retries never duplicate orders.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.errors import BrokerNotFoundError
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
from alphabrief_execution.broker.oanda.orders import (
    OandaOrderRequest,
    serialize_order,
)

OrderStateValue = Literal[
    "PENDING", "FILLED", "TRIGGERED", "CANCELLED", "REJECTED", "EXPIRED"
]

#: States in which an order may still be replaced or cancelled.
_MUTABLE_STATES = frozenset({"PENDING"})


class OrderOperationError(RuntimeError):
    """A classified order operation failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        super().__init__(f"order operation failed ({kind}): {detail}")


class OrderStateResult(BaseModel):
    """One typed order state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_order_id: str = Field(min_length=1)
    client_order_id: str | None = None
    symbol: str = Field(min_length=1)
    state: OrderStateValue
    units: Decimal
    price: Decimal | None = None
    submitted_at: datetime | None = None
    request_id: str = Field(min_length=1)


class OrderCreateResult(BaseModel):
    """One typed create result with its correlation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_order_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)
    state: OrderStateValue
    request_id: str = Field(min_length=1)
    reused: bool = False


class OrderListResult(BaseModel):
    """One typed, paginated order page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    orders: tuple[OrderStateResult, ...]
    page: int = Field(ge=1)
    has_more: bool
    request_id: str = Field(min_length=1)


class OrderCancelResult(BaseModel):
    """One typed cancel result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_order_id: str = Field(min_length=1)
    cancelled: bool
    request_id: str = Field(min_length=1)


class OrderReplaceResult(BaseModel):
    """One typed replace result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_order_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)
    state: OrderStateValue
    request_id: str = Field(min_length=1)


class OrderOpsClient:
    """Order command and query port over the OANDA practice client."""

    def __init__(self, client: OandaHttpClient) -> None:
        self._client = client
        self._created: dict[str, OrderCreateResult] = {}

    def create_order(
        self,
        request: OandaOrderRequest,
        instrument: InstrumentMetadata,
        *,
        client_order_id: str,
        request_id: str | None = None,
    ) -> OrderCreateResult:
        """Create one order; idempotent on ``client_order_id``.

        Retries with the same ``client_order_id`` return the prior
        result instead of duplicating the order.
        """
        if not client_order_id.strip():
            raise OrderOperationError("invalid_request_id", "client_order_id is empty")
        existing = self._created.get(client_order_id)
        if existing is not None:
            return existing.model_copy(update={"reused": True})

        payload = serialize_order(request, instrument)
        payload["clientExtensions"] = {"id": client_order_id}
        correlation = request_id or f"create-{client_order_id}"
        response = self._client.request(
            "POST",
            self._client.account_path("/orders"),
            json_body={"order": payload},
        )
        body = response.json_body
        if not isinstance(body, dict):
            raise OrderOperationError("protocol_error", "create response is not JSON")
        create_tx = body.get("orderCreateTransaction")
        fill_tx = body.get("orderFillTransaction")
        if not isinstance(create_tx, dict) or not isinstance(
            create_tx.get("id"), str
        ):
            raise OrderOperationError(
                "protocol_error", "create response missing transaction"
            )
        broker_order_id = str(create_tx["id"])
        state: OrderStateValue = (
            "FILLED" if isinstance(fill_tx, dict) else "PENDING"
        )
        result = OrderCreateResult(
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
            state=state,
            request_id=correlation,
        )
        self._created[client_order_id] = result
        return result

    def get_order(
        self,
        broker_order_id: str,
        *,
        request_id: str | None = None,
    ) -> OrderStateResult:
        """Fetch one typed order state; unknown orders fail closed."""
        if not broker_order_id.strip():
            raise OrderOperationError("invalid_request_id", "broker_order_id is empty")
        try:
            response = self._client.request(
                "GET", self._client.account_path(f"/orders/{_path(broker_order_id)}")
            )
        except BrokerNotFoundError as exc:
            raise OrderOperationError("unknown_order", broker_order_id) from exc
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("order"), dict):
            raise OrderOperationError("protocol_error", "get response is not JSON")
        order = body["order"]
        try:
            units = Decimal(str(order.get("units", "0")))
            state = _parse_state(str(order.get("state", "")))
            return OrderStateResult(
                broker_order_id=str(order.get("id", "")).strip(),
                client_order_id=_client_extensions_id(order),
                symbol=str(order.get("instrument", "")).strip(),
                state=state,
                units=units,
                price=(
                    Decimal(str(order["price"]))
                    if order.get("price") not in (None, "")
                    else None
                ),
                submitted_at=_parse_time(order.get("createTime")),
                request_id=request_id or f"get-{broker_order_id}",
            )
        except (KeyError, ValueError) as exc:
            raise OrderOperationError(
                "protocol_error", f"order parse failed: {exc}"
            ) from exc

    def list_orders(
        self,
        *,
        status: OrderStateValue | None = None,
        page: int = 1,
        page_size: int = 50,
        request_id: str | None = None,
    ) -> OrderListResult:
        """List orders with deterministic bounded pagination."""
        params: dict[str, Any] = {"state": "ALL", "count": page_size}
        response = self._client.request(
            "GET", self._client.account_path("/orders"), params=params
        )
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("orders"), list):
            raise OrderOperationError("protocol_error", "list response is not JSON")
        orders = [
            self._order_state_from_row(row)
            for row in body["orders"]
            if isinstance(row, dict)
        ]
        if status is not None:
            orders = [order for order in orders if order.state == status]
        start = (page - 1) * page_size
        page_orders = orders[start : start + page_size]
        return OrderListResult(
            orders=tuple(page_orders),
            page=page,
            has_more=(start + page_size) < len(orders),
            request_id=request_id or f"list-{page}",
        )

    def cancel_order(
        self,
        broker_order_id: str,
        *,
        request_id: str | None = None,
    ) -> OrderCancelResult:
        """Cancel a pending order; non-pending orders fail closed."""
        current = self.get_order(broker_order_id)
        if current.state not in _MUTABLE_STATES:
            raise OrderOperationError(
                "order_state_invalid",
                f"order {broker_order_id} is {current.state} and cannot be cancelled",
            )
        self._client.request(
            "PUT", self._client.account_path(f"/orders/{_path(broker_order_id)}/cancel")
        )
        return OrderCancelResult(
            broker_order_id=broker_order_id,
            cancelled=True,
            request_id=request_id or f"cancel-{broker_order_id}",
        )

    def replace_order(
        self,
        broker_order_id: str,
        request: OandaOrderRequest,
        instrument: InstrumentMetadata,
        *,
        request_id: str | None = None,
    ) -> OrderReplaceResult:
        """Replace a pending order; stale or non-pending orders fail closed.

        The order state is re-checked immediately before the replace so
        a race (state changed between read and write) fails closed
        instead of replacing a filled or cancelled order.
        """
        current = self.get_order(broker_order_id)
        if current.state not in _MUTABLE_STATES:
            raise OrderOperationError(
                "order_state_invalid",
                f"order {broker_order_id} is {current.state} and cannot be replaced",
            )
        payload = serialize_order(request, instrument)
        response = self._client.request(
            "PUT",
            self._client.account_path(f"/orders/{_path(broker_order_id)}"),
            json_body={"order": payload},
        )
        body = response.json_body
        if not isinstance(body, dict):
            raise OrderOperationError("protocol_error", "replace response is not JSON")
        tx = body.get("orderReplaceTransaction") or body.get("orderCreateTransaction")
        if not isinstance(tx, dict) or not isinstance(tx.get("id"), str):
            raise OrderOperationError(
                "protocol_error", "replace response missing transaction"
            )
        return OrderReplaceResult(
            broker_order_id=str(tx["id"]),
            client_order_id=current.client_order_id or "",
            state="PENDING",
            request_id=request_id or f"replace-{broker_order_id}",
        )

    def _order_state_from_row(self, row: dict[str, Any]) -> OrderStateResult:
        try:
            return OrderStateResult(
                broker_order_id=str(row.get("id", "")).strip(),
                client_order_id=_client_extensions_id(row),
                symbol=str(row.get("instrument", "")).strip(),
                state=_parse_state(str(row.get("state", ""))),
                units=Decimal(str(row.get("units", "0"))),
                price=(
                    Decimal(str(row["price"]))
                    if row.get("price") not in (None, "")
                    else None
                ),
                submitted_at=_parse_time(row.get("createTime")),
                request_id=f"list-row-{row.get('id', '')}",
            )
        except (KeyError, ValueError) as exc:
            raise OrderOperationError(
                "protocol_error", f"row parse failed: {exc}"
            ) from exc


_ORDER_STATES = frozenset(
    {"PENDING", "FILLED", "TRIGGERED", "CANCELLED", "REJECTED", "EXPIRED"}
)


def _parse_state(raw: str) -> OrderStateValue:
    normalized = raw.strip().upper()
    if normalized not in _ORDER_STATES:
        raise OrderOperationError("protocol_error", f"unknown order state {raw!r}")
    return normalized  # type: ignore[return-value]


def _client_extensions_id(order: dict[str, Any]) -> str | None:
    extensions = order.get("clientExtensions")
    if isinstance(extensions, dict):
        value = str(extensions.get("id", "")).strip()
        if value:
            return value
    return None


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _path(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


__all__ = [
    "OrderCancelResult",
    "OrderCreateResult",
    "OrderListResult",
    "OrderOperationError",
    "OrderOpsClient",
    "OrderReplaceResult",
    "OrderStateResult",
    "OrderStateValue",
]
