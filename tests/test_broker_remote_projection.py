"""M07-W03: durable remote account projections — golden history.

Covers:
- golden transaction histories rebuild exact account, order, fill,
  trade, position, balance, NAV, margin, PnL, and financing projections
  with broker IDs and UTC timestamps (AC-M07-W03-01).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_execution.broker.oanda.account_projection import (
    AccountProjectionStore,
    ProjectionFact,
)

ACCOUNT = "101-004-1234567-001"
T0 = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _fact(
    fact_id: str,
    kind: str,
    *,
    order_id: str | None = None,
    trade_id: str | None = None,
    instrument: str | None = "EUR_USD",
    units: str = "0",
    price: str | None = None,
    realized_pl: str = "0",
    financing: str = "0",
    occurred_at: datetime = T0,
) -> ProjectionFact:
    return ProjectionFact(
        fact_id=fact_id,
        kind=kind,  # type: ignore[arg-type]
        order_id=order_id,
        trade_id=trade_id,
        instrument=instrument,
        units=Decimal(units),
        price=Decimal(price) if price is not None else None,
        realized_pl=Decimal(realized_pl),
        financing=Decimal(financing),
        occurred_at=occurred_at,
    )


def _golden_history() -> list[ProjectionFact]:
    """One deterministic golden transaction history."""
    return [
        _fact("2001", "DEPOSIT", units="10000.00"),
        _fact("2002", "ORDER_CREATE", order_id="o-1", units="1000", price="1.10500"),
        _fact(
            "2003",
            "ORDER_FILL",
            order_id="o-1",
            trade_id="t-1",
            units="1000",
            price="1.10500",
        ),
        _fact(
            "2004",
            "ORDER_CREATE",
            order_id="o-2",
            units="-500",
            price="1.10000",
        ),
        _fact(
            "2005",
            "ORDER_FILL",
            order_id="o-2",
            trade_id="t-2",
            units="-500",
            price="1.10000",
            realized_pl="0",
        ),
        _fact("2006", "ORDER_CREATE", order_id="o-3", units="200"),
        _fact("2007", "ORDER_CANCEL", order_id="o-3", units="200"),
        _fact("2008", "DAILY_FINANCING", financing="-0.05"),
        _fact(
            "2009",
            "TRADE_REDUCE",
            trade_id="t-1",
            units="-400",
            price="1.10700",
            realized_pl="0.80",
        ),
        _fact(
            "2010",
            "TRADE_CLOSE",
            trade_id="t-1",
            units="-600",
            price="1.10900",
            realized_pl="2.40",
            financing="-0.02",
        ),
        _fact("2011", "WITHDRAWAL", units="100.00"),
    ]


def test_golden_history_rebuilds_exact_projections(tmp_path: Path) -> None:
    store = AccountProjectionStore(db_path=tmp_path / "projection.db")
    try:
        snapshot = store.rebuild(
            ACCOUNT,
            _golden_history(),
            initial_balance=Decimal("1000.00"),
        )
        assert snapshot.account_id == ACCOUNT
        assert snapshot.last_transaction_id == "2011"
        # Balance: seed 1000 + deposit 10000 - withdrawal 100
        #           + realized (0.80 + 2.40) + financing (-0.05 - 0.02).
        assert snapshot.balance == Decimal("10903.13")
        assert snapshot.realized_pl == Decimal("3.20")
        assert snapshot.financing_total == Decimal("-0.07")
        # Order projections carry broker IDs and states.
        orders = {o.broker_order_id: o for o in snapshot.orders}
        assert orders["o-1"].state == "FILLED"
        assert orders["o-1"].price == Decimal("1.10500")
        assert orders["o-2"].state == "FILLED"
        assert orders["o-3"].state == "CANCELLED"
        # Trades: t-1 closed, t-2 still open (short 500 @ 1.10000).
        trades = {t.broker_trade_id: t for t in snapshot.trades}
        assert trades["t-1"].state == "CLOSED"
        assert trades["t-1"].current_units == Decimal("0")
        assert trades["t-1"].realized_pl == Decimal("3.20")
        assert trades["t-2"].state == "OPEN"
        assert trades["t-2"].current_units == Decimal("-500")
        assert trades["t-2"].open_time == T0
        # Positions: only the open short side remains.
        positions = {p.instrument: p for p in snapshot.positions}
        assert positions["EUR_USD"].short_units == Decimal("500")
        assert positions["EUR_USD"].long_units == Decimal("0")
        # Unrealized: short 500 sold at 1.10000, mark now 1.10900.
        assert positions["EUR_USD"].unrealized_pl == Decimal("-4.50")
        # NAV = balance + unrealized; margin on the short notional.
        assert snapshot.unrealized_pl == Decimal("-4.50")
        assert snapshot.nav == Decimal("10898.63")
        expected_margin = Decimal("500") * Decimal("1.10000") * Decimal("0.05")
        assert snapshot.margin_used == expected_margin
        assert snapshot.margin_available == snapshot.nav - expected_margin
        assert snapshot.open_trade_count == 1
        assert snapshot.open_position_count == 1
        # Fills carry broker IDs and UTC timestamps.
        assert len(snapshot.fills) == 2
        assert snapshot.fills[0].fact_id == "2003"
        assert snapshot.fills[0].occurred_at == T0
    finally:
        store.close()


def test_rebuild_persists_and_reloads_identically(tmp_path: Path) -> None:
    store = AccountProjectionStore(db_path=tmp_path / "projection.db")
    try:
        first = store.rebuild(ACCOUNT, _golden_history())
        second = store.snapshot(ACCOUNT)
        assert second is not None
        assert second == first
        # UTC timestamps survive the round trip.
        assert second.fills[0].occurred_at.tzinfo is not None
    finally:
        store.close()


def test_unknown_fact_kind_is_rejected_at_construction() -> None:
    # Unsupported fact kinds fail closed at construction: a projection
    # can never silently skip a fact it does not understand.
    with pytest.raises(ValueError):
        _fact("2012", "CLIENT_CONFIGURE", instrument=None)
