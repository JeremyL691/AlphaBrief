"""OANDA Paper broker adapter.

Maps the broker-neutral :mod:`alphabrief_execution.broker.port` to
the OANDA v20 REST API.

Idempotency contract: a submit that re-uses an existing
``client_order_id`` returns the previously issued ``broker_order_id``
without creating a duplicate order. The mapping is kept in-memory for
the life of the adapter. OANDA ``clientExtensions.id`` is also populated
so broker-side responses can carry the caller's ID when available.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from alphabrief_execution.broker.errors import BrokerProtocolError, BrokerRejectError
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerTimeInForce,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status / field mapping
# ---------------------------------------------------------------------------

_STATUS_MAP: dict[str, BrokerOrderStatus] = {
    "pending": BrokerOrderStatus.NEW,
    "filled": BrokerOrderStatus.FILLED,
    "triggered": BrokerOrderStatus.FILLED,
    "cancelled": BrokerOrderStatus.CANCELLED,
    "canceled": BrokerOrderStatus.CANCELLED,
    "rejected": BrokerOrderStatus.REJECTED,
    "expired": BrokerOrderStatus.EXPIRED,
}

_SIDE_MAP: dict[BrokerOrderSide, str] = {
    BrokerOrderSide.BUY: "buy",
    BrokerOrderSide.SELL: "sell",
}

_TYPE_MAP: dict[BrokerOrderType, str] = {
    BrokerOrderType.MARKET: "MARKET",
    BrokerOrderType.LIMIT: "LIMIT",
}

_TIF_MAP: dict[BrokerTimeInForce, str] = {
    BrokerTimeInForce.GTC: "GTC",
    BrokerTimeInForce.IOC: "IOC",
    BrokerTimeInForce.FOK: "FOK",
}


def _to_broker_status(raw: str) -> BrokerOrderStatus:
    normalized = raw.strip().lower()
    if normalized not in _STATUS_MAP:
        raise BrokerProtocolError(f"oanda returned unknown order status: {raw!r}")
    return _STATUS_MAP[normalized]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class OandaPaperAdapter(BrokerAdapter):
    """Adapter for the OANDA v20 practice REST API.

    Submit / cancel / list / get / fills / positions / account operations
    are mapped to the OANDA account-scoped endpoints.
    """

    def __init__(
        self,
        *,
        client: OandaHttpClient,
        known_client_order_ids: dict[str, str] | None = None,
        clock: type[datetime] | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            client: OANDA HTTP client with credentials and account ID.
            known_client_order_ids: Optional restored idempotency mapping.
            clock: Optional datetime class injected by tests.
        """
        self._client = client
        self._client_to_broker: dict[str, str] = dict(known_client_order_ids or {})
        self._clock = clock or datetime

    # ------------------------------------------------------------------
    # Idempotency helpers
    # ------------------------------------------------------------------

    def register_known_mapping(
        self, *, client_order_id: str, broker_order_id: str
    ) -> None:
        """Seed a client_order_id -> broker_order_id mapping.

        Args:
            client_order_id: AlphaBrief idempotency key.
            broker_order_id: OANDA order ID previously returned for the key.
        """
        self._client_to_broker[client_order_id] = broker_order_id

    def known_mappings(self) -> dict[str, str]:
        """Return a copy of the in-memory mapping for persistence."""
        return dict(self._client_to_broker)

    # ------------------------------------------------------------------
    # BrokerAdapter implementation
    # ------------------------------------------------------------------

    async def health(self) -> BrokerHealth:
        """Probe OANDA account-list access and credential validity."""
        try:
            response = self._client.request("GET", "/v3/accounts")
        except Exception as exc:  # noqa: BLE001 — health is best-effort
            return BrokerHealth(
                healthy=False,
                detail=f"oanda health probe failed: {exc}",
                checked_at=self._clock.now(UTC),
            )
        body = response.json_body
        if not isinstance(body, dict):
            return BrokerHealth(
                healthy=False,
                detail="oanda health response was not a JSON object",
                checked_at=self._clock.now(UTC),
            )
        accounts = body.get("accounts")
        account_count = len(accounts) if isinstance(accounts, list) else "unknown"
        return BrokerHealth(
            healthy=isinstance(accounts, list),
            detail=f"accounts={account_count}",
            checked_at=self._clock.now(UTC),
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        """Submit one OANDA order, idempotent on ``client_order_id``."""
        if request.order_type == BrokerOrderType.LIMIT and request.limit_price is None:
            raise BrokerRejectError("limit orders require a positive limit_price")
        if (
            request.order_type == BrokerOrderType.MARKET
            and request.limit_price is not None
        ):
            raise BrokerRejectError("market orders must not include a limit_price")

        existing = self._client_to_broker.get(client_order_id)
        if existing is not None:
            current = await self.get_order(existing)
            return SubmitResult(
                broker_order_id=current.broker_order_id,
                client_order_id=client_order_id,
                status=current.status,
                accepted_at=current.submitted_at,
            )

        order: dict[str, Any] = {
            "type": _TYPE_MAP[request.order_type],
            "instrument": request.symbol,
            "units": _decimal_to_oanda_units(request.quantity),
            "side": _SIDE_MAP[request.side],
            "timeInForce": _time_in_force_to_oanda(
                request.time_in_force, request.order_type
            ),
            "clientExtensions": {"id": client_order_id},
        }
        if request.limit_price is not None:
            order["price"] = _decimal_to_oanda_price(request.limit_price)

        try:
            response = self._client.request(
                "POST", self._client.account_path("/orders"), json_body={"order": order}
            )
        except BrokerRejectError as exc:
            raise BrokerRejectError(exc.reason, broker_code=exc.broker_code) from exc

        body = response.json_body
        if not isinstance(body, dict):
            raise BrokerProtocolError("oanda submit response was not a JSON object")
        create_tx = body.get("orderCreateTransaction")
        if not isinstance(create_tx, dict):
            raise BrokerProtocolError(
                "oanda submit response missing 'orderCreateTransaction'"
            )
        fill_tx = body.get("orderFillTransaction")
        broker_order_id = _submit_broker_order_id(create_tx, fill_tx)
        self._client_to_broker[client_order_id] = broker_order_id
        return SubmitResult(
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
            status=(
                BrokerOrderStatus.FILLED
                if isinstance(fill_tx, dict)
                else BrokerOrderStatus.NEW
            ),
            accepted_at=_parse_oanda_timestamp(create_tx.get("time")),
        )

    async def cancel(self, broker_order_id: str) -> CancelResult:
        """Cancel one pending OANDA order."""
        if not broker_order_id.strip():
            raise BrokerProtocolError("cancel requires a non-empty broker_order_id")
        response = self._client.request(
            "PUT",
            self._client.account_path(f"/orders/{_path_part(broker_order_id)}/cancel"),
        )
        body = response.json_body
        cancelled_at: datetime | None = None
        if isinstance(body, dict):
            tx = body.get("orderCancelTransaction")
            if isinstance(tx, dict):
                cancelled_at = _parse_oanda_timestamp(tx.get("time"))
        return CancelResult(
            broker_order_id=broker_order_id,
            status=BrokerOrderStatus.CANCELLED,
            cancelled_at=cancelled_at,
        )

    async def get_order(self, broker_order_id: str) -> OrderState:
        """Fetch the current state of a single OANDA order."""
        response = self._client.request(
            "GET", self._client.account_path(f"/orders/{_path_part(broker_order_id)}")
        )
        body = response.json_body
        if not isinstance(body, dict):
            raise BrokerProtocolError("oanda get_order response was not a JSON object")
        return _parse_order_state(body.get("order"))

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        """List OANDA orders, optionally filtered by broker-neutral status."""
        response = self._client.request(
            "GET", self._client.account_path("/orders"), params={"state": "ALL"}
        )
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("orders"), list):
            raise BrokerProtocolError(
                "oanda list_orders response missing JSON array 'orders'"
            )
        orders = [
            _parse_order_state(item)
            for item in body["orders"]
            if isinstance(item, dict)
        ]
        if status is None:
            return orders
        return [order for order in orders if order.status == status]

    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        """List OANDA order-fill transactions since ``since`` when provided.

        OANDA's ``/transactions`` endpoint returns a paginated response
        without the actual transaction objects.  We call it first to get
        the ``lastTransactionID``, then fetch the actual transactions
        via ``/transactions/idrange`` which returns a JSON array under
        the ``transactions`` key.
        """
        # Step 1: get the latest transaction ID
        meta_params: dict[str, Any] = {"type": "ORDER_FILL", "count": 1}
        if since is not None:
            meta_params["from"] = _oanda_isoformat(since)
        meta_resp = self._client.request(
            "GET", self._client.account_path("/transactions"),
            params=meta_params,
        )
        meta_body = meta_resp.json_body
        if not isinstance(meta_body, dict):
            raise BrokerProtocolError(
                "oanda list_fills first response was not a JSON object"
            )
        last_id = meta_body.get("lastTransactionID")
        if not last_id:
            return []

        # Step 2: fetch the actual fill transactions by ID range
        idrange_params: dict[str, Any] = {
            "from": "1",
            "to": str(last_id),
            "type": "ORDER_FILL",
        }
        if since is not None:
            idrange_params["from"] = _oanda_isoformat(since)
        response = self._client.request(
            "GET", self._client.account_path("/transactions/idrange"),
            params=idrange_params,
        )
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("transactions"), list):
            return []
        fills: list[Fill] = []
        for item in body["transactions"]:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "ORDER_FILL":
                continue
            try:
                fills.append(_parse_fill(item))
            except (BrokerProtocolError, ValidationError) as exc:
                _LOGGER.warning("oanda fill parse skipped: %s", exc)
        return fills

    async def get_positions(self) -> list[Position]:
        """Return all currently open OANDA positions."""
        response = self._client.request(
            "GET", self._client.account_path("/openPositions")
        )
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("positions"), list):
            raise BrokerProtocolError(
                "oanda get_positions response missing JSON array 'positions'"
            )
        positions: list[Position] = []
        for item in body["positions"]:
            if not isinstance(item, dict):
                continue
            try:
                positions.extend(_parse_positions(item))
            except (BrokerProtocolError, ValidationError) as exc:
                _LOGGER.warning("oanda position parse skipped: %s", exc)
        return positions

    async def get_account(self) -> AccountSnapshot:
        """Return the current OANDA account cash/equity snapshot."""
        response = self._client.request("GET", self._client.account_path())
        body = response.json_body
        if not isinstance(body, dict):
            raise BrokerProtocolError(
                "oanda get_account response was not a JSON object"
            )
        return _parse_account(body.get("account"))


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_order_state(body: Any) -> OrderState:
    if not isinstance(body, dict):
        raise BrokerProtocolError("oanda order payload was not a JSON object")
    try:
        units = Decimal(str(body.get("units", "0")))
        client_order_id = _client_order_id(body)
        return OrderState(
            broker_order_id=str(body.get("id", "")).strip(),
            client_order_id=client_order_id,
            symbol=str(body.get("instrument", "")).strip(),
            side=_side_from_units(units),
            order_type=_parse_order_type(str(body.get("type", ""))),
            quantity=abs(units),
            filled_quantity=_filled_quantity(body, units),
            limit_price=(
                Decimal(str(body["price"]))
                if body.get("price") not in (None, "")
                else None
            ),
            status=_to_broker_status(str(body.get("state", "PENDING"))),
            submitted_at=_parse_oanda_timestamp(body.get("createTime")),
            updated_at=_parse_oanda_timestamp(
                body.get("filledTime")
                or body.get("cancelledTime")
                or body.get("createTime")
            ),
        )
    except (KeyError, ValueError, ValidationError) as exc:
        raise BrokerProtocolError(
            f"oanda order payload could not be parsed: {exc}"
        ) from exc


