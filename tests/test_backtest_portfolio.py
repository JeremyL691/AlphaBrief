"""M12-W03: multi-instrument portfolio accounting in home currency.

Covers AC-M12-W03-01: multi-instrument fixtures update cash, NAV, gross
and net exposure, margin, positions, realized and unrealized PnL, and
category attribution in account home currency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from alphabrief_backtest import (
    BacktestInstrumentMetadata,
    BacktestMetadataSet,
    OrderFill,
    OrderRequest,
    PortfolioSimulator,
    execute_order,
)

# Monday 22:00 UTC is inside every category session window (CURRENCY
# and METAL open Monday 21:00 UTC; CFD categories open Monday 00:00).
OPEN_MONDAY = datetime(2026, 8, 10, 22, 0, tzinfo=UTC)
OPEN_TUESDAY = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)


def _metadata_set(
    *, spread_bps: str = "0", financing: str = "0"
) -> BacktestMetadataSet:
    return BacktestMetadataSet(
        version="fixture-metadata-v1",
        instruments={
            "EUR_USD": BacktestInstrumentMetadata(
                symbol="EUR_USD",
                category="CURRENCY",
                display_precision=5,
                trade_units_precision=0,
                minimum_trade_size=Decimal("1"),
                maximum_order_units=Decimal("10000000"),
                maximum_position_size=Decimal("20000000"),
                margin_rate=Decimal("0.05"),
                spread_bps=Decimal(spread_bps),
                financing_rate_per_unit_per_day=Decimal(financing),
            ),
            "XAU_USD": BacktestInstrumentMetadata(
                symbol="XAU_USD",
                category="METAL",
                display_precision=3,
                trade_units_precision=0,
                minimum_trade_size=Decimal("1"),
                maximum_order_units=Decimal("100000"),
                maximum_position_size=Decimal("200000"),
                margin_rate=Decimal("0.10"),
                spread_bps=Decimal(spread_bps),
                financing_rate_per_unit_per_day=Decimal(financing),
            ),
            "US100": BacktestInstrumentMetadata(
                symbol="US100",
                category="INDEX_CFD",
                display_precision=2,
                trade_units_precision=1,
                minimum_trade_size=Decimal("1"),
                maximum_order_units=Decimal("100000"),
                maximum_position_size=Decimal("200000"),
                margin_rate=Decimal("0.20"),
                spread_bps=Decimal(spread_bps),
                financing_rate_per_unit_per_day=Decimal(financing),
            ),
        },
    )


def _order(
    symbol: str,
    side: str,
    units: str,
    mid: str,
    *,
    fee_bps: str = "2",
    slippage_bps: str = "0",
    timestamp: datetime = OPEN_MONDAY,
) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        side=side,
        units=Decimal(units),
        timestamp=timestamp,
        reference_mid=Decimal(mid),
        fee_bps=Decimal(fee_bps),
        slippage_bps=Decimal(slippage_bps),
    )


def _fill(
    simulator_metadata: BacktestMetadataSet, order: OrderRequest
) -> OrderFill:
    return execute_order(
        order,
        simulator_metadata.require(order.symbol),
        nav=Decimal("100000"),
        existing_units=Decimal("0"),
        price_age_seconds=0,
    )


class TestMultiInstrumentAccounting:
    def test_buy_fills_update_cash_positions_and_exposure(self) -> None:
        metadata = _metadata_set()
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        eur = _fill(metadata, _order("EUR_USD", "buy", "10000", "1.10000"))
        xau = _fill(metadata, _order("XAU_USD", "buy", "10", "2400.000"))
        us100 = _fill(metadata, _order("US100", "buy", "5", "5200.00"))

        assert eur.accepted and xau.accepted and us100.accepted
        simulator.apply_fill(eur)
        simulator.apply_fill(xau)
        simulator.apply_fill(us100)

        snapshot = simulator.mark_to_market(
            timestamp=OPEN_MONDAY,
            mid_prices={
                "EUR_USD": Decimal("1.10000"),
                "XAU_USD": Decimal("2400.000"),
                "US100": Decimal("5200.00"),
            },
        )

        assert snapshot.home_currency == "USD"
        assert snapshot.cash < Decimal("100000")
        assert len(snapshot.positions) == 3
        gross = snapshot.gross_exposure
        assert gross == snapshot.net_exposure  # all-long portfolio
        assert gross > 0
        assert snapshot.margin_used > 0
        assert snapshot.margin_used < gross
        assert snapshot.unrealized_pnl == 0  # marked at entry prices
        assert snapshot.nav == snapshot.cash + snapshot.unrealized_pnl

    def test_category_attribution_groups_exposure_by_category(self) -> None:
        metadata = _metadata_set()
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        simulator.apply_fill(
            _fill(metadata, _order("EUR_USD", "buy", "10000", "1.10000"))
        )
        simulator.apply_fill(
            _fill(metadata, _order("XAU_USD", "buy", "10", "2400.000"))
        )
        snapshot = simulator.mark_to_market(
            timestamp=OPEN_MONDAY,
            mid_prices={
                "EUR_USD": Decimal("1.10000"),
                "XAU_USD": Decimal("2400.000"),
            },
        )
        categories = {a.category: a for a in snapshot.category_attribution}
        assert set(categories) == {"CURRENCY", "METAL"}
        assert categories["CURRENCY"].gross_exposure == Decimal("11000")
        assert categories["METAL"].gross_exposure == Decimal("24000")
        # Attribution sums reconcile with portfolio totals.
        assert sum(a.gross_exposure for a in snapshot.category_attribution) == (
            snapshot.gross_exposure
        )
        assert sum(a.net_exposure for a in snapshot.category_attribution) == (
            snapshot.net_exposure
        )

    def test_mark_to_market_realizes_unrealized_pnl(self) -> None:
        metadata = _metadata_set()
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        fill = _fill(metadata, _order("EUR_USD", "buy", "10000", "1.10000"))
        simulator.apply_fill(fill)
        snapshot = simulator.mark_to_market(
            timestamp=OPEN_TUESDAY,
            mid_prices={"EUR_USD": Decimal("1.11000")},
        )
        assert snapshot.unrealized_pnl == Decimal("100.00")
        assert snapshot.nav == simulator.cash + snapshot.unrealized_pnl

    def test_partial_close_realizes_pnl_and_reduces_position(self) -> None:
        metadata = _metadata_set()
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        entry = _fill(metadata, _order("EUR_USD", "buy", "10000", "1.10000"))
        simulator.apply_fill(entry)
        close = _fill(metadata, _order("EUR_USD", "sell", "4000", "1.12000"))
        simulator.apply_fill(close)
        snapshot = simulator.mark_to_market(
            timestamp=OPEN_TUESDAY,
            mid_prices={"EUR_USD": Decimal("1.12000")},
        )
        position = snapshot.positions[0]
        assert position.units == Decimal("6000")
        # 4000 units closed at +0.02 -> 80.00 realized.
        assert snapshot.realized_pnl == Decimal("80.00")
        assert snapshot.unrealized_pnl == Decimal("120.00")

    def test_full_close_realizes_all_pnl(self) -> None:
        metadata = _metadata_set()
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        entry = _fill(metadata, _order("EUR_USD", "buy", "10000", "1.10000"))
        simulator.apply_fill(entry)
        close = _fill(metadata, _order("EUR_USD", "sell", "10000", "1.10500"))
        simulator.apply_fill(close)
        snapshot = simulator.mark_to_market(
            timestamp=OPEN_TUESDAY, mid_prices={"EUR_USD": Decimal("1.10500")}
        )
        assert snapshot.positions == ()
        assert snapshot.realized_pnl == Decimal("50.00")
        assert snapshot.unrealized_pnl == Decimal("0")

    def test_reversal_updates_short_position_and_realizes_pnl(self) -> None:
        metadata = _metadata_set()
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        entry = _fill(metadata, _order("EUR_USD", "buy", "10000", "1.10000"))
        simulator.apply_fill(entry)
        reverse = _fill(metadata, _order("EUR_USD", "sell", "15000", "1.11000"))
        simulator.apply_fill(reverse)
        snapshot = simulator.mark_to_market(
            timestamp=OPEN_TUESDAY,
            mid_prices={"EUR_USD": Decimal("1.11000")},
        )
        assert snapshot.positions[0].units == Decimal("-5000")
        assert snapshot.realized_pnl == Decimal("100.00")
        assert snapshot.unrealized_pnl == Decimal("0")

    def test_financing_accrual_reduces_cash(self) -> None:
        metadata = _metadata_set(financing="0.0001")
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        entry = _fill(metadata, _order("EUR_USD", "buy", "10000", "1.10000"))
        simulator.apply_fill(entry)
        cash_before = simulator.cash
        simulator.accrue_financing(timestamp=OPEN_TUESDAY, nights=1)
        assert simulator.cash == cash_before - Decimal("1.00")
        assert len(simulator.financing_events) == 1
        event = simulator.financing_events[0]
        assert event.symbol == "EUR_USD"
        assert event.amount == Decimal("1.00")

    def test_short_position_net_exposure_is_negative(self) -> None:
        metadata = _metadata_set()
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        sell = _fill(metadata, _order("EUR_USD", "sell", "10000", "1.10000"))
        simulator.apply_fill(sell)
        snapshot = simulator.mark_to_market(
            timestamp=OPEN_MONDAY,
            mid_prices={"EUR_USD": Decimal("1.10000")},
        )
        assert snapshot.positions[0].units == Decimal("-10000")
        assert snapshot.net_exposure == Decimal("-11000")
        assert snapshot.gross_exposure == Decimal("11000")

    def test_rejected_fills_never_mutate_state(self) -> None:
        metadata = _metadata_set()
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        rejected = _fill(metadata, _order("EUR_USD", "buy", "0.5", "1.10000"))
        assert not rejected.accepted
        simulator.apply_fill(rejected)
        snapshot = simulator.mark_to_market(
            timestamp=OPEN_MONDAY, mid_prices={"EUR_USD": Decimal("1.10000")}
        )
        assert snapshot.positions == ()
        assert snapshot.cash == Decimal("100000")

    def test_identical_inputs_produce_identical_snapshots(self) -> None:
        def run_once() -> object:
            metadata = _metadata_set()
            simulator = PortfolioSimulator(
                initial_cash=Decimal("100000"), metadata_set=metadata
            )
            fill = _fill(metadata, _order("EUR_USD", "buy", "10000", "1.10000"))
            simulator.apply_fill(fill)
            return simulator.mark_to_market(
                timestamp=OPEN_MONDAY,
                mid_prices={"EUR_USD": Decimal("1.10000")},
            ).model_dump()

        assert run_once() == run_once()
