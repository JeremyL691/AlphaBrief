"""OANDA batch pricing and home-currency conversion evidence (M05-W02).

Fetches current prices in deterministic bounded chunks and retains bid
and ask ladders, spread, liquidity, tradeable state, closeout prices,
quote-to-home conversion factors, broker time, and request correlation.
Quality validation rejects missing sides, crossed prices, nonpositive
conversion factors, duplicate instruments, account mismatch, and
malformed timestamps instead of silently repairing them; partial broker
responses publish explicit per-instrument coverage and are never
represented as a complete pricing snapshot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alphabrief_execution.broker.oanda.client import OandaHttpClient

#: Default deterministic chunk size for pricing requests.
DEFAULT_MAX_INSTRUMENTS_PER_REQUEST = 50

#: Immutable source identity for pricing facts.
PRICING_SOURCE_VERSION = "oanda-v20-pricing-1"


class PricingRequest(BaseModel):
    """One bounded batch pricing request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbols: tuple[str, ...] = Field(min_length=1)
    max_instruments_per_request: int = Field(
        default=DEFAULT_MAX_INSTRUMENTS_PER_REQUEST, ge=1, le=500
    )


class PriceLadderEntry(BaseModel):
    """One bid or ask ladder entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    price: Decimal
    liquidity: int = Field(ge=0)


class OandaPrice(BaseModel):
    """One validated price fact for a single instrument."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    bids: tuple[PriceLadderEntry, ...] = Field(min_length=1)
    asks: tuple[PriceLadderEntry, ...] = Field(min_length=1)
    spread: Decimal = Field(ge=0)
    tradeable: bool
    closeout_bid: Decimal
    closeout_ask: Decimal
    conversion_factor: Decimal = Field(gt=0)
    broker_time: datetime
    request_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)

    @field_validator("closeout_bid", "closeout_ask", "conversion_factor", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("pricing numeric fields must not be floats")
        return value

    @model_validator(mode="after")
    def prices_must_not_be_crossed(self) -> OandaPrice:
        crossed = (
            self.closeout_ask < self.closeout_bid
            or self.asks[0].price < self.bids[0].price
        )
        if crossed:
            raise ValueError(f"{self.symbol} prices are crossed")
        return self


class InstrumentCoverage(BaseModel):
    """Per-instrument coverage of one pricing batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested: tuple[str, ...]
    returned: tuple[str, ...]
    missing: tuple[str, ...]
    failed: tuple[str, ...]
    complete: bool


class PricingBatch(BaseModel):
    """One pricing batch with explicit per-instrument coverage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prices: tuple[OandaPrice, ...]
    coverage: InstrumentCoverage
    broker_time: datetime | None = None


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, float):
        raise ValueError(f"{field} must not be a float")
    try:
        return Decimal(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not Decimal-safe") from exc


def _parse_broker_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"broker time must be a string, got {value!r}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"broker time {value!r} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_pricing_response(
    body: Any,
    *,
    requested: tuple[str, ...],
    request_id: str,
    source_version: str = PRICING_SOURCE_VERSION,
) -> PricingBatch:
    """Convert one OANDA pricing response into validated price facts.

    Duplicate instruments, missing sides, crossed prices, nonpositive
    conversion factors, and malformed timestamps reject the affected row
    and are reported as per-instrument failures; coverage is explicit so
    a partial response is never treated as a complete snapshot.
    """
    if not isinstance(body, dict) or not isinstance(body.get("prices"), list):
        raise ValueError("pricing response is not a JSON object")

    prices: list[OandaPrice] = []
    failed: list[str] = []
    seen: set[str] = set()
    broker_time: datetime | None = None
    for row in body["prices"]:
        if not isinstance(row, dict):
            failed.append("<non-object-row>")
            continue
        symbol = str(row.get("instrument", "")).strip()
        if not symbol:
            failed.append("<missing-instrument>")
            continue
        if symbol in seen:
            failed.append(f"{symbol} (duplicate)")
            continue
        seen.add(symbol)
        try:
            bids = tuple(
                PriceLadderEntry(
                    price=_decimal(entry.get("price"), f"{symbol} bid price"),
                    liquidity=int(str(entry.get("liquidity", "0"))),
                )
                for entry in row.get("bids", [])
                if isinstance(entry, dict)
            )
            asks = tuple(
                PriceLadderEntry(
                    price=_decimal(entry.get("price"), f"{symbol} ask price"),
                    liquidity=int(str(entry.get("liquidity", "0"))),
                )
                for entry in row.get("asks", [])
                if isinstance(entry, dict)
            )
            if not bids or not asks:
                raise ValueError("missing bid or ask side")
            conversions = row.get("quoteHomeConversionFactors")
            conversion_factor = Decimal("1")
            if isinstance(conversions, dict):
                positive = conversions.get("positiveUnits")
                if positive not in (None, ""):
                    conversion_factor = _decimal(positive, "conversion factor")
            if conversion_factor <= 0:
                raise ValueError("nonpositive conversion factor")

            raw_time = row.get("time")
            row_time = _parse_broker_time(raw_time) if raw_time else None
            if row_time is None:
                raise ValueError("malformed broker timestamp")

            best_bid = bids[0].price
            best_ask = asks[0].price
            raw_spread = row.get("spread")
            spread = (
                _decimal(raw_spread, "spread")
                if raw_spread not in (None, "")
                else best_ask - best_bid
            )
            price = OandaPrice(
                symbol=symbol,
                bids=bids,
                asks=asks,
                spread=spread,
                tradeable=bool(row.get("tradeable", True)),
                closeout_bid=_decimal(row.get("closeoutBid"), "closeoutBid"),
                closeout_ask=_decimal(row.get("closeoutAsk"), "closeoutAsk"),
                conversion_factor=conversion_factor,
                broker_time=row_time,
                request_id=request_id,
                source_version=source_version,
            )
            if best_ask < best_bid:
                raise ValueError("prices are crossed")
            prices.append(price)
            broker_time = row_time
        except (ValueError, TypeError) as exc:
            failed.append(f"{symbol} ({exc})")

    returned = tuple(price.symbol for price in prices)
    requested_set = set(requested)
    missing = tuple(sorted(requested_set - set(returned)))
    return PricingBatch(
        prices=tuple(prices),
        coverage=InstrumentCoverage(
            requested=requested,
            returned=returned,
            missing=missing,
            failed=tuple(failed),
            complete=bool(prices) and not missing and not failed
            and len(returned) == len(requested_set),
        ),
        broker_time=broker_time,
    )


def fetch_pricing(
    client: OandaHttpClient,
    *,
    request: PricingRequest,
    request_id: str,
    source_version: str = PRICING_SOURCE_VERSION,
) -> PricingBatch:
    """Fetch pricing in deterministic bounded chunks.

    Each chunk becomes one request with its own correlation ID suffix;
    all parsed facts carry the request correlation.
    """
    chunk_size = request.max_instruments_per_request
    all_prices: list[OandaPrice] = []
    all_failed: list[str] = []
    all_returned: list[str] = []
    broker_time: datetime | None = None
    for index in range(0, len(request.symbols), chunk_size):
        chunk = request.symbols[index : index + chunk_size]
        chunk_request_id = f"{request_id}-{index // chunk_size}"
        response = client.request(
            "GET",
            f"/v3/accounts/{client.account_id}/pricing",
            params={"instruments": ",".join(chunk)},
        )
        batch = parse_pricing_response(
            response.json_body,
            requested=chunk,
            request_id=chunk_request_id,
            source_version=source_version,
        )
        all_prices.extend(batch.prices)
        all_failed.extend(batch.coverage.failed)
        all_returned.extend(batch.coverage.returned)
        if batch.broker_time is not None:
            broker_time = batch.broker_time

    requested_set = set(request.symbols)
    missing = tuple(sorted(requested_set - set(all_returned)))
    return PricingBatch(
        prices=tuple(all_prices),
        coverage=InstrumentCoverage(
            requested=request.symbols,
            returned=tuple(all_returned),
            missing=missing,
            failed=tuple(all_failed),
            complete=bool(all_prices) and not missing and not all_failed
            and len(set(all_returned)) == len(requested_set),
        ),
        broker_time=broker_time,
    )


__all__ = [
    "DEFAULT_MAX_INSTRUMENTS_PER_REQUEST",
    "InstrumentCoverage",
    "OandaPrice",
    "PRICING_SOURCE_VERSION",
    "PriceLadderEntry",
    "PricingBatch",
    "PricingRequest",
    "fetch_pricing",
    "parse_pricing_response",
]
