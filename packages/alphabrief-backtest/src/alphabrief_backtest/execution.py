"""Deterministic OANDA-semantic order execution simulation (M12-W03).

Orders are validated against versioned instrument metadata before any
fill: market closure, stale prices, below-minimum / above-maximum
units, non-representable precision, and insufficient margin each
produce an explicit rejection with a stable reason. Accepted fills
apply spread (mid-based bid/ask), adverse slippage, and fees
deterministically; financing is charged separately per holding night
(REQ-STRAT-004).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_backtest.metadata import (
    SEMANTICS_VERSION,
    BacktestConstraintError,
    BacktestInstrumentMetadata,
    normalize_backtest_price,
    normalize_backtest_units,
    round_backtest_price,
)

BPS_DENOMINATOR = Decimal("10000")

#: Default maximum age of the reference mid price (seconds).
DEFAULT_MAX_PRICE_AGE_SECONDS = 300


class OrderRequest(BaseModel):
    """One deterministic order request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    side: str
    units: Decimal
    timestamp: datetime
    reference_mid: Decimal
    fee_bps: Decimal = Field(ge=0)
    slippage_bps: Decimal = Field(ge=0)

    @field_validator("side")
    @classmethod
    def side_must_be_buy_or_sell(cls, value: str) -> str:
        if value not in ("buy", "sell"):
            raise ValueError("order side must be 'buy' or 'sell'")
        return value

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("order timestamp must be timezone-aware")
        return value

    @field_validator("units")
    @classmethod
    def units_must_not_be_zero(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("order units must not be zero")
        return value


class OrderFill(BaseModel):
    """One deterministic fill or explicit rejection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    side: str
    units: Decimal
    timestamp: datetime
    reference_mid: Decimal
    execution_price: Decimal | None
    bid: Decimal | None
    ask: Decimal | None
    spread_cost: Decimal | None
    slippage_cost: Decimal | None
    fee: Decimal | None
    margin_used: Decimal | None
    accepted: bool
    reject_reason: str | None
    metadata_version: str = Field(min_length=1)
    semantics_version: str = Field(min_length=1)


def _quote_prices(
    mid: Decimal, metadata: BacktestInstrumentMetadata
) -> tuple[Decimal, Decimal]:
    """Deterministic bid/ask around the mid from the metadata spread."""
    half_spread = mid * (metadata.spread_bps / BPS_DENOMINATOR) / Decimal("2")
    bid = round_backtest_price(mid - half_spread, metadata)
    ask = round_backtest_price(mid + half_spread, metadata)
    return bid, ask


def _reject(request: OrderRequest, reason: str) -> OrderFill:
    return OrderFill(
        symbol=request.symbol,
        side=request.side,
        units=request.units,
        timestamp=request.timestamp,
        reference_mid=request.reference_mid,
        execution_price=None,
        bid=None,
        ask=None,
        spread_cost=None,
        slippage_cost=None,
        fee=None,
        margin_used=None,
        accepted=False,
        reject_reason=reason,
        metadata_version=f"instrument-{request.symbol}",
        semantics_version=SEMANTICS_VERSION,
    )


def execute_order(
    request: OrderRequest,
    metadata: BacktestInstrumentMetadata,
    *,
    nav: Decimal,
    existing_units: Decimal,
    price_age_seconds: int,
    max_price_age_seconds: int = DEFAULT_MAX_PRICE_AGE_SECONDS,
) -> OrderFill:
    """Validate and fill one order, or reject it with an explicit reason.

    The verdict is a pure function of its inputs: identical inputs
    always produce identical fills or identical rejections.
    """
    if price_age_seconds > max_price_age_seconds:
        return _reject(
            request,
            f"stale_price: reference mid is {price_age_seconds}s old "
            f"(max {max_price_age_seconds}s)",
        )

    if not metadata.effective_session_window().is_open(request.timestamp):
        return _reject(
            request,
            f"market_closed: {request.symbol} session is closed at "
            f"{request.timestamp.isoformat()}",
        )

    try:
        normalized_units = normalize_backtest_units(request.units, metadata)
        normalized_mid = normalize_backtest_price(request.reference_mid, metadata)
    except BacktestConstraintError as exc:
        return _reject(request, f"{exc.kind}: {exc}")

    if abs(normalized_units) < metadata.minimum_trade_size:
        return _reject(
            request,
            f"below_minimum_units: |{normalized_units}| < "
            f"minimum_trade_size {metadata.minimum_trade_size}",
        )

    if abs(normalized_units) > metadata.maximum_order_units:
        return _reject(
            request,
            f"above_maximum_units: |{normalized_units}| > "
            f"maximum_order_units {metadata.maximum_order_units}",
        )

    bid, ask = _quote_prices(normalized_mid, metadata)
    slippage_factor = request.slippage_bps / BPS_DENOMINATOR
    if request.side == "buy":
        quoted_side = ask
        execution_price = round_backtest_price(
            quoted_side * (Decimal("1") + slippage_factor), metadata
        )
    else:
        quoted_side = bid
        execution_price = round_backtest_price(
            quoted_side * (Decimal("1") - slippage_factor), metadata
        )

    spread_cost = abs(quoted_side - normalized_mid) * abs(normalized_units)
    slippage_cost = abs(execution_price - quoted_side) * abs(normalized_units)
    notional = abs(execution_price * normalized_units)
    fee = notional * request.fee_bps / BPS_DENOMINATOR

    position_after = existing_units + (
        normalized_units if request.side == "buy" else -normalized_units
    )
    if abs(position_after) > metadata.maximum_position_size:
        return _reject(
            request,
            f"above_maximum_position: |{position_after}| > "
            f"maximum_position_size {metadata.maximum_position_size}",
        )

    margin_used = abs(position_after) * execution_price * metadata.margin_rate
    if margin_used > nav:
        return _reject(
            request,
            f"insufficient_margin: projected margin {margin_used} exceeds "
            f"nav {nav}",
        )

    return OrderFill(
        symbol=request.symbol,
        side=request.side,
        units=normalized_units,
        timestamp=request.timestamp,
        reference_mid=request.reference_mid,
        execution_price=execution_price,
        bid=bid,
        ask=ask,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        fee=fee,
        margin_used=margin_used,
        accepted=True,
        reject_reason=None,
        metadata_version=f"instrument-{request.symbol}",
        semantics_version=SEMANTICS_VERSION,
    )


def financing_charge(
    units: Decimal,
    metadata: BacktestInstrumentMetadata,
    *,
    nights: int,
) -> Decimal:
    """Deterministic financing charge for a position held ``nights``.

    The charge is ``units * financing_rate_per_unit_per_day * nights``
    in account home currency (positive = cost to the portfolio).
    """
    if nights < 0:
        raise ValueError("nights must not be negative")
    return units * metadata.financing_rate_per_unit_per_day * Decimal(nights)


__all__ = [
    "DEFAULT_MAX_PRICE_AGE_SECONDS",
    "OrderFill",
    "OrderRequest",
    "execute_order",
    "financing_charge",
]
