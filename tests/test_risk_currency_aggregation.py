"""M08-W03: exposure limits and fail-closed evidence (AC-M08-W03-02/03).

- single-order, symbol, category, direction, gross, net, leverage, and
  concentration limits clamp or reject against the projected post-trade
  exposure with Decimal-safe evidence (AC-M08-W03-02);
- missing, stale, zero, inconsistent, or unsupported conversion and
  correlation evidence fails closed and can never fall back to nominal
  units or cost basis (AC-M08-W03-03).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alphabrief_risk.exposure_aggregation import (
    CategoryEvidence,
    ConversionEvidence,
    CorrelationEvidence,
    CurrencyDirectionEvidence,
    ExposureError,
    ExposureInputs,
    ExposureLimits,
    ExposureSnapshot,
    PositionLeg,
    PriceEvidence,
    compute_exposure,
    evaluate_exposure_limits,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _price(symbol: str, mid: str, captured_at: datetime = NOW) -> PriceEvidence:
    return PriceEvidence(
        symbol=symbol,
        mid=Decimal(mid),
        captured_at=captured_at,
        source_id=f"px-{symbol}",
    )


def _conversion(
    symbol: str, factor: str, captured_at: datetime = NOW
) -> ConversionEvidence:
    return ConversionEvidence(
        symbol=symbol,
        factor=Decimal(factor),
        captured_at=captured_at,
        source_id=f"fx-{symbol}",
    )


def _inputs(**overrides: object) -> ExposureInputs:
    payload: dict[str, object] = {
        "home_currency": "USD",
        "equity": Decimal("100000"),
        "positions": (
            PositionLeg(symbol="EUR_USD", long_units=Decimal("10000")),
            PositionLeg(symbol="XAU_USD", long_units=Decimal("10")),
        ),
        "prices": (
            _price("EUR_USD", "1.10000"),
            _price("XAU_USD", "4000.00"),
        ),
        "conversions": (
            _conversion("EUR_USD", "1.0"),
            _conversion("XAU_USD", "1.0"),
        ),
        "categories": (
            CategoryEvidence(symbol="EUR_USD", category="CURRENCY"),
            CategoryEvidence(symbol="XAU_USD", category="METAL"),
        ),
        "currency_directions": (
            CurrencyDirectionEvidence(symbol="EUR_USD", currency="EUR"),
            CurrencyDirectionEvidence(symbol="XAU_USD", currency="USD"),
        ),
    }
    payload.update(overrides)
    return ExposureInputs.model_validate(payload)


def _snapshot(**overrides: object) -> ExposureSnapshot:
    return compute_exposure(_inputs(**overrides))


def _limits(**overrides: object) -> ExposureLimits:
    return ExposureLimits.model_validate(overrides)


# ---------------------------------------------------------------------------
# AC-M08-W03-02: limits evaluate against projected post-trade exposure
# ---------------------------------------------------------------------------


def test_single_order_notional_limit_rejects_overage() -> None:
    snapshot = _snapshot()
    results = evaluate_exposure_limits(
        snapshot,
        _limits(max_single_order_notional=Decimal("5000")),
        order_symbol="EUR_USD",
        order_notional=Decimal("6000"),
    )
    by_limit = {r.limit: r for r in results}
    assert by_limit["max_single_order_notional"].passed is False
    assert by_limit["max_single_order_notional"].value == "6000"
    results_ok = evaluate_exposure_limits(
        snapshot,
        _limits(max_single_order_notional=Decimal("5000")),
        order_symbol="EUR_USD",
        order_notional=Decimal("5000"),
    )
    assert results_ok[0].passed is True


def test_order_notional_missing_fails_closed() -> None:
    results = evaluate_exposure_limits(
        _snapshot(),
        _limits(max_single_order_notional=Decimal("5000")),
    )
    assert results[0].passed is False
    assert "not supplied" in results[0].detail


def test_symbol_limit_binds_to_order_symbol() -> None:
    snapshot = _snapshot()
    results = evaluate_exposure_limits(
        snapshot,
        _limits(max_symbol_exposure=Decimal("30000")),
        order_symbol="XAU_USD",
    )
    by_limit = {r.limit: r for r in results}
    # XAU post-trade gross is 40000 > 30000.
    assert by_limit["max_symbol_exposure"].passed is False
    assert by_limit["max_symbol_exposure"].value == "40000.000"


def test_category_direction_gross_net_leverage_concentration() -> None:
    results = evaluate_exposure_limits(
        _snapshot(),
        _limits(
            max_category_exposure=Decimal("20000"),
            max_direction_exposure=Decimal("60000"),
            max_gross_exposure=Decimal("50000"),
            max_net_exposure=Decimal("60000"),
            max_leverage=Decimal("1"),
            max_concentration_pct=Decimal("0.5"),
        ),
    )
    by_limit = {r.limit: r for r in results}
    assert by_limit["max_category_exposure"].passed is False  # METAL 40000 > 20000
    assert by_limit["max_direction_exposure"].passed is True  # long 51000 <= 60000
    assert by_limit["max_gross_exposure"].passed is False  # 51000 > 50000
    assert by_limit["max_net_exposure"].passed is True  # 51000 <= 60000
    assert by_limit["max_leverage"].passed is True  # 0.51 <= 1
    assert by_limit["max_concentration_pct"].passed is False  # ~0.784 > 0.5


def test_all_limits_pass_within_ceilings() -> None:
    results = evaluate_exposure_limits(
        _snapshot(),
        _limits(
            max_single_order_notional=Decimal("100000"),
            max_symbol_exposure=Decimal("50000"),
            max_category_exposure=Decimal("50000"),
            max_direction_exposure=Decimal("100000"),
            max_gross_exposure=Decimal("100000"),
            max_net_exposure=Decimal("100000"),
            max_leverage=Decimal("2"),
            max_concentration_pct=Decimal("1"),
        ),
        order_symbol="EUR_USD",
        order_notional=Decimal("1000"),
    )
    assert all(result.passed for result in results)
    assert {r.limit for r in results} == {
        "max_single_order_notional",
        "max_symbol_exposure",
        "max_category_exposure",
        "max_direction_exposure",
        "max_gross_exposure",
        "max_net_exposure",
        "max_leverage",
        "max_concentration_pct",
    }


def test_unconfigured_limits_emit_no_results() -> None:
    results = evaluate_exposure_limits(_snapshot(), _limits())
    assert results == ()


# ---------------------------------------------------------------------------
# AC-M08-W03-03: evidence fails closed, never nominal/cost-basis fallback
# ---------------------------------------------------------------------------


def test_missing_price_fails_closed() -> None:
    with pytest.raises(ExposureError) as excinfo:
        _snapshot(prices=(_price("EUR_USD", "1.10000"),))
    assert excinfo.value.kind == "missing_price"
    assert "XAU_USD" in excinfo.value.detail


def test_missing_conversion_fails_closed() -> None:
    with pytest.raises(ExposureError) as excinfo:
        _snapshot(conversions=(_conversion("EUR_USD", "1.0"),))
    assert excinfo.value.kind == "missing_conversion"
    assert "XAU_USD" in excinfo.value.detail


def test_stale_conversion_fails_closed() -> None:
    stale = NOW - timedelta(seconds=600)
    with pytest.raises(ExposureError) as excinfo:
        compute_exposure(
            _inputs(
                conversions=(
                    _conversion("EUR_USD", "1.0", captured_at=stale),
                    _conversion("XAU_USD", "1.0", captured_at=stale),
                ),
            ),
            clock=lambda: NOW,
        )
    assert excinfo.value.kind == "stale_conversion"


def test_zero_conversion_factor_fails_closed() -> None:
    # A zero/negative factor is rejected at schema construction — the
    # evidence can never enter the computation.
    with pytest.raises(ValueError):
        _conversion("EUR_USD", "0")
    with pytest.raises(ValueError):
        _conversion("EUR_USD", "-1")


def test_missing_category_and_currency_direction_fail_closed() -> None:
    with pytest.raises(ExposureError) as excinfo:
        _snapshot(categories=(CategoryEvidence(symbol="EUR_USD", category="CURRENCY"),))
    assert excinfo.value.kind == "missing_category"
    with pytest.raises(ExposureError) as excinfo:
        _snapshot(
            currency_directions=(
                CurrencyDirectionEvidence(symbol="EUR_USD", currency="EUR"),
            )
        )
    assert excinfo.value.kind == "missing_currency_direction"


def test_symbol_in_no_correlation_group_fails_closed() -> None:
    with pytest.raises(ExposureError) as excinfo:
        _snapshot(
            correlation_groups=(
                CorrelationEvidence(
                    group="precious",
                    symbols=("XAU_USD",),
                    source_id="corr-1",
                    captured_at=NOW,
                ),
            )
        )
    assert excinfo.value.kind == "unsupported_correlation"
    assert "EUR_USD" in excinfo.value.detail


def test_symbol_in_two_correlation_groups_fails_closed() -> None:
    with pytest.raises(ExposureError) as excinfo:
        _snapshot(
            correlation_groups=(
                CorrelationEvidence(
                    group="a",
                    symbols=("EUR_USD", "XAU_USD"),
                    source_id="c1",
                    captured_at=NOW,
                ),
                CorrelationEvidence(
                    group="b", symbols=("EUR_USD",), source_id="c2", captured_at=NOW
                ),
            )
        )
    assert excinfo.value.kind == "unsupported_correlation"
    assert "2 correlation groups" in excinfo.value.detail


def test_zero_or_negative_equity_fails_closed() -> None:
    with pytest.raises(ValueError):
        _inputs(equity=Decimal("0"))
    with pytest.raises(ValueError):
        _inputs(equity=Decimal("-100"))


def test_float_exposure_values_rejected() -> None:
    with pytest.raises(ValueError):
        PositionLeg(symbol="EUR_USD", long_units=1000.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ConversionEvidence(
            symbol="EUR_USD",
            factor=1.0,  # type: ignore[arg-type]
            captured_at=NOW,
            source_id="fx-EUR_USD",
        )
