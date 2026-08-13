"""Home-currency exposure, concentration, and correlation aggregation (M08-W03).

Computes pre-trade and post-trade gross, net, symbol, category,
currency-direction, correlated-group, and concentration exposure in the
account home currency using persisted conversion evidence
(REQ-RISK-003, REQ-RISK-006). Everything is Decimal-safe and evidence-
backed: a missing, stale, zero, inconsistent, or unsupported conversion,
price, category, or correlation input fails closed with a classified
:class:`ExposureError` — exposure is never silently computed in nominal
units or at cost basis (AC-M08-W03-03).

Limits (single-order notional, symbol, category, direction, gross, net,
leverage, concentration) are evaluated against the projected post-trade
snapshot and produce stable typed rule results (AC-M08-W03-02).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("exposure decimal values must not be floats")
    return value


class PositionLeg(BaseModel):
    """One position with distinct long/short sides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    long_units: Decimal = Decimal("0")
    short_units: Decimal = Decimal("0")

    @field_validator("long_units", "short_units", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class PendingOrderLeg(BaseModel):
    """One pending order projected into post-trade exposure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    units: Decimal  # signed: positive long, negative short
    price: Decimal | None = None

    @field_validator("units", "price", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class PriceEvidence(BaseModel):
    """One per-symbol mid price with its capture time and source ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    mid: Decimal = Field(gt=0)
    captured_at: datetime
    source_id: str = Field(min_length=1)

    @field_validator("mid", mode="before")
    @classmethod
    def mid_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class ConversionEvidence(BaseModel):
    """One quote-to-home conversion factor with its evidence trail."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    factor: Decimal = Field(gt=0)
    captured_at: datetime
    source_id: str = Field(min_length=1)

    @field_validator("factor", mode="before")
    @classmethod
    def factor_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class CategoryEvidence(BaseModel):
    """One explicit symbol -> category mapping (never inferred from names)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    category: str = Field(min_length=1)


class CurrencyDirectionEvidence(BaseModel):
    """One explicit symbol -> currency-direction mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    currency: str = Field(min_length=1)


class CorrelationEvidence(BaseModel):
    """One correlated group with its source ID and capture time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    group: str = Field(min_length=1)
    symbols: tuple[str, ...] = Field(min_length=1)
    source_id: str = Field(min_length=1)
    captured_at: datetime


class ExposureInputs(BaseModel):
    """One deterministic exposure input bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_currency: str = Field(min_length=1)
    equity: Decimal = Field(gt=0)
    positions: tuple[PositionLeg, ...] = ()
    pending_orders: tuple[PendingOrderLeg, ...] = ()
    prices: tuple[PriceEvidence, ...] = ()
    conversions: tuple[ConversionEvidence, ...] = ()
    categories: tuple[CategoryEvidence, ...] = ()
    currency_directions: tuple[CurrencyDirectionEvidence, ...] = ()
    correlation_groups: tuple[CorrelationEvidence, ...] = ()
    conversion_max_age_seconds: int = 300

    @field_validator("equity", mode="before")
    @classmethod
    def equity_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class SymbolExposure(BaseModel):
    """One symbol's home-currency exposure pre and post trade."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    category: str
    currency: str
    pre_long: Decimal
    pre_short: Decimal
    pre_gross: Decimal
    pre_net: Decimal
    post_long: Decimal
    post_short: Decimal
    post_gross: Decimal
    post_net: Decimal


class ExposureSnapshot(BaseModel):
    """One deterministic exposure snapshot in account home currency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_currency: str
    symbols: tuple[SymbolExposure, ...]
    category_totals: tuple[tuple[str, Decimal, Decimal], ...]  # (category, gross, net)
    currency_direction_totals: tuple[tuple[str, Decimal, Decimal], ...]
    correlated_group_totals: tuple[tuple[str, Decimal], ...]  # (group, gross)
    total_pre_gross: Decimal
    total_pre_net: Decimal
    total_post_gross: Decimal
    total_post_net: Decimal
    long_total: Decimal
    short_total: Decimal
    concentration: Decimal  # max symbol gross / total gross
    leverage: Decimal  # gross / equity
    conversion_evidence: tuple[tuple[str, str], ...]  # (symbol, source_id)
    correlation_evidence: tuple[tuple[str, str], ...]  # (group, source_id)


class ExposureError(RuntimeError):
    """A classified fail-closed exposure failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"exposure aggregation failed ({kind}): {detail}")


class ExposureRuleResult(BaseModel):
    """One stable typed exposure-limit verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    limit: str = Field(min_length=1)
    passed: bool
    value: str
    ceiling: str
    detail: str = ""


class ExposureLimits(BaseModel):
    """One deterministic exposure-limit set (None = unconfigured)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_single_order_notional: Decimal | None = None
    max_symbol_exposure: Decimal | None = None
    max_category_exposure: Decimal | None = None
    max_direction_exposure: Decimal | None = None
    max_gross_exposure: Decimal | None = None
    max_net_exposure: Decimal | None = None
    max_leverage: Decimal | None = None
    max_concentration_pct: Decimal | None = None

    @field_validator(
        "max_single_order_notional",
        "max_symbol_exposure",
        "max_category_exposure",
        "max_direction_exposure",
        "max_gross_exposure",
        "max_net_exposure",
        "max_leverage",
        "max_concentration_pct",
        mode="before",
    )
    @classmethod
    def limits_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