def _parse_fill(body: dict[str, Any]) -> Fill:
    units = Decimal(str(body.get("units", "0")))
    return Fill(
        fill_id=str(body.get("id", "")).strip(),
        broker_order_id=str(
            body.get("orderID") or body.get("tradeID") or body.get("id", "")
        ).strip(),
        symbol=str(body.get("instrument", "")).strip(),
        side=_side_from_units(units),
        quantity=abs(units),
        price=Decimal(str(body.get("price", "0"))),
        fees=Decimal("0"),
        filled_at=_parse_oanda_timestamp(body.get("time")),
    )


def _parse_positions(body: dict[str, Any]) -> list[Position]:
    symbol = str(body.get("instrument", "")).strip()
    if not symbol:
        raise BrokerProtocolError("oanda position missing instrument")
    parsed: list[Position] = []
    for side_key in ("long", "short"):
        side = body.get(side_key)
        if not isinstance(side, dict):
            continue
        units = Decimal(str(side.get("units", "0")))
        if units == 0:
            continue
        parsed.append(
            Position(
                symbol=symbol,
                quantity=units,
                average_price=Decimal(str(side.get("averagePrice", "0"))),
            )
        )
    return parsed


def _parse_account(body: Any) -> AccountSnapshot:
    if not isinstance(body, dict):
        raise BrokerProtocolError("oanda account payload was not a JSON object")
    return AccountSnapshot(
        account_id=str(body.get("id", "")).strip(),
        cash=Decimal(str(body.get("balance", "0"))),
        equity=Decimal(str(body.get("NAV", body.get("balance", "0")))),
        buying_power=Decimal(str(body.get("marginAvailable", "0"))),
        currency=str(body.get("currency", "USD")).strip() or "USD",
        captured_at=datetime.now(UTC),
    )


