"""M07-W03: account projection store — convergence and authority.

Covers:
- full snapshot plus incremental changes converges to the same
  normalized projection as a clean replay of all facts
  (AC-M07-W02-02);
- API, CLI, and scheduler readers resolve the same persisted account
  authority and cannot expose conflicting process-local portfolio state
  (AC-M07-W03-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from alphabrief_execution.broker.oanda.account_projection import (
    AccountProjectionStore,
    AccountSnapshot,
    ProjectionFact,
    resolve_account_snapshot,
)


def _normalized(snapshot: AccountSnapshot) -> dict[str, Any]:
    """The normalized projection without the wall-clock rebuilt_at."""
    return snapshot.model_dump(exclude={"rebuilt_at"})


ACCOUNT = "101-004-1234567-001"
T0 = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _fact(
    fact_id: str,
    kind: str,
    *,
    order_id: str | None = None,
    trade_id: str | None = None,
    units: str = "0",
    price: str | None = None,
    realized_pl: str = "0",
    financing: str = "0",
) -> ProjectionFact:
    return ProjectionFact(
        fact_id=fact_id,
        kind=kind,  # type: ignore[arg-type]
        order_id=order_id,
        trade_id=trade_id,
        instrument="EUR_USD",
        units=Decimal(units),
        price=Decimal(price) if price is not None else None,
        realized_pl=Decimal(realized_pl),
        financing=Decimal(financing),
        occurred_at=T0,
    )


def _full_history() -> list[ProjectionFact]:
    """The complete fact history."""
    return [
        _fact("3001", "DEPOSIT", units="10000.00"),
        _fact("3002", "ORDER_CREATE", order_id="o-1", units="1000", price="1.10500"),
        _fact(
            "3003",
            "ORDER_FILL",
            order_id="o-1",
            trade_id="t-1",
            units="1000",
            price="1.10500",
        ),
        _fact("3004", "DAILY_FINANCING", financing="-0.05"),
        _fact(
            "3005",
            "TRADE_REDUCE",
            trade_id="t-1",
            units="-400",
            price="1.10700",
            realized_pl="0.80",
        ),
        _fact(
            "3006",
            "TRADE_CLOSE",
            trade_id="t-1",
            units="-600",
            price="1.10900",
            realized_pl="2.40",
            financing="-0.02",
        ),
        _fact(
            "3007",
            "ORDER_CREATE",
            order_id="o-2",
            units="-200",
            price="1.10000",
        ),
        _fact(
            "3008",
            "ORDER_FILL",
            order_id="o-2",
            trade_id="t-2",
            units="-200",
            price="1.10000",
        ),
    ]


# ---------------------------------------------------------------------------
# AC-M07-W03-02: full snapshot + incremental changes converge
# ---------------------------------------------------------------------------


def test_incremental_converges_to_clean_replay(tmp_path: Path) -> None:
    history = _full_history()

    # Path A: a clean replay of every fact from scratch.
    clean = AccountProjectionStore(db_path=tmp_path / "clean.db")
    try:
        expected = clean.rebuild(ACCOUNT, history)
    finally:
        clean.close()

    # Path B: a full snapshot, then incremental changes on top.
    incremental = AccountProjectionStore(db_path=tmp_path / "incremental.db")
    try:
        full_snapshot = history[:5]
        delta = history[5:]
        incremental.rebuild(ACCOUNT, full_snapshot)
        actual = incremental.apply_changes(ACCOUNT, delta)
        assert _normalized(actual) == _normalized(expected)
    finally:
        incremental.close()


def test_multiple_incremental_batches_converge(tmp_path: Path) -> None:
    history = _full_history()

    clean = AccountProjectionStore(db_path=tmp_path / "clean.db")
    try:
        expected = clean.rebuild(ACCOUNT, history)
    finally:
        clean.close()

    incremental = AccountProjectionStore(db_path=tmp_path / "incremental.db")
    try:
        incremental.rebuild(ACCOUNT, history[:2])
        incremental.apply_changes(ACCOUNT, history[2:5])
        incremental.apply_changes(ACCOUNT, history[5:7])
        actual = incremental.apply_changes(ACCOUNT, history[7:])
        assert _normalized(actual) == _normalized(expected)
        # The persisted authority matches the clean replay exactly.
        persisted = incremental.snapshot(ACCOUNT)
        assert persisted is not None
        assert _normalized(persisted) == _normalized(expected)
    finally:
        incremental.close()


def test_replay_and_incremental_balance_nav_identical(tmp_path: Path) -> None:
    history = _full_history()
    clean = AccountProjectionStore(db_path=tmp_path / "clean.db")
    incremental = AccountProjectionStore(db_path=tmp_path / "inc.db")
    try:
        expected = clean.rebuild(ACCOUNT, history)
        incremental.rebuild(ACCOUNT, history[:3])
        actual = incremental.apply_changes(ACCOUNT, history[3:])
        assert actual.balance == expected.balance
        assert actual.nav == expected.nav
        assert actual.margin_used == expected.margin_used
        assert actual.unrealized_pl == expected.unrealized_pl
        assert actual.open_trade_count == expected.open_trade_count
        assert actual.orders == expected.orders
        assert actual.trades == expected.trades
        assert actual.positions == expected.positions
        assert actual.fills == expected.fills
    finally:
        clean.close()
        incremental.close()


# ---------------------------------------------------------------------------
# AC-M07-W03-03: one persisted account authority for every reader
# ---------------------------------------------------------------------------


def test_readers_resolve_the_same_persisted_authority(tmp_path: Path) -> None:
    db = tmp_path / "authority.db"
    writer = AccountProjectionStore(db_path=db)
    try:
        writer.rebuild(ACCOUNT, _full_history())
    finally:
        writer.close()

    # API, CLI, and scheduler readers all resolve the same store file.
    first = resolve_account_snapshot(ACCOUNT, db_path=db)
    second = resolve_account_snapshot(ACCOUNT, db_path=db)
    assert first is not None
    assert second is not None
    assert first == second
    assert first.balance == Decimal("10003.13")
    assert first.last_transaction_id == "3008"


def test_reader_never_exposes_process_local_state(tmp_path: Path) -> None:
    db = tmp_path / "authority.db"
    # Two store instances over the same file: a write from one is
    # immediately the authority for the other — no process-local
    # portfolio state can diverge.
    first = AccountProjectionStore(db_path=db)
    second = AccountProjectionStore(db_path=db)
    try:
        first.rebuild(ACCOUNT, _full_history())
        from_second = second.snapshot(ACCOUNT)
        assert from_second is not None
        assert from_second == first.snapshot(ACCOUNT)
    finally:
        first.close()
        second.close()
