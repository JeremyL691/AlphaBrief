"""Complete OANDA v20 candles contract (M05-W01).

Supports the official candle granularities, bid/ask/mid components,
alignment parameters, bounded duplicate-free pagination, complete-candle
semantics, and immutable source identities. Each component of each row
becomes its own Decimal-safe candle fact: components are never collapsed
and no source version overwrites another.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_execution.broker.oanda.client import OandaHttpClient

#: Official OANDA v20 candle granularities.
CandleGranularity = Literal[
    "S5", "S10", "S15", "S30", "M1", "M2", "M4", "M5", "M10", "M15", "M30",
    "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D", "W", "M",
]

#: Candle price components (mid / bid / ask).
CandleComponent = Literal["M", "B", "A"]

#: OANDA hard cap on candles per request; our bounded pagination never
#: exceeds it.
MAX_CANDLES_PER_REQUEST = 5000

#: Immutable source identity for candle facts produced by this contract.
CANDLE_SOURCE_VERSION = "oanda-v20-candles-1"


class CandleRequest(BaseModel):
    """One bounded OANDA candles request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    granularity: CandleGranularity
    components: tuple[CandleComponent, ...] = Field(min_length=1)
    count: int = Field(ge=1, le=MAX_CANDLES_PER_REQUEST)
    from_time: datetime | None = None
    to_time: datetime | None = None
    daily_alignment: int | None = Field(default=None, ge=0, le=23)
    weekly_alignment: CandleGranularity | None = None


class OandaCandle(BaseModel):
    """One immutable candle fact for a single component."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    time: datetime
    component: CandleComponent
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    complete: bool
    source_version: str = Field(min_length=1)

    @field_validator("open", "high", "low", "close", "volume", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("candle numeric fields must not be floats")
        return value

    @field_validator("time", mode="before")
    @classmethod
    def time_must_be_utc(cls, value: Any) -> Any:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, datetime):
            parsed = value
        else:
            raise ValueError(f"candle time must be a datetime, got {value!r}")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)


class CandlePage(BaseModel):
    """One bounded, duplicate-free page of candle facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    granularity: CandleGranularity
    candles: tuple[OandaCandle, ...]
    next_from_time: datetime | None = None


_COMPONENT_KEYS: dict[str, str] = {"M": "mid", "B": "bid", "A": "ask"}


def _component_price(row: dict[str, Any], component: str) -> dict[str, Decimal] | None:
    raw = row.get(_COMPONENT_KEYS[component])
    if not isinstance(raw, dict):
        return None
    if any(isinstance(raw.get(key), float) for key in ("o", "h", "l", "c")):
        raise ValueError(f"{component} OHLC values must not be floats")
    try:
        return {
            key: Decimal(str(raw[key]))
            for key in ("o", "h", "l", "c")
            if raw.get(key) is not None
        }
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{component} OHLC values are not Decimal-safe") from exc


def parse_candles_response(
    body: Any,
    *,
    symbol: str,
    granularity: CandleGranularity,
    components: tuple[CandleComponent, ...],
    source_version: str = CANDLE_SOURCE_VERSION,
) -> CandlePage:
    """Convert one OANDA candles response into immutable candle facts.

    Every requested component of every row becomes exactly one candle
    fact; missing component prices are a contract error, and duplicate
    (time, component) rows are rejected rather than merged.
    """
    if not isinstance(body, dict) or not isinstance(body.get("candles"), list):
        raise ValueError("candles response is not a JSON object")
    raw_rows = body["candles"]
    seen: set[tuple[str, str]] = set()
    candles: list[OandaCandle] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            raise ValueError("candle row is not an object")
        time = row.get("time")
        volume = Decimal(str(row.get("volume", "0")))
        complete = bool(row.get("complete", False))
        for component in components:
            prices = _component_price(row, component)
            if prices is None:
                raise ValueError(
                    f"candle row {time!r} missing {component} prices"
                )
            if len(prices) != 4:
                raise ValueError(
                    f"candle row {time!r} {component} OHLC is incomplete"
                )
            key = (str(time), component)
            if key in seen:
                raise ValueError(f"duplicate candle row for {key}")
            seen.add(key)
            candle_time = _parse_row_time(time)
            candles.append(
                OandaCandle(
                    symbol=symbol,
                    time=candle_time,
                    component=component,
                    open=prices["o"],
                    high=prices["h"],
                    low=prices["l"],
                    close=prices["c"],
                    volume=volume,
                    complete=complete,
                    source_version=source_version,
                )
            )

    last_time = str(raw_rows[-1]["time"]) if raw_rows else None
    return CandlePage(
        symbol=symbol,
        granularity=granularity,
        candles=tuple(candles),
        next_from_time=(
            datetime.fromisoformat(last_time.replace("Z", "+00:00")).astimezone(UTC)
            if last_time
            else None
        ),
    )


def fetch_candles(
    client: OandaHttpClient,
    *,
    request: CandleRequest,
    source_version: str = CANDLE_SOURCE_VERSION,
) -> CandlePage:
    """Fetch one bounded page of candles for the account."""
    params: dict[str, Any] = {
        "granularity": request.granularity,
        "count": request.count,
        "price": ",".join(request.components),
    }
    if request.from_time is not None:
        params["from"] = _oanda_isoformat(request.from_time)
    if request.to_time is not None:
        params["to"] = _oanda_isoformat(request.to_time)
    if request.daily_alignment is not None:
        params["dailyAlignment"] = request.daily_alignment
    if request.weekly_alignment is not None:
        params["weeklyAlignment"] = request.weekly_alignment

    response = client.request(
        "GET",
        f"/v3/accounts/{client.account_id}/instruments/"
        f"{_path_part(request.symbol)}/candles",
        params=params,
    )
    return parse_candles_response(
        response.json_body,
        symbol=request.symbol,
        granularity=request.granularity,
        components=request.components,
        source_version=source_version,
    )


def completed_only(candles: tuple[OandaCandle, ...]) -> tuple[OandaCandle, ...]:
    """Return only complete candles (decision inputs; raw facts kept aside)."""
    return tuple(candle for candle in candles if candle.complete)


def _parse_row_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"candle time must be a string, got {value!r}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"candle time {value!r} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _oanda_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _path_part(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


__all__ = [
    "CANDLE_SOURCE_VERSION",
    "CandleComponent",
    "CandleGranularity",
    "CandlePage",
    "CandleRequest",
    "MAX_CANDLES_PER_REQUEST",
    "OandaCandle",
    "completed_only",
    "fetch_candles",
    "parse_candles_response",
]
