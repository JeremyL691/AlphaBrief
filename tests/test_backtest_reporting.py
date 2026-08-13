"""M12-W05: research-grade metrics and attribution reports.

Covers AC-M12-W05-01/02/03: every report carries the full REQ-STRAT-005
metric set; reports include instrument and category attribution, cost
attribution, rejection attribution, benchmark delta, and IS/OOS labels;
degenerate fixtures (zero-return, no-trade, all-loss, sparse,
missing-benchmark, multi-currency) serialize without NaN or misleading
infinity.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alphabrief_backtest import (
    BacktestInstrumentMetadata,
    BacktestMetadataSet,
    OrderFill,
    OrderRequest,
    PortfolioReport,
    PortfolioSimulator,
    PortfolioSnapshot,
    build_portfolio_report,
    execute_order,
)
from alphabrief_backtest.portfolio import PortfolioTrade

DATA_VERSION = "fixture-data-v1"
OPEN = datetime(2026, 8, 10, 22, 0, tzinfo=UTC)


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
    timestamp: datetime = OPEN,
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
    metadata: BacktestMetadataSet, order: OrderRequest
) -> OrderFill:
    return execute_order(
        order,
        metadata.require(order.symbol),
        nav=Decimal("100000"),
        existing_units=Decimal("0"),
        price_age_seconds=0,
    )


def _reject(
    metadata: BacktestMetadataSet,
    order: OrderRequest,
    *,
    price_age_seconds: int,
) -> OrderFill:
    return execute_order(
        order,
        metadata.require(order.symbol),
        nav=Decimal("100000"),
        existing_units=Decimal("0"),
        price_age_seconds=price_age_seconds,
    )


def _run_scenario() -> tuple[PortfolioReport, PortfolioSimulator]:
    """A normal scenario: two winners, one partial-close loser, an open
    position whose mid moves (so statistical metrics are computable),
    financing while positions are open, and two rejection classes."""
    metadata = _metadata_set(spread_bps="4", financing="0.0001")
    simulator = PortfolioSimulator(
        initial_cash=Decimal("100000"), metadata_set=metadata
    )
    fills: list[OrderFill] = []
    # Open three positions, then charge two nights of financing.
    fills.append(_fill(metadata, _order("EUR_USD", "buy", "10000", "1.10000")))
    simulator.apply_fill(fills[-1])
    fills.append(_fill(metadata, _order("XAU_USD", "buy", "10", "2400.000")))
    simulator.apply_fill(fills[-1])
    fills.append(_fill(metadata, _order("US100", "buy", "5", "5200.00")))
    simulator.apply_fill(fills[-1])
    simulator.accrue_financing(timestamp=OPEN + timedelta(hours=48), nights=2)
    # Winner 1: EUR_USD round trip +0.02 on 10000 units.
    fills.append(_fill(metadata, _order("EUR_USD", "sell", "10000", "1.12000")))
    simulator.apply_fill(fills[-1])
    # Winner 2: XAU_USD round trip +100 on 10 units.
    fills.append(_fill(metadata, _order("XAU_USD", "sell", "10", "2500.000")))
    simulator.apply_fill(fills[-1])
    # Loser: partial close of US100 2 units at -100.
    fills.append(_fill(metadata, _order("US100", "sell", "2", "5100.00")))
    simulator.apply_fill(fills[-1])
    # Rejections: one stale price, one non-representable size.
    rejections = (
        _reject(
            metadata,
            _order("EUR_USD", "buy", "10000", "1.10000"),
            price_age_seconds=400,
        ),
        _reject(
            metadata,
            _order("EUR_USD", "buy", "0.5", "1.10000"),
            price_age_seconds=0,
        ),
    )
    # 25 hourly snapshots with a moving US100 mid (open position).
    us100_mids = [str(5050 + (hour % 5) * 50) for hour in range(25)]
    snapshots = tuple(
        simulator.mark_to_market(
            timestamp=OPEN + timedelta(hours=hour),
            mid_prices={"US100": Decimal(us100_mids[hour])},
        )
        for hour in range(25)
    )
    report = build_portfolio_report(
        run_id="run-scenario-1",
        strategy_id="trend_fit_v1",
        strategy_version="1.0.0",
        data_version=DATA_VERSION,
        label="OOS",
        initial_cash=Decimal("100000"),
        snapshots=snapshots,
        fills=tuple(fills),
        trades=simulator.trade_log,
        financing_events=simulator.financing_events,
        rejections=rejections,
        benchmark_total_return=Decimal("0.02"),
    )
    return report, simulator


def _flat_snapshot() -> PortfolioSnapshot:
    metadata = _metadata_set()
    simulator = PortfolioSimulator(
        initial_cash=Decimal("100000"), metadata_set=metadata
    )
    return simulator.mark_to_market(timestamp=OPEN, mid_prices={})


def _flat_snapshots(count: int = 25) -> tuple[PortfolioSnapshot, ...]:
    metadata = _metadata_set()
    simulator = PortfolioSimulator(
        initial_cash=Decimal("100000"), metadata_set=metadata
    )
    return tuple(
        simulator.mark_to_market(
            timestamp=OPEN + timedelta(hours=hour), mid_prices={}
        )
        for hour in range(count)
    )


class TestFullMetricSet:
    def test_every_report_includes_all_required_metrics(self) -> None:
        report, _ = _run_scenario()
        metrics_class = type(report.metrics)
        for field in (
            "total_return",
            "volatility",
            "sharpe",
            "sortino",
            "calmar",
            "max_drawdown",
            "turnover",
            "exposure_pct",
            "hit_rate",
            "profit_factor",
            "tail_loss",
        ):
            assert field in metrics_class.model_fields

    def test_metric_values_match_the_scenario(self) -> None:
        report, _ = _run_scenario()
        metrics = report.metrics
        # Two winners and one loser (spread/fees reduce exact PnL).
        assert metrics.hit_rate == Decimal("2") / Decimal("3")
        assert metrics.profit_factor is not None
        assert metrics.profit_factor > 1
        assert metrics.total_return > 0
        assert metrics.volatility is not None
        assert metrics.sharpe is not None
        assert metrics.sortino is not None
        assert metrics.tail_loss is not None
        assert metrics.max_drawdown >= 0
        assert metrics.exposure_pct >= 0
        assert metrics.turnover > 0
        assert report.label == "OOS"
        assert report.data_version == DATA_VERSION


class TestAttribution:
    def test_instrument_and_category_attribution(self) -> None:
        report, _ = _run_scenario()
        instruments = {row.key: row for row in report.instrument_attribution}
        assert set(instruments) == {"EUR_USD", "XAU_USD", "US100"}
        assert instruments["EUR_USD"].realized_pnl > 0
        assert instruments["XAU_USD"].realized_pnl > 0
        assert instruments["US100"].realized_pnl < 0
        assert instruments["XAU_USD"].realized_pnl > (
            instruments["EUR_USD"].realized_pnl
        )
        categories = {row.key: row for row in report.category_attribution}
        assert set(categories) == {"CURRENCY", "METAL", "INDEX_CFD"}
        # Category attribution reconciles with instrument attribution.
        assert sum(row.total_pnl for row in categories.values()) == (
            sum(row.total_pnl for row in instruments.values())
        )

    def test_cost_attribution_breaks_down_costs(self) -> None:
        report, _ = _run_scenario()
        costs = report.cost_attribution
        assert costs.spread_cost > 0
        assert costs.slippage_cost == 0
        assert costs.fee_cost > 0
        # Financing: (10000 + 10 + 5) units * 0.0001 * 2 nights.
        assert costs.financing_cost == Decimal("2.003")
        assert costs.total_cost == (
            costs.spread_cost
            + costs.slippage_cost
            + costs.fee_cost
            + costs.financing_cost
        )

    def test_rejection_attribution_counts_each_reason(self) -> None:
        report, _ = _run_scenario()
        by_reason = {
            row.reason.split(":")[0]: row
            for row in report.rejection_attribution
        }
        assert set(by_reason) == {"stale_price", "units_precision"}
        assert by_reason["stale_price"].count == 1
        assert by_reason["units_precision"].count == 1
        assert by_reason["stale_price"].rejected_notional > 0

    def test_benchmark_delta(self) -> None:
        report, _ = _run_scenario()
        assert report.benchmark_total_return == Decimal("0.02")
        assert report.benchmark_delta == (
            report.metrics.total_return - Decimal("0.02")
        )

    def test_missing_benchmark_yields_null_delta(self) -> None:
        report = build_portfolio_report(
            run_id="no-benchmark",
            strategy_id="s1",
            strategy_version="1",
            data_version=DATA_VERSION,
            label="OOS",
            initial_cash=Decimal("100000"),
            snapshots=_flat_snapshots(),
            fills=(),
            trades=(),
            financing_events=(),
            rejections=(),
            benchmark_total_return=None,
        )
        assert report.metrics.total_return == 0
        assert report.benchmark_total_return is None
        assert report.benchmark_delta is None


class TestDegenerateFixtures:
    def _flat_report(self) -> PortfolioReport:
        metadata = _metadata_set()
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        snapshots = tuple(
            simulator.mark_to_market(
                timestamp=OPEN + timedelta(hours=hour),
                mid_prices={},
            )
            for hour in range(25)
        )
        return build_portfolio_report(
            run_id="flat",
            strategy_id="s1",
            strategy_version="1",
            data_version=DATA_VERSION,
            label="IS",
            initial_cash=Decimal("100000"),
            snapshots=snapshots,
            fills=(),
            trades=(),
            financing_events=(),
            rejections=(),
            benchmark_total_return=None,
        )

    def test_zero_return_fixture(self) -> None:
        report = self._flat_report()
        assert report.metrics.total_return == 0
        assert report.metrics.max_drawdown == 0
        assert report.metrics.turnover == 0
        assert report.metrics.exposure_pct == 0
        # Zero variance / no trades -> statistical metrics are None.
        assert report.metrics.volatility is None
        assert report.metrics.sharpe is None
        assert report.metrics.sortino is None
        assert report.metrics.calmar is None
        assert report.metrics.hit_rate is None
        assert report.metrics.profit_factor is None
        assert report.metrics.tail_loss is None

    def test_no_trade_fixture_has_no_misleading_metrics(self) -> None:
        report = self._flat_report()
        assert report.metrics.hit_rate is None
        assert report.metrics.profit_factor is None
        assert report.metrics.turnover == 0
        assert report.instrument_attribution == ()

    def test_all_loss_fixture_has_zero_profit_factor(self) -> None:
        losing_trades = (
            PortfolioTrade(
                symbol="EUR_USD",
                units=Decimal("10000"),
                entry_price=Decimal("1.10000"),
                exit_price=Decimal("1.09000"),
                realized_pnl=Decimal("-100.00"),
                closed_at=OPEN,
            ),
            PortfolioTrade(
                symbol="EUR_USD",
                units=Decimal("5000"),
                entry_price=Decimal("1.10000"),
                exit_price=Decimal("1.09500"),
                realized_pnl=Decimal("-25.00"),
                closed_at=OPEN,
            ),
        )
        report = build_portfolio_report(
            run_id="all-loss",
            strategy_id="s1",
            strategy_version="1",
            data_version=DATA_VERSION,
            label="FULL",
            initial_cash=Decimal("100000"),
            snapshots=_flat_snapshots(),
            fills=(),
            trades=losing_trades,
            financing_events=(),
            rejections=(),
            benchmark_total_return=None,
        )
        assert report.metrics.hit_rate == 0
        assert report.metrics.profit_factor == 0
        assert report.metrics.turnover > 0

    def test_sparse_fixture_returns_none_stats(self) -> None:
        metadata = _metadata_set()
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        snapshots = (
            simulator.mark_to_market(timestamp=OPEN, mid_prices={}),
            simulator.mark_to_market(
                timestamp=OPEN + timedelta(hours=1), mid_prices={}
            ),
        )
        report = build_portfolio_report(
            run_id="sparse",
            strategy_id="s1",
            strategy_version="1",
            data_version=DATA_VERSION,
            label="FULL",
            initial_cash=Decimal("100000"),
            snapshots=snapshots,
            fills=(),
            trades=(),
            financing_events=(),
            rejections=(),
            benchmark_total_return=None,
        )
        assert report.metrics.volatility is None
        assert report.metrics.sharpe is None
        assert report.metrics.sortino is None
        assert report.metrics.calmar is None
        assert report.metrics.tail_loss is None

    def test_multi_currency_portfolio_reconciles(self) -> None:
        metadata = _metadata_set()
        simulator = PortfolioSimulator(
            initial_cash=Decimal("100000"), metadata_set=metadata
        )
        fill = _fill(metadata, _order("EUR_USD", "buy", "10000", "1.10000"))
        simulator.apply_fill(fill)
        fill2 = _fill(metadata, _order("XAU_USD", "buy", "10", "2400.000"))
        simulator.apply_fill(fill2)
        snapshot = simulator.mark_to_market(
            timestamp=OPEN,
            mid_prices={
                "EUR_USD": Decimal("1.10000"),
                "XAU_USD": Decimal("2400.000"),
            },
        )
        report = build_portfolio_report(
            run_id="multi",
            strategy_id="s1",
            strategy_version="1",
            data_version=DATA_VERSION,
            label="FULL",
            initial_cash=Decimal("100000"),
            snapshots=(snapshot,),
            fills=(fill, fill2),
            trades=(),
            financing_events=(),
            rejections=(),
            benchmark_total_return=None,
        )
        assert report.home_currency == "USD"
        categories = {row.key for row in report.category_attribution}
        assert categories == {"CURRENCY", "METAL"}
        instruments = {row.key for row in report.instrument_attribution}
        assert instruments == {"EUR_USD", "XAU_USD"}

    def test_no_nan_or_infinity_in_any_serialization(self) -> None:
        from decimal import Decimal as _Decimal

        reports = [self._flat_report(), _run_scenario()[0]]
        for report in reports:
            serialized = report.normalized_json()
            assert "NaN" not in serialized
            assert "Infinity" not in serialized
            # Every Decimal field is finite (None where degenerate).
            for field in type(report.metrics).model_fields:
                value = getattr(report.metrics, field)
                if value is not None:
                    assert isinstance(value, _Decimal)
                    assert value.is_finite()
            for row in report.instrument_attribution:
                for value in (
                    row.gross_exposure,
                    row.net_exposure,
                    row.realized_pnl,
                    row.unrealized_pnl,
                    row.total_pnl,
                    row.contribution,
                ):
                    assert value.is_finite()
            for value in (
                report.initial_cash,
                report.final_nav,
                report.cost_attribution.spread_cost,
                report.cost_attribution.slippage_cost,
                report.cost_attribution.fee_cost,
                report.cost_attribution.financing_cost,
                report.cost_attribution.total_cost,
            ):
                assert value.is_finite()
            for rejection in report.rejection_attribution:
                assert rejection.rejected_notional.is_finite()


class TestReportContract:
    def test_identical_inputs_produce_identical_reports(self) -> None:
        first = _run_scenario()[0]
        second = _run_scenario()[0]
        assert first.model_dump() == second.model_dump()
        assert first.normalized_json() == second.normalized_json()

    def test_report_requires_snapshots_and_positive_cash(self) -> None:
        with pytest.raises(ValueError, match="snapshot"):
            build_portfolio_report(
                run_id="x",
                strategy_id="s",
                strategy_version="1",
                data_version="v",
                label="FULL",
                initial_cash=Decimal("10000"),
                snapshots=(),
                fills=(),
                trades=(),
                financing_events=(),
                rejections=(),
                benchmark_total_return=None,
            )
        with pytest.raises(ValueError, match="initial_cash"):
            build_portfolio_report(
                run_id="x",
                strategy_id="s",
                strategy_version="1",
                data_version="v",
                label="FULL",
                initial_cash=Decimal("0"),
                snapshots=(_flat_snapshot(),),
                fills=(),
                trades=(),
                financing_events=(),
                rejections=(),
                benchmark_total_return=None,
            )
