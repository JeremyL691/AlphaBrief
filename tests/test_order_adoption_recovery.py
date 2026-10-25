"""An out-of-band broker order has a documented recovery path.

Reconciliation is right to treat an order carrying a client identity this
system never issued as CRITICAL and to freeze new exposure. The problem was
that nothing could ever end that state: an out-of-band order (manual
intervention, an external tool, a test that polluted the account) froze the
account permanently.

Adoption records *why* the order exists, and it must stay deliberately narrow:
it is evidence, not a switch. It lifts no freeze, changes no threshold, and a
full reconciliation still has to come back clean afterwards.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_execution.broker.oanda.account_projection import (
    AccountSnapshot,
)
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger
from alphabrief_execution.broker.oanda.reconcile import (
    Reconciler,
    RemoteAccountView,
    RemoteOrder,
)


def _snapshot() -> AccountSnapshot:
    """A local view with no orders, trades or positions."""
    return AccountSnapshot(
        account_id="acct",
        last_transaction_id="1",
        balance=Decimal("0"),
        nav=Decimal("0"),
        unrealized_pl=Decimal("0"),
        margin_used=Decimal("0"),
        margin_available=Decimal("0"),
        realized_pl=Decimal("0"),
        financing_total=Decimal("0"),
        open_trade_count=0,
        open_position_count=0,
        orders=(),
        trades=(),
        positions=(),
        fills=(),
        rebuilt_at=datetime(2026, 10, 25, tzinfo=UTC),
    )


def _remote(client_order_id: str | None) -> RemoteAccountView:
    return RemoteAccountView(
        account_id="acct",
        orders=(
            RemoteOrder(
                broker_order_id="38",
                state="FILLED",
                units=Decimal("1"),
                client_order_id=client_order_id,
                client_tag=None,
                create_time=None,
            ),
        ),
        trades=(),
        positions=(),
        balance=Decimal("0"),
        nav=Decimal("0"),
        margin_used=Decimal("0"),
        financing_total=None,
        remote_fill_count=0,
        last_transaction_id="1",
    )


def _ledger(tmp_path: Path) -> OrderLedger:
    return OrderLedger(db_path=tmp_path / "ledger.duckdb")


def test_an_unknown_client_identity_is_critical(tmp_path: Path) -> None:
    """The freeze trigger itself must not soften."""
    ledger = _ledger(tmp_path)
    try:
        report = Reconciler().reconcile(
            _snapshot(), _remote("external:intent-42"), ledger=ledger
        )
    finally:
        ledger.close()

    assert [d.severity for d in report.diffs if d.kind == "order_diff"] == ["CRITICAL"]


def test_adoption_records_the_explanation_and_downgrades_to_evidence(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    try:
        ledger.adopt_external_order(
            client_order_id="external:intent-42",
            broker_order_id="38",
            reason="placed by a test run that was not marked practice",
        )
        report = Reconciler().reconcile(
            _snapshot(), _remote("external:intent-42"), ledger=ledger
        )
        stored = ledger.adoption("external:intent-42")
    finally:
        ledger.close()

    order_diffs = [d for d in report.diffs if d.kind == "order_diff"]
    assert [d.severity for d in order_diffs] == ["INFO"]
    assert "placed by a test run" in order_diffs[0].detail
    assert stored is not None and stored["broker_order_id"] == "38"


def test_adoption_requires_a_written_reason(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    try:
        with pytest.raises(ValueError):
            ledger.adopt_external_order(
                client_order_id="external:intent-42",
                broker_order_id="38",
                reason="   ",
            )
    finally:
        ledger.close()


def test_adoption_is_idempotent(tmp_path: Path) -> None:
    """Re-adopting must not rewrite history with a new reason."""
    ledger = _ledger(tmp_path)
    try:
        first = ledger.adopt_external_order(
            client_order_id="external:intent-42",
            broker_order_id="38",
            reason="first explanation",
        )
        second = ledger.adopt_external_order(
            client_order_id="external:intent-42",
            broker_order_id="38",
            reason="a later, different story",
        )
    finally:
        ledger.close()

    assert first["reason"] == "first explanation"
    assert second["reason"] == "first explanation"


def test_adoption_does_not_touch_risk_configuration(tmp_path: Path) -> None:
    """Adoption is bookkeeping: it must not re-enable trading by itself."""
    from alphabrief_core import load_runtime_settings

    before = load_runtime_settings().settings.trading.discipline
    ledger = _ledger(tmp_path)
    try:
        ledger.adopt_external_order(
            client_order_id="external:intent-42",
            broker_order_id="38",
            reason="documented",
        )
    finally:
        ledger.close()
    after = load_runtime_settings().settings.trading.discipline

    assert before == after
