"""Tests for the risk-based position sizing (PROJECT_GUIDE 5.6)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from alphabrief_trader.sizing import (
    DEFAULT_MAX_ORDER_NOTIONAL_PCT,
    DEFAULT_RISK_PCT,
    SizingError,
    compute_units,
    soak_risk_pct,
)

NAV = Decimal("100000")


class TestRiskBudget:
    def test_risk_amount_is_a_quarter_percent_of_nav(self) -> None:
        result = compute_units(
            nav=NAV,
            stop_distance=Decimal("0.0050"),
            price=Decimal("1.1000"),
        )

        assert result.risk_amount == NAV * DEFAULT_RISK_PCT
        # 250 / 0.0050 = 50000 units, but the notional cap binds first.
        assert result.units > 0

    def test_soak_first_days_risk_half(self) -> None:
        assert soak_risk_pct(soak_day=1) == DEFAULT_RISK_PCT / 2
        assert soak_risk_pct(soak_day=3) == DEFAULT_RISK_PCT / 2
        assert soak_risk_pct(soak_day=4) == DEFAULT_RISK_PCT
        assert soak_risk_pct(soak_day=None) == DEFAULT_RISK_PCT


class TestEurUsdSizing:
    """EUR_USD: the quote currency is the home currency (factor 1)."""

    def test_units_follow_the_risk_budget(self) -> None:
        result = compute_units(
            nav=NAV,
            stop_distance=Decimal("0.0050"),
            quote_to_home=Decimal("1"),
            trade_units_precision=0,
            minimum_trade_size=Decimal("1"),
            price=Decimal("1.1000"),
            max_order_notional_pct=None,
        )

        # 100000 * 0.0025 = 250 risk; 250 / 0.0050 = 50000 units.
        assert result.units == Decimal("50000")
        assert result.outcome == "sized"

    def test_notional_cap_clamps_the_size(self) -> None:
        result = compute_units(
            nav=NAV,
            stop_distance=Decimal("0.0050"),
            quote_to_home=Decimal("1"),
            price=Decimal("1.1000"),
            max_order_notional_pct=DEFAULT_MAX_ORDER_NOTIONAL_PCT,
        )

        # 50% of 100000 NAV at 1.10 = 45454 units.
        assert result.units == Decimal("45454")
        assert "clamped" in result.reason
        assert result.notional <= NAV * DEFAULT_MAX_ORDER_NOTIONAL_PCT


class TestUsdJpySizing:
    """USD_JPY: the quote currency is JPY, so the factor converts the loss."""

    def test_conversion_factor_is_applied(self) -> None:
        # 1 JPY is about 0.0067 USD, so the same price move risks far less
        # per unit and the position must be correspondingly larger.
        result = compute_units(
            nav=NAV,
            stop_distance=Decimal("0.150"),
            quote_to_home=Decimal("0.0066667"),
            trade_units_precision=0,
            minimum_trade_size=Decimal("1"),
            price=Decimal("150"),
            # No notional cap here: this test is about the risk budget.
            max_order_notional_pct=None,
        )

        # 250 / (0.150 * 0.0066667) = 249998.75, floored to 249998 units:
        # sizing never rounds up past the risk budget.
        assert result.units == Decimal("249998")
        assert result.outcome == "sized"

    def test_without_the_factor_the_size_would_be_wrong(self) -> None:
        with_factor = compute_units(
            nav=NAV,
            stop_distance=Decimal("0.150"),
            quote_to_home=Decimal("0.0066667"),
            price=Decimal("150"),
            max_order_notional_pct=None,
        )
        without_factor = compute_units(
            nav=NAV,
            stop_distance=Decimal("0.150"),
            quote_to_home=Decimal("1"),
            price=Decimal("150"),
            max_order_notional_pct=None,
        )

        assert with_factor.units > without_factor.units


class TestNoTradeCases:
    def test_zero_units_is_no_trade(self) -> None:
        result = compute_units(
            nav=NAV,
            stop_distance=Decimal("100000"),
            price=Decimal("1.1"),
        )

        assert result.outcome == "no_trade"
        assert result.units == 0
        assert "rounds to zero" in result.reason

    def test_below_minimum_trade_size_is_no_trade(self) -> None:
        result = compute_units(
            nav=NAV,
            stop_distance=Decimal("5000"),
            minimum_trade_size=Decimal("1000"),
            price=Decimal("1.1"),
        )

        assert result.outcome == "no_trade"

    def test_cap_leaving_nothing_is_no_trade(self) -> None:
        result = compute_units(
            nav=Decimal("10"),
            stop_distance=Decimal("0.0001"),
            price=Decimal("1.1"),
            max_order_notional_pct=Decimal("0.01"),
        )

        assert result.outcome == "no_trade"
        assert "notional cap" in result.reason


class TestValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"nav": Decimal("0")},
            {"stop_distance": Decimal("0")},
            {"quote_to_home": Decimal("0")},
            {"risk_pct": Decimal("0")},
        ],
    )
    def test_invalid_inputs_are_refused(self, kwargs: dict[str, object]) -> None:
        payload: dict[str, Any] = {
            "nav": NAV,
            "stop_distance": Decimal("0.005"),
            "quote_to_home": Decimal("1"),
            "price": Decimal("1.1"),
            "risk_pct": DEFAULT_RISK_PCT,
        }
        payload.update(kwargs)

        with pytest.raises(SizingError):
            compute_units(**payload)

    def test_fractional_precision_is_respected(self) -> None:
        result = compute_units(
            nav=NAV,
            stop_distance=Decimal("0.0075"),
            trade_units_precision=1,
            price=Decimal("1.1000"),
            max_order_notional_pct=None,
        )

        # 250 / 0.0075 = 33333.33..., floored to one decimal place.
        assert result.units == Decimal("33333.3")
        assert result.units % Decimal("0.1") == 0
