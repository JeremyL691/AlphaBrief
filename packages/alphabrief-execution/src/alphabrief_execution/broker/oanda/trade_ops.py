"""OANDA trade operations port (M06-W04).

Get, list, partial close, full close, and protective dependent-order
operations for trades with exact typed responses, request correlation on
every result, and fail-closed semantics: missing, stale, already closed,
account-mismatched, over-close, and unsupported requests raise classified
errors and never mutate local state or fabricate a fill.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.errors import BrokerNotFoundError
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata

TradeStateValue = Literal["OPEN", "CLOSED", "CLOSE_WHEN_TRADABLE"]

#: States in which a trade may still be closed or modified.
_OPEN_STATES = frozenset({"OPEN", "CLOSE_WHEN_TRADABLE"})


class TradeOperationError(RuntimeError):
    """A classified trade operation failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        super().__init__(f"trade operation failed ({kind}): {detail}")


class TradeStateResult(BaseModel):
    """One typed trade state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_trade_id: str = Field(min_length=1)
    client_order_id: str | None = None
    instrument: str = Field(min_length=1)
    state: TradeStateValue
    current_units: Decimal
    initial_units: Decimal
    realized_pl: Decimal
    unrealized_pl: Decimal
    financing: Decimal
    open_time: datetime | None = None
    close_time: datetime | None = None
    request_id: str = Field(min_length=1)


class TradeListResult(BaseModel):
    """One typed, paginated trade page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trades: tuple[TradeStateResult, ...]
    page: int = Field(ge=1)
    has_more: bool
    request_id: str = Field(min_length=1)


class TradeCloseResult(BaseModel):
    """One typed close result with distinct broker transaction IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_trade_id: str = Field(min_length=1)
    closed_units: Decimal
    realized_pl: Decimal
    financing: Decimal
    order_create_transaction_id: str
    order_fill_transaction_id: str | None = None
    trade_close_transaction_id: str | None = None
    request_id: str = Field(min_length=1)


class TradeDependentResult(BaseModel):
    """One typed protective dependent-order result on a trade."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_trade_id: str = Field(min_length=1)
    dependent_order_id: str = Field(min_length=1)
    dependent_type: str = Field(min_length=1)
    request_id: str = Field(min_length=1)


