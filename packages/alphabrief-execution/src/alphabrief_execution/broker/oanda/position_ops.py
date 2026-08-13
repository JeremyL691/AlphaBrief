"""OANDA position operations port (M06-W04).

Get, list, and close positions with exact OANDA semantics: side-specific
long/short units with explicit ``ALL``/``NONE``/partial unit handling,
distinct typed transaction IDs per side, and fail-closed behavior for
missing, account-mismatched, over-close, and unsupported requests — a
local synthetic position mutation never happens and an unspecified side
is never silently closed in full.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.errors import BrokerNotFoundError
from alphabrief_execution.broker.oanda.client import OandaHttpClient

PositionSide = Literal["LONG", "SHORT", "BOTH", "NONE"]


class PositionOperationError(RuntimeError):
    """A classified position operation failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        super().__init__(f"position operation failed ({kind}): {detail}")


class PositionResult(BaseModel):
    """One typed position with distinct long and short sides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument: str = Field(min_length=1)
    side: PositionSide
    long_units: Decimal
    long_average_price: Decimal | None = None
    long_pl: Decimal
    long_unrealized_pl: Decimal
    short_units: Decimal
    short_average_price: Decimal | None = None
    short_pl: Decimal
    short_unrealized_pl: Decimal
    request_id: str = Field(min_length=1)


class PositionListResult(BaseModel):
    """One typed position list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    positions: tuple[PositionResult, ...]
    request_id: str = Field(min_length=1)


