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
    #: ``clientExtensions.tag`` as reported by the broker; ``alphabrief``
    #: marks an order as this system's own (reconciliation evidence).
    client_tag: str | None = None
    #: ``None`` for dependent orders (stop loss / take profit), which the
    #: broker reports against their trade rather than an instrument.
    symbol: str | None = None
    state: OrderStateValue
    #: Zero for dependent orders: they close the parent trade instead of
    #: carrying units of their own.
    units: Decimal = Decimal("0")
    #: The trade a dependent order belongs to, when the broker reports one.
    trade_id: str | None = None
    reduce_only: bool = False
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
        tag: str | None = None,
        comment: str | None = None,
    ) -> OrderCreateResult:
        """Create one order; idempotent on ``client_order_id``.

        Retries with the same ``client_order_id`` return the prior
        result instead of duplicating the order. ``tag`` and ``comment``
        land in ``clientExtensions`` so reconciliation can recognise this
        system's orders and trace them back to a committee round.
        """
        if not client_order_id.strip():
            raise OrderOperationError("invalid_request_id", "client_order_id is empty")
        existing = self._created.get(client_order_id)
        if existing is not None:
            return existing.model_copy(update={"reused": True})

        payload = serialize_order(request, instrument)
        extensions: dict[str, str] = {"id": client_order_id}
        if tag is not None:
            extensions["tag"] = tag
        if comment is not None:
            extensions["comment"] = comment
        payload["clientExtensions"] = extensions
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
        if not isinstance(create_tx, dict) or not isinstance(create_tx.get("id"), str):
            raise OrderOperationError(
                "protocol_error", "create response missing transaction"
            )
        broker_order_id = str(create_tx["id"])
        state: OrderStateValue = "FILLED" if isinstance(fill_tx, dict) else "PENDING"
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
                client_tag=_client_extensions_tag(order),
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

    def list_pending_orders(self, *, request_id: str | None = None) -> OrderListResult:
        """Read the complete pending snapshot, never a truncated historical page."""
        response = self._client.request(
            "GET",
            self._client.account_path("/pendingOrders"),
        )
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("orders"), list):
            raise OrderOperationError("protocol_error", "pending orders missing")
        orders: list[OrderStateResult] = []
        seen: set[str] = set()
        dependent_types = {
            "STOP_LOSS",
            "TAKE_PROFIT",
            "TRAILING_STOP_LOSS",
            "GUARANTEED_STOP_LOSS",
        }
        for row in body["orders"]:
            if not isinstance(row, dict) or row.get("state") != "PENDING":
                raise OrderOperationError("protocol_error", "invalid pending order row")
            if row.get("instrument"):
                if row.get("type") not in {
                    "MARKET",
                    "LIMIT",
                    "STOP",
                    "MARKET_IF_TOUCHED",
                }:
                    raise OrderOperationError(
                        "protocol_error", "unknown pending entry type"
                    )
                if row["type"] != "MARKET" and row.get("price") is None:
                    raise OrderOperationError(
                        "protocol_error", "pending entry price missing"
                    )
                raw = row.get("units")
                if raw is None or isinstance(raw, (float, bool)):
                    raise OrderOperationError(
                        "protocol_error", "pending units missing or invalid"
                    )
                try:
                    units = Decimal(str(raw))
                    if not units.is_finite() or units == 0:
                        raise ValueError("invalid units")
                except (ValueError, ArithmeticError) as exc:
                    raise OrderOperationError(
                        "protocol_error", "invalid pending units"
                    ) from exc
            elif row.get("type") not in dependent_types or not row.get("tradeID"):
                raise OrderOperationError(
                    "protocol_error", "unidentified pending order"
                )
            if isinstance(row.get("price"), (float, bool)):
                raise OrderOperationError("protocol_error", "invalid pending price")
            try:
                order = self._order_state_from_row(row)
            except (ValueError, ArithmeticError) as exc:
                raise OrderOperationError(
                    "protocol_error", "invalid pending order"
                ) from exc
            if order.price is not None and (
                not order.price.is_finite() or order.price <= 0
            ):
                raise OrderOperationError("protocol_error", "invalid pending price")
            if order.broker_order_id in seen:
                raise OrderOperationError("protocol_error", "duplicate pending order")
            seen.add(order.broker_order_id)
            orders.append(order)
        return OrderListResult(
            orders=tuple(orders),
            page=1,
            has_more=False,
            request_id=request_id or "pending-orders",
        )

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
                client_tag=_client_extensions_tag(row),
                symbol=str(row.get("instrument") or "").strip() or None,
                state=_parse_state(str(row.get("state", ""))),
                units=Decimal(str(row.get("units") or "0")),
                trade_id=str(row.get("tradeID") or "").strip() or None,
                reduce_only=row.get("positionFill") == "REDUCE_ONLY",
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


def _client_extensions_tag(order: dict[str, Any]) -> str | None:
    """Return ``clientExtensions.tag`` when the broker reports one."""
    extensions = order.get("clientExtensions")
    if isinstance(extensions, dict):
        tag = str(extensions.get("tag", "")).strip()
        if tag:
            return tag
    return None


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
