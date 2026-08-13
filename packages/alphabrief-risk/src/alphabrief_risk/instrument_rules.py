"""Deterministic instrument constraint rules (M08-W02).

Evaluates catalog allowability, active and tradeable state, units and
price precision, minimum and maximum size, position cap, session state,
and every execution-relevant freshness signal as stable typed rule
results (REQ-RISK-002, REQ-OANDA-003, REQ-OANDA-009, REQ-OANDA-010).
The layer is pure and deterministic: identical evidence produces
identical rule results, a failing rule can never be silenced, and any
fail-closed input (unknown instrument, inactive catalog state, broker
``tradeable`` false, closed or holiday session, stale session evidence,
stale quote, stale catalog, incomplete candle, excessive gap, missing
conversion, partial pricing coverage) rejects new exposure.

Instrument normalization happens before the final risk evaluation:
prices are quantized to the instrument's ``display_precision`` and units
to ``trade_units_precision`` (fractional units beyond the precision are
rejected, never silently rounded into a different order). Executable
inputs are bound to the approved decision through a deterministic hash,
so any post-decision change of symbol, units, price, instrument version,
or snapshot hash invalidates execution (REQ-RISK-010, AC-M08-W02-03).
"""

from __future__ import annotations

import hashlib
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("instrument rule decimal values must not be floats")
    return value


def _decimal_power(digits: int) -> Decimal:
    """``10^-digits`` as a Decimal quantize exponent."""
    return Decimal("1").scaleb(-digits)


class MarketEvidence(BaseModel):
    """One deterministic snapshot of execution-relevant market evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_known: bool = True
    catalog_active: bool = True
    tradeable: bool = True
    session_open: bool = True
    session_holiday: bool = False
    session_evidence_stale: bool = False
    quote_present: bool = True
    quote_fresh: bool = True
    candle_complete: bool = True
    gap_excessive: bool = False
    conversion_present: bool = True
    pricing_coverage_complete: bool = True


class InstrumentRuleResult(BaseModel):
    """One stable typed rule verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: str = Field(min_length=1)
    passed: bool
    reason: str = Field(min_length=1)


class NormalizedInputs(BaseModel):
    """Normalized executable inputs (Decimal-safe, precision-quantized)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    units: Decimal
    price: Decimal | None = None

    @field_validator("units", "price", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class InstrumentConstraintError(ValueError):
    """A classified instrument-constraint failure (always fail-closed)."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"instrument constraint failed ({kind}): {detail}")


def normalize_instrument_units(
    units: Decimal, metadata: InstrumentMetadata
) -> Decimal:
    """Quantize units to the instrument's trade-units precision.

    Units not representable at that precision raise an
    :class:`InstrumentConstraintError` instead of being silently rounded
    into a different order.
    """
    exponent = _decimal_power(metadata.trade_units_precision)
    try:
        quantized = units.quantize(exponent)
    except InvalidOperation as exc:
        raise InstrumentConstraintError(
            "units_precision",
            f"units {units} exceed trade_units_precision "
            f"{metadata.trade_units_precision}",
        ) from exc
    if quantized != units:
        raise InstrumentConstraintError(
            "units_precision",
            f"units {units} exceed trade_units_precision "
            f"{metadata.trade_units_precision}",
        )
    return quantized


def normalize_instrument_price(
    price: Decimal, metadata: InstrumentMetadata
) -> Decimal:
    """Normalize a price to the instrument's display precision.

    The price must already be representable at ``display_precision``
    digits — silent rounding would change the intended order, so a
    non-representable price raises an
    :class:`InstrumentConstraintError` instead.
    """
    if price <= 0:
        raise InstrumentConstraintError("price_invalid", "price must be positive")
    exponent = _decimal_power(metadata.display_precision)
    quantized = price.quantize(exponent, rounding=ROUND_HALF_UP)
    if quantized != price:
        raise InstrumentConstraintError(
            "price_precision",
            f"price {price} exceeds display_precision "
            f"{metadata.display_precision}",
        )
    return quantized


