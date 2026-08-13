"""M08-W03: home-currency exposure property matrix (AC-M08-W03-01).

Property matrices cover long and short FX legs, Metal and CFD exposure,
pending orders, hedged and netted positions, account-currency
conversion, category totals, currency-direction totals, correlated
groups, and concentration — all in account home currency with
Decimal-safe evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from alphabrief_risk.exposure_aggregation import (
    CategoryEvidence,
    ConversionEvidence,
    CorrelationEvidence,
    CurrencyDirectionEvidence,
    ExposureInputs,
    ExposureSnapshot,
    PendingOrderLeg,
    PositionLeg,
    PriceEvidence,
    compute_exposure,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _price(symbol: str, mid: str) -> PriceEvidence:
    return PriceEvidence(
        symbol=symbol, mid=Decimal(mid), captured_at=NOW, source_id=f"px-{symbol}"
    )


def _conversion(symbol: str, factor: str) -> ConversionEvidence:
    return ConversionEvidence(
        symbol=symbol,
        factor=Decimal(factor),
        captured_at=NOW,
        source_id=f"fx-{symbol}",
    )


def _category(symbol: str, category: str) -> CategoryEvidence:
    return CategoryEvidence(symbol=symbol, category=category)


def _direction(symbol: str, currency: str) -> CurrencyDirectionEvidence:
    return CurrencyDirectionEvidence(symbol=symbol, currency=currency)


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
            _category("EUR_USD", "CURRENCY"),
            _category("XAU_USD", "METAL"),
        ),
        "currency_directions": (
            _direction("EUR_USD", "EUR"),
            _direction("XAU_USD", "USD"),
        ),
    }
    payload.update(overrides)
    return ExposureInputs.model_validate(payload)


def _snapshot(**overrides: object) -> ExposureSnapshot:
    return compute_exposure(_inputs(**overrides))


# ---------------------------------------------------------------------------
# Long / short FX legs, hedged and netted positions
# ---------------------------------------------------------------------------


def test_long_fx_leg_exposure_in_home_currency() -> None:
    snapshot = _snapshot()
    by_symbol = {s.symbol: s for s in snapshot.symbols}
    eur = by_symbol["EUR_USD"]
    # 10000 units * 1.10 * factor 1.0 = 11000 home-currency gross.
    assert eur.post_gross == Decimal("11000.0000")
    assert eur.post_long == Decimal("11000.0000")
    assert eur.post_short == Decimal("0")
    assert eur.post_net == Decimal("11000.0000")
    assert eur.category == "CURRENCY"
    assert eur.currency == "EUR"
    # Metal exposure at 10 * 4000 = 40000.
    xau = by_symbol["XAU_USD"]
    assert xau.post_gross == Decimal("40000.000")
    assert snapshot.total_post_gross == Decimal("51000.0000")
    assert snapshot.long_total == Decimal("51000.0000")
    assert snapshot.short_total == Decimal("0")
    # Concentration: XAU is the largest symbol fraction.
    assert snapshot.concentration == Decimal("40000.000") / Decimal("51000.0000")


def test_short_fx_leg_reports_short_side() -> None:
    snapshot = _snapshot(
        positions=(
            PositionLeg(symbol="EUR_USD", short_units=Decimal("5000")),
        ),
    )
    by_symbol = {s.symbol: s for s in snapshot.symbols}
    eur = by_symbol["EUR_USD"]
    assert eur.post_short == Decimal("5500.0000")
    assert eur.post_long == Decimal("0")
    assert eur.post_net == Decimal("-5500.0000")
    assert snapshot.short_total == Decimal("5500.0000")
    assert snapshot.total_post_net == Decimal("-5500.0000")


def test_hedged_position_nets_to_zero_gross_keeps_both_sides() -> None:
    snapshot = _snapshot(
        positions=(
            PositionLeg(
                symbol="EUR_USD",
                long_units=Decimal("10000"),
                short_units=Decimal("10000"),
            ),
        ),
    )
    eur = snapshot.symbols[0]
    # Hedged units net to zero but the gross exposure is still real.
    assert eur.post_net == Decimal("0")
    assert eur.post_gross == Decimal("22000.0000")
    assert snapshot.total_post_net == Decimal("0")
    assert snapshot.total_post_gross == Decimal("22000.0000")


def test_cfd_exposure_with_pending_order_projects_post_trade() -> None:
    snapshot = _snapshot(
        positions=(PositionLeg(symbol="US30_USD", long_units=Decimal("2")),),
        pending_orders=(
            PendingOrderLeg(
                symbol="US30_USD",
                units=Decimal("1"),
                price=Decimal("40000"),
            ),
        ),
        prices=(_price("US30_USD", "40000.00"),),
        conversions=(_conversion("US30_USD", "1.0"),),
        categories=(_category("US30_USD", "CFD"),),
        currency_directions=(_direction("US30_USD", "USD"),),
    )
    us30 = snapshot.symbols[0]
    # Pre-trade 2 * 40000 = 80000; the pending order adds 1 * 40000.
    assert us30.pre_gross == Decimal("80000")
    assert us30.post_gross == Decimal("120000")
    assert snapshot.total_pre_gross == Decimal("80000")
    assert snapshot.total_post_gross == Decimal("120000")


# ---------------------------------------------------------------------------
# Category totals, currency-direction totals, correlated groups
# ---------------------------------------------------------------------------


def test_category_totals_aggregate_in_home_currency() -> None:
    snapshot = _snapshot(
        positions=(
            PositionLeg(symbol="EUR_USD", long_units=Decimal("10000")),
            PositionLeg(symbol="GBP_USD", long_units=Decimal("5000")),
            PositionLeg(symbol="XAU_USD", long_units=Decimal("10")),
        ),
        prices=(
            _price("EUR_USD", "1.10000"),
            _price("GBP_USD", "1.30000"),
            _price("XAU_USD", "4000.00"),
        ),
        conversions=(
            _conversion("EUR_USD", "1.0"),
            _conversion("GBP_USD", "1.0"),
            _conversion("XAU_USD", "1.0"),
        ),
        categories=(
            _category("EUR_USD", "CURRENCY"),
            _category("GBP_USD", "CURRENCY"),
            _category("XAU_USD", "METAL"),
        ),
        currency_directions=(
            _direction("EUR_USD", "EUR"),
            _direction("GBP_USD", "GBP"),
            _direction("XAU_USD", "USD"),
        ),
    )
    category_totals = dict((c, g) for c, g, _n in snapshot.category_totals)
    # CURRENCY: 11000 + 6500 = 17500; METAL: 40000.
    assert category_totals["CURRENCY"] == Decimal("17500.0000")
    assert category_totals["METAL"] == Decimal("40000.000")
    currency_totals = dict((c, g) for c, g, _n in snapshot.currency_direction_totals)
    assert currency_totals["EUR"] == Decimal("11000.0000")
    assert currency_totals["GBP"] == Decimal("6500.0000")
    assert currency_totals["USD"] == Decimal("40000.000")


def test_correlated_group_totals_and_evidence() -> None:
    snapshot = _snapshot(
        positions=(
            PositionLeg(symbol="EUR_USD", long_units=Decimal("10000")),
            PositionLeg(symbol="XAU_USD", long_units=Decimal("10")),
        ),
        correlation_groups=(
            CorrelationEvidence(
                group="euro-bloc",
                symbols=("EUR_USD",),
                source_id="corr-1",
                captured_at=NOW,
            ),
            CorrelationEvidence(
                group="precious",
                symbols=("XAU_USD",),
                source_id="corr-2",
                captured_at=NOW,
            ),
        ),
    )
    group_totals = dict(snapshot.correlated_group_totals)
    assert group_totals["euro-bloc"] == Decimal("11000.0000")
    assert group_totals["precious"] == Decimal("40000.000")
    assert snapshot.correlation_evidence == (
        ("euro-bloc", "corr-1"),
        ("precious", "corr-2"),
    )
    # Conversion evidence trail is preserved per symbol.
    assert snapshot.conversion_evidence == (
        ("EUR_USD", "fx-EUR_USD"),
        ("XAU_USD", "fx-XAU_USD"),
    )


def test_conversion_factor_applies_to_home_currency() -> None:
    # USD_JPY quoted in JPY with a USD home account: factor converts.
    snapshot = _snapshot(
        positions=(PositionLeg(symbol="USD_JPY", long_units=Decimal("100000")),),
        prices=(_price("USD_JPY", "150.00"),),
        conversions=(_conversion("USD_JPY", "0.00666667"),),
        categories=(_category("USD_JPY", "CURRENCY"),),
        currency_directions=(_direction("USD_JPY", "USD"),),
    )
    usdjpy = snapshot.symbols[0]
    # 100000 * 150 * 0.00666667 = 100000.05 home-currency gross.
    assert usdjpy.post_gross == Decimal("100000.05")
    assert snapshot.home_currency == "USD"


def test_leverage_is_gross_over_equity() -> None:
    snapshot = _snapshot(equity=Decimal("50000"))
    assert snapshot.leverage == Decimal("51000.0000") / Decimal("50000")
