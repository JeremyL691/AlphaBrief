"""Practice test: reconciliation against the real OANDA practice account.

Run with ``pytest -m practice -k live_reconciliation_practice``; CI
excludes it. The account has no open positions, so a clean verdict is the
expected result — and any unexpected diff would surface as a freeze.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_core import load_env_file
from alphabrief_execution.broker.oanda.account_projection import AccountProjectionStore
from alphabrief_execution.broker.oanda.live_reconciliation import LiveReconciler
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger
from alphabrief_execution.broker.oanda.transaction_cursor import (
    TransactionCursorStore,
)
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.broker.runtime import (
    build_oanda_paper_client,
    oanda_is_configured,
)

pytestmark = pytest.mark.practice

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_real_account_reconciles_clean(tmp_path: Path) -> None:
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        load_env_file(env_path)
    if not oanda_is_configured():
        pytest.fail(
            "OANDA practice credentials are required "
            "(ALPHABRIEF_OANDA_TOKEN / ALPHABRIEF_OANDA_ACCOUNT_ID)"
        )

    database = tmp_path / "recon-state.duckdb"
    store = BrokerReconStore(db_path=tmp_path / "recon.db")
    reconciler = LiveReconciler(
        client=build_oanda_paper_client(),
        store=store,
        cursor_store=TransactionCursorStore(db_path=database),
        projection_store=AccountProjectionStore(db_path=database),
        order_ledger=OrderLedger(db_path=database),
    )
    try:
        result = reconciler.reconcile(scope="cycle")
    finally:
        reconciler.close()
        store.close()

    # The practice account has never traded from this system: nothing may
    # be unexplained, so no freeze and no CRITICAL/WARN differences.
    assert result.gap_count == 0
    assert [d.kind for d in result.report.diffs if d.severity != "INFO"] == []
    assert result.freeze_raised is False
    assert result.cursor is not None
