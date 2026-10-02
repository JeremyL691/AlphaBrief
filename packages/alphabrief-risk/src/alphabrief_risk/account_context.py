"""Account-level exposure context for runtime risk enforcement.

This module provides :class:`AccountExposureContext`, a frozen,
audit-friendly value object that carries the **live account state**
:class:`alphabrief_risk.RiskGate` needs to enforce the
``PaperExecutionPolicy.max_total_exposure`` cap at runtime.

It is deliberately a plain data carrier with **no dependency on the
execution layer**. The risk package sits below the execution package,
so :class:`RiskGate` must not import :class:`BrokerAdapter`,
:class:`Position`, or :class:`AccountSnapshot`. Instead, the execution
layer projects live broker state into this object and passes it to
``RiskGate.evaluate(..., account_context=...)``. The dependency arrow
stays one-way: execution -> risk, never the reverse.

The object is **advisory input only**. It never relaxes a risk limit;
it only lets the gate apply a tighten-only account-exposure check (see
:meth:`alphabrief_risk.RiskGate._check_account_exposure`). All decimal
inputs reject ``float`` (Decimal-first throughout, matching
:class:`alphabrief_core.PaperExecutionPolicy`).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _reject_float(value: Any) -> Any:
    """Reject ``float`` inputs so exposure figures stay Decimal-first.

    Mirrors
    :meth:`alphabrief_core.PaperExecutionPolicy.decimal_values_must_not_be_float`.
    """
    if isinstance(value, float):
        raise ValueError("account exposure decimal values must not be floats")
    return value


class AccountExposureContext(BaseModel):
    """Live account state projected for the runtime exposure check.

    Fields
    ----------
    current_total_exposure
        Gross long + short notional the caller computed from live
        positions (``sum(|qty| * mark_price)``). Always ``>= 0``.
    exposure_by_symbol
        Per-symbol gross notional, keyed by upper-cased symbol. Used
        for audit / diagnostics and for per-symbol / concentration
        checks; not required for the total cap but cheap to carry.
    cash
        Account cash from the broker snapshot. May be negative; surfaced
        for audit and as the base of ``equity`` when the caller projects
        it.
    account_id
        Stable broker account identifier.
    captured_at
        When the snapshot was taken. Must be timezone-aware.
    equity
        Optional account equity (``cash + sum(qty * mark)``) the caller
        projected. Required only when a rule that needs it (e.g. max
        leverage) is configured; the gate fails closed if it is missing.
        Carried here rather than computed in the gate so the projection
        stays in the execution layer (one-way dependency).
    reference_mark_prices
        Optional per-symbol live mark prices the caller supplied, keyed
        by upper-cased symbol. Used by the price-deviation check to
        compare the order's estimated price against the current market.
    equity_high_water_mark
        Optional peak equity seen so far (persisted across restarts by
        the caller). Required when ``max_drawdown_floor_pct`` is
        configured; the gate fails closed if it is missing.
    day_start_equity
        Optional equity at the start of the trading day. Required when
        ``max_daily_loss_pct`` is configured; the gate fails closed if
        it is missing.
    day_realized_pnl
        Optional realized P&L accumulated since day start. Surfaced for
        audit/diagnostics only; not gated on (advisory).
    open_position_count
        Number of instruments the account currently holds. Required by the
        max-open-positions rule.
    daily_open_count / daily_symbol_open_count
        New positions opened today (all symbols / this symbol). Required by
        the daily intent caps.
    quote_captured_at / quote_tradeable
        Freshness and tradeability of the quote for the order's symbol.
        Required by the quote rules.
    frozen_symbols
        Symbols temporarily barred from new exposure (for example after a
        losing streak), with the reason kept for the decision record.
    recent_high_impact_events
        Symbols with a high-impact macro/news event inside the rule-6
        window, mapped to the human-readable reason. The news layer
        classifies the headlines; the gate only reads this map.
    drawdown_block_reason
        Set when the rule-11 drawdown state machine currently blocks new
        exposure (3% for 48 hours, or 5% for the rest of the soak). The
        caller advances the persisted state; the gate only reads it.
    current_spread / recent_spreads
        The live spread and the same-period sample history rule 4 compares
        it against. The caller reads the samples from the durable quote
        store; the gate only applies the median rule.
    reconciliation_state
        The durable reconciliation state (``clean`` / ``frozen`` /
        ``unknown``) rule 1 reads: a frozen account opens no new exposure.
    symbol_types
        The broker's instrument classification per symbol (for example
        ``CURRENCY``), which rule 2 requires before an entry.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    current_total_exposure: Decimal = Field(ge=0)
    exposure_by_symbol: dict[str, Decimal] = Field(default_factory=dict)
    cash: Decimal
    account_id: str = Field(min_length=1)
    captured_at: datetime
    equity: Decimal | None = Field(default=None, ge=0)
    margin_used: Decimal | None = Field(default=None, ge=0)
    reference_mark_prices: dict[str, Decimal] = Field(default_factory=dict)
    equity_high_water_mark: Decimal | None = Field(default=None, ge=0)
    day_start_equity: Decimal | None = Field(default=None, ge=0)
    day_realized_pnl: Decimal | None = Field(default=None)
    open_position_count: int | None = Field(default=None, ge=0)
    daily_open_count: int | None = Field(default=None, ge=0)
    daily_symbol_open_count: int | None = Field(default=None, ge=0)
    quote_captured_at: datetime | None = None
    quote_tradeable: bool | None = None
    frozen_symbols: dict[str, str] = Field(default_factory=dict)
    recent_high_impact_events: dict[str, str] = Field(default_factory=dict)
    drawdown_block_reason: str | None = None
    current_spread: Decimal | None = Field(default=None, ge=0)
    recent_spreads: tuple[Decimal, ...] = ()
    reconciliation_state: Literal["clean", "frozen", "unknown"] | None = None
    symbol_types: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "current_total_exposure",
        "cash",
        "equity",
        "margin_used",
        "equity_high_water_mark",
        "day_start_equity",
        "day_realized_pnl",
        mode="before",
    )
    @classmethod
    def _decimal_values_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("exposure_by_symbol", mode="before")
    @classmethod
    def _exposure_by_symbol_must_not_contain_floats(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for inner in value.values():
                if isinstance(inner, float):
                    raise ValueError(
                        "account exposure decimal values must not be floats"
                    )
        return value

    @field_validator("reference_mark_prices", mode="before")
    @classmethod
    def _reference_mark_prices_must_not_contain_floats(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for inner in value.values():
                if isinstance(inner, float):
                    raise ValueError(
                        "account exposure decimal values must not be floats"
                    )
        return value

    @field_validator("captured_at")
    @classmethod
    def _captured_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("captured_at must be timezone-aware")
        return value


__all__ = ["AccountExposureContext"]
