"""Complete OANDA v20 instruments contract (M04-W02).

``fetch_instruments`` retrieves every instrument returned for the
configured account; ``parse_instruments_response`` converts each row
into exactly one strict :class:`InstrumentMetadata` object. Unknown
fields are preserved in a versioned raw payload, all numeric values are
Decimal-safe, and a row with missing or invalid required trading fields
rejects the entire candidate snapshot without partial publication —
precision or size is never inferred from symbol naming.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_execution.broker.oanda.client import OandaHttpClient

#: Raw instrument types OANDA may return (kept verbatim; unknown types
#: are preserved, never dropped).
_KNOWN_RAW_TYPES = frozenset(
    {"CURRENCY", "METAL", "CFD", "INDEX", "BOND", "COMMODITY", "SHARE"}
)


class InstrumentParseError(ValueError):
    """Raised when any instrument row fails the strict contract."""


class InstrumentMetadata(BaseModel):
    """One strict instrument metadata object (M04-W02).

    Every numeric trading field is a ``Decimal``; the raw broker type and
    any unknown response fields are preserved verbatim in
    ``raw_payload`` for later versioned taxonomies.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    raw_type: str = Field(min_length=1)
    display_precision: int
    trade_units_precision: int
    minimum_trade_size: Decimal = Field(ge=0)
    maximum_order_units: Decimal = Field(ge=0)
    maximum_position_size: Decimal = Field(ge=0)
    margin_rate: Decimal = Field(gt=0)
    pip_location: int
    minimum_trailing_stop_distance: Decimal | None = None
    maximum_trailing_stop_distance: Decimal | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("display_precision", "trade_units_precision", mode="before")
    @classmethod
    def precision_must_be_integer(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(f"precision must be an integer, got {value!r}")
        return int(str(value))

    @field_validator("pip_location", mode="before")
    @classmethod
    def pip_location_must_be_integer(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(f"pipLocation must be an integer, got {value!r}")
        return int(str(value))

    @field_validator(
        "minimum_trade_size",
        "maximum_order_units",
        "maximum_position_size",
        "margin_rate",
        "minimum_trailing_stop_distance",
        "maximum_trailing_stop_distance",
        mode="before",
    )
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("instrument numeric fields must not be floats")
        return value


class InstrumentCatalogSnapshot(BaseModel):
    """One validated instrument catalog response for the account."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id_hash: str = Field(min_length=1)
    fetched_at: datetime
    instruments: tuple[InstrumentMetadata, ...] = Field(min_length=1)
    raw_payload_version: str = "oanda-v20-1"


def _scrub_account_id(account_id: str) -> str:
    import hashlib

    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()


def _optional_decimal(value: Any, field: str) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, float):
        raise InstrumentParseError(f"{field} must not be a float")
    try:
        return Decimal(str(value))
    except (TypeError, ValueError) as exc:
        raise InstrumentParseError(f"{field} is not a Decimal-safe value") from exc


def _int_or_error(value: Any, field: str) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise InstrumentParseError(f"{field} is not an integer") from exc


def parse_instruments_response(
    body: Any,
    *,
    account_id: str,
) -> InstrumentCatalogSnapshot:
    """Convert one OANDA instruments response into a strict snapshot.

    Every row becomes exactly one metadata object; a row with missing or
    invalid required trading fields rejects the whole candidate snapshot
    (no partial publication). Unknown response fields are retained in
    each row's ``raw_payload``.
    """
    if not isinstance(body, dict) or not isinstance(body.get("instruments"), list):
        raise InstrumentParseError("instruments response is not a JSON object")
    if not body["instruments"]:
        raise InstrumentParseError("instruments response contains no rows")

    instruments: list[InstrumentMetadata] = []
    for index, row in enumerate(body["instruments"]):
        if not isinstance(row, dict):
            raise InstrumentParseError(f"instrument row {index} is not an object")
        try:
            raw_payload = dict(row)
            name = str(row.get("name", "")).strip()
            display_name = str(row.get("displayName", "")).strip()
            raw_type = str(row.get("type", "")).strip()
            display_precision = _int_or_error(
                row.get("displayPrecision"), "displayPrecision"
            )
            trade_units_precision = _int_or_error(
                row.get("tradeUnitsPrecision"), "tradeUnitsPrecision"
            )
            pip_location = _int_or_error(row.get("pipLocation"), "pipLocation")
            minimum_trade_size = _optional_decimal(
                row.get("minimumTradeSize"), "minimumTradeSize"
            )
            margin_rate = _optional_decimal(row.get("marginRate"), "marginRate")
            if not name or not display_name:
                raise InstrumentParseError(
                    f"instrument row {index} missing name or displayName"
                )
            if not raw_type:
                raise InstrumentParseError(f"instrument row {index} missing type")
            if minimum_trade_size is None or margin_rate is None:
                raise InstrumentParseError(
                    f"instrument row {index} missing minimumTradeSize or marginRate"
                )
            instruments.append(
                InstrumentMetadata(
                    name=name,
                    display_name=display_name,
                    raw_type=raw_type,
                    display_precision=display_precision,
                    trade_units_precision=trade_units_precision,
                    minimum_trade_size=minimum_trade_size,
                    maximum_order_units=_optional_decimal(
                        row.get("maximumOrderUnits", "0"), "maximumOrderUnits"
                    )
                    or Decimal("0"),
                    maximum_position_size=_optional_decimal(
                        row.get("maximumPositionSize", "0"), "maximumPositionSize"
                    )
                    or Decimal("0"),
                    margin_rate=margin_rate,
                    pip_location=pip_location,
                    minimum_trailing_stop_distance=_optional_decimal(
                        row.get("minimumTrailingStopDistance"),
                        "minimumTrailingStopDistance",
                    ),
                    maximum_trailing_stop_distance=_optional_decimal(
                        row.get("maximumTrailingStopDistance"),
                        "maximumTrailingStopDistance",
                    ),
                    raw_payload=raw_payload,
                )
            )
        except InstrumentParseError:
            raise
        except (TypeError, ValueError) as exc:
            raise InstrumentParseError(
                f"instrument row {index} fails the strict contract: {exc}"
            ) from exc

    return InstrumentCatalogSnapshot(
        account_id_hash=_scrub_account_id(account_id),
        fetched_at=datetime.now(UTC),
        instruments=tuple(instruments),
    )


def fetch_instruments(
    client: OandaHttpClient,
    *,
    account_id: str,
) -> InstrumentCatalogSnapshot:
    """Fetch and strictly validate every instrument for the account."""
    response = client.request("GET", f"/v3/accounts/{account_id}/instruments")
    return parse_instruments_response(response.json_body, account_id=account_id)


__all__ = [
    "InstrumentCatalogSnapshot",
    "InstrumentMetadata",
    "InstrumentParseError",
    "fetch_instruments",
    "parse_instruments_response",
]
