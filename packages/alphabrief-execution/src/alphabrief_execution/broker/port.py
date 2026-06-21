"""Broker-neutral port types for AlphaBrief external paper execution.

The port defines the **only** contract that business code (strategy,
risk, research, dashboard) is allowed to depend on when interacting
with an external broker. Concrete broker SDKs (Alpaca, IBKR, ...)
live in sibling subpackages and must not leak their types past the
adapter boundary.

Phase 17 introduces one concrete adapter (Alpaca Paper). Adding a
second broker must not require any change outside this package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums (deliberately broker-neutral)
# ---------------------------------------------------------------------------


class BrokerOrderSide(StrEnum):
    """Side of a broker order. Mirrors the AlphaBrief OrderIntent vocabulary."""

    BUY = "buy"
    SELL = "sell"


class BrokerOrderType(StrEnum):
    """Order type supported by the AlphaBrief paper port."""

    MARKET = "market"
    LIMIT = "limit"


class BrokerTimeInForce(StrEnum):
    """Time-in-force policy for a broker order."""

    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class BrokerOrderStatus(StrEnum):
    """Lifecycle status reported by an external broker."""

    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    PENDING_CANCEL = "pending_cancel"


# ---------------------------------------------------------------------------
# Port models
# ---------------------------------------------------------------------------


class SubmitRequest(BaseModel):
    """Input to ``BrokerAdapter.submit`` after RiskGate approval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1)
    side: BrokerOrderSide
    order_type: BrokerOrderType
    quantity: Decimal = Field(gt=0)
    limit_price: Decimal | None = None
    time_in_force: BrokerTimeInForce = BrokerTimeInForce.DAY


class SubmitResult(BaseModel):
    """Result returned from a single ``submit`` call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    broker_order_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)
    status: BrokerOrderStatus
    accepted_at: datetime


class CancelResult(BaseModel):
    """Result returned from a ``cancel`` call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    broker_order_id: str = Field(min_length=1)
    status: BrokerOrderStatus
    cancelled_at: datetime | None = None


class OrderState(BaseModel):
    """Snapshot of a broker order at a point in time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    broker_order_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: BrokerOrderSide
    order_type: BrokerOrderType
    quantity: Decimal = Field(gt=0)
    filled_quantity: Decimal = Field(ge=0)
    limit_price: Decimal | None = None
    status: BrokerOrderStatus
    submitted_at: datetime
    updated_at: datetime


class Fill(BaseModel):
    """One execution report from a broker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fill_id: str = Field(min_length=1)
    broker_order_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: BrokerOrderSide
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fees: Decimal = Field(ge=0)
    filled_at: datetime


class Position(BaseModel):
    """A single open position reported by the broker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1)
    quantity: Decimal
    average_price: Decimal = Field(ge=0)


class AccountSnapshot(BaseModel):
    """Account-level cash and equity snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str = Field(min_length=1)
    cash: Decimal
    equity: Decimal
    buying_power: Decimal
    currency: str = Field(min_length=1, max_length=8)
    captured_at: datetime


class BrokerHealth(BaseModel):
    """Health probe result for a broker adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    healthy: bool
    detail: str
    checked_at: datetime


# ---------------------------------------------------------------------------
# Adapter port
# ---------------------------------------------------------------------------


class BrokerAdapter(ABC):
    """Abstract base class for external paper broker adapters.

    Implementations MUST be idempotent with respect to ``client_order_id``:
    repeating a submit with the same client_order_id returns the existing
    broker_order_id and does not create a new order.

    Implementations MUST NOT mutate the supplied ``SubmitRequest``.
    """

    @abstractmethod
    async def health(self) -> BrokerHealth:
        """Probe broker connectivity and credentials."""

    @abstractmethod
    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        """Submit one new order. Idempotent on ``client_order_id``."""

    @abstractmethod
    async def cancel(self, broker_order_id: str) -> CancelResult:
        """Cancel one open order."""

    @abstractmethod
    async def get_order(self, broker_order_id: str) -> OrderState:
        """Fetch the current state of a single order."""

    @abstractmethod
    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        """List orders, optionally filtered by lifecycle status."""

    @abstractmethod
    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        """List fills since ``since`` (or all-time when ``None``)."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open positions."""

    @abstractmethod
    async def get_account(self) -> AccountSnapshot:
        """Return the current cash and equity snapshot."""


__all__ = [
    "AccountSnapshot",
    "BrokerAdapter",
    "BrokerHealth",
    "BrokerOrderSide",
    "BrokerOrderStatus",
    "BrokerOrderType",
    "BrokerTimeInForce",
    "CancelResult",
    "Fill",
    "OrderState",
    "Position",
    "SubmitRequest",
    "SubmitResult",
]
