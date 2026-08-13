"""M08-W06: reduce-only and close validation (AC-M08-W06-02/03).

Reduce-only and close operations are permitted only when they provably
reduce the relevant position and gross risk and still satisfy
instrument, price, identity, and audit rules. A mislabeled reduce
request, side reversal, over-close, exposure-increasing dependent order,
stale quantity, or missing position truth fails closed — reduce-only can
never be used as a bypass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphabrief_risk.reduce_only import (
    PositionTruth,
    ReduceOnlyOrder,
    ReduceOnlyPreconditions,
    validate_reduce_only,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _long_position(**overrides: object) -> PositionTruth:
    payload: dict[str, object] = {
        "symbol": "EUR_USD",
        "long_units": Decimal("10000"),
        "short_units": Decimal("0"),
        "average_price": Decimal("1.10000"),
        "captured_at": NOW,
        "source_id": "pos-1",
    }
    payload.update(overrides)
    return PositionTruth.model_validate(payload)


def _short_position(**overrides: object) -> PositionTruth:
    payload: dict[str, object] = {
        "symbol": "EUR_USD",
        "long_units": Decimal("0"),
        "short_units": Decimal("5000"),
        "average_price": Decimal("1.10000"),
        "captured_at": NOW,
        "source_id": "pos-1",
    }
    payload.update(overrides)
    return PositionTruth.model_validate(payload)


def _preconditions(**overrides: object) -> ReduceOnlyPreconditions:
    payload: dict[str, object] = {
        "identity_matched": True,
        "instrument_rules_ok": True,
        "price_fresh": True,
        "audit_recorded": True,
    }
    payload.update(overrides)
    return ReduceOnlyPreconditions.model_validate(payload)


def _order(**overrides: object) -> ReduceOnlyOrder:
    payload: dict[str, object] = {
        "side": "sell",
        "units": Decimal("2000"),
        "price": Decimal("1.10000"),
    }
    payload.update(overrides)
    return ReduceOnlyOrder.model_validate(payload)


# ---------------------------------------------------------------------------
# AC-M08-W06-02: permitted only when it provably reduces risk
# ---------------------------------------------------------------------------


def test_valid_long_reduce_is_permitted_and_reduces_gross() -> None:
    verdict = validate_reduce_only(
        position=_long_position(),
        order=_order(),
        preconditions=_preconditions(),
        now=NOW,
    )
    assert verdict.permitted is True
    assert verdict.reasons == ()
    # Gross 10000 * 1.10 = 11000 -> 8000 * 1.10 = 8800.
    assert verdict.pre_gross == Decimal("11000.0000")
    assert verdict.post_gross == Decimal("8800.0000")
    assert verdict.reduced_by == Decimal("2200.0000")


def test_valid_short_reduce_is_permitted() -> None:
    verdict = validate_reduce_only(
        position=_short_position(),
        order=_order(side="buy", units=Decimal("1000")),
        preconditions=_preconditions(),
        now=NOW,
    )
    assert verdict.permitted is True
    assert verdict.reduced_by == Decimal("1100.0000")


def test_full_close_is_permitted() -> None:
    verdict = validate_reduce_only(
        position=_long_position(),
        order=_order(units=Decimal("10000")),
        preconditions=_preconditions(),
        now=NOW,
    )
    assert verdict.permitted is True
    assert verdict.post_gross == Decimal("0")
    assert verdict.reduced_by == verdict.pre_gross


# ---------------------------------------------------------------------------
# AC-M08-W06-03: every bypass attempt fails closed
# ---------------------------------------------------------------------------


def test_mislabeled_reduce_without_preconditions_fails() -> None:
    verdict = validate_reduce_only(
        position=_long_position(),
        order=_order(),
        preconditions=_preconditions(
            identity_matched=False, instrument_rules_ok=False
        ),
        now=NOW,
    )
    assert verdict.permitted is False
    assert any("preconditions failed" in reason for reason in verdict.reasons)


def test_side_reversal_fails() -> None:
    verdict = validate_reduce_only(
        position=_long_position(),
        order=_order(side="buy"),
        preconditions=_preconditions(),
        now=NOW,
    )
    assert verdict.permitted is False
    assert any("side reversal" in reason for reason in verdict.reasons)
    verdict = validate_reduce_only(
        position=_short_position(),
        order=_order(side="sell"),
        preconditions=_preconditions(),
        now=NOW,
    )
    assert verdict.permitted is False
    assert any("side reversal" in reason for reason in verdict.reasons)


def test_over_close_fails() -> None:
    verdict = validate_reduce_only(
        position=_long_position(),
        order=_order(units=Decimal("10001")),
        preconditions=_preconditions(),
        now=NOW,
    )
    assert verdict.permitted is False
    assert any("over-close" in reason for reason in verdict.reasons)


def test_exposure_increasing_dependent_order_fails() -> None:
    verdict = validate_reduce_only(
        position=_long_position(),
        order=_order(dependent_increases_exposure=True),
        preconditions=_preconditions(),
        now=NOW,
    )
    assert verdict.permitted is False
    assert any("increases exposure" in reason for reason in verdict.reasons)


def test_stale_quantity_fails() -> None:
    verdict = validate_reduce_only(
        position=_long_position(captured_at=NOW - timedelta(seconds=600)),
        order=_order(position_max_age_seconds=300),
        preconditions=_preconditions(),
        now=NOW,
    )
    assert verdict.permitted is False
    assert any("stale" in reason for reason in verdict.reasons)


def test_missing_position_truth_fails() -> None:
    verdict = validate_reduce_only(
        position=_long_position(long_units=Decimal("0")),
        order=_order(),
        preconditions=_preconditions(),
        now=NOW,
    )
    assert verdict.permitted is False
    assert any("no position truth" in reason for reason in verdict.reasons)


def test_reduce_on_wrong_side_fails_when_no_matching_side() -> None:
    # Long position, sell is valid; a buy into flat fails as reversal.
    verdict = validate_reduce_only(
        position=_long_position(long_units=Decimal("0")),
        order=_order(side="buy"),
        preconditions=_preconditions(),
        now=NOW,
    )
    assert verdict.permitted is False


def test_float_inputs_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        _order(units=1000.0)
    with pytest.raises(ValueError):
        _long_position(long_units=10000.0)