class TradeOpsClient:
    """Trade command and query port over the OANDA practice client."""

    def __init__(self, client: OandaHttpClient) -> None:
        self._client = client

    def get_trade(
        self,
        broker_trade_id: str,
        *,
        request_id: str | None = None,
    ) -> TradeStateResult:
        """Fetch one typed trade state; unknown trades fail closed."""
        if not broker_trade_id.strip():
            raise TradeOperationError("invalid_request_id", "broker_trade_id is empty")
        try:
            response = self._client.request(
                "GET", self._client.account_path(f"/trades/{_path(broker_trade_id)}")
            )
        except BrokerNotFoundError as exc:
            raise TradeOperationError("unknown_trade", broker_trade_id) from exc
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("trade"), dict):
            raise TradeOperationError("protocol_error", "get response is not JSON")
        try:
            return _trade_state_from_row(
                body["trade"],
                request_id=request_id or f"get-{broker_trade_id}",
            )
        except (KeyError, ValueError) as exc:
            raise TradeOperationError(
                "protocol_error", f"trade parse failed: {exc}"
            ) from exc

    def list_trades(
        self,
        *,
        state: TradeStateValue | None = None,
        page: int = 1,
        page_size: int = 50,
        request_id: str | None = None,
    ) -> TradeListResult:
        """List trades with deterministic bounded pagination."""
        response = self._client.request(
            "GET",
            self._client.account_path("/trades"),
            params={"state": "ALL", "count": page_size},
        )
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("trades"), list):
            raise TradeOperationError("protocol_error", "list response is not JSON")
        trades = [
            _trade_state_from_row(row, request_id=f"list-row-{row.get('id', '')}")
            for row in body["trades"]
            if isinstance(row, dict)
        ]
        if state is not None:
            trades = [trade for trade in trades if trade.state == state]
        start = (page - 1) * page_size
        page_trades = trades[start : start + page_size]
        return TradeListResult(
            trades=tuple(page_trades),
            page=page,
            has_more=(start + page_size) < len(trades),
            request_id=request_id or f"list-{page}",
        )

    def close_trade(
        self,
        broker_trade_id: str,
        *,
        units: Decimal | None = None,
        request_id: str | None = None,
    ) -> TradeCloseResult:
        """Close a trade; ``units=None`` closes all open units.

        Partial close requires positive units that do not exceed the open
        units. The trade state is re-checked immediately before the close
        so a race (already closed between read and write) fails closed.
        """
        current = self.get_trade(broker_trade_id)
        if current.state not in _OPEN_STATES:
            raise TradeOperationError(
                "trade_state_invalid",
                f"trade {broker_trade_id} is {current.state} and cannot be closed",
            )
        if units is not None:
            if units <= 0:
                raise TradeOperationError(
                    "invalid_units", "close units must be positive"
                )
            if units > abs(current.current_units):
                raise TradeOperationError(
                    "over_close",
                    f"close {units} exceeds open units {abs(current.current_units)}",
                )
        body: dict[str, Any] = {}
        if units is not None:
            body["units"] = str(units)
        response = self._client.request(
            "PUT",
            self._client.account_path(f"/trades/{_path(broker_trade_id)}/close"),
            json_body=body,
        )
        payload = response.json_body
        if not isinstance(payload, dict):
            raise TradeOperationError("protocol_error", "close response is not JSON")
        try:
            create_tx = payload.get("orderCreateTransaction")
            fill_tx = payload.get("orderFillTransaction")
            close_tx = payload.get("tradeCloseTransaction")
            if not isinstance(fill_tx, dict):
                # The broker cancelled the close instead of filling it
                # (the trade was already closed by a race). Fail closed.
                raise TradeOperationError(
                    "trade_state_invalid",
                    f"trade {broker_trade_id} closed before the close request",
                )
            # Exact broker truth wins: the fill transaction reports the
            # units actually closed, including ALL-close outcomes.
            if str(fill_tx.get("units", "")).strip():
                closed_units = _decimal(fill_tx["units"])
            else:
                closed_units = (
                    units if units is not None else abs(current.current_units)
                )
            return TradeCloseResult(
                broker_trade_id=broker_trade_id,
                closed_units=closed_units,
                realized_pl=_decimal(payload.get("realizedPL", "0")),
                financing=_decimal(payload.get("financing", "0")),
                order_create_transaction_id=_tx_id(create_tx),
                order_fill_transaction_id=(
                    _tx_id(fill_tx) if isinstance(fill_tx, dict) else None
                ),
                trade_close_transaction_id=(
                    _tx_id(close_tx) if isinstance(close_tx, dict) else None
                ),
                request_id=request_id or f"close-{broker_trade_id}",
            )
        except (KeyError, ValueError) as exc:
            raise TradeOperationError(
                "protocol_error", f"close parse failed: {exc}"
            ) from exc

    def add_trade_dependent(
        self,
        broker_trade_id: str,
        instrument: InstrumentMetadata,
        *,
        take_profit_price: Decimal | None = None,
        stop_loss_price: Decimal | None = None,
        trailing_stop_distance: Decimal | None = None,
        guaranteed_stop_price: Decimal | None = None,
        request_id: str | None = None,
    ) -> TradeDependentResult:
        """Attach one protective dependent order to a trade.

        Exactly one of the four dependent-order kinds must be supplied.
        Guaranteed stop loss is rejected for instruments whose account
        mode is not ``ENABLED``; unknown or closed trades fail closed.
        """
        current = self.get_trade(broker_trade_id)
        if current.state not in _OPEN_STATES:
            raise TradeOperationError(
                "trade_state_invalid",
                f"trade {broker_trade_id} is {current.state} and cannot be modified",
            )
        kinds = {
            "takeProfit": take_profit_price,
            "stopLoss": stop_loss_price,
            "trailingStopLoss": trailing_stop_distance,
            "guaranteedStopLoss": guaranteed_stop_price,
        }
        supplied = {kind: price for kind, price in kinds.items() if price is not None}
        if len(supplied) != 1:
            raise TradeOperationError(
                "invalid_dependent",
                "exactly one dependent order kind must be supplied",
            )
        if guaranteed_stop_price is not None:
            mode = str(
                instrument.raw_payload.get("guaranteedStopLossOrderMode", "")
            ).upper()
            if mode != "ENABLED":
                raise TradeOperationError(
                    "unsupported_dependent",
                    "guaranteed stop loss is not enabled for this instrument",
                )
        kind, price = next(iter(supplied.items()))
        if price <= 0:
            raise TradeOperationError(
                "invalid_dependent", f"{kind} price must be positive"
            )
        if kind == "trailingStopLoss":
            dependent: dict[str, Any] = {"distance": str(price)}
        else:
            dependent = {"price": str(price)}
        response = self._client.request(
            "PUT",
            self._client.account_path(f"/trades/{_path(broker_trade_id)}/orders"),
            json_body={kind: dependent},
        )
        payload = response.json_body
        if not isinstance(payload, dict):
            raise TradeOperationError(
                "protocol_error", "dependent response is not JSON"
            )
        create_tx = payload.get("orderCreateTransaction")
        if not isinstance(create_tx, dict) or not isinstance(
            create_tx.get("id"), str
        ):
            raise TradeOperationError(
                "protocol_error", "dependent response missing transaction"
            )
        return TradeDependentResult(
            broker_trade_id=broker_trade_id,
            dependent_order_id=str(create_tx["id"]),
            dependent_type=str(create_tx.get("type", "")).strip(),
            request_id=request_id or f"dependent-{broker_trade_id}",
        )


