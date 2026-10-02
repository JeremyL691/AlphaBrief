"""OANDA Paper broker adapter.

Maps the broker-neutral :mod:`alphabrief_execution.broker.port` to
the OANDA v20 REST API.

Order path: every submit is serialized by
:mod:`alphabrief_execution.broker.oanda.orders` (signed integer units, no
``side`` field, ``stopLossOnFill`` / ``takeProfitOnFill``) and sent by
:mod:`alphabrief_execution.broker.oanda.order_ops`, so precision
normalization and payload shape come from one implementation.

Idempotency contract: a submit that re-uses an existing
``client_order_id`` returns the previously issued ``broker_order_id``
without creating a duplicate order. The mapping is kept in-memory for
the life of the adapter and flushed to the durable recon store by the
runtime. ``clientExtensions`` carries ``id`` (the idempotency key),
``tag=alphabrief`` and the originating cycle id as ``comment``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from alphabrief_execution.broker.errors import BrokerProtocolError, BrokerRejectError
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.instruments import (
    InstrumentMetadata,
    fetch_instruments,
)
from alphabrief_execution.broker.oanda.order_ops import (
    OrderOperationError,
    OrderOpsClient,
)
from alphabrief_execution.broker.oanda.orders import (
    DependentOrder,
    OandaOrderRequest,
    OandaOrderType,
    OandaTimeInForce,
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

_TYPE_MAP: dict[BrokerOrderType, OandaOrderType] = {
    BrokerOrderType.MARKET: "MARKET",
    BrokerOrderType.LIMIT: "LIMIT",
}

_TIF_MAP: dict[BrokerTimeInForce, OandaTimeInForce] = {
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
        self._instruments: dict[str, InstrumentMetadata] = {}

    # ------------------------------------------------------------------
    # Idempotency helpers
    # ------------------------------------------------------------------

    @property
    def client(self) -> OandaHttpClient:
        """The underlying practice HTTP client (read-only accessor)."""
        return self._client

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

        instrument = self.instrument_metadata(request.symbol)
        units = (
            request.quantity
            if request.side == BrokerOrderSide.BUY
            else -request.quantity
        )
        order_request = OandaOrderRequest(
            type=_TYPE_MAP[request.order_type],
            instrument=request.symbol,
            units=units,
            time_in_force=_time_in_force_for(request),
            price=request.limit_price,
            position_fill="REDUCE_ONLY" if request.reduce_only else "DEFAULT",
            stop_loss=(
                DependentOrder(kind="stop_loss", price=request.stop_loss)
                if request.stop_loss is not None
                else None
            ),
            take_profit=(
                DependentOrder(kind="take_profit", price=request.take_profit)
                if request.take_profit is not None
                else None
            ),
        )
        try:
            created = OrderOpsClient(self._client).create_order(
                order_request,
                instrument,
                client_order_id=client_order_id,
                tag=ORDER_TAG,
                comment=request.cycle_id,
            )
        except OrderOperationError as exc:
            raise BrokerRejectError(f"oanda rejected the order: {exc}") from exc

        self._client_to_broker[client_order_id] = created.broker_order_id
        return SubmitResult(
            broker_order_id=created.broker_order_id,
            client_order_id=client_order_id,
            status=(
                BrokerOrderStatus.FILLED
                if created.state == "FILLED"
                else BrokerOrderStatus.NEW
            ),
            accepted_at=self._clock.now(UTC),
        )

    # ------------------------------------------------------------------
    # Instrument metadata
    # ------------------------------------------------------------------

    def instrument_metadata(self, symbol: str) -> InstrumentMetadata:
        """Return the account's metadata for ``symbol`` (fail closed).

        Precision and minimum size come from the account's own catalog,
        never from the symbol's spelling. An unknown or unclassified
        instrument can therefore never be ordered.
        """
        if symbol in self._instruments:
            return self._instruments[symbol]
        catalog = fetch_instruments(self._client, account_id=self._client.account_id)
        for instrument in catalog.instruments:
            self._instruments[instrument.name] = instrument
        if symbol not in self._instruments:
            raise BrokerRejectError(
                f"{symbol} is not in the account's instrument catalog"
            )
        return self._instruments[symbol]

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


#: Tag written into every order's ``clientExtensions``.
ORDER_TAG = "alphabrief"


def _time_in_force_for(request: SubmitRequest) -> OandaTimeInForce:
    """Return the OANDA time-in-force for one submit.

    Market orders are Fill-or-Kill (PROJECT_GUIDE 5.8) so a partially
    filled market order can never rest on the book unnoticed; resting
    limit orders keep the caller's explicit time-in-force. The
    broker-neutral ``DAY`` default is never silently remapped: market
    orders are FOK by design and limit orders must say what they want.
    """
    if request.order_type == BrokerOrderType.MARKET:
        return "FOK"
    if request.time_in_force == BrokerTimeInForce.DAY:
        raise BrokerRejectError(
            "resting limit orders require an explicit GTC/IOC/FOK time in force"
        )
    return _TIF_MAP[request.time_in_force]


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