def _parse_oanda_timestamp(value: Any) -> datetime:
    if value in (None, ""):
        return datetime.now(UTC)
    if not isinstance(value, str):
        raise BrokerProtocolError(
            f"oanda timestamp must be a string, got {type(value).__name__}"
        )
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "." in text:
        head, tail = text.split(".", 1)
        offset = ""
        for marker in ("+", "-"):
            if marker in tail:
                fraction, offset = tail.split(marker, 1)
                offset = marker + offset
                break
        else:
            fraction = tail
        text = f"{head}.{fraction[:6].ljust(6, '0')}{offset}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BrokerProtocolError(
            f"oanda timestamp {value!r} is not ISO-8601: {exc}"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _oanda_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal_to_oanda_units(value: Decimal) -> str:
    if value <= 0:
        raise BrokerRejectError("quantity must be positive")
    if value != value.to_integral_value():
        raise BrokerRejectError("oanda quantity must be a whole number of units")
    return str(value.quantize(Decimal("1")))


def _decimal_to_oanda_price(value: Decimal) -> str:
    if value <= 0:
        raise BrokerRejectError("limit_price must be positive")
    return str(value)


def _time_in_force_to_oanda(
    value: BrokerTimeInForce, order_type: BrokerOrderType
) -> str:
    if value == BrokerTimeInForce.DAY:
        # ponytail: OANDA has no DAY in the requested v20 subset; use the
        # nearest default (FOK for market orders, GTC for resting limit orders).
        return "FOK" if order_type == BrokerOrderType.MARKET else "GTC"
    return _TIF_MAP[value]


