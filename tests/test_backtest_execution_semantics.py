"""M12-W03: OANDA-semantic order execution and explicit rejection.

Covers AC-M12-W03-02: spread, slippage, financing, market closure,
stale price, minimum units, precision, maximum units, and insufficient
margin each change fills or produce an explicit rejection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_backtest import (
    BacktestInstrumentMetadata,
    BacktestMetadataSet,
    OrderFill,
    OrderRequest,
    PortfolioSimulator,
    execute_order,
    financing_charge,
)
from alphabrief_strategy import StrategyInstrumentCategory

#: Monday 22:00 UTC is inside every default category session window.
OPEN = datetime(2026, 8, 10, 22, 0, tzinfo=UTC)
#: Saturday 12:00 UTC is outside every default category session window.
WEEKEND = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _metadata(
    *,
    spread_bps: str = "10",
    minimum_trade_size: str = "1",
    maximum_order_units: str = "1000000",
    maximum_position_size: str = "2000000",
    margin_rate: str = "0.05",
    trade_units_precision: int = 0,
    display_precision: int = 5,
    financing: str = "0",
    category: StrategyInstrumentCategory = "CURRENCY",
) -> BacktestInstrumentMetadata:
    return BacktestInstrumentMetadata(
        symbol="EUR_USD",
        category=category,
        display_precision=display_precision,
        trade_units_precision=trade_units_precision,
        minimum_trade_size=Decimal(minimum_trade_size),
        maximum_order_units=Decimal(maximum_order_units),
        maximum_position_size=Decimal(maximum_position_size),
        margin_rate=Decimal(margin_rate),
        spread_bps=Decimal(spread_bps),
        financing_rate_per_unit_per_day=Decimal(financing),
    )


def _request(
    *,
    side: str = "buy",
    units: str = "10000",
    mid: str = "1.10000",
    fee_bps: str = "2",
    slippage_bps: str = "0",
    timestamp: datetime = OPEN,
) -> OrderRequest:
    return OrderRequest(
        symbol="EUR_USD",
        side=side,
        units=Decimal(units),
        timestamp=timestamp,
        reference_mid=Decimal(mid),
        fee_bps=Decimal(fee_bps),
        slippage_bps=Decimal(slippage_bps),
    )


def _execute(
    request: OrderRequest,
    metadata: BacktestInstrumentMetadata,
    *,
    nav: str = "100000",
    existing_units: str = "0",
    price_age_seconds: int = 0,
    max_price_age_seconds: int = 300,
) -> OrderFill:
    return execute_order(
        request,
        metadata,
        nav=Decimal(nav),
        existing_units=Decimal(existing_units),
        price_age_seconds=price_age_seconds,
        max_price_age_seconds=max_price_age_seconds,
    )


class TestSpreadAndSlippage:
    def test_buy_fills_at_ask_above_mid(self) -> None:
        metadata = _metadata(spread_bps="10")
        fill = _execute(_request(mid="1.10000"), metadata)
        assert fill.accepted
        assert fill.ask is not None and fill.ask > Decimal("1.10000")
        assert fill.bid is not None and fill.bid < Decimal("1.10000")
        assert fill.execution_price is not None
        assert fill.spread_cost is not None and fill.spread_cost > 0
        assert fill.execution_price == fill.ask

    def test_sell_fills_at_bid_below_mid(self) -> None:
        metadata = _metadata(spread_bps="10")
        fill = _execute(_request(side="sell", mid="1.10000"), metadata)
        assert fill.accepted
        assert fill.bid is not None
        assert fill.execution_price is not None
        assert fill.execution_price == fill.bid
        assert fill.execution_price < Decimal("1.10000")

    def test_wider_spread_changes_fill_price(self) -> None:
        narrow = _execute(_request(mid="1.10000"), _metadata(spread_bps="2"))
        wide = _execute(_request(mid="1.10000"), _metadata(spread_bps="40"))
        assert narrow.execution_price is not None
        assert wide.execution_price is not None
        assert narrow.spread_cost is not None
        assert wide.spread_cost is not None
        assert narrow.execution_price < wide.execution_price
        assert narrow.spread_cost < wide.spread_cost

    def test_slippage_moves_fill_adversely_and_is_recorded(self) -> None:
        metadata = _metadata(spread_bps="10")
        plain = _execute(_request(mid="1.10000", slippage_bps="0"), metadata)
        slipped = _execute(
            _request(mid="1.10000", slippage_bps="25"), metadata
        )
        assert slipped.accepted
        assert slipped.execution_price is not None
        assert plain.execution_price is not None
        assert slipped.slippage_cost is not None and slipped.slippage_cost > 0
        assert plain.slippage_cost is not None
        assert slipped.execution_price > plain.execution_price
        assert plain.slippage_cost == 0

    def test_fee_is_charged_on_notional(self) -> None:
        metadata = _metadata(spread_bps="0")
        fill = _execute(_request(units="10000", mid="1.10000", fee_bps="5"), metadata)
        assert fill.accepted
        assert fill.fee is not None
        # Notional 11000.00, 5 bps -> 5.50 fee.
        assert fill.fee == Decimal("5.50")


class TestMarketClosureAndStaleness:
    def test_weekend_order_is_rejected_market_closed(self) -> None:
        metadata = _metadata()
        fill = _execute(_request(timestamp=WEEKEND), metadata)
        assert not fill.accepted
        assert fill.reject_reason is not None
        assert fill.reject_reason.startswith("market_closed")

    def test_stale_price_is_rejected(self) -> None:
        metadata = _metadata()
        fresh = _execute(_request(), metadata, price_age_seconds=299)
        stale = _execute(_request(), metadata, price_age_seconds=301)
        assert fresh.accepted
        assert not stale.accepted
        assert stale.reject_reason is not None
        assert stale.reject_reason.startswith("stale_price")


class TestUnitConstraints:
    def test_below_minimum_units_is_rejected(self) -> None:
        metadata = _metadata(minimum_trade_size="100")
        fill = _execute(_request(units="50"), metadata)
        assert not fill.accepted
        assert fill.reject_reason is not None
        assert fill.reject_reason.startswith("below_minimum_units")

    def test_non_representable_units_are_rejected(self) -> None:
        metadata = _metadata(trade_units_precision=0)
        fill = _execute(_request(units="123.5"), metadata)
        assert not fill.accepted
        assert fill.reject_reason is not None
        assert fill.reject_reason.startswith("units_precision")

    def test_above_maximum_order_units_is_rejected(self) -> None:
        metadata = _metadata(maximum_order_units="5000")
        fill = _execute(_request(units="6000"), metadata)
        assert not fill.accepted
        assert fill.reject_reason is not None
        assert fill.reject_reason.startswith("above_maximum_units")

    def test_above_maximum_position_is_rejected(self) -> None:
        metadata = _metadata(maximum_position_size="8000")
        fill = _execute(_request(units="10000"), metadata)
        assert not fill.accepted
        assert fill.reject_reason is not None
        assert fill.reject_reason.startswith("above_maximum_position")


class TestMargin:
    def test_insufficient_margin_is_rejected(self) -> None:
        metadata = _metadata(margin_rate="0.20", spread_bps="0")
        fill = _execute(
            _request(units="1000000", mid="1.10000"),
            metadata,
            nav="10000",
        )
        assert not fill.accepted
        assert fill.reject_reason is not None
        assert fill.reject_reason.startswith("insufficient_margin")

    def test_margin_used_reflects_position_after_fill(self) -> None:
        metadata = _metadata(margin_rate="0.05", spread_bps="0")
        fill = _execute(_request(units="10000", mid="1.10000"), metadata)
        assert fill.accepted
        assert fill.margin_used is not None
        # 10000 units * 1.10 * 5% = 550.00 margin.
        assert fill.margin_used == Decimal("550.00")

    def test_existing_position_counts_toward_margin(self) -> None:
        metadata = _metadata(margin_rate="0.05", spread_bps="0")
        fill = _execute(
            _request(units="10000", mid="1.10000"),
            metadata,
            existing_units="20000",
        )
        assert fill.accepted
        assert fill.margin_used is not None
        # 30000 units * 1.10 * 5% = 1650.00 margin.
        assert fill.margin_used == Decimal("1650.00")


class TestFinancing:
    def test_financing_charge_is_proportional_to_units_and_nights(self) -> None:
        metadata = _metadata(financing="0.0001")
        one_night = financing_charge(
            Decimal("10000"), metadata, nights=1
        )
        three_nights = financing_charge(
            Decimal("10000"), metadata, nights=3
        )
        assert one_night == Decimal("1.00")
        assert three_nights == Decimal("3.00")

    def test_financing_reduces_portfolio_cash(self) -> None:
        metadata_set = BacktestMetadataSet(
            version="fixture-v1",
            instruments={"EUR_USD": _metadata(financing="0.0001")},
        )
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata_set
        )
        fill = _execute(_request(), metadata_set.require("EUR_USD"))
        assert fill.accepted
        simulator.apply_fill(fill)
        cash_before = simulator.cash
        simulator.accrue_financing(timestamp=OPEN, nights=2)
        assert simulator.cash == cash_before - Decimal("2.00")

    def test_negative_nights_are_rejected(self) -> None:
        metadata = _metadata(financing="0.0001")
        with pytest.raises(ValueError, match="nights"):
            financing_charge(Decimal("10000"), metadata, nights=-1)


class TestExecutionContract:
    def test_rejection_reason_is_explicit_and_versioned(self) -> None:
        metadata = _metadata()
        fill = _execute(_request(timestamp=WEEKEND), metadata)
        assert not fill.accepted
        assert fill.reject_reason is not None
        assert fill.metadata_version == "instrument-EUR_USD"
        assert fill.semantics_version == "oanda-practice-mirror-1"

    def test_identical_inputs_produce_identical_fills(self) -> None:
        metadata = _metadata(spread_bps="10")
        first = _execute(_request(mid="1.10000", slippage_bps="5"), metadata)
        second = _execute(_request(mid="1.10000", slippage_bps="5"), metadata)
        assert first.model_dump() == second.model_dump()

    def test_accepted_fill_records_all_costs(self) -> None:
        metadata = _metadata(spread_bps="10")
        fill = _execute(_request(slippage_bps="5"), metadata)
        assert fill.accepted
        for field in (
            "execution_price",
            "bid",
            "ask",
            "spread_cost",
            "slippage_cost",
            "fee",
            "margin_used",
        ):
            assert getattr(fill, field) is not None
        assert fill.reject_reason is None