_TRADE_STATES = frozenset({"OPEN", "CLOSED", "CLOSE_WHEN_TRADABLE"})


def _trade_state_from_row(row: dict[str, Any], *, request_id: str) -> TradeStateResult:
    return TradeStateResult(
        broker_trade_id=str(row.get("id", "")).strip(),
        client_order_id=_client_extensions_id(row),
        instrument=str(row.get("instrument", "")).strip(),
        state=_parse_state(str(row.get("state", ""))),
        current_units=_decimal(row.get("currentUnits", "0")),
        initial_units=_decimal(row.get("initialUnits", "0")),
        realized_pl=_decimal(row.get("realizedPL", "0")),
        unrealized_pl=_decimal(row.get("unrealizedPL", "0")),
        financing=_decimal(row.get("financing", "0")),
        open_time=_parse_time(row.get("openTime")),
        close_time=_parse_time(row.get("closeTime")),
        request_id=request_id,
    )


def _parse_state(raw: str) -> TradeStateValue:
    normalized = raw.strip().upper()
    if normalized not in _TRADE_STATES:
        raise TradeOperationError("protocol_error", f"unknown trade state {raw!r}")
    return normalized  # type: ignore[return-value]


def _client_extensions_id(row: dict[str, Any]) -> str | None:
    extensions = row.get("clientExtensions")
    if isinstance(extensions, dict):
        value = str(extensions.get("id", "")).strip()
        if value:
            return value
    return None


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _tx_id(transaction: Any) -> str:
    if not isinstance(transaction, dict) or not isinstance(
        transaction.get("id"), str
    ):
        raise TradeOperationError(
            "protocol_error", "transaction id missing or malformed"
        )
    return str(transaction["id"])


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
    "TradeCloseResult",
    "TradeDependentResult",
    "TradeListResult",
    "TradeOperationError",
    "TradeOpsClient",
    "TradeStateResult",
    "TradeStateValue",
]
