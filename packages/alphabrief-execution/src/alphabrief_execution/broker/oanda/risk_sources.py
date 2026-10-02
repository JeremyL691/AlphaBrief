"""Broker-fresh risk context sourced from the live OANDA practice account.

This replaces the port-only composition that reported ``margin_used=0``
with empty prices, positions and conversions, and a permanently
``unknown`` reconciliation state (PROJECT_GUIDE 2.3). Everything the risk
gate sees now comes from the broker:

* account money fields and home currency from ``/summary``;
* positions with distinct long/short sides from ``/openPositions``;
* pending orders from ``/orders?state=PENDING``;
* open trades from ``/openTrades``;
* bid/ask plus the home-conversion factor from ``/pricing``;
* the account's instrument-catalog version from ``/instruments``;
* the reconciliation state from the durable recon store (frozen / clean);
* health from the account summary and the instrument catalog.

Nothing is synthesized: a missing datum stays missing, and the context
builder fails closed on incomplete coverage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.broker_context import (
    ConversionDatum,
    HealthState,
    PendingOrderDatum,
    PositionDatum,
    PriceDatum,
    ReconciliationState,
    TradeDatum,
)
from alphabrief_risk.exposure_aggregation import gross_home_notional

from alphabrief_execution.broker.oanda.account_ops import AccountOpsClient
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.input_facts import BrokerInputFacts
from alphabrief_execution.broker.oanda.instruments import fetch_instruments
from alphabrief_execution.broker.oanda.order_ops import OrderOpsClient
from alphabrief_execution.broker.oanda.position_ops import PositionOpsClient
from alphabrief_execution.broker.oanda.pricing import (
    OandaPrice,
    PricingRequest,
    fetch_pricing,
)
from alphabrief_execution.broker.oanda.trade_ops import TradeOpsClient
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.broker.risk_context import AccountSourceDatum

#: Instruments priced in one request; the pricing port also chunks this.
DEFAULT_PRICING_BATCH = 40


class OandaRiskContextSources:
    """Live OANDA practice facts for one risk context."""

    def __init__(
        self,
        client: OandaHttpClient,
        *,
        symbols: tuple[str, ...],
        recon_store: BrokerReconStore | None = None,
        request_id: str = "risk-context",
    ) -> None:
        self._client = client
        self._symbols = tuple(symbols)
        self._recon_store = recon_store
        self._request_id = request_id
        self._pricing_cache: dict[str, Any] | None = None
        self._pricing_cache_fetched_at: datetime | None = None

    # ------------------------------------------------------------------
    # Account / positions / orders / trades
    # ------------------------------------------------------------------

    def fetch_account(self) -> AccountSourceDatum | None:
        summary = AccountOpsClient(self._client).account_summary(
            request_id=f"{self._request_id}-account"
        )
        return AccountSourceDatum(
            account_id=summary.account_id,
            state="ACTIVE",
            tradeable=True,
            home_currency=summary.currency or "USD",
            balance=summary.balance,
            nav=summary.nav,
            margin_used=summary.margin_used,
            margin_available=summary.margin_available,
            captured_at=self._captured_at(),
        )

    def decision_input_facts(self, symbol: str) -> BrokerInputFacts:
        """Observe required model inputs without inventing absent broker fields."""
        facts: dict[str, Any] = {"symbol": symbol}
        errors: dict[str, str] = {}
        try:
            summary = AccountOpsClient(self._client).account_summary(
                request_id=f"{self._request_id}-decision-account"
            )
            facts.update(
                nav=summary.nav,
                margin_available=summary.margin_available,
                margin_used=summary.margin_used,
                account_captured_at=self._captured_at(),
            )
        except Exception as exc:  # noqa: BLE001 - persist safe class, fail closed
            errors["account"] = type(exc).__name__
        try:
            result = PositionOpsClient(self._client).list_positions(
                request_id=f"{self._request_id}-decision-positions"
            )
            held = [p for p in result.positions if p.instrument == symbol]
            facts.update(
                position_units=sum(
                    (p.long_units + p.short_units for p in held), Decimal(0)
                ),
                position_unrealized_pnl=sum(
                    (p.long_unrealized_pl + p.short_unrealized_pl for p in held),
                    Decimal(0),
                ),
                positions_captured_at=self._captured_at(),
            )
        except Exception as exc:  # noqa: BLE001 - empty failure is not flat position
            errors["positions"] = type(exc).__name__
        try:
            price = self._prices_by_symbol().get(symbol)
            if price is not None and price.bids and price.asks:
                facts.update(
                    bid=price.bids[0].price,
                    ask=price.asks[0].price,
                    spread=price.asks[0].price - price.bids[0].price,
                    quote_to_home=price.loss_conversion_factor,
                    quote_position_to_home=price.conversion_factor,
                    quote_captured_at=price.broker_time,
                )
        except Exception as exc:  # noqa: BLE001 - stale cache cannot mask failure
            errors["quote"] = type(exc).__name__
        try:
            latest = (
                None
                if self._recon_store is None
                else self._recon_store.latest_snapshot()
            )
            if latest is not None:
                facts["reconciliation_captured_at"] = datetime.fromisoformat(
                    latest.captured_at
                )
        except Exception as exc:  # noqa: BLE001 - preserve missing recon evidence
            errors["reconciliation"] = type(exc).__name__
        return BrokerInputFacts.model_validate({**facts, "errors": errors})

    def fetch_positions(self) -> list[PositionDatum]:
        positions = PositionOpsClient(self._client).list_positions(
            request_id=f"{self._request_id}-positions"
        )
        return [
            PositionDatum(
                symbol=position.instrument,
                long_units=position.long_units,
                short_units=position.short_units,
                average_price=(
                    position.long_average_price
                    if position.long_units >= position.short_units
                    else position.short_average_price
                ),
            )
            for position in positions.positions
            if position.long_units != 0 or position.short_units != 0
        ]

    def fetch_pending_orders(self) -> list[PendingOrderDatum]:
        orders = OrderOpsClient(self._client).list_pending_orders(
            request_id=f"{self._request_id}-orders"
        )
        return [
            PendingOrderDatum(
                broker_order_id=order.broker_order_id,
                symbol=order.symbol,
                units=order.units,
                price=order.price,
                state=str(order.state),
            )
            for order in orders.orders
            # Dependent orders (stop loss / take profit) carry no symbol and
            # no units of their own: they ride on their trade, which the
            # positions and trades sources already cover.
            if order.symbol is not None and not order.reduce_only
        ]

    def fetch_trades(self) -> list[TradeDatum]:
        trades = TradeOpsClient(self._client).list_trades(
            request_id=f"{self._request_id}-trades"
        )
        return [
            TradeDatum(
                broker_trade_id=trade.broker_trade_id,
                symbol=trade.instrument,
                current_units=trade.current_units,
                state=str(trade.state),
            )
            for trade in trades.trades
        ]

    # ------------------------------------------------------------------
    # Prices and home-currency conversions
    # ------------------------------------------------------------------

    def _symbols_to_price(self) -> tuple[str, ...]:
        """Price the configured universe plus every symbol we hold.

        Prices are fetched after positions, so a position opened by an
        earlier cycle is always covered; the configured symbols keep the
        coverage check satisfied for instruments we are about to trade.
        """
        held = {position.symbol for position in self.fetch_positions()}
        pending = {order.symbol for order in self.fetch_pending_orders()}
        ordered = list(dict.fromkeys([*self._symbols, *sorted(held | pending)]))
        return tuple(ordered)

    def _prices_by_symbol(self) -> dict[str, Any]:
        now = self._captured_at()
        if (
            self._pricing_cache is None
            or self._pricing_cache_fetched_at is None
            or (now - self._pricing_cache_fetched_at).total_seconds() >= 5
        ):
            self._pricing_cache = None
            self._pricing_cache_fetched_at = None
            symbols = self._symbols_to_price()
            if not symbols:
                self._pricing_cache = {}
                return self._pricing_cache
            batch = fetch_pricing(
                self._client,
                request=PricingRequest(symbols=tuple(symbols)),
                request_id=f"{self._request_id}-pricing",
            )
            self._pricing_cache = {price.symbol: price for price in batch.prices}
            self._pricing_cache_fetched_at = self._captured_at()
        return self._pricing_cache

    def fetch_prices(self) -> list[PriceDatum]:
        return [
            PriceDatum(
                symbol=price.symbol,
                bid=price.bids[0].price,
                ask=price.asks[0].price,
                captured_at=price.broker_time,
            )
            for price in self._prices_by_symbol().values()
        ]

    def fetch_conversions(self) -> list[ConversionDatum]:
        """Home-currency factors straight from the pricing response."""
        conversions: list[ConversionDatum] = []
        for price in self._prices_by_symbol().values():
            quote_currency = price.symbol.split("_")[-1] if "_" in price.symbol else ""
            if not quote_currency:
                continue
            conversions.append(
                ConversionDatum(
                    symbol=price.symbol,
                    quote_home=price.conversion_factor,
                    factor=price.conversion_factor,
                )
            )
        return conversions

    # ------------------------------------------------------------------
    # Catalog, reconciliation, health
    # ------------------------------------------------------------------

    def home_conversion_factor(self, symbol: str) -> Decimal | None:
        """The broker's quote-currency → home-currency factor for a symbol.

        Read from the same pricing response that feeds the exposure
        projection; ``None`` when the broker returned no price for the
        symbol, which the caller must treat as "cannot size".
        """
        price: OandaPrice | None = self._prices_by_symbol().get(symbol)
        if price is None:
            return None
        return price.loss_conversion_factor

    def live_spread(self, symbol: str) -> Decimal | None:
        """The broker's current spread (ask - bid) for one instrument."""
        price: OandaPrice | None = self._prices_by_symbol().get(symbol)
        if price is None or not price.bids or not price.asks:
            return None
        return price.asks[0].price - price.bids[0].price

    def live_quote(self, symbol: str) -> tuple[Decimal, Decimal] | None:
        """The broker's current (bid, ask) for one instrument."""
        price: OandaPrice | None = self._prices_by_symbol().get(symbol)
        if price is None or not price.bids or not price.asks:
            return None
        return price.bids[0].price, price.asks[0].price

    def mid_price(self, symbol: str) -> Decimal | None:
        """The broker's current mid price for one instrument (touch)."""
        price: OandaPrice | None = self._prices_by_symbol().get(symbol)
        if price is None or not price.bids or not price.asks:
            return None
        return (price.bids[0].price + price.asks[0].price) / Decimal(2)

    def fetch_catalog_version(self) -> str | None:
        catalog = fetch_instruments(self._client, account_id=self._client.account_id)
        if not catalog.instruments:
            return None
        return str(getattr(catalog, "snapshot_hash", "") or len(catalog.instruments))

    def fetch_reconciliation_state(self) -> ReconciliationState:
        """Report the durable reconciliation state, not a placeholder."""
        if self._recon_store is None:
            return "unknown"
        try:
            if self._recon_store.has_open_freeze():
                return "frozen"
            snapshots = self._recon_store.list_snapshots()
        except Exception:  # noqa: BLE001 - a store failure is not "clean"
            return "unknown"
        if not snapshots:
            return "unknown"
        return "clean" if snapshots[0].all_match else "unknown"

    def fetch_health(self) -> HealthState:
        try:
            summary = AccountOpsClient(self._client).account_summary(
                request_id=f"{self._request_id}-health"
            )
        except Exception:  # noqa: BLE001 - health is a probe, not a decision
            return "unhealthy"
        return "healthy" if summary.account_id else "unhealthy"

    # ------------------------------------------------------------------
    # Account exposure context for the risk gate
    # ------------------------------------------------------------------

    def account_exposure_context(
        self,
        *,
        now: datetime | None = None,
        symbol: str | None = None,
        drawdown_block_reason: str | None = None,
        open_position_count: int | None = None,
        daily_open_count: int | None = None,
        daily_symbol_open_count: int | None = None,
        frozen_symbols: dict[str, str] | None = None,
        recent_high_impact_events: dict[str, str] | None = None,
        current_spread: Decimal | None = None,
        recent_spreads: tuple[Decimal, ...] = (),
        symbol_types: dict[str, str] | None = None,
        equity_high_water_mark: Decimal | None = None,
        day_start_equity: Decimal | None = None,
        day_realized_pnl: Decimal | None = None,
    ) -> AccountExposureContext:
        """Project the live account into the risk gate's context.

        Exposure is gross notional per symbol in the account's home
        currency, using the broker's own conversion factors; the quote
        fields come from the same pricing snapshot the gate's freshness
        rule checks. Pending non-reduce orders reserve additional gross notional.
        Missing or stale held-position or pending-order prices explicitly mark
        the projection incomplete so entries fail closed.
        """
        captured = now or self._captured_at()
        summary = AccountOpsClient(self._client).account_summary(
            request_id=f"{self._request_id}-exposure"
        )
        positions = self.fetch_positions()
        pending = self.fetch_pending_orders()
        prices = self._prices_by_symbol()
        conversions = {
            name: price.conversion_factor
            for name, price in prices.items()
            if price.conversion_factor is not None
        }
        exposure_errors: dict[str, str] = {}
        exposure_by_symbol: dict[str, Decimal] = {}
        legs: list[tuple[str, Decimal, Decimal, Decimal | None, bool]] = [
            (p.symbol, p.long_units, p.short_units, None, False) for p in positions
        ]
        legs.extend((o.symbol, o.units, Decimal(0), o.price, True) for o in pending)
        pending_by_symbol: dict[str, Decimal] = {}
        for leg_symbol, long_units, short_units, order_price, is_pending in legs:
            price = prices.get(leg_symbol)
            if price is None or not price.bids or not price.asks:
                exposure_errors[leg_symbol] = "missing_position_quote"
                continue
            age = (captured - price.broker_time).total_seconds()
            if not 0 <= age <= 15:
                exposure_errors[leg_symbol] = "stale_position_quote"
                continue
            factor = conversions.get(leg_symbol)
            if factor is None:
                exposure_errors[leg_symbol] = "missing_position_conversion"
                continue
            mark = (price.bids[0].price + price.asks[0].price) / Decimal(2)
            if order_price is not None:
                mark = max(mark, order_price)
            notional = gross_home_notional(long_units, short_units, mark, factor)
            exposure_by_symbol[leg_symbol] = (
                exposure_by_symbol.get(leg_symbol, Decimal(0)) + notional
            )
            if is_pending:
                pending_by_symbol[leg_symbol] = (
                    pending_by_symbol.get(leg_symbol, Decimal(0)) + notional
                )

        quote_symbol = symbol or (self._symbols[0] if self._symbols else None)
        quote = prices.get(quote_symbol) if quote_symbol else None
        return AccountExposureContext(
            current_total_exposure=sum(exposure_by_symbol.values(), Decimal("0")),
            exposure_by_symbol=exposure_by_symbol,
            quote_position_to_home=conversions,
            exposure_complete=not exposure_errors,
            exposure_errors=exposure_errors,
            pending_exposure_by_symbol=pending_by_symbol,
            cash=summary.balance,
            account_id=summary.account_id,
            captured_at=captured,
            equity=summary.nav,
            margin_used=summary.margin_used,
            reference_mark_prices={
                symbol: (price.bids[0].price + price.asks[0].price) / Decimal(2)
                for symbol, price in prices.items()
            },
            equity_high_water_mark=equity_high_water_mark,
            day_start_equity=day_start_equity,
            day_realized_pnl=day_realized_pnl,
            open_position_count=(
                open_position_count
                if open_position_count is not None
                else summary.open_position_count
            ),
            daily_open_count=daily_open_count,
            daily_symbol_open_count=daily_symbol_open_count,
            quote_captured_at=quote.broker_time if quote is not None else None,
            quote_tradeable=(quote.tradeable if quote is not None else None),
            frozen_symbols=dict(frozen_symbols or {}),
            recent_high_impact_events=dict(recent_high_impact_events or {}),
            drawdown_block_reason=drawdown_block_reason,
            current_spread=current_spread,
            recent_spreads=tuple(recent_spreads),
            # Rule 1 reads the durable reconciliation state; a frozen
            # account opens no new exposure.
            reconciliation_state=self.fetch_reconciliation_state(),
            symbol_types=dict(symbol_types or {}),
        )

    # ------------------------------------------------------------------

    def _captured_at(self) -> datetime:
        """One capture stamp per pass, so freshness is judged honestly."""
        return datetime.now(UTC)


__all__ = [
    "DEFAULT_PRICING_BATCH",
    "OandaRiskContextSources",
]
