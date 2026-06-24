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
from typing import Any

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
        for audit / diagnostics; not required for the cap check but
        cheap to carry.
    cash
        Account cash from the broker snapshot. May be negative; surfaced
        for audit only (the exposure check does not gate on cash).
    account_id
        Stable broker account identifier.
    captured_at
        When the snapshot was taken. Must be timezone-aware.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    current_total_exposure: Decimal = Field(ge=0)
    exposure_by_symbol: dict[str, Decimal] = Field(default_factory=dict)
    cash: Decimal
    account_id: str = Field(min_length=1)
    captured_at: datetime

    @field_validator("current_total_exposure", "cash", mode="before")
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

    @field_validator("captured_at")
    @classmethod
    def _captured_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("captured_at must be timezone-aware")
        return value


__all__ = ["AccountExposureContext"]