class PositionCloseResult(BaseModel):
    """One typed position close with distinct transaction IDs per side."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument: str = Field(min_length=1)
    long_closed_units: Decimal
    short_closed_units: Decimal
    long_order_create_transaction_id: str | None = None
    long_order_fill_transaction_id: str | None = None
    short_order_create_transaction_id: str | None = None
    short_order_fill_transaction_id: str | None = None
    request_id: str = Field(min_length=1)


class PositionOpsClient:
    """Position command and query port over the OANDA practice client."""

    def __init__(self, client: OandaHttpClient) -> None:
        self._client = client

    def get_position(
        self,
        instrument: str,
        *,
        request_id: str | None = None,
    ) -> PositionResult:
        """Fetch one typed position; missing instruments fail closed."""
        if not instrument.strip():
            raise PositionOperationError("invalid_request_id", "instrument is empty")
        try:
            response = self._client.request(
                "GET",
                self._client.account_path(f"/positions/{_path(instrument)}"),
            )
        except BrokerNotFoundError as exc:
            raise PositionOperationError("unknown_position", instrument) from exc
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("position"), dict):
            raise PositionOperationError("protocol_error", "get response is not JSON")
        try:
            return _position_from_row(
                body["position"], request_id=request_id or f"get-{instrument}"
            )
        except (KeyError, ValueError) as exc:
            raise PositionOperationError(
                "protocol_error", f"position parse failed: {exc}"
            ) from exc

    def list_positions(
        self,
        *,
        request_id: str | None = None,
    ) -> PositionListResult:
        """List all typed positions for the account."""
        response = self._client.request(
            "GET", self._client.account_path("/positions")
        )
        body = response.json_body
        if not isinstance(body, dict) or not isinstance(body.get("positions"), list):
            raise PositionOperationError("protocol_error", "list response is not JSON")
        positions = tuple(
            _position_from_row(row, request_id=f"list-row-{row.get('instrument', '')}")
            for row in body["positions"]
            if isinstance(row, dict)
        )
        return PositionListResult(
            positions=positions,
            request_id=request_id or "list",
        )

    def close_position(
        self,
        instrument: str,
        *,
        long_units: Decimal | Literal["ALL", "NONE"] | None = None,
        short_units: Decimal | Literal["ALL", "NONE"] | None = None,
        request_id: str | None = None,
    ) -> PositionCloseResult:
        """Close a position with exact OANDA semantics.

        Every side that must be touched is supplied explicitly: ``"ALL"``
        closes that side in full, ``"NONE"`` leaves it untouched, and a
        positive Decimal closes that many units. At least one side is
        required because OANDA's own default for an omitted side is
        ``ALL``; silently closing an unspecified side is forbidden.
        Over-close requests fail closed before any request reaches the
        broker.
        """
        if not instrument.strip():
            raise PositionOperationError("invalid_request_id", "instrument is empty")
        if long_units is None and short_units is None:
            raise PositionOperationError(
                "invalid_units", "at least one of long_units or short_units is required"
            )
        requested: dict[str, str] = {}
        for label, value in (("longUnits", long_units), ("shortUnits", short_units)):
            if value is None:
                continue
            if isinstance(value, str):
                if value not in ("ALL", "NONE"):
                    raise PositionOperationError(
                        "invalid_units",
                        f"{label} must be ALL, NONE, or a positive number",
                    )
                requested[label] = value
                continue
            if value <= 0:
                raise PositionOperationError(
                    "invalid_units", f"{label} must be positive"
                )
            requested[label] = str(value)
        current = self.get_position(instrument, request_id=request_id or "precheck")
        for label, value in (("longUnits", long_units), ("shortUnits", short_units)):
            if value is None or isinstance(value, str):
                continue
            open_units = (
                abs(current.long_units)
                if label == "longUnits"
                else abs(current.short_units)
            )
            if value > open_units:
                raise PositionOperationError(
                    "over_close",
                    f"{label} close {value} exceeds open units {open_units}",
                )
        response = self._client.request(
            "PUT",
            self._client.account_path(f"/positions/{_path(instrument)}/close"),
            json_body=requested,
        )
        payload = response.json_body
        if not isinstance(payload, dict):
            raise PositionOperationError("protocol_error", "close response is not JSON")
        try:
            long_create = payload.get("longOrderCreateTransaction")
            long_fill = payload.get("longOrderFillTransaction")
            short_create = payload.get("shortOrderCreateTransaction")
            short_fill = payload.get("shortOrderFillTransaction")
            return PositionCloseResult(
                instrument=instrument,
                long_closed_units=_side_closed_units(long_fill, long_units),
                short_closed_units=_side_closed_units(short_fill, short_units),
                long_order_create_transaction_id=_maybe_tx_id(long_create),
                long_order_fill_transaction_id=_maybe_tx_id(long_fill),
                short_order_create_transaction_id=_maybe_tx_id(short_create),
                short_order_fill_transaction_id=_maybe_tx_id(short_fill),
                request_id=request_id or f"close-{instrument}",
            )
        except (KeyError, ValueError) as exc:
            raise PositionOperationError(
                "protocol_error", f"close parse failed: {exc}"
            ) from exc


def _position_from_row(row: dict[str, Any], *, request_id: str) -> PositionResult:
    raw_long = row.get("long")
    raw_short = row.get("short")
    long: dict[str, Any] = raw_long if isinstance(raw_long, dict) else {}
    short: dict[str, Any] = raw_short if isinstance(raw_short, dict) else {}
    long_units = _decimal(long.get("units", "0"))
    short_units = _decimal(short.get("units", "0"))
    if long_units != 0 and short_units != 0:
        side: PositionSide = "BOTH"
    elif long_units != 0:
        side = "LONG"
    elif short_units != 0:
        side = "SHORT"
    else:
        side = "NONE"
    return PositionResult(
        instrument=str(row.get("instrument", "")).strip(),
        side=side,
        long_units=long_units,
        long_average_price=_optional_decimal(long.get("averagePrice")),
        long_pl=_decimal(long.get("pl", "0")),
        long_unrealized_pl=_decimal(long.get("unrealizedPL", "0")),
        short_units=short_units,
        short_average_price=_optional_decimal(short.get("averagePrice")),
        short_pl=_decimal(short.get("pl", "0")),
        short_unrealized_pl=_decimal(short.get("unrealizedPL", "0")),
        request_id=request_id,
    )


def _side_closed_units(
    fill_transaction: Any,
    requested_units: Decimal | Literal["ALL", "NONE"] | None,
) -> Decimal:
    if isinstance(fill_transaction, dict) and str(
        fill_transaction.get("units", "")
    ).strip():
        return _decimal(fill_transaction["units"])
    if isinstance(requested_units, Decimal):
        return requested_units
    # No fill transaction: "ALL"/"NONE" sentinels or absent sides close
    # nothing on that side.
    return Decimal("0")


def _maybe_tx_id(transaction: Any) -> str | None:
    if isinstance(transaction, dict) and isinstance(transaction.get("id"), str):
        return str(transaction["id"])
    return None


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return _decimal(value)


def _path(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


__all__ = [
    "PositionCloseResult",
    "PositionListResult",
    "PositionOperationError",
    "PositionOpsClient",
    "PositionResult",
    "PositionSide",
]
