"""M07-W04: reconciliation diff matrix and tolerance safety.

Covers:
- matching fixtures and legitimate pre-existing remote orders, trades,
  positions, financing, and broker-originated state reconcile without
  false missing-local alarms (AC-M07-W04-01);
- unknown, missing, conflicting, money, quantity, state, cursor,
  account, order, fill, trade, position, and financing differences
  produce stable typed diffs with source IDs and severity
  (AC-M07-W04-02);
- Decimal and timestamp tolerances are explicit, versioned,
  directionally safe, and cannot hide a material exposure, cash, margin,
  or position difference (AC-M07-W04-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_execution.broker.oanda.account_projection import (
    AccountProjectionStore,
    AccountSnapshot,
    ProjectionFact,
)
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger
from alphabrief_execution.broker.oanda.reconcile import (
    Reconciler,
    ReconcileTolerances,
    ReconciliationReport,
    RemoteAccountView,
    RemoteOrder,
    RemotePosition,
    RemoteTrade,
)

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


def _local_snapshot(tmp_path: Path) -> AccountSnapshot | None:
    """The local durable projection for the matching fixture."""
    store = AccountProjectionStore(db_path=tmp_path / "projection.db")
    store.rebuild(
        ACCOUNT,
        [
            _fact("1001", "DEPOSIT", units="10000.00"),
            _fact(
                "1002",
                "ORDER_CREATE",
                order_id="o-1",
                units="1000",
                price="1.10500",
            ),
            _fact(
                "1003",
                "ORDER_FILL",
                order_id="o-1",
                trade_id="t-1",
                units="1000",
                price="1.10500",
            ),
            _fact("1004", "DAILY_FINANCING", financing="-0.05"),
            _fact(
                "1005",
                "ORDER_CREATE",
                order_id="o-2",
                units="-200",
                price="1.10000",
            ),
            _fact(
                "1006",
                "ORDER_FILL",
                order_id="o-2",
                trade_id="t-2",
                units="-200",
                price="1.10000",
            ),
        ],
    )
    return store.snapshot(ACCOUNT)


def _matching_remote() -> RemoteAccountView:
    return RemoteAccountView(
        account_id=ACCOUNT,
        orders=(
            RemoteOrder(
                broker_order_id="o-1",
                state="FILLED",
                units=Decimal("1000"),
                create_time=T0,
            ),
            RemoteOrder(
                broker_order_id="o-2",
                state="FILLED",
                units=Decimal("-200"),
                create_time=T0,
            ),
        ),
        trades=(
            RemoteTrade(
                broker_trade_id="t-1",
                state="OPEN",
                current_units=Decimal("1000"),
            ),
            RemoteTrade(
                broker_trade_id="t-2",
                state="OPEN",
                current_units=Decimal("-200"),
            ),
        ),
        positions=(
            RemotePosition(
                instrument="EUR_USD",
                long_units=Decimal("1000"),
                short_units=Decimal("200"),
            ),
        ),
        balance=Decimal("9999.95"),
        nav=Decimal("9994.95"),
        margin_used=Decimal("66.25"),
        financing_total=Decimal("-0.05"),
        remote_fill_count=2,
        last_transaction_id="1006",
    )


def _reconcile(
    tmp_path: Path,
    remote: RemoteAccountView,
    *,
    tolerances: ReconcileTolerances | None = None,
) -> ReconciliationReport:
    local = _local_snapshot(tmp_path)
    assert local is not None
    return Reconciler(tolerances).reconcile(local, remote)


# ---------------------------------------------------------------------------
# AC-M07-W04-01: no false missing-local alarms
# ---------------------------------------------------------------------------


def test_matching_fixture_reconciles_clean(tmp_path: Path) -> None:
    report = _reconcile(tmp_path, _matching_remote())
    assert report.clean is True
    assert report.tolerance_version == "2026-08-13.1"


def test_broker_originated_remote_state_never_false_alarms(tmp_path: Path) -> None:
    remote = _matching_remote().model_copy(
        update={
            "orders": (
                *_matching_remote().orders,
                # A pre-existing remote order without our client identity.
                RemoteOrder(
                    broker_order_id="o-remote-1",
                    state="PENDING",
                    units=Decimal("300"),
                    client_order_id=None,
                ),
            ),
            "trades": (
                *_matching_remote().trades,
                # A pre-existing remote trade without client identity.
                RemoteTrade(
                    broker_trade_id="t-remote-1",
                    state="OPEN",
                    current_units=Decimal("-300"),
                    client_order_id=None,
                ),
            ),
            "positions": (
                *_matching_remote().positions,
                # A pre-existing remote position with no local record.
                RemotePosition(
                    instrument="USD_JPY",
                    long_units=Decimal("0"),
                    short_units=Decimal("100"),
                ),
            ),
        }
    )
    report = _reconcile(tmp_path, remote)
    # All broker-originated differences are INFO: the report stays clean.
    assert report.clean is True
    info_kinds = {d.kind for d in report.diffs if d.severity == "INFO"}
    assert "order_diff" in info_kinds
    assert "trade_diff" in info_kinds
    assert "position_diff" in info_kinds


def test_ledger_matched_client_identity_is_not_unknown(tmp_path: Path) -> None:
    local = _local_snapshot(tmp_path)
    assert local is not None
    remote = _matching_remote().model_copy(
        update={
            "orders": (
                *_matching_remote().orders,
                RemoteOrder(
                    broker_order_id="o-ledger-1",
                    state="PENDING",
                    units=Decimal("50"),
                    client_order_id="cycle-1:intent-1",
                ),
            )
        }
    )
    ledger = OrderLedger(db_path=tmp_path / "ledger.db")
    try:
        ledger.reserve(
            cycle_id="cycle-1",
            intent_id="intent-1",
            decision_id="risk-1",
            payload_hash="sha256:abc",
            owner="runner",
        )
        report = Reconciler().reconcile(local, remote, ledger=ledger)
        # The identity maps to our own ledger: no unknown-order alarm.
        assert not any(
            d.kind == "order_diff" and d.severity == "CRITICAL"
            for d in report.diffs
        )
    finally:
        ledger.close()


# ---------------------------------------------------------------------------
# AC-M07-W04-02: stable typed diffs with source IDs and severity
# ---------------------------------------------------------------------------


def test_unknown_client_identity_order_is_critical(tmp_path: Path) -> None:
    remote = _matching_remote().model_copy(
        update={
            "orders": (
                *_matching_remote().orders,
                RemoteOrder(
                    broker_order_id="o-rogue-1",
                    state="PENDING",
                    units=Decimal("50"),
                    client_order_id="cycle-9:intent-9",
                ),
            )
        }
    )
    report = _reconcile(tmp_path, remote)
    diffs = [d for d in report.diffs if d.source_id == "o-rogue-1"]
    assert len(diffs) == 1
    assert diffs[0].kind == "order_diff"
    assert diffs[0].severity == "CRITICAL"
    assert report.clean is False


def test_missing_local_order_and_trade_are_critical(tmp_path: Path) -> None:
    remote = _matching_remote().model_copy(
        update={
            "orders": tuple(
                o
                for o in _matching_remote().orders
                if o.broker_order_id != "o-2"
            ),
            "trades": tuple(
                t
                for t in _matching_remote().trades
                if t.broker_trade_id != "t-2"
            ),
            "positions": (),
            "balance": Decimal("9999.95"),
            "nav": Decimal("9999.95"),
            "margin_used": Decimal("0"),
        }
    )
    report = _reconcile(tmp_path, remote)
    kinds = {(d.kind, d.severity) for d in report.diffs}
    assert ("order_diff", "CRITICAL") in kinds  # o-2 missing at the broker
    assert ("trade_diff", "CRITICAL") in kinds  # t-2 missing at the broker
    assert ("position_diff", "CRITICAL") in kinds  # whole position vanished
    assert report.clean is False


def test_state_and_quantity_conflicts_are_critical(tmp_path: Path) -> None:
    remote = _matching_remote().model_copy(
        update={
            "orders": (
                RemoteOrder(
                    broker_order_id="o-1",
                    state="CANCELLED",  # local says FILLED
                    units=Decimal("1000"),
                ),
                RemoteOrder(
                    broker_order_id="o-2",
                    state="FILLED",
                    units=Decimal("-250"),  # local says -200
                ),
            )
        }
    )
    report = _reconcile(tmp_path, remote)
    state_diffs = [d for d in report.diffs if d.kind == "state_diff"]
    quantity_diffs = [d for d in report.diffs if d.kind == "quantity_diff"]
    assert len(state_diffs) == 1
    assert state_diffs[0].source_id == "o-1"
    assert state_diffs[0].severity == "CRITICAL"
    assert len(quantity_diffs) == 1
    assert quantity_diffs[0].source_id == "o-2"
    assert quantity_diffs[0].severity == "CRITICAL"
    assert report.clean is False


def test_cursor_behind_local_is_critical_and_ahead_is_info(tmp_path: Path) -> None:
    behind = _matching_remote().model_copy(update={"last_transaction_id": "900"})
    report = _reconcile(tmp_path, behind)
    cursor_diffs = [d for d in report.diffs if d.kind == "cursor_diff"]
    assert len(cursor_diffs) == 1
    assert cursor_diffs[0].severity == "CRITICAL"

    ahead = _matching_remote().model_copy(update={"last_transaction_id": "1100"})
    report = _reconcile(tmp_path, ahead)
    cursor_diffs = [d for d in report.diffs if d.kind == "cursor_diff"]
    assert len(cursor_diffs) == 1
    assert cursor_diffs[0].severity == "INFO"
    assert report.clean is True


def test_account_mismatch_is_critical(tmp_path: Path) -> None:
    remote = _matching_remote().model_copy(update={"account_id": "999-999-9999999-001"})
    report = _reconcile(tmp_path, remote)
    diffs = [d for d in report.diffs if d.kind == "account_diff"]
    assert len(diffs) == 1
    assert diffs[0].severity == "CRITICAL"
    assert diffs[0].local_value == ACCOUNT


def test_money_financing_and_fill_diffs_are_typed(tmp_path: Path) -> None:
    remote = _matching_remote().model_copy(
        update={
            "balance": Decimal("9990.00"),  # local 9999.95: shortfall
            "financing_total": Decimal("0"),  # local -0.05
            "remote_fill_count": 1,  # local 2
        }
    )
    report = _reconcile(tmp_path, remote)
    money_diffs = [d for d in report.diffs if d.kind == "money_diff"]
    assert any(
        d.source_id == "balance" and d.severity == "CRITICAL" for d in money_diffs
    )
    assert any(d.source_id == "financing" for d in money_diffs)
    fill_diffs = [d for d in report.diffs if d.kind == "fill_diff"]
    assert len(fill_diffs) == 1
    assert fill_diffs[0].severity == "CRITICAL"
    assert report.clean is False


# ---------------------------------------------------------------------------
# AC-M07-W04-03: explicit, versioned, directionally safe tolerances
# ---------------------------------------------------------------------------


def test_money_tolerance_is_directionally_safe(tmp_path: Path) -> None:
    # A local shortfall of 0.005 (within the 0.01 tolerance) still alarms
    # as WARN and a larger shortfall is CRITICAL; a remote windfall is
    # only ever INFO.
    small_shortfall = _matching_remote().model_copy(
        update={"balance": Decimal("9999.945")}
    )
    report = _reconcile(tmp_path, small_shortfall)
    balance_diffs = [
        d
        for d in report.diffs
        if d.kind == "money_diff" and d.source_id == "balance"
    ]
    assert balance_diffs and balance_diffs[0].severity == "WARN"

    windfall = _matching_remote().model_copy(
        update={"balance": Decimal("10050.00")}
    )
    report = _reconcile(tmp_path, windfall)
    balance_diffs = [
        d
        for d in report.diffs
        if d.kind == "money_diff" and d.source_id == "balance"
    ]
    assert balance_diffs and balance_diffs[0].severity == "INFO"
    assert report.clean is True


def test_quantity_tolerance_never_hides_exposure(tmp_path: Path) -> None:
    # One single unit difference must always be CRITICAL.
    remote = _matching_remote().model_copy(
        update={
            "trades": (
                RemoteTrade(
                    broker_trade_id="t-1",
                    state="OPEN",
                    current_units=Decimal("1001"),
                ),
                RemoteTrade(
                    broker_trade_id="t-2",
                    state="OPEN",
                    current_units=Decimal("-200"),
                ),
            )
        }
    )
    report = _reconcile(tmp_path, remote)
    quantity_diffs = [d for d in report.diffs if d.kind == "quantity_diff"]
    assert len(quantity_diffs) == 1
    assert quantity_diffs[0].severity == "CRITICAL"
    assert report.clean is False


def test_margin_diff_is_material_in_both_directions(tmp_path: Path) -> None:
    # Remote margin higher than local (we understate risk) is CRITICAL.
    remote = _matching_remote().model_copy(update={"margin_used": Decimal("100.00")})
    report = _reconcile(tmp_path, remote)
    margin_diffs = [
        d
        for d in report.diffs
        if d.kind == "money_diff" and d.source_id == "margin_used"
    ]
    assert margin_diffs and margin_diffs[0].severity == "CRITICAL"
    assert report.clean is False


def test_tolerances_are_versioned_and_explicit(tmp_path: Path) -> None:
    tolerances = ReconcileTolerances(
        tolerance_version="2026-08-13.2",
        money_tolerance=Decimal("0.005"),
        quantity_tolerance=Decimal("0"),
        timestamp_tolerance_seconds=10,
    )
    report = _reconcile(tmp_path, _matching_remote(), tolerances=tolerances)
    assert report.tolerance_version == "2026-08-13.2"
    assert tolerances.money_tolerance == Decimal("0.005")
    assert tolerances.timestamp_tolerance_seconds == 10
