"""Alpaca Paper broker adapter.

Maps the broker-neutral :mod:`alphabrief_execution.broker.port` to
the Alpaca Paper REST API.

Idempotency contract: a submit that re-uses an existing
``client_order_id`` returns the previously issued
``broker_order_id`` without creating a duplicate order. The mapping
is kept in-memory for the life of the adapter. Cross-restart
durability is provided by ``BrokerReconStore`` (see
``alphabrief_execution.broker.reconciliation``); reload the
mapping from the store before the first submit after restart.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from alphabrief_execution.broker.alpaca.client import AlpacaHttpClient
from alphabrief_execution.broker.errors import (
    BrokerProtocolError,
    BrokerRejectError,
)
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
# Status mapping
# ---------------------------------------------------------------------------

_STATUS_MAP: dict[str, BrokerOrderStatus] = {
    "new": BrokerOrderStatus.NEW,
    "partially_filled": BrokerOrderStatus.PARTIALLY_FILLED,
    "filled": BrokerOrderStatus.FILLED,
    "canceled": BrokerOrderStatus.CANCELLED,
    "cancelled": BrokerOrderStatus.CANCELLED,
    "rejected": BrokerOrderStatus.REJECTED,
    "expired": BrokerOrderStatus.EXPIRED,
    "pending_cancel": BrokerOrderStatus.PENDING_CANCEL,
    "accepted": BrokerOrderStatus.NEW,
    "pending_new": BrokerOrderStatus.NEW,
}


_SIDE_MAP: dict[BrokerOrderSide, str] = {
    BrokerOrderSide.BUY: "buy",
    BrokerOrderSide.SELL: "sell",
}


_TYPE_MAP: dict[BrokerOrderType, str] = {
    BrokerOrderType.MARKET: "market",
    BrokerOrderType.LIMIT: "limit",
}


_TIF_MAP: dict[BrokerTimeInForce, str] = {
    BrokerTimeInForce.DAY: "day",
    BrokerTimeInForce.GTC: "gtc",
    BrokerTimeInForce.IOC: "ioc",
    BrokerTimeInForce.FOK: "fok",
}


def _to_broker_status(raw: str) -> BrokerOrderStatus:
    normalized = raw.strip().lower()
    if normalized not in _STATUS_MAP:
        raise BrokerProtocolError(f"alpaca returned unknown order status: {raw!r}")
    return _STATUS_MAP[normalized]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class AlpacaPaperAdapter(BrokerAdapter):
    """Adapter for the Alpaca Paper REST API.

    Submit / cancel / list / get / fills / positions / account
    operations are mapped to the Alpaca Paper endpoints.

    The adapter does NOT implement reconciliation, freeze, or
    scheduling. Those live in higher-level components.
    """

    def __init__(
        self,
        *,
        client: AlpacaHttpClient,
        known_client_order_ids: dict[str, str] | None = None,
        clock: type[datetime] | None = None,  # injected for tests
    ) -> None:
        self._client = client
        self._client_to_broker: dict[str, str] = dict(known_client_order_ids or {})
        # default to datetime; tests pass a stub
        self._clock = clock or datetime

    # ------------------------------------------------------------------
    # Idempotency helpers
    # ------------------------------------------------------------------

    def register_known_mapping(
        self, *, client_order_id: str, broker_order_id: str
    ) -> None:
        """Seed a client_order_id -> broker_order_id mapping.

        Call this once on startup after loading from the recon store
        so restarts do not produce duplicate orders.
        """
        self._client_to_broker[client_order_id] = broker_order_id

    def known_mappings(self) -> dict[str, str]:
        """Return a copy of the in-memory mapping (for persistence)."""
        return dict(self._client_to_broker)

    # ------------------------------------------------------------------
    # BrokerAdapter implementation
    # ------------------------------------------------------------------

    async def health(self) -> BrokerHealth:
        try:
            response = self._client.request("GET", "/v2/account")
        except Exception as exc:  # noqa: BLE001 — health is best-effort
            return BrokerHealth(
                healthy=False,
                detail=f"alpaca health probe failed: {exc}",
                checked_at=self._clock.now(UTC),
            )
        body = response.json_body
        if not isinstance(body, dict):
            return BrokerHealth(
                healthy=False,
                detail="alpaca health response was not a JSON object",
                checked_at=self._clock.now(UTC),
            )
        return BrokerHealth(
            healthy=True,
            detail=str(body.get("status", "unknown")),
            checked_at=self._clock.now(UTC),
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
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

        payload: dict[str, Any] = {
            "symbol": request.symbol,
            "qty": _decimal_to_alpaca_qty(request.quantity),
            "side": _SIDE_MAP[request.side],
            "type": _TYPE_MAP[request.order_type],
            "time_in_force": _TIF_MAP[request.time_in_force],
            "client_order_id": client_order_id,
        }
        if request.limit_price is not None:
            payload["limit_price"] = _decimal_to_alpaca_price(request.limit_price)

        try:
            response = self._client.request("POST", "/v2/orders", json_body=payload)
        except BrokerRejectError as exc:
            raise BrokerRejectError(exc.reason, broker_code=exc.broker_code) from exc

        body = response.json_body
        if not isinstance(body, dict):
            raise BrokerProtocolError("alpaca submit response was not a JSON object")
        broker_order_id = str(body.get("id", "")).strip()
        if not broker_order_id:
            raise BrokerProtocolError("alpaca submit response missing 'id'")
        self._client_to_broker[client_order_id] = broker_order_id
        return SubmitResult(
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
            status=_to_broker_status(str(body.get("status", "new"))),
            accepted_at=_parse_alpaca_timestamp(body.get("submitted_at")),
        )

    async def cancel(self, broker_order_id: str) -> CancelResult:
        if not broker_order_id.strip():
            raise BrokerProtocolError("cancel requires a non-empty broker_order_id")
        self._client.request("DELETE", f"/v2/orders/{broker_order_id}")
        current = await self.get_order(broker_order_id)
        return CancelResult(
            broker_order_id=broker_order_id,
            status=current.status,
            cancelled_at=current.updated_at,
        )

    async def get_order(self, broker_order_id: str) -> OrderState:
        response = self._client.request("GET", f"/v2/orders/{broker_order_id}")
        return _parse_order_state(response.json_body)

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        params: dict[str, Any] = {"status": "all"}
        if status is not None:
            params["status"] = _status_to_alpaca_filter(status)
        response = self._client.request("GET", "/v2/orders", params=params)
        body = response.json_body
        if not isinstance(body, list):
            raise BrokerProtocolError(
                "alpaca list_orders response was not a JSON array"
            )
        return [_parse_order_state(item) for item in body if isinstance(item, dict)]

    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        params: dict[str, Any] = {}
        if since is not None:
            params["after"] = _alpaca_isoformat(since)
        response = self._client.request(
            "GET", "/v2/account/activities/FILL", params=params
        )
        body = response.json_body
        if body is None:
            return []
        if not isinstance(body, list):
            raise BrokerProtocolError("alpaca list_fills response was not a JSON array")
        fills: list[Fill] = []
        for item in body:
            if not isinstance(item, dict):
                continue
            try:
                fills.append(_parse_fill(item))
            except (BrokerProtocolError, ValidationError) as exc:
                _LOGGER.warning("alpaca fill parse skipped: %s", exc)
        return fills

    async def get_positions(self) -> list[Position]:
        response = self._client.request("GET", "/v2/positions")
        body = response.json_body
        if body is None:
            return []
        if not isinstance(body, list):
            raise BrokerProtocolError(
                "alpaca get_positions response was not a JSON array"
            )
        positions: list[Position] = []
        for item in body:
            if not isinstance(item, dict):
                continue
            try:
                positions.append(_parse_position(item))
            except (BrokerProtocolError, ValidationError) as exc:
                _LOGGER.warning("alpaca position parse skipped: %s", exc)
        return positions

    async def get_account(self) -> AccountSnapshot:
        response = self._client.request("GET", "/v2/account")
        body = response.json_body
        if not isinstance(body, dict):
            raise BrokerProtocolError(
                "alpaca get_account response was not a JSON object"
            )
        return _parse_account(body)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_order_state(body: Any) -> OrderState:
    if not isinstance(body, dict):
        raise BrokerProtocolError("alpaca order payload was not a JSON object")
    try:
        return OrderState(
            broker_order_id=str(body.get("id", "")).strip(),
            client_order_id=str(body.get("client_order_id", "")).strip(),
            symbol=str(body.get("symbol", "")).strip(),
            side=BrokerOrderSide(str(body.get("side", "")).strip().lower()),
            order_type=BrokerOrderType(str(body.get("type", "")).strip().lower()),
            quantity=Decimal(str(body.get("qty", "0"))),
            filled_quantity=Decimal(str(body.get("filled_qty", "0"))),
            limit_price=(
                Decimal(str(body["limit_price"]))
                if body.get("limit_price") not in (None, "")
                else None
            ),
            status=_to_broker_status(str(body.get("status", "new"))),
            submitted_at=_parse_alpaca_timestamp(body.get("submitted_at")),
            updated_at=_parse_alpaca_timestamp(body.get("updated_at")),
        )
    except (KeyError, ValueError, ValidationError) as exc:
        raise BrokerProtocolError(
            f"alpaca order payload could not be parsed: {exc}"
        ) from exc


def _parse_fill(body: dict[str, Any]) -> Fill:
    return Fill(
        fill_id=str(body.get("id", "")).strip(),
        broker_order_id=str(body.get("order_id", "")).strip(),
        symbol=str(body.get("symbol", "")).strip(),
        side=BrokerOrderSide(str(body.get("side", "")).strip().lower()),
        quantity=Decimal(str(body.get("qty", "0"))),
        price=Decimal(str(body.get("price", "0"))),
        fees=Decimal("0"),
        filled_at=_parse_alpaca_timestamp(body.get("transaction_time")),
    )


def _parse_position(body: dict[str, Any]) -> Position:
    return Position(
        symbol=str(body.get("symbol", "")).strip(),
        quantity=Decimal(str(body.get("qty", "0"))),
        average_price=Decimal(str(body.get("avg_entry_price", "0"))),
    )


def _parse_account(body: dict[str, Any]) -> AccountSnapshot:
    return AccountSnapshot(
        account_id=str(body.get("account_number", "")).strip(),
        cash=Decimal(str(body.get("cash", "0"))),
        equity=Decimal(str(body.get("equity", "0"))),
        buying_power=Decimal(str(body.get("buying_power", "0"))),
        currency=str(body.get("currency", "USD")).strip() or "USD",
        captured_at=datetime.now(UTC),
    )


def _parse_alpaca_timestamp(value: Any) -> datetime:
    if value in (None, ""):
        return datetime.now(UTC)
    if not isinstance(value, str):
        raise BrokerProtocolError(
            f"alpaca timestamp must be a string, got {type(value).__name__}"
        )
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BrokerProtocolError(
            f"alpaca timestamp {value!r} is not ISO-8601: {exc}"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _alpaca_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _decimal_to_alpaca_qty(value: Decimal) -> str:
    if value <= 0:
        raise BrokerRejectError("quantity must be positive")
    return str(value)


def _decimal_to_alpaca_price(value: Decimal) -> str:
    if value <= 0:
        raise BrokerRejectError("limit_price must be positive")
    return str(value)


def _status_to_alpaca_filter(status: BrokerOrderStatus) -> str:
    mapping = {
        BrokerOrderStatus.NEW: "open",
        BrokerOrderStatus.PARTIALLY_FILLED: "open",
        BrokerOrderStatus.PENDING_CANCEL: "open",
        BrokerOrderStatus.FILLED: "closed",
        BrokerOrderStatus.CANCELLED: "closed",
        BrokerOrderStatus.REJECTED: "closed",
        BrokerOrderStatus.EXPIRED: "closed",
    }
    return mapping[status]


__all__ = ["AlpacaPaperAdapter"]
