"""Tests for AccountExposureContext (Phase 19 R19.1)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_risk import AccountExposureContext

NOW = datetime(2026, 6, 23, 10, 0, tzinfo=UTC)


def _ctx(**overrides: object) -> AccountExposureContext:
    payload: dict[str, object] = {
        "current_total_exposure": Decimal("150"),
        "exposure_by_symbol": {"SPY": Decimal("150")},
        "cash": Decimal("850"),
        "account_id": "acct_1",
        "captured_at": NOW,
    }
    payload.update(overrides)
    return AccountExposureContext.model_validate(payload)


def test_account_exposure_context_constructs_with_defaults() -> None:
    ctx = AccountExposureContext(
        current_total_exposure=Decimal("0"),
        cash=Decimal("1000"),
        account_id="acct_1",
        captured_at=NOW,
    )
    assert ctx.current_total_exposure == Decimal("0")
    assert ctx.exposure_by_symbol == {}
    assert ctx.cash == Decimal("1000")
    assert ctx.account_id == "acct_1"
    assert ctx.captured_at == NOW


def test_account_exposure_context_is_frozen() -> None:
    ctx = _ctx()
    with pytest.raises((ValueError, TypeError)):
        ctx.current_total_exposure = Decimal("999")


def test_account_exposure_context_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        AccountExposureContext.model_validate(
            {
                "current_total_exposure": Decimal("0"),
                "cash": Decimal("1000"),
                "account_id": "acct_1",
                "captured_at": NOW,
                "secret": "nope",
            }
        )


def test_account_exposure_context_rejects_float_totals() -> None:
    with pytest.raises(ValueError):
        AccountExposureContext.model_validate(
            {
                "current_total_exposure": 150.0,
                "cash": Decimal("850"),
                "account_id": "acct_1",
                "captured_at": NOW,
            }
        )


def test_account_exposure_context_rejects_float_cash() -> None:
    with pytest.raises(ValueError):
        AccountExposureContext.model_validate(
            {
                "current_total_exposure": Decimal("0"),
                "cash": 850.0,
                "account_id": "acct_1",
                "captured_at": NOW,
            }
        )


def test_account_exposure_context_rejects_float_in_exposure_by_symbol() -> None:
    with pytest.raises(ValueError):
        AccountExposureContext.model_validate(
            {
                "current_total_exposure": Decimal("0"),
                "exposure_by_symbol": {"SPY": 150.0},
                "cash": Decimal("850"),
                "account_id": "acct_1",
                "captured_at": NOW,
            }
        )


def test_account_exposure_context_rejects_negative_total_exposure() -> None:
    with pytest.raises(ValueError):
        AccountExposureContext.model_validate(
            {
                "current_total_exposure": Decimal("-1"),
                "cash": Decimal("850"),
                "account_id": "acct_1",
                "captured_at": NOW,
            }
        )


def test_account_exposure_context_rejects_blank_account_id() -> None:
    with pytest.raises(ValueError):
        AccountExposureContext.model_validate(
            {
                "current_total_exposure": Decimal("0"),
                "cash": Decimal("850"),
                "account_id": "",
                "captured_at": NOW,
            }
        )


def test_account_exposure_context_rejects_naive_captured_at() -> None:
    naive = datetime(2026, 6, 23, 10, 0)  # no tzinfo
    with pytest.raises(ValueError):
        AccountExposureContext.model_validate(
            {
                "current_total_exposure": Decimal("0"),
                "cash": Decimal("850"),
                "account_id": "acct_1",
                "captured_at": naive,
            }
        )


def test_account_exposure_context_allows_negative_cash() -> None:
    # Cash may legitimately be negative (margin / overdraft); the
    # exposure check does not gate on it, so it must be accepted.
    ctx = _ctx(cash=Decimal("-50"))
    assert ctx.cash == Decimal("-50")