def evaluate_instrument_rules(
    *,
    symbol: str,
    units: Decimal,
    price: Decimal | None,
    metadata: InstrumentMetadata | None,
    evidence: MarketEvidence,
    current_position_units: Decimal = Decimal("0"),
) -> tuple[InstrumentRuleResult, ...]:
    """Evaluate every deterministic instrument rule for one order input.

    Order of rules is fixed; results are stable for identical evidence.
    """
    results: list[InstrumentRuleResult] = []
    symbol = symbol.strip().upper()
    if not symbol:
        raise InstrumentConstraintError("symbol_invalid", "symbol is empty")

    def _add(rule: str, passed: bool, reason: str) -> None:
        results.append(
            InstrumentRuleResult(rule=rule, passed=passed, reason=reason)
        )

    if not evidence.catalog_known:
        _add("catalog_known", False, f"instrument {symbol} is not in the catalog")
    elif metadata is None:
        _add(
            "catalog_known",
            False,
            f"no metadata for instrument {symbol}; treated as unknown",
        )
    else:
        _add("catalog_known", True, f"instrument {symbol} is in the catalog")

    _add(
        "catalog_active",
        evidence.catalog_active,
        "catalog state is active"
        if evidence.catalog_active
        else "catalog state is inactive",
    )
    _add(
        "broker_tradeable",
        evidence.tradeable,
        "broker reports tradeable"
        if evidence.tradeable
        else "broker reports not tradeable",
    )
    session_reasons: list[str] = []
    if evidence.session_holiday:
        session_reasons.append("holiday")
    if not evidence.session_open:
        session_reasons.append("closed")
    if evidence.session_evidence_stale:
        session_reasons.append("stale session evidence")
    session_blocked = "session blocked: " + ", ".join(session_reasons)
    _add(
        "session_open",
        not session_reasons,
        "session is open" if not session_reasons else session_blocked,
    )

    quote_reasons: list[str] = []
    if not evidence.quote_present:
        quote_reasons.append("no quote")
    if not evidence.quote_fresh:
        quote_reasons.append("stale quote")
    quote_blocked = "quote blocked: " + ", ".join(quote_reasons)
    _add(
        "quote_fresh",
        not quote_reasons,
        "quote is fresh" if not quote_reasons else quote_blocked,
    )
    _add(
        "candle_complete",
        evidence.candle_complete,
        "candle complete" if evidence.candle_complete else "incomplete candle",
    )
    _add(
        "gap_bounded",
        not evidence.gap_excessive,
        "no excessive gap" if not evidence.gap_excessive else "excessive gap",
    )
    _add(
        "conversion_present",
        evidence.conversion_present,
        "conversion present"
        if evidence.conversion_present
        else "missing conversion",
    )
    _add(
        "pricing_coverage_complete",
        evidence.pricing_coverage_complete,
        "pricing coverage complete"
        if evidence.pricing_coverage_complete
        else "partial pricing coverage",
    )

    if metadata is None:
        # Metadata-gated rules cannot pass without metadata.
        for rule, reason in (
            ("units_precision", "no metadata for precision check"),
            ("price_precision", "no metadata for precision check"),
            ("minimum_size", "no metadata for minimum size check"),
            ("maximum_order_units", "no metadata for maximum order units check"),
            ("position_cap", "no metadata for position cap check"),
        ):
            _add(rule, False, reason)
        return tuple(results)

    try:
        normalized_units = normalize_instrument_units(units, metadata)
    except InstrumentConstraintError as exc:
        normalized_units = units
        _add("units_precision", False, exc.detail)
    else:
        precision = metadata.trade_units_precision
        _add("units_precision", True, f"units representable at precision {precision}")

    if price is None:
        _add("price_precision", False, "no price supplied for precision check")
    else:
        try:
            normalize_instrument_price(price, metadata)
        except InstrumentConstraintError as exc:
            _add("price_precision", False, exc.detail)
        else:
            precision = metadata.display_precision
            _add(
                "price_precision", True,
                f"price representable at precision {precision}",
            )

    minimum_size = metadata.minimum_trade_size
    size_ok = abs(normalized_units) >= minimum_size
    _add(
        "minimum_size",
        size_ok,
        f"units >= minimum trade size {minimum_size}"
        if size_ok
        else f"units below minimum trade size {minimum_size}",
    )
    _add(
        "normalized_zero",
        normalized_units != 0,
        "normalized units are nonzero"
        if normalized_units != 0
        else "normalized units are zero",
    )

    if metadata.maximum_order_units > 0:
        order_units_ok = abs(normalized_units) <= metadata.maximum_order_units
        _add(
            "maximum_order_units",
            order_units_ok,
            f"units within maximum order units {metadata.maximum_order_units}"
            if order_units_ok
            else f"units exceed maximum order units {metadata.maximum_order_units}",
        )
    else:
        _add("maximum_order_units", True, "no maximum order units configured")

    if metadata.maximum_position_size > 0:
        projected = abs(current_position_units) + abs(normalized_units)
        cap_ok = projected <= metadata.maximum_position_size
        _add(
            "position_cap",
            cap_ok,
            (
                f"projected position {projected} "
                f"within cap {metadata.maximum_position_size}"
            )
            if cap_ok
            else (
                f"projected position {projected} "
                f"exceeds cap {metadata.maximum_position_size}"
            ),
        )
    else:
        _add("position_cap", True, "no maximum position size configured")

    return tuple(results)

    try:
        normalized_units = normalize_instrument_units(units, metadata)
    except InstrumentConstraintError as exc:
        normalized_units = units
        _add("units_precision", False, exc.detail)
    else:
        precision = metadata.trade_units_precision
        _add("units_precision", True, f"units representable at precision {precision}")

    if price is None:
        _add("price_precision", False, "no price supplied for precision check")
    else:
        try:
            normalize_instrument_price(price, metadata)
        except InstrumentConstraintError as exc:
            _add("price_precision", False, exc.detail)
        else:
            precision = metadata.display_precision
            _add(
                "price_precision", True,
                f"price representable at precision {precision}",
            )

    minimum_size = metadata.minimum_trade_size
    _add(
        "minimum_size",
        abs(normalized_units) >= minimum_size,
        f"units >= minimum trade size {minimum_size}"
        if abs(normalized_units) >= minimum_size
        else f"units below minimum trade size {minimum_size}",
    )
    _add(
        "normalized_zero",
        normalized_units != 0,
        "normalized units are nonzero"
        if normalized_units != 0
        else "normalized units are zero",
    )

    if metadata.maximum_order_units > 0:
        _add(
            "maximum_order_units",
            abs(normalized_units) <= metadata.maximum_order_units,
            f"units within maximum order units {metadata.maximum_order_units}"
            if abs(normalized_units) <= metadata.maximum_order_units
            else f"units exceed maximum order units {metadata.maximum_order_units}",
        )
    else:
        _add("maximum_order_units", True, "no maximum order units configured")

    if metadata.maximum_position_size > 0:
        projected = abs(current_position_units) + abs(normalized_units)
        _add(
            "position_cap",
            projected <= metadata.maximum_position_size,
            (
                f"projected position {projected} "
                f"within cap {metadata.maximum_position_size}"
            )
            if projected <= metadata.maximum_position_size
            else (
                f"projected position {projected} "
                f"exceeds cap {metadata.maximum_position_size}"
            ),
        )
    else:
        _add("position_cap", True, "no maximum position size configured")

    return tuple(results)


