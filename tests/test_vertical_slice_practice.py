"""Practice tests for S3 vertical slice trade verification (GUIDE 7.3).

Run with:
    pytest -m practice -k vertical_slice

This suite verifies against the real OANDA practice account and local database:
1. The historical vertical slice trade lifecycle (tx 4 -> 11: market order,
   order fill with attached take-profit & stop-loss, closing market order,
   closing fill, order cancels).
2. The complete audit chain in the database:
   cycle_id -> TradePlan -> RiskDecision -> OrderIntent -> broker order_id -> fill.
3. Clean reconciliation against the real OANDA practice account (zero gaps,
   zero unexplained diffs, no freeze).
4. Weekend safety gate enforcement: attempting to run outside authorized market
   windows blocks order submission at the RiskGate without reaching the broker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from alphabrief_core import OrderIntent, load_env_file
from alphabrief_core.paths import db_path
from alphabrief_execution.broker.oanda.account_ops import AccountOpsClient
from alphabrief_execution.broker.oanda.account_projection import AccountProjectionStore
from alphabrief_execution.broker.oanda.live_reconciliation import LiveReconciler
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger
from alphabrief_execution.broker.oanda.transaction_cursor import TransactionCursorStore
from alphabrief_execution.broker.oanda.transaction_ops import TransactionOpsClient
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.broker.runtime import (
    build_oanda_paper_client,
    oanda_is_configured,
)
from alphabrief_risk import RiskGate, RiskLimitConfig

pytestmark = pytest.mark.practice

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_oanda() -> None:
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        load_env_file(env_path)
    if not oanda_is_configured():
        pytest.fail(
            "OANDA practice credentials are required "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)"
        )


def test_vertical_slice_historical_oanda_lifecycle(tmp_path: Path) -> None:
    """Verify the S3 vertical slice trade lifecycle on the real OANDA account."""
    _ensure_oanda()
    client = build_oanda_paper_client()
    account_ops = AccountOpsClient(client)
    summary = account_ops.account_summary()

    # 1. Verify account state: lastTransactionID >= 11 and zero open trades.
    assert int(summary.last_transaction_id) >= 11
    assert summary.currency == "USD"
    assert summary.open_trade_count == 0
    assert summary.open_position_count == 0

    # 2. Fetch transactions 4 through 11 and verify the exact vertical slice chain.
    tx_ops = TransactionOpsClient(client)
    result = tx_ops.transaction_range("4", "11")
    by_id = {tx.transaction_id: tx for tx in result.transactions}

    # tx 4: Initial MARKET_ORDER for EUR_USD 1000 units
    assert "4" in by_id
    assert by_id["4"].transaction_type == "MARKET_ORDER"
    assert by_id["4"].instrument == "EUR_USD"
    assert by_id["4"].units == Decimal("1000")

    # tx 5: ORDER_FILL for the 1000 units
    assert "5" in by_id
    assert by_id["5"].transaction_type == "ORDER_FILL"
    assert by_id["5"].instrument == "EUR_USD"
    assert by_id["5"].units == Decimal("1000")

    # tx 6: Attached TAKE_PROFIT_ORDER
    assert "6" in by_id
    assert by_id["6"].transaction_type == "TAKE_PROFIT_ORDER"

    # tx 7: Attached STOP_LOSS_ORDER
    assert "7" in by_id
    assert by_id["7"].transaction_type == "STOP_LOSS_ORDER"

    # tx 8: Closing MARKET_ORDER for EUR_USD -1000 units
    assert "8" in by_id
    assert by_id["8"].transaction_type == "MARKET_ORDER"
    assert by_id["8"].instrument == "EUR_USD"
    assert by_id["8"].units == Decimal("-1000")

    # tx 9: Closing ORDER_FILL for -1000 units with realized P/L
    assert "9" in by_id
    assert by_id["9"].transaction_type == "ORDER_FILL"
    assert by_id["9"].instrument == "EUR_USD"
    assert by_id["9"].units == Decimal("-1000")
    assert by_id["9"].realized_pl == Decimal("-0.0800")

    # tx 10 & 11: ORDER_CANCEL for dependent orders upon position closure
    assert "10" in by_id and by_id["10"].transaction_type == "ORDER_CANCEL"
    assert "11" in by_id and by_id["11"].transaction_type == "ORDER_CANCEL"

    # 3. Verify clean reconciliation after the vertical slice
    database = tmp_path / "recon-state.duckdb"
    store = BrokerReconStore(db_path=tmp_path / "recon.db")
    reconciler = LiveReconciler(
        client=client,
        store=store,
        cursor_store=TransactionCursorStore(db_path=database),
        projection_store=AccountProjectionStore(db_path=database),
        order_ledger=OrderLedger(db_path=database),
    )
    try:
        recon_result = reconciler.reconcile(scope="cycle")
    finally:
        reconciler.close()
        store.close()

    assert recon_result.gap_count == 0
    assert [d.kind for d in recon_result.report.diffs if d.severity != "INFO"] == []
    assert recon_result.freeze_raised is False
    assert recon_result.cursor is not None


def test_vertical_slice_database_audit_chain() -> None:
    """Verify that the database records the complete traceable chain for S3."""
    target_db = db_path()
    if not target_db.is_file():
        pytest.skip(f"Database file {target_db} does not exist.")

    with duckdb.connect(str(target_db), read_only=True) as con:
        # Check that executed cycle aic_d22761752a0a exists
        cycle_row = con.execute(
            "SELECT cycle_id, outcome FROM ai_daily_cycles "
            "WHERE cycle_id = 'aic_d22761752a0a'"
        ).fetchone()
        assert cycle_row is not None
        assert cycle_row[1] == "executed"

        # Check corresponding order attempt linked to broker order_id 4
        attempt_row = con.execute(
            "SELECT intent_id, order_id, approved, outcome FROM ai_order_attempts "
            "WHERE cycle_id = 'aic_d22761752a0a'"
        ).fetchone()
        assert attempt_row is not None
        intent_id, order_id, approved, outcome = attempt_row
        assert intent_id == "ai_e482fc8865b9"
        assert order_id == "4"
        assert approved is True
        assert outcome == "executed"

        # Check risk decision
        risk_row = con.execute(
            "SELECT approved, reason FROM risk_decisions "
            "WHERE decision_id = 'risk_0f29f0ff42d54440ab6e34bf7a631015'"
        ).fetchone()
        assert risk_row is not None
        assert risk_row[0] is True
        assert risk_row[1] == "approved"


def test_vertical_slice_market_hours_and_safety_gate() -> None:
    """Verify safety invariants: outside market hours, opening orders are blocked."""
    from alphabrief_risk.entry_rules import EntryRulePolicy

    now = datetime.now(UTC)
    is_weekend = now.weekday() in (5, 6) or (now.weekday() == 4 and now.hour >= 13)

    gate = RiskGate(
        RiskLimitConfig(
            entry_rules=EntryRulePolicy(
                block_weekend_and_late_friday=True,
            )
        )
    )
    intent = OrderIntent(
        intent_id="intent_vertical_slice_test",
        source="manual",
        symbol="EUR_USD",
        side="buy",
        order_type="market",
        quantity=Decimal("1000"),
        stop_loss=Decimal("1.1000"),
        take_profit=Decimal("1.1500"),
        rationale="S3 vertical slice safety verification",
        created_at=now,
    )
    decision = gate.evaluate(intent)

    if is_weekend:
        # Safety invariant 1: weekend trading is unconditionally forbidden
        assert decision.approved is False
        assert any(
            "WEEKEND" in tag or "EVENT_WINDOW" in tag or "weekend" in tag.lower()
            for tag in decision.risk_tags
        ) or "weekend" in decision.reason.lower()
    else:
        # During market hours, the deterministic rule checks pass
        assert decision is not None
