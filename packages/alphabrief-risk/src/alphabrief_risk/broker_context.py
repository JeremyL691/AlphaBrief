"""Broker-fresh risk context value object (M08-W01).

One versioned, frozen, Decimal-safe input contract that every execution
path builds through the same context service before risk evaluation and
submit, carrying account state, positions, pending orders, trades,
bid/ask prices, conversions, catalog version, reconciliation state,
health state, source IDs, capture times, and freshness verdicts
(REQ-RISK-001, REQ-PLAT-009). A plain data carrier owned by the risk
layer: construction is strict (``float`` rejected, unknown fields
forbidden, immutable), so a partial or inconsistent context cannot
exist silently (AC-M08-W01-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Version of the context schema itself (bumped on shape/semantics change).
DEFAULT_CONTEXT_VERSION = "2026-08-13.1"

#: Version of the execution policy stamped on every context (shared authority).
DEFAULT_POLICY_VERSION = "2026-08-13.1"

#: Deterministic tolerance for the OANDA margin identity
#: ``margin_available == nav - margin_used``.
MARGIN_IDENTITY_TOLERANCE = Decimal("0.01")


def _reject_float(value: Any) -> Any:
    """Reject ``float`` so context figures stay Decimal-first."""
    if isinstance(value, float):
        raise ValueError("broker risk context decimal values must not be floats")
    return value


def _utc_time(value: Any) -> datetime:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError("context time must be a datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class AccountStateDatum(BaseModel):
    """Broker account identity and state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1)
    state: str = Field(min_length=1)
    tradeable: bool
    home_currency: str = Field(min_length=1)


class PositionDatum(BaseModel):
    """One open position with distinct sides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    long_units: Decimal = Decimal("0")
    short_units: Decimal = Decimal("0")
    average_price: Decimal | None = None

    @field_validator("long_units", "short_units", "average_price", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class PendingOrderDatum(BaseModel):
    """One pending (not terminal) broker order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_order_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    units: Decimal = Decimal("0")
    state: str = Field(min_length=1)

    @field_validator("units", mode="before")
    @classmethod
    def units_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class TradeDatum(BaseModel):
    """One open broker trade."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_trade_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    current_units: Decimal = Decimal("0")
    state: str = Field(min_length=1)

    @field_validator("current_units", mode="before")
    @classmethod
    def units_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class PriceDatum(BaseModel):
    """One bid/ask price observation with its capture time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    bid: Decimal
    ask: Decimal
    captured_at: datetime

    @field_validator("bid", "ask", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("captured_at", mode="before")
    @classmethod
    def time_must_be_utc(cls, value: Any) -> Any:
        return _utc_time(value)

    @property
    def spread(self) -> Decimal:
        """The deterministic ask - bid spread (>= 0 when not crossed)."""
        return self.ask - self.bid


class ConversionDatum(BaseModel):
    """One quote-to-home conversion factor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    quote_home: Decimal = Field(gt=0)
    factor: Decimal = Field(gt=0)

    @field_validator("quote_home", "factor", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class FreshnessVerdict(BaseModel):
    """One per-source freshness verdict with its evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1)
    fresh: bool
    captured_at: datetime | None = None
    max_age_seconds: int | None = None
    detail: str = ""

    @field_validator("captured_at", mode="before")
    @classmethod
    def time_must_be_utc(cls, value: Any) -> Any:
        if value is None:
            return None
        return _utc_time(value)


ReconciliationState = Literal["clean", "frozen", "unknown"]
HealthState = Literal["healthy", "unhealthy", "unknown"]


class BrokerRiskContext(BaseModel):
    """One versioned broker-fresh risk context (immutable)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    context_version: str = DEFAULT_CONTEXT_VERSION
    policy_version: str = DEFAULT_POLICY_VERSION
    account: AccountStateDatum
    captured_at: datetime
    source_ids: tuple[str, ...] = Field(min_length=1)
    balance: Decimal
    nav: Decimal
    margin_used: Decimal
    margin_available: Decimal
    positions: tuple[PositionDatum, ...] = ()
    pending_orders: tuple[PendingOrderDatum, ...] = ()
    trades: tuple[TradeDatum, ...] = ()
    prices: tuple[PriceDatum, ...] = ()
    conversions: tuple[ConversionDatum, ...] = ()
    catalog_version: str | None = None
    reconciliation_state: ReconciliationState = "unknown"
    health_state: HealthState = "unknown"
    freshness: tuple[FreshnessVerdict, ...] = ()

    @field_validator(
        "balance",
        "nav",
        "margin_used",
        "margin_available",
        mode="before",
    )
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("captured_at", mode="before")
    @classmethod
    def time_must_be_utc(cls, value: Any) -> Any:
        return _utc_time(value)

    @property
    def all_fresh(self) -> bool:
        """True when every recorded freshness verdict is fresh."""
        return all(verdict.fresh for verdict in self.freshness)

    def inconsistencies(self) -> tuple[str, ...]:
        """Deterministic internal-consistency violations (empty = consistent).

        Checks that never depend on external state:

        - the margin identity ``margin_available == nav - margin_used``
          within the explicit tolerance;
        - every price is uncrossed (``bid <= ask``);
        - every conversion factor is positive (guaranteed by the schema).

        Clock-dependent checks (a capture time in the future) live in the
        context builder, which owns the authoritative clock.
        """
        violations: list[str] = []
        expected_available = self.nav - self.margin_used
        if abs(self.margin_available - expected_available) > MARGIN_IDENTITY_TOLERANCE:
            violations.append(
                "margin identity violated: "
                f"margin_available={self.margin_available} != "
                f"nav - margin_used={expected_available}"
            )
        for price in self.prices:
            if price.bid > price.ask:
                violations.append(
                    f"crossed price for {price.symbol}: bid={price.bid} "
                    f"ask={price.ask}"
                )
        return tuple(violations)

    @property
    def internally_consistent(self) -> bool:
        """True when no deterministic consistency violation exists."""
        return not self.inconsistencies()


__all__ = [
    "AccountStateDatum",
    "BrokerRiskContext",
    "ConversionDatum",
    "DEFAULT_CONTEXT_VERSION",
    "DEFAULT_POLICY_VERSION",
    "FreshnessVerdict",
    "HealthState",
    "MARGIN_IDENTITY_TOLERANCE",
    "PendingOrderDatum",
    "PositionDatum",
    "PriceDatum",
    "ReconciliationState",
    "TradeDatum",
]
