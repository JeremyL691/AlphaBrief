"""Long/short units must use one sign convention on both sides.

OANDA reports a short position's units as a negative number
(``"short": {"units": "-44582"}``) while a long is positive. The local
projection stores each side as a magnitude, because a position's short side is
already labelled by the field name.

The reconciler compared the two conventions directly, so an open short position
subtracted as ``44582 - (-44582)`` and every cycle reported a CRITICAL
``quantity_diff`` and raised a freeze. The soak surfaced it the first time a
position stayed open across a reconciliation.

Normalising at the broker boundary keeps one convention everywhere else.
"""

from __future__ import annotations

from decimal import Decimal

from alphabrief_execution.broker.oanda.live_reconciliation import (
    normalize_position_units,
)


def test_a_short_position_is_stored_as_a_magnitude() -> None:
    """OANDA's negative short units become the magnitude the projection uses."""
    assert normalize_position_units(Decimal("0"), Decimal("-44582")) == (
        Decimal("0"),
        Decimal("44582"),
    )


def test_a_long_position_is_unchanged() -> None:
    """A long side is already positive; normalising must not alter it."""
    assert normalize_position_units(Decimal("44582"), Decimal("0")) == (
        Decimal("44582"),
        Decimal("0"),
    )


def test_a_signed_positive_value_is_still_a_magnitude() -> None:
    """Some feeds report short units as positive; both forms normalise alike."""
    assert normalize_position_units(Decimal("0"), Decimal("44582")) == (
        Decimal("0"),
        Decimal("44582"),
    )


def test_matching_magnitudes_compare_equal() -> None:
    """The pair the reconciler sees is what the local projection holds."""
    local_long, local_short = Decimal("0"), Decimal("44582")
    remote_long, remote_short = normalize_position_units(
        Decimal("0"), Decimal("-44582")
    )

    assert (local_long, local_short) == (remote_long, remote_short)


def test_an_empty_position_normalises_to_zero() -> None:
    assert normalize_position_units(Decimal("0"), Decimal("0")) == (
        Decimal("0"),
        Decimal("0"),
    )
