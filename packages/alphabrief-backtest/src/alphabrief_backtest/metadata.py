"""Versioned OANDA-semantic backtest instrument metadata (M12-W03).

Backtest execution resolves the same instrument fields the OANDA
practice runtime uses (display/trade-units precision, minimum trade
size, maximum order units / position size, margin rate) through a
versioned mirror. ``SEMANTICS_VERSION`` and ``SEMANTICS_DIFFERENCES``
explicitly record the relationship to the practice runtime so any drift
is visible (REQ-STRAT-008). Normalization mirrors
``alphabrief_risk.instrument_rules``: a value that is not representable
at the declared precision is rejected, never silently rounded into a
different order.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from alphabrief_strategy import StrategyInstrumentCategory
from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Bump when the mirrored OANDA practice fields or rules change.
SEMANTICS_VERSION = "oanda-practice-mirror-1"

#: Declared differences vs the practice runtime. Empty = the mirrored
#: fields and normalization rules below are used unchanged by both.
SEMANTICS_DIFFERENCES: tuple[str, ...] = ()


class BacktestConstraintError(ValueError):
    """Raised when an order violates a deterministic OANDA constraint."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def _decimal_power(precision: int) -> Decimal:
    return Decimal(1).scaleb(-precision)


class BacktestSessionWindow(BaseModel):
    """A weekly session window in UTC minutes (mirrors M05-W04 sessions).

    ``end`` at or before ``start`` wraps by a full week (overnight and
    24x7 sessions). UTC-fixed windows make DST transitions
    deterministic.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_weekday: int = Field(ge=0, le=6)
    start_minutes: int = Field(ge=0, le=1439)
    end_weekday: int = Field(ge=0, le=6)
    end_minutes: int = Field(ge=0, le=1439)

    def is_open(self, moment: datetime) -> bool:
        """Deterministic open/closed verdict for one UTC moment.

        Naive moments are treated as UTC and any timezone is converted
        to UTC first (UTC-fixed windows; mirrors the practice runtime).
        """
        utc_moment = (
            moment.replace(tzinfo=UTC)
            if moment.tzinfo is None
            else moment.astimezone(UTC)
        )
        start = self.start_weekday * 1440 + self.start_minutes
        end = self.end_weekday * 1440 + self.end_minutes
        if end <= start:
            end += 7 * 1440
        now = (
            utc_moment.weekday() * 1440
            + utc_moment.hour * 60
            + utc_moment.minute
        )
        return start <= now < end


#: Per-category default windows, mirroring the practice runtime's
#: ``CATEGORY_SESSIONS`` (UTC-fixed; unknown categories get no window
#: and therefore fail closed).
CATEGORY_SESSION_WINDOWS: dict[StrategyInstrumentCategory, BacktestSessionWindow] = {
    "CURRENCY": BacktestSessionWindow(
        start_weekday=0, start_minutes=21 * 60, end_weekday=4, end_minutes=21 * 60
    ),
    "METAL": BacktestSessionWindow(
        start_weekday=0, start_minutes=21 * 60, end_weekday=4, end_minutes=21 * 60
    ),
    "INDEX_CFD": BacktestSessionWindow(
        start_weekday=0, start_minutes=0, end_weekday=4, end_minutes=21 * 60
    ),
    "COMMODITY_CFD": BacktestSessionWindow(
        start_weekday=0, start_minutes=0, end_weekday=4, end_minutes=21 * 60
    ),
    "BOND_CFD": BacktestSessionWindow(
        start_weekday=0, start_minutes=0, end_weekday=4, end_minutes=21 * 60
    ),
    "EQUITY_CFD": BacktestSessionWindow(
        start_weekday=0, start_minutes=0, end_weekday=4, end_minutes=21 * 60
    ),
    "CRYPTO_CFD": BacktestSessionWindow(
        start_weekday=0, start_minutes=0, end_weekday=6, end_minutes=23 * 60 + 59
    ),
    "OTHER_CFD": BacktestSessionWindow(
        start_weekday=0, start_minutes=0, end_weekday=4, end_minutes=21 * 60
    ),
}


def default_session_window(
    category: StrategyInstrumentCategory,
) -> BacktestSessionWindow:
    """The deterministic default window for one category."""
    return CATEGORY_SESSION_WINDOWS[category]


class BacktestInstrumentMetadata(BaseModel):
    """One instrument's backtest-facing OANDA metadata (REQ-OANDA-003).

    All numeric fields are ``Decimal``. ``session_window`` defaults to
    the category window when omitted; an unknown category has no window
    and therefore fails closed (never silently assumed open).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    category: StrategyInstrumentCategory
    display_precision: int
    trade_units_precision: int
    minimum_trade_size: Decimal = Field(ge=0)
    maximum_order_units: Decimal = Field(ge=0)
    maximum_position_size: Decimal = Field(ge=0)
    margin_rate: Decimal = Field(gt=0)
    spread_bps: Decimal = Field(ge=0)
    financing_rate_per_unit_per_day: Decimal = Field(default=Decimal("0"))
    session_window: BacktestSessionWindow | None = None

    @field_validator("display_precision", "trade_units_precision", mode="before")
    @classmethod
    def precision_must_be_integer(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(
                f"precision must be an integer, got {value!r}"
            )
        return int(str(value))

    def effective_session_window(self) -> BacktestSessionWindow:
        """The window actually used: per-instrument override or category."""
        if self.session_window is not None:
            return self.session_window
        return default_session_window(self.category)


class BacktestMetadataSet(BaseModel):
    """One immutable, versioned metadata snapshot for many instruments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    instruments: dict[str, BacktestInstrumentMetadata] = Field(min_length=1)

    @field_validator("version")
    @classmethod
    def version_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("metadata set version must not be blank")
        return normalized

    def require(self, symbol: str) -> BacktestInstrumentMetadata:
        """Resolve one instrument's metadata deterministically."""
        try:
            return self.instruments[symbol]
        except KeyError:
            raise KeyError(
                f"no backtest metadata for instrument {symbol!r}"
            ) from None


def normalize_backtest_units(
    units: Decimal,
    metadata: BacktestInstrumentMetadata,
) -> Decimal:
    """Quantize units to the instrument's trade-units precision.

    Units not representable at that precision raise
    :class:`BacktestConstraintError` instead of being silently rounded
    into a different order (mirrors the practice runtime rule).
    """
    exponent = _decimal_power(metadata.trade_units_precision)
    try:
        quantized = units.quantize(exponent)
    except InvalidOperation as exc:
        raise BacktestConstraintError(
            "units_precision",
            f"units {units} exceed trade_units_precision "
            f"{metadata.trade_units_precision}",
        ) from exc
    if quantized != units:
        raise BacktestConstraintError(
            "units_precision",
            f"units {units} exceed trade_units_precision "
            f"{metadata.trade_units_precision}",
        )
    return quantized


def normalize_backtest_price(
    price: Decimal,
    metadata: BacktestInstrumentMetadata,
) -> Decimal:
    """Normalize a price to the instrument's display precision.

    The price must already be representable at ``display_precision``
    digits; a non-representable price raises
    :class:`BacktestConstraintError` (mirrors the practice runtime).
    """
    if price <= 0:
        raise BacktestConstraintError("price_invalid", "price must be positive")
    exponent = _decimal_power(metadata.display_precision)
    quantized = price.quantize(exponent, rounding=ROUND_HALF_UP)
    if quantized != price:
        raise BacktestConstraintError(
            "price_precision",
            f"price {price} exceeds display_precision "
            f"{metadata.display_precision}",
        )
    return quantized


def round_backtest_price(
    price: Decimal,
    metadata: BacktestInstrumentMetadata,
) -> Decimal:
    """Round an engine-computed price to display precision.

    Unlike :func:`normalize_backtest_price` (which validates
    user-supplied prices and rejects non-representable values), this
    rounds arithmetic results — spread and slippage products — the way
    the broker rounds execution prices. Never raises for precision.
    """
    if price <= 0:
        raise BacktestConstraintError("price_invalid", "price must be positive")
    exponent = _decimal_power(metadata.display_precision)
    return price.quantize(exponent, rounding=ROUND_HALF_UP)


__all__ = [
    "CATEGORY_SESSION_WINDOWS",
    "SEMANTICS_DIFFERENCES",
    "SEMANTICS_VERSION",
    "BacktestConstraintError",
    "BacktestInstrumentMetadata",
    "BacktestMetadataSet",
    "BacktestSessionWindow",
    "default_session_window",
    "normalize_backtest_price",
    "normalize_backtest_units",
    "round_backtest_price",
]
