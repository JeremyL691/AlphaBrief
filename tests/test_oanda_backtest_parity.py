"""M12-W03: backtest metadata parity with the OANDA practice runtime.

Covers AC-M12-W03-03: backtest metadata and execution semantics resolve
the same instrument version and normalization rules used by the OANDA
practice runtime, or record an explicit versioned difference.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import get_args

import pytest
from alphabrief_backtest import (
    CATEGORY_SESSION_WINDOWS,
    SEMANTICS_DIFFERENCES,
    SEMANTICS_VERSION,
    BacktestConstraintError,
    BacktestInstrumentMetadata,
    BacktestMetadataSet,
    normalize_backtest_price,
    normalize_backtest_units,
)
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
from alphabrief_execution.broker.oanda.sessions import (
    CATEGORY_SESSIONS,
    session_verdict,
)
from alphabrief_execution.broker.oanda.taxonomy import (
    InstrumentCategory as OandaInstrumentCategory,
)
from alphabrief_risk.instrument_rules import (
    InstrumentConstraintError,
    normalize_instrument_price,
    normalize_instrument_units,
)
from alphabrief_strategy import StrategyInstrumentCategory


def _oanda_metadata() -> InstrumentMetadata:
    return InstrumentMetadata(
        name="EUR_USD",
        display_name="EUR/USD",
        raw_type="CURRENCY",
        display_precision=5,
        trade_units_precision=0,
        minimum_trade_size=Decimal("1"),
        maximum_order_units=Decimal("10000000"),
        maximum_position_size=Decimal("20000000"),
        margin_rate=Decimal("0.05"),
        pip_location=-4,
    )


def _backtest_metadata(
    *, spread_bps: str = "5", financing: str = "0"
) -> BacktestInstrumentMetadata:
    return BacktestInstrumentMetadata(
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
    )


class TestInstrumentFieldParity:
    def test_backtest_metadata_carries_the_practice_fields(self) -> None:
        oanda = _oanda_metadata()
        backtest = _backtest_metadata()
        assert backtest.display_precision == oanda.display_precision
        assert backtest.trade_units_precision == oanda.trade_units_precision
        assert backtest.minimum_trade_size == oanda.minimum_trade_size
        assert backtest.maximum_order_units == oanda.maximum_order_units
        assert backtest.maximum_position_size == oanda.maximum_position_size
        assert backtest.margin_rate == oanda.margin_rate

    def test_metadata_set_version_is_explicit(self) -> None:
        metadata_set = BacktestMetadataSet(
            version="fixture-metadata-v1",
            instruments={"EUR_USD": _backtest_metadata()},
        )
        assert metadata_set.version == "fixture-metadata-v1"
        assert metadata_set.require("EUR_USD") == _backtest_metadata()
        with pytest.raises(KeyError, match="missing"):
            metadata_set.require("missing")


class TestNormalizationParity:
    def test_units_normalization_matches_practice_runtime(self) -> None:
        oanda = _oanda_metadata()
        backtest = _backtest_metadata()
        for units in ("100", "10000", "999"):
            expected = normalize_instrument_units(Decimal(units), oanda)
            actual = normalize_backtest_units(Decimal(units), backtest)
            assert actual == expected

    def test_non_representable_units_rejected_like_practice_runtime(
        self,
    ) -> None:
        oanda = _oanda_metadata()
        backtest = _backtest_metadata()
        with pytest.raises(InstrumentConstraintError):
            normalize_instrument_units(Decimal("100.5"), oanda)
        with pytest.raises(BacktestConstraintError) as exc_info:
            normalize_backtest_units(Decimal("100.5"), backtest)
        assert exc_info.value.kind == "units_precision"

    def test_price_normalization_matches_practice_runtime(self) -> None:
        oanda = _oanda_metadata()
        backtest = _backtest_metadata()
        for price in ("1.10000", "1.23456", "0.99999"):
            expected = normalize_instrument_price(Decimal(price), oanda)
            actual = normalize_backtest_price(Decimal(price), backtest)
            assert actual == expected

    def test_non_representable_price_rejected_like_practice_runtime(
        self,
    ) -> None:
        oanda = _oanda_metadata()
        backtest = _backtest_metadata()
        with pytest.raises(InstrumentConstraintError):
            normalize_instrument_price(Decimal("1.100001"), oanda)
        with pytest.raises(BacktestConstraintError) as exc_info:
            normalize_backtest_price(Decimal("1.100001"), backtest)
        assert exc_info.value.kind == "price_precision"

    def test_non_positive_price_rejected_like_practice_runtime(self) -> None:
        backtest = _backtest_metadata()
        with pytest.raises(BacktestConstraintError) as exc_info:
            normalize_backtest_price(Decimal("0"), backtest)
        assert exc_info.value.kind == "price_invalid"


class TestSessionParity:
    def test_category_windows_match_practice_runtime(self) -> None:
        categories = set(get_args(OandaInstrumentCategory))
        assert categories == set(get_args(StrategyInstrumentCategory))
        for category in categories:
            practice = CATEGORY_SESSIONS[category]
            backtest = CATEGORY_SESSION_WINDOWS[category]
            assert backtest.start_weekday == practice[0]
            assert backtest.start_minutes == practice[1].hour * 60 + practice[1].minute
            assert backtest.end_weekday == practice[2]
            assert backtest.end_minutes == practice[3].hour * 60 + practice[3].minute

    @pytest.mark.parametrize("category", sorted(get_args(OandaInstrumentCategory)))
    def test_session_verdicts_match_practice_runtime_across_the_week(
        self, category: OandaInstrumentCategory
    ) -> None:
        backtest_window = CATEGORY_SESSION_WINDOWS[category]
        start = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)  # Monday 00:00
        for hour in range(0, 7 * 24, 3):
            moment = start + timedelta(hours=hour)
            practice = session_verdict(category, moment).open
            assert backtest_window.is_open(moment) == practice, (
                f"{category} at {moment.isoformat()}"
            )

    def test_naive_moments_are_treated_as_utc(self) -> None:
        window = CATEGORY_SESSION_WINDOWS["CURRENCY"]
        assert window.is_open(datetime(2026, 8, 10, 22, 0)) is True


class TestVersionedSemanticsRecord:
    def test_semantics_version_is_explicit(self) -> None:
        assert SEMANTICS_VERSION == "oanda-practice-mirror-1"
        assert SEMANTICS_VERSION.strip() != ""

    def test_differences_are_explicitly_recorded(self) -> None:
        assert isinstance(SEMANTICS_DIFFERENCES, tuple)
        # Empty means: the mirrored fields and rules are used unchanged.
        assert SEMANTICS_DIFFERENCES == ()

    def test_fills_record_the_semantics_version(self) -> None:
        from alphabrief_backtest import OrderRequest, execute_order

        request = OrderRequest(
            symbol="EUR_USD",
            side="buy",
            units=Decimal("10000"),
            timestamp=datetime(2026, 8, 10, 22, 0, tzinfo=UTC),
            reference_mid=Decimal("1.10000"),
            fee_bps=Decimal("2"),
            slippage_bps=Decimal("0"),
        )
        fill = execute_order(
            request,
            _backtest_metadata(),
            nav=Decimal("100000"),
            existing_units=Decimal("0"),
            price_age_seconds=0,
        )
        assert fill.accepted
        assert fill.semantics_version == SEMANTICS_VERSION
        assert fill.metadata_version == "instrument-EUR_USD"
