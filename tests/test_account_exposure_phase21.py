"""Tests for the Phase 21 R21.x extensions to ``AccountExposureContext``.

R21.1 (Phase 19) introduced the value object with the original five
fields. R21.2 / R21.3 extended it with the inputs that the new risk
checks need:

- ``equity``                 (max_leverage / drawdown / daily_loss)
- ``reference_mark_prices``  (max_price_deviation_pct)
- ``equity_high_water_mark`` (max_drawdown_floor_pct)
- ``day_start_equity``       (max_daily_loss_pct)
- ``day_realized_pnl``       (audit / diagnostics)

These tests cover Decimal-floats, ``Field(ge=0)`` boundaries, and
``field_validator`` semantics — the same shape as
``test_account_exposure.py``, only for the new fields.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_risk import AccountExposureContext

NOW = datetime(2026, 6, 23, 10, 0, tzinfo=UTC)


def _ctx(**overrides: object) -> AccountExposureContext:
    payload: dict[str, object] = {
        "current_total_exposure": Decimal("0"),
        "exposure_by_symbol": {},
        "cash": Decimal("1000"),
        "account_id": "acct_p21",
        "captured_at": NOW,
    }
    payload.update(overrides)
    return AccountExposureContext.model_validate(payload)


# ---------------------------------------------------------------------------
# equity
# ---------------------------------------------------------------------------


def test_equity_defaults_to_none() -> None:
    ctx = _ctx()
    assert ctx.equity is None


def test_equity_accepts_zero() -> None:
    ctx = _ctx(equity=Decimal("0"))
    assert ctx.equity == Decimal("0")


def test_equity_accepts_positive_decimal() -> None:
    ctx = _ctx(equity=Decimal("1500.5"))
    assert ctx.equity == Decimal("1500.5")


def test_equity_rejects_negative() -> None:
    with pytest.raises(ValueError):
        _ctx(equity=Decimal("-1"))


def test_equity_rejects_float() -> None:
    with pytest.raises(ValueError):
        _ctx(equity=1500.5)


# ---------------------------------------------------------------------------
# reference_mark_prices
# ---------------------------------------------------------------------------


def test_reference_mark_prices_default_empty() -> None:
    ctx = _ctx()
    assert ctx.reference_mark_prices == {}


def test_reference_mark_prices_accepts_decimal_dict() -> None:
    ctx = _ctx(reference_mark_prices={"SPY": Decimal("100"), "QQQ": Decimal("50")})
    assert ctx.reference_mark_prices == {
        "SPY": Decimal("100"),
        "QQQ": Decimal("50"),
    }


def test_reference_mark_prices_rejects_floats() -> None:
    with pytest.raises(ValueError):
        _ctx(reference_mark_prices={"SPY": 100.0})


# ---------------------------------------------------------------------------
# equity_high_water_mark
# ---------------------------------------------------------------------------


def test_equity_high_water_mark_defaults_to_none() -> None:
    ctx = _ctx()
    assert ctx.equity_high_water_mark is None


def test_equity_high_water_mark_accepts_positive_decimal() -> None:
    ctx = _ctx(equity_high_water_mark=Decimal("2000"))
    assert ctx.equity_high_water_mark == Decimal("2000")


def test_equity_high_water_mark_rejects_negative() -> None:
    with pytest.raises(ValueError):
        _ctx(equity_high_water_mark=Decimal("-1"))


def test_equity_high_water_mark_rejects_float() -> None:
    with pytest.raises(ValueError):
        _ctx(equity_high_water_mark=2000.0)


# ---------------------------------------------------------------------------
# day_start_equity
# ---------------------------------------------------------------------------


def test_day_start_equity_defaults_to_none() -> None:
    ctx = _ctx()
    assert ctx.day_start_equity is None


def test_day_start_equity_accepts_positive_decimal() -> None:
    ctx = _ctx(day_start_equity=Decimal("1000"))
    assert ctx.day_start_equity == Decimal("1000")


def test_day_start_equity_rejects_negative() -> None:
    with pytest.raises(ValueError):
        _ctx(day_start_equity=Decimal("-1"))


# ---------------------------------------------------------------------------
# day_realized_pnl
# ---------------------------------------------------------------------------


def test_day_realized_pnl_defaults_to_none() -> None:
    ctx = _ctx()
    assert ctx.day_realized_pnl is None


def test_day_realized_pnl_accepts_negative_for_loss() -> None:
    """Loss days produce a negative realized PnL. The field has no
    ``ge=0`` constraint because that would reject loss — surface it
    for audit / diagnostics only."""
    ctx = _ctx(day_realized_pnl=Decimal("-50"))
    assert ctx.day_realized_pnl == Decimal("-50")


def test_day_realized_pnl_accepts_positive_for_gain() -> None:
    ctx = _ctx(day_realized_pnl=Decimal("100"))
    assert ctx.day_realized_pnl == Decimal("100")


def test_day_realized_pnl_rejects_float() -> None:
    with pytest.raises(ValueError):
        _ctx(day_realized_pnl=100.0)


# ---------------------------------------------------------------------------
# Round-trip — frozen model can be reconstructed from dict
# ---------------------------------------------------------------------------


def test_account_exposure_round_trip_preserves_phase21_fields() -> None:
    ctx = _ctx(
        equity=Decimal("1000"),
        reference_mark_prices={"SPY": Decimal("500")},
        equity_high_water_mark=Decimal("1200"),
        day_start_equity=Decimal("1100"),
        day_realized_pnl=Decimal("-50"),
    )
    rebuilt = AccountExposureContext.model_validate(ctx.model_dump())
    assert rebuilt.equity == Decimal("1000")
    assert rebuilt.reference_mark_prices == {"SPY": Decimal("500")}
    assert rebuilt.equity_high_water_mark == Decimal("1200")
    assert rebuilt.day_start_equity == Decimal("1100")
    assert rebuilt.day_realized_pnl == Decimal("-50")