def _evidence_map(
    items: tuple[BaseModel, ...], field: str
) -> dict[str, Any]:
    return {getattr(item, field): item for item in items}


def compute_exposure(
    inputs: ExposureInputs,
    *,
    clock: Callable[[], datetime] | None = None,
) -> ExposureSnapshot:
    """Compute one deterministic home-currency exposure snapshot.

    Fail-closed evidence requirements (AC-M08-W03-03):

    - every position and pending-order symbol needs a price, a
      conversion factor, a category, and a currency direction;
    - conversion factors must be fresh (within
      ``conversion_max_age_seconds``) and positive;
    - when correlation groups are configured, every exposure symbol must
      belong to exactly one group;
    - exposure is always computed at mid prices times conversion
      factors — never at nominal units or cost basis.
    """
    prices = _evidence_map(inputs.prices, "symbol")
    conversions = _evidence_map(inputs.conversions, "symbol")
    categories = _evidence_map(inputs.categories, "symbol")
    directions = _evidence_map(inputs.currency_directions, "symbol")
    now = (clock or (lambda: datetime.now(UTC)))()

    symbols: set[str] = set()
    for position in inputs.positions:
        symbols.add(position.symbol)
    for pending in inputs.pending_orders:
        symbols.add(pending.symbol)

    for symbol in sorted(symbols):
        if symbol not in prices:
            raise ExposureError(
                "missing_price", f"no price evidence for {symbol}"
            )
        if symbol not in conversions:
            raise ExposureError(
                "missing_conversion", f"no conversion evidence for {symbol}"
            )
        conversion = conversions[symbol]
        age = (now - conversion.captured_at).total_seconds()
        if conversion.factor <= 0:
            raise ExposureError(
                "invalid_conversion",
                f"conversion factor for {symbol} is not positive",
            )
        if age > inputs.conversion_max_age_seconds:
            raise ExposureError(
                "stale_conversion",
                f"conversion evidence for {symbol} is {age:.1f}s old",
            )
        if symbol not in categories:
            raise ExposureError(
                "missing_category", f"no category evidence for {symbol}"
            )
        if symbol not in directions:
            raise ExposureError(
                "missing_currency_direction",
                f"no currency-direction evidence for {symbol}",
            )

    if inputs.correlation_groups:
        group_membership: dict[str, str | None] = {}
        for symbol in sorted(symbols):
            matched = [
                group
                for group in inputs.correlation_groups
                if symbol in group.symbols
            ]
            if len(matched) != 1:
                raise ExposureError(
                    "unsupported_correlation",
                    f"{symbol} belongs to {len(matched)} correlation groups; "
                    "exactly one is required",
                )
            group_membership[symbol] = matched[0].group

    # Long and short units are separate magnitudes: net = long - short,
    # gross = both legs (hedged positions still carry real notional).
    long_units: dict[str, Decimal] = {}
    short_units: dict[str, Decimal] = {}
    order_units: dict[str, Decimal] = {}
    for position in inputs.positions:
        long_units[position.symbol] = position.long_units
        short_units[position.symbol] = position.short_units
    for pending in inputs.pending_orders:
        order_units[pending.symbol] = (
            order_units.get(pending.symbol, Decimal("0")) + pending.units
        )

    symbol_exposures: list[SymbolExposure] = []
    for symbol in sorted(symbols):
        price = prices[symbol].mid
        factor = conversions[symbol].factor
        category = categories[symbol].category
        currency = directions[symbol].currency
        home = price * factor

        long = long_units.get(symbol, Decimal("0"))
        short = short_units.get(symbol, Decimal("0"))
        order = order_units.get(symbol, Decimal("0"))
        pre_net = long - short
        post_net = pre_net + order
        post_long = max(post_net, Decimal("0"))
        post_short = max(-post_net, Decimal("0"))
        symbol_exposures.append(
            SymbolExposure(
                symbol=symbol,
                category=category,
                currency=currency,
                pre_long=long * home,
                pre_short=short * home,
                pre_gross=(long + short) * home,
                pre_net=pre_net * home,
                post_long=post_long * home,
                post_short=post_short * home,
                post_gross=(long + short + abs(order)) * home,
                post_net=post_net * home,
            )
        )

    category_gross: dict[str, Decimal] = {}
    category_net: dict[str, Decimal] = {}
    currency_gross: dict[str, Decimal] = {}
    currency_net: dict[str, Decimal] = {}
    group_gross: dict[str, Decimal] = {}
    total_pre_gross = Decimal("0")
    total_pre_net = Decimal("0")
    total_post_gross = Decimal("0")
    total_post_net = Decimal("0")
    long_total = Decimal("0")
    short_total = Decimal("0")
    for exposure in symbol_exposures:
        category_gross[exposure.category] = (
            category_gross.get(exposure.category, Decimal("0"))
            + exposure.post_gross
        )
        category_net[exposure.category] = (
            category_net.get(exposure.category, Decimal("0"))
            + exposure.post_net
        )
        currency_gross[exposure.currency] = (
            currency_gross.get(exposure.currency, Decimal("0"))
            + exposure.post_gross
        )
        currency_net[exposure.currency] = (
            currency_net.get(exposure.currency, Decimal("0"))
            + exposure.post_net
        )
        if inputs.correlation_groups:
            group = group_membership[exposure.symbol]
            assert group is not None
            group_gross[group] = (
                group_gross.get(group, Decimal("0")) + exposure.post_gross
            )
        total_pre_gross += exposure.pre_gross
        total_pre_net += exposure.pre_net
        total_post_gross += exposure.post_gross
        total_post_net += exposure.post_net
        long_total += exposure.post_long
        short_total += exposure.post_short

    concentration = Decimal("0")
    if total_post_gross > 0:
        concentration = max(
            (exposure.post_gross / total_post_gross for exposure in symbol_exposures),
            default=Decimal("0"),
        )

    return ExposureSnapshot(
        home_currency=inputs.home_currency,
        symbols=tuple(symbol_exposures),
        category_totals=tuple(
            (category, category_gross[category], category_net[category])
            for category in sorted(category_gross)
        ),
        currency_direction_totals=tuple(
            (currency, currency_gross[currency], currency_net[currency])
            for currency in sorted(currency_gross)
        ),
        correlated_group_totals=tuple(
            (group, group_gross[group]) for group in sorted(group_gross)
        ),
        total_pre_gross=total_pre_gross,
        total_pre_net=total_pre_net,
        total_post_gross=total_post_gross,
        total_post_net=total_post_net,
        long_total=long_total,
        short_total=short_total,
        concentration=concentration,
        leverage=total_post_gross / inputs.equity,
        conversion_evidence=tuple(
            (symbol, conversions[symbol].source_id) for symbol in sorted(symbols)
        ),
        correlation_evidence=tuple(
            (group, inputs.correlation_groups[i].source_id)
            for i, group in enumerate(sorted(group_gross))
        ),
    )


