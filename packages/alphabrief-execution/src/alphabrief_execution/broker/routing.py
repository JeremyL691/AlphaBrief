"""Routed broker adapter: multi-venue paper execution.

The policy universe spans venues that no single broker covers — OANDA
practice serves FX / metals / index CFDs, Alpaca paper serves US
equities and crypto. :class:`RoutingBrokerAdapter` picks the venue per
symbol and degrades to the built-in :class:`SimulatedBrokerAdapter`
when a venue's credentials are missing, so the system stays usable out
of the box.

Symbol classes (internal AlphaBrief identifiers):

* ``XXX_YYY`` (e.g. ``EUR_USD``, ``XAU_USD``, ``US30_USD``) → OANDA
* contains ``-`` (e.g. ``BTC-USD``) → Alpaca crypto
* plain ticker (e.g. ``AAPL``) → Alpaca equity

The simulated adapter fills orders at a synthetic reference price
(default ``$100`` unless overridden via :meth:`record_reference_price`),
which keeps the fallback deterministic and documented as synthetic.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from alphabrief_core import OrderIntent, OrderSide, OrderType, RiskDecision

from alphabrief_execution.broker.legacy import (
    PaperBroker,
    PaperBrokerError,
    PaperBrokerResult,
)
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)

_OANDA_SYMBOL_RE = re.compile(r"^[A-Z0-9]+_[A-Z0-9]{3}$")


def route_symbol_to_venue(symbol: str) -> str:
    """Return the venue name (``oanda_paper`` / ``alpaca_paper``) for a symbol."""
    normalized = symbol.strip().upper()
    if _OANDA_SYMBOL_RE.match(normalized):
        return "oanda_paper"
    return "alpaca_paper"


class SimulatedBrokerAdapter(BrokerAdapter):
    """Async adapter wrapping the deterministic in-memory :class:`PaperBroker`.

    Used as the no-credentials fallback for a venue. Fills happen at the
    recorded reference price (``record_reference_price``) or a synthetic
    default of ``$100`` when no price was recorded. Portfolio state is
    in-memory and process-local; it is not persisted across restarts.
    """

    def __init__(
        self,
        *,
        broker: PaperBroker | None = None,
        default_price: Decimal = Decimal("100"),
        account_id: str = "simulated-paper",
        currency: str = "USD",
    ) -> None:
        if default_price <= 0:
            raise ValueError("default_price must be positive")
        self._broker = broker or PaperBroker(portfolio=_build_simulated_portfolio())
        self._default_price = default_price
        self._account_id = account_id
        self._currency = currency
        self._reference_prices: dict[str, Decimal] = {}

    @property
    def broker(self) -> PaperBroker:
        """Expose the wrapped simulator (audit / portfolio inspection)."""
        return self._broker

    def record_reference_price(self, symbol: str, price: Decimal) -> None:
        """Record the latest market reference price for *symbol*."""
        if price <= 0:
            return
        self._reference_prices[symbol.strip().upper()] = price

    def _price_for(self, symbol: str) -> Decimal:
        return self._reference_prices.get(
            symbol.strip().upper(), self._default_price
        )

    # ------------------------------------------------------------------
    # BrokerAdapter port
    # ------------------------------------------------------------------

    async def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=True,
            detail="simulated paper broker (no external credentials)",
            checked_at=datetime.now(UTC),
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        intent = OrderIntent(
            intent_id=client_order_id,
            source="model",
            symbol=request.symbol,
            side=_to_core_side(request.side),
            order_type=_to_core_order_type(request.order_type),
            quantity=request.quantity,
            rationale="simulated paper execution (routed fallback)",
            created_at=datetime.now(UTC),
        )
        decision = RiskDecision(
            decision_id=f"sim_{uuid4().hex[:12]}",
            intent_id=intent.intent_id,
            approved=True,
            reason="simulated adapter executes post-RiskGate approval",
            max_quantity=None,
            risk_tags=[],
            requires_human_review=False,
            created_at=datetime.now(UTC),
        )
        try:
            result: PaperBrokerResult = self._broker.submit(
                intent,
                decision,
                reference_price=self._price_for(request.symbol),
            )
        except PaperBrokerError as exc:
            raise _BrokerSimulatedError(str(exc)) from exc
        return SubmitResult(
            broker_order_id=str(result.order.order_id),
            client_order_id=client_order_id,
            status=BrokerOrderStatus.FILLED,
            accepted_at=datetime.now(UTC),
        )

    async def cancel(self, broker_order_id: str) -> CancelResult:
        return CancelResult(
            broker_order_id=broker_order_id,
            status=BrokerOrderStatus.CANCELLED,
            cancelled_at=datetime.now(UTC),
        )

    async def get_order(self, broker_order_id: str) -> OrderState:
        raise _BrokerSimulatedError(
            f"simulated order {broker_order_id!r} not found"
        )

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        return []

    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        return []

    async def get_positions(self) -> list[Position]:
        return [
            Position(
                symbol=symbol,
                quantity=position.quantity,
                average_price=position.average_price,
            )
            for symbol, position in sorted(self._broker.portfolio.positions.items())
        ]

    async def get_account(self) -> AccountSnapshot:
        portfolio = self._broker.portfolio
        cash = portfolio.cash
        mark_value = sum(
            position.quantity * position.average_price
            for position in portfolio.positions.values()
        )
        return AccountSnapshot(
            account_id=self._account_id,
            cash=cash,
            equity=cash + mark_value,
            buying_power=cash,
            currency=self._currency,
            captured_at=datetime.now(UTC),
        )


class _BrokerSimulatedError(Exception):
    """Raised when a simulated adapter call cannot be completed."""


class RoutingBrokerAdapter(BrokerAdapter):
    """Multi-venue paper adapter that routes each symbol to its venue.

    Venue adapters are optional: a missing venue falls back to the
    simulated adapter so execution always works. The wrapped adapters
    are built lazily by the caller via the ``build_*`` factory hooks.
    """

    def __init__(
        self,
        *,
        oanda: BrokerAdapter | None = None,
        alpaca: BrokerAdapter | None = None,
        simulated: BrokerAdapter | None = None,
        venue_for: Callable[[str], str] = route_symbol_to_venue,
    ) -> None:
        self._oanda = oanda
        self._alpaca = alpaca
        self._simulated = simulated or SimulatedBrokerAdapter()
        self._venue_for = venue_for

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def venue_for_symbol(self, symbol: str) -> str:
        return self._venue_for(symbol)

    def _adapter_for(self, symbol: str) -> BrokerAdapter:
        venue = self.venue_for_symbol(symbol)
        if venue == "oanda_paper":
            return self._oanda or self._simulated
        if venue == "alpaca_paper":
            return self._alpaca or self._simulated
        return self._simulated

    def record_reference_price(self, symbol: str, price: Decimal) -> None:
        """Record a market price so the simulated fallback fills realistically."""
        if isinstance(self._simulated, SimulatedBrokerAdapter):
            self._simulated.record_reference_price(symbol, price)

    # ------------------------------------------------------------------
    # BrokerAdapter port
    # ------------------------------------------------------------------

    async def health(self) -> BrokerHealth:
        venues: list[str] = []
        if self._oanda is not None:
            venues.append("oanda")
        if self._alpaca is not None:
            venues.append("alpaca")
        if not venues:
            return BrokerHealth(
                healthy=True,
                detail="simulated paper broker (no external credentials)",
                checked_at=datetime.now(UTC),
            )
        return BrokerHealth(
            healthy=True,
            detail=f"routed paper venues: {', '.join(venues)} (+simulated fallback)",
            checked_at=datetime.now(UTC),
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        return await self._adapter_for(request.symbol).submit(
            request, client_order_id=client_order_id
        )

    async def cancel(self, broker_order_id: str) -> CancelResult:
        # Order ids are venue-scoped; try every live venue then simulated.
        for adapter in self._live_adapters():
            try:
                return await adapter.cancel(broker_order_id)
            except Exception:  # noqa: BLE001 — try the next venue
                continue
        return await self._simulated.cancel(broker_order_id)

    async def get_order(self, broker_order_id: str) -> OrderState:
        for adapter in self._live_adapters():
            try:
                return await adapter.get_order(broker_order_id)
            except Exception:  # noqa: BLE001 — try the next venue
                continue
        raise _BrokerSimulatedError(
            f"order {broker_order_id!r} not found on any venue"
        )

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        orders: list[OrderState] = []
        for adapter in self._live_adapters():
            orders.extend(await adapter.list_orders(status=status))
        orders.extend(await self._simulated.list_orders(status=status))
        return orders

    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        fills: list[Fill] = []
        for adapter in self._live_adapters():
            fills.extend(await adapter.list_fills(since=since))
        fills.extend(await self._simulated.list_fills(since=since))
        return fills

    async def get_positions(self) -> list[Position]:
        positions: list[Position] = []
        for adapter in self._live_adapters():
            positions.extend(await adapter.get_positions())
        positions.extend(await self._simulated.get_positions())
        return positions

    async def get_account(self) -> AccountSnapshot:
        # The port models a single account. With live venues present,
        # surface the first live venue's account (or its failure) so
        # callers keep their 503-style unavailable contract; the
        # simulated account is only the no-venue fallback.
        live = self._live_adapters()
        if not live:
            return await self._simulated.get_account()
        return await live[0].get_account()

    def _live_adapters(self) -> list[BrokerAdapter]:
        return [a for a in (self._oanda, self._alpaca) if a is not None]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_simulated_portfolio() -> Any:
    from alphabrief_execution import PortfolioState

    return PortfolioState(cash=Decimal("100000"))


def _to_core_side(side: BrokerOrderSide) -> OrderSide:
    return "buy" if side == BrokerOrderSide.BUY else "sell"


def _to_core_order_type(order_type: BrokerOrderType) -> OrderType:
    return "market" if order_type == BrokerOrderType.MARKET else "limit"


__all__ = [
    "RoutingBrokerAdapter",
    "SimulatedBrokerAdapter",
    "route_symbol_to_venue",
]
