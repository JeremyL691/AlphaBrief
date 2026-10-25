"""A fill that reduces a trade must stay linked to that trade.

OANDA's ORDER_FILL transaction references the affected trade through
``tradeOpened`` (a dict), ``tradesClosed`` (an array) or — for a *partial*
reduction — ``tradeReduced`` (**a singular dict**). The parser only read the
first two shapes plus ``tradesReduced``, so every partial close lost its trade
link. The projection then received a fill with ``trade_id is None`` and dropped
it, leaving the local position permanently one step behind the broker: the
account reconciled as a CRITICAL ``quantity_diff`` on every cycle forever.

The soak found this the first time a position was partially reduced.
"""

from __future__ import annotations

from decimal import Decimal

from alphabrief_execution.broker.oanda.transaction_ops import _transaction_from_row


def _fill_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "39",
        "type": "ORDER_FILL",
        "time": "2026-10-23T06:40:11.632465708Z",
        "instrument": "EUR_USD",
        "units": "1",
        "price": "1.12089",
        "reason": "MARKET_ORDER",
    }
    row.update(overrides)
    return row


def test_a_partially_reduced_trade_keeps_its_link() -> None:
    """``tradeReduced`` is a single object, and that is the shape OANDA sends."""
    transaction = _transaction_from_row(
        _fill_row(tradeReduced={"tradeID": "35", "units": "1", "price": "1.12089"}),
        request_id="probe",
    )

    assert transaction.trade_id == "35", (
        "the fill was dropped from the projection because its trade link was "
        "never read, so the local position can never match the broker"
    )


def test_a_closed_trade_keeps_its_link() -> None:
    """``tradesClosed`` is an array; it must keep working."""
    transaction = _transaction_from_row(
        _fill_row(tradesClosed=[{"tradeID": "35", "units": "-44581"}])
        | {"units": "-44581"},
        request_id="probe",
    )

    assert transaction.trade_id == "35"


def test_an_opened_trade_keeps_its_link() -> None:
    """``tradeOpened`` is a single object; it must keep working."""
    transaction = _transaction_from_row(
        _fill_row(tradeOpened={"tradeID": "35", "units": "-44582"}),
        request_id="probe",
    )

    assert transaction.trade_id == "35"


def test_a_fill_without_any_trade_reference_stays_unlinked() -> None:
    """No reference means no link; inventing one would corrupt the projection."""
    transaction = _transaction_from_row(_fill_row(), request_id="probe")

    assert transaction.trade_id is None
    assert Decimal(str(transaction.units)) == Decimal("1")