def bind_execution_inputs(
    decision_id: str,
    *,
    symbol: str,
    units: Decimal,
    price: Decimal | None,
    instrument_version: str | None,
    snapshot_hash: str | None,
) -> str:
    """Bind executable inputs to an approved decision as one hash.

    Any post-decision change of symbol, units, price, instrument
    version, or snapshot hash produces a different hash and invalidates
    execution (AC-M08-W02-03, REQ-RISK-010).
    """
    payload = "|".join(
        [
            decision_id,
            symbol.strip().upper(),
            str(units),
            "" if price is None else str(price),
            instrument_version or "",
            snapshot_hash or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_execution_inputs(
    decision_id: str,
    bound_hash: str,
    *,
    symbol: str,
    units: Decimal,
    price: Decimal | None,
    instrument_version: str | None,
    snapshot_hash: str | None,
) -> bool:
    """Return True only when the executable inputs still match the hash
    bound to the approved decision."""
    return bind_execution_inputs(
        decision_id,
        symbol=symbol,
        units=units,
        price=price,
        instrument_version=instrument_version,
        snapshot_hash=snapshot_hash,
    ) == bound_hash


__all__ = [
    "InstrumentConstraintError",
    "InstrumentRuleResult",
    "MarketEvidence",
    "NormalizedInputs",
    "bind_execution_inputs",
    "evaluate_instrument_rules",
    "normalize_instrument_price",
    "normalize_instrument_units",
    "validate_execution_inputs",
]