def evaluate_exposure_limits(
    snapshot: ExposureSnapshot,
    limits: ExposureLimits,
    *,
    order_symbol: str | None = None,
    order_notional: Decimal | None = None,
) -> tuple[ExposureRuleResult, ...]:
    """Evaluate every configured limit against the post-trade snapshot."""
    results: list[ExposureRuleResult] = []

    def _check(
        limit: str,
        value: Decimal,
        ceiling: Decimal | None,
        *,
        label: str,
    ) -> None:
        if ceiling is None:
            return
        passed = value <= ceiling
        results.append(
            ExposureRuleResult(
                limit=limit,
                passed=passed,
                value=str(value),
                ceiling=str(ceiling),
                detail=(
                    f"{label} within ceiling"
                    if passed
                    else f"{label} exceeds ceiling"
                ),
            )
        )

    if limits.max_single_order_notional is not None:
        if order_notional is None:
            results.append(
                ExposureRuleResult(
                    limit="max_single_order_notional",
                    passed=False,
                    value="unknown",
                    ceiling=str(limits.max_single_order_notional),
                    detail="order notional not supplied; fails closed",
                )
            )
        else:
            _check(
                "max_single_order_notional",
                order_notional,
                limits.max_single_order_notional,
                label="single-order notional",
            )
    if order_symbol is not None:
        for exposure in snapshot.symbols:
            if exposure.symbol != order_symbol:
                continue
            _check(
                "max_symbol_exposure",
                exposure.post_gross,
                limits.max_symbol_exposure,
                label=f"{order_symbol} post-trade gross",
            )
            break
    for category, gross, _net in snapshot.category_totals:
        _check(
            "max_category_exposure",
            gross,
            limits.max_category_exposure,
            label=f"{category} post-trade gross",
        )
    _check(
        "max_direction_exposure",
        max(snapshot.long_total, snapshot.short_total),
        limits.max_direction_exposure,
        label="largest direction total",
    )
    _check(
        "max_gross_exposure",
        snapshot.total_post_gross,
        limits.max_gross_exposure,
        label="total post-trade gross",
    )
    _check(
        "max_net_exposure",
        abs(snapshot.total_post_net),
        limits.max_net_exposure,
        label="absolute post-trade net",
    )
    _check(
        "max_leverage",
        snapshot.leverage,
        limits.max_leverage,
        label="gross leverage",
    )
    _check(
        "max_concentration_pct",
        snapshot.concentration,
        limits.max_concentration_pct,
        label="symbol concentration",
    )
    return tuple(results)


__all__ = [
    "CategoryEvidence",
    "ConversionEvidence",
    "CorrelationEvidence",
    "CurrencyDirectionEvidence",
    "ExposureError",
    "ExposureInputs",
    "ExposureLimits",
    "ExposureRuleResult",
    "ExposureSnapshot",
    "PendingOrderLeg",
    "PositionLeg",
    "PriceEvidence",
    "SymbolExposure",
    "compute_exposure",
    "evaluate_exposure_limits",
]