def _submit_broker_order_id(create_tx: dict[str, Any], fill_tx: Any) -> str:
    if isinstance(fill_tx, dict):
        broker_order_id = str(fill_tx.get("orderID", "")).strip()
        if broker_order_id:
            return broker_order_id
    broker_order_id = str(create_tx.get("id", "")).strip()
    if not broker_order_id:
        raise BrokerProtocolError("oanda submit response missing order id")
    return broker_order_id


def _client_order_id(body: dict[str, Any]) -> str:
    extensions = body.get("clientExtensions")
    if isinstance(extensions, dict):
        client_order_id = str(extensions.get("id", "")).strip()
        if client_order_id:
            return client_order_id
    return str(body.get("id", "")).strip()


def _parse_order_type(raw: str) -> BrokerOrderType:
    normalized = raw.strip().lower()
    if normalized.endswith("_order"):
        normalized = normalized[: -len("_order")]
    return BrokerOrderType(normalized)


def _filled_quantity(body: dict[str, Any], units: Decimal) -> Decimal:
    if body.get("state") in ("FILLED", "TRIGGERED") or body.get("fillingTransactionID"):
        return abs(units)
    return Decimal("0")


def _side_from_units(units: Decimal) -> BrokerOrderSide:
    return BrokerOrderSide.SELL if units < 0 else BrokerOrderSide.BUY


def _path_part(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


__all__ = ["OandaPaperAdapter"]
