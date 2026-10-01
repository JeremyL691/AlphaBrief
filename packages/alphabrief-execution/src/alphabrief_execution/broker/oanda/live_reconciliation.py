"""Live OANDA reconciliation: cursor → projection → typed diff verdict.

This is the runtime reconciliation path (PROJECT_GUIDE 5.9). It replaces
the old runner that treated *every* remote position and every unregistered
order as a difference — a design that froze the scheduler the moment a
real fill happened.

The pipeline is:

1. fetch the transaction window strictly after the durable cursor and
   advance the cursor atomically (``TransactionCursorStore``);
2. fold those broker facts into the persisted account projection so the
   local side of the comparison is derived from broker facts, never from
   process memory;
3. compare the projection with a fresh remote view through the typed
   :class:`Reconciler`, which classifies differences as explainable
   (own orders, protective-order fills, financing/fees) or not;
4. freeze new exposure only when the verdict is not clean; record the
   snapshot either way.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from alphabrief_execution.broker.oanda.account_ops import AccountOpsClient
from alphabrief_execution.broker.oanda.account_projection import (
    AccountProjectionStore,
    AccountSnapshot,
    FactKind,
    ProjectionFact,
)
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger
from alphabrief_execution.broker.oanda.order_ops import OrderOpsClient
from alphabrief_execution.broker.oanda.position_ops import PositionOpsClient
from alphabrief_execution.broker.oanda.reconcile import (
    DiffRecord,
    Reconciler,
    ReconciliationReport,
    RemoteAccountView,
    RemoteOrder,
    RemotePosition,
    RemoteTrade,
)
from alphabrief_execution.broker.oanda.trade_ops import TradeOpsClient
from alphabrief_execution.broker.oanda.transaction_cursor import (
    TransactionCursorStore,
)
from alphabrief_execution.broker.oanda.transaction_ops import TransactionOpsClient
from alphabrief_execution.broker.recon_store import BrokerReconStore

#: Allowed reconciliation scope names. Anything else is rejected.
ALLOWED_SCOPES: frozenset[str] = frozenset({"startup", "cycle", "eod"})


@dataclass
class ReconcilerConfig:
    """Per-scope freeze policy for unexplained differences."""

    freeze_on_diff: dict[str, bool] = field(
        default_factory=lambda: {
            "startup": True,
            "cycle": True,
            # End-of-day records the verdict but does not freeze: the
            # trading day may legitimately end flat.
            "eod": False,
        }
    )

    def should_freeze(self, scope: str) -> bool:
        if scope not in self.freeze_on_diff:
            raise ValueError(f"unknown reconciliation scope: {scope!r}")
        return self.freeze_on_diff[scope]


#: Transaction types that are explainable by construction.
_EXPLAINABLE_TYPES = frozenset(
    {
        "ORDER_FILL",
        "ORDER_CREATE",
        "ORDER_CANCEL",
        "ORDER_CLIENT_EXTENSIONS_MODIFY",
        "STOP_LOSS_ORDER",
        "TAKE_PROFIT_ORDER",
        "TRAILING_STOP_LOSS_ORDER",
        "MARKET_ORDER",
        "MARKET_ORDER_POSITION_CLOSEOUT",
        "MARKET_ORDER_TRADE_CLOSE",
        "MARKET_ORDER_REDUCE_ONLY",
        "DAILY_FINANCING",
        "TRANSFER_FUNDS",
        "CLIENT_CONFIGURE",
        "CREATE",
    }
)


@dataclass
class LiveReconcileResult:
    """Outcome of one live reconciliation pass."""

    report: ReconciliationReport
    cursor: str | None
    facts_applied: int
    gap_count: int
    freeze_raised: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def clean(self) -> bool:
        return self.report.clean

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.report.account_id,
            "clean": self.clean,
            "cursor": self.cursor,
            "facts_applied": self.facts_applied,
            "gap_count": self.gap_count,
            "freeze_raised": self.freeze_raised,
            "diffs": [
                {
                    "kind": diff.kind,
                    "severity": diff.severity,
                    "source_id": diff.source_id,
                    "detail": diff.detail,
                }
                for diff in self.report.diffs
            ],
            "warnings": list(self.warnings),
        }


#: Transaction types the account projection knows how to fold. Anything
#: else is recorded as evidence but never folded: an unknown type must not
#: silently mutate the local account state.
PROJECTABLE_KINDS: frozenset[str] = frozenset(
    {
        "ORDER_CREATE",
        "ORDER_FILL",
        "ORDER_CANCEL",
        "TRADE_CLOSE",
        "TRADE_REDUCE",
        "DAILY_FINANCING",
        "DEPOSIT",
        "WITHDRAWAL",
    }
)


def facts_from_transactions(
    transactions: Sequence[Any],
) -> tuple[list[ProjectionFact], tuple[str, ...]]:
    """Split transactions into projectable facts and unrecognised types.

    Returns ``(facts, unprojected_types)``. The second element names the
    transaction types that were seen but deliberately not folded, so the
    caller can surface them instead of pretending they were understood.
    """
    facts: list[ProjectionFact] = []
    unprojected: set[str] = set()
    for transaction in transactions:
        transaction_type = str(transaction.transaction_type)
        if transaction_type not in PROJECTABLE_KINDS:
            unprojected.add(transaction_type)
            continue
        trade_id = getattr(transaction, "trade_id", None)
        facts.append(
            ProjectionFact(
                fact_id=str(transaction.transaction_id),
                kind=cast(FactKind, transaction_type),
                order_id=(
                    str(transaction.transaction_id)
                    if transaction_type.startswith("ORDER_")
                    else None
                ),
                trade_id=str(trade_id) if trade_id else None,
                instrument=transaction.instrument,
                units=transaction.units or Decimal("0"),
                price=transaction.price,
                realized_pl=transaction.realized_pl or Decimal("0"),
                financing=transaction.financing or Decimal("0"),
                occurred_at=transaction.time or datetime.now(UTC),
            )
        )
    return facts, tuple(sorted(unprojected))


def explainable_facts(transactions: Sequence[Any]) -> tuple[str, ...]:
    """Return the transaction types seen that are explainable by design."""
    return tuple(
        sorted(
            {
                str(transaction.transaction_type)
                for transaction in transactions
                if str(transaction.transaction_type) in _EXPLAINABLE_TYPES
            }
        )
    )


def rebuild_projection(
    client: OandaHttpClient,
    *,
    projection_store: AccountProjectionStore,
) -> AccountSnapshot:
    """Rebuild the local projection from the account's full history.

    The seed is the *opening* balance: the current balance minus every
    realised P&L and financing amount in the history. Seeding with the
    current balance would double-count that history. Used when the
    projection must be replayed (for example after a parser fix), because
    the projection is derived data and the broker is the authority.
    """
    summary = AccountOpsClient(client).account_summary(request_id="rebuild")
    window = TransactionOpsClient(client).transaction_range(
        from_id="1",
        to_id=summary.last_transaction_id,
        request_id="rebuild",
    )
    facts, _unprojected = facts_from_transactions(window.transactions)
    movement = sum(
        (fact.realized_pl + fact.financing for fact in facts),
        Decimal("0"),
    )
    opening_balance = summary.balance - movement
    return projection_store.rebuild(
        summary.account_id,
        facts,
        initial_balance=opening_balance,
    )


class LiveReconciler:
    """Reconcile the local projection against the live practice account."""

    def __init__(
        self,
        *,
        client: OandaHttpClient,
        store: BrokerReconStore,
        cursor_store: TransactionCursorStore | None = None,
        projection_store: AccountProjectionStore | None = None,
        reconciler: Reconciler | None = None,
        order_ledger: OrderLedger | None = None,
        clock: Callable[[], datetime] | None = None,
        config: ReconcilerConfig | None = None,
    ) -> None:
        self._client = client
        self._store = store
        self._cursor_store = cursor_store or TransactionCursorStore()
        self._projection_store = projection_store or AccountProjectionStore()
        self._reconciler = reconciler or Reconciler()
        self._order_ledger = order_ledger
        self._clock = clock or (lambda: datetime.now(UTC))
        self._config = config or ReconcilerConfig()

    # ------------------------------------------------------------------
    # Remote view
    # ------------------------------------------------------------------

    def account_summary(self) -> Any:
        """Fetch the account summary once per pass."""
        return AccountOpsClient(self._client).account_summary(
            request_id="reconcile-summary"
        )

    def remote_view(
        self, account: Any
    ) -> tuple[RemoteAccountView, AccountSnapshot]:
        """Build the broker's current view from one account summary."""
        orders = OrderOpsClient(self._client).list_orders()
        trades = TradeOpsClient(self._client).list_trades()
        positions = PositionOpsClient(self._client).list_positions()

        return (
            RemoteAccountView(
                account_id=account.account_id,
                orders=tuple(
                    RemoteOrder(
                        broker_order_id=order.broker_order_id,
                        state=str(order.state),
                        units=order.units,
                        client_order_id=order.client_order_id,
                        client_tag=order.client_tag,
                        create_time=order.submitted_at,
                    )
                    for order in orders.orders
                ),
                trades=tuple(
                    RemoteTrade(
                        broker_trade_id=trade.broker_trade_id,
                        state=str(trade.state),
                        current_units=trade.current_units,
                        client_order_id=trade.client_order_id,
                    )
                    for trade in trades.trades
                ),
                positions=tuple(
                    RemotePosition(
                        instrument=position.instrument,
                        long_units=position.long_units,
                        short_units=position.short_units,
                    )
                    for position in positions.positions
                ),
                balance=account.balance,
                nav=account.nav,
                margin_used=account.margin_used,
                financing_total=Decimal("0"),
                remote_fill_count=self._remote_fill_count(
                    account.last_transaction_id
                ),
                last_transaction_id=account.last_transaction_id,
            ),
            AccountSnapshot(
                account_id=account.account_id,
                last_transaction_id=account.last_transaction_id,
                balance=account.balance,
                nav=account.nav,
                unrealized_pl=account.unrealized_pl,
                margin_used=account.margin_used,
                margin_available=account.margin_available,
                realized_pl=Decimal("0"),
                financing_total=Decimal("0"),
                open_trade_count=account.open_trade_count,
                open_position_count=account.open_position_count,
                orders=(),
                trades=(),
                positions=(),
                fills=(),
                rebuilt_at=self._clock(),
            ),
        )

    def _ensure_seeded(self, account_id: str, balance: Decimal) -> None:
        """Seed the projection from the live balance on the first pass.

        Without this the first comparison would see a zero-balance local
        projection against a funded account and report a spurious money
        difference.
        """
        if self._projection_store.snapshot(account_id) is not None:
            return
        self._projection_store.rebuild(
            account_id,
            facts=[],
            initial_balance=balance,
        )

    def _remote_fill_count(self, last_transaction_id: str) -> int:
        """Count the account's fill transactions (broker-authoritative)."""
        window = TransactionOpsClient(self._client).transaction_range(
            from_id="1",
            to_id=last_transaction_id,
            request_id="reconcile-fills",
        )
        return sum(
            1
            for transaction in window.transactions
            if str(transaction.transaction_type) == "ORDER_FILL"
        )

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def sync(
        self, account_id: str
    ) -> tuple[str | None, int, int, tuple[str, ...]]:
        """Advance the cursor and fold new facts into the projection."""
        cursor = self._cursor_store.cursor(account_id) or "0"
        window = TransactionOpsClient(self._client).transactions_since(
            cursor, request_id="reconcile-sync"
        )
        advance = self._cursor_store.advance(
            account_id,
            list(window.transactions),
            owner="reconciler",
        )
        facts, unprojected = facts_from_transactions(window.transactions)
        if facts:
            self._projection_store.apply_changes(account_id, facts)
        if advance.cursor is not None:
            self._projection_store.advance_cursor(account_id, advance.cursor)
        seen = explainable_facts(window.transactions)
        warnings = tuple(sorted({*seen, *unprojected}))
        return advance.cursor, len(facts), len(advance.gaps), warnings

    # ------------------------------------------------------------------
    # Reconcile
    # ------------------------------------------------------------------

    def reconcile(self, *, scope: str = "cycle") -> LiveReconcileResult:
        """Run one full pass: seed, sync, compare, persist, maybe freeze."""
        if scope not in ALLOWED_SCOPES:
            raise ValueError(f"unknown reconciliation scope: {scope!r}")
        summary = self.account_summary()
        # The broker-reported account id is the authority for every local
        # key (cursor, projection): a misconfigured account id must not
        # silently reconcile against a different account's state.
        account_id = summary.account_id
        self._ensure_seeded(account_id, summary.balance)
        cursor, facts_applied, gap_count, warnings = self.sync(account_id)
        remote, account = self.remote_view(summary)
        local = self._projection_store.snapshot(remote.account_id)
        assert local is not None

        # The order ledger is the durable record of this system's own
        # submit identities; it is what lets a matched order reconcile
        # without a false "unknown broker order" alarm.
        ledger = self._order_ledger or OrderLedger()
        report = self._reconciler.reconcile(local, remote, ledger=ledger)
        if gap_count:
            report = report.model_copy(
                update={
                    "diffs": (
                        *report.diffs,
                        DiffRecord(
                            kind="cursor_diff",
                            source_id=remote.account_id,
                            severity="CRITICAL",
                            detail=f"{gap_count} cursor gap(s) after advancing",
                        ),
                    )
                }
            )

        snapshot = self._store.record_snapshot(
            scope=scope,
            orders_match=report.clean,
            fills_match=report.clean,
            cash_match=report.clean,
            positions_match=report.clean,
            diff={
                "diffs": [
                    {
                        "kind": diff.kind,
                        "severity": diff.severity,
                        "source_id": diff.source_id,
                        "detail": diff.detail,
                    }
                    for diff in report.diffs
                ],
                "cursor": cursor,
                "explainable": list(warnings),
            },
        )

        freeze_raised = False
        if not report.clean and self._config.should_freeze(scope):
            reason = "; ".join(
                f"{diff.kind}:{diff.detail}"
                for diff in report.diffs
                if diff.severity != "INFO"
            )[:500]
            self._store.raise_freeze(
                reason=reason or "unexplained reconciliation difference",
                source="reconciler",
                related_snapshot_id=snapshot.snapshot_id,
            )
            freeze_raised = True

        return LiveReconcileResult(
            report=report,
            cursor=cursor,
            facts_applied=facts_applied,
            gap_count=gap_count,
            freeze_raised=freeze_raised,
            warnings=warnings,
        )

    def close(self) -> None:
        self._cursor_store.close()
        self._projection_store.close()


def record_broker_not_configured(
    store: BrokerReconStore,
    *,
    scope: str,
    config: ReconcilerConfig | None = None,
) -> LiveReconcileResult:
    """Record the fail-closed verdict when no practice broker is configured.

    Without credentials there is nothing to compare against, so the
    snapshot is explicitly non-matching: a vacuous "all match" would let
    an unattended run believe it reconciled.
    """
    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"unknown reconciliation scope: {scope!r}")
    policy = config or ReconcilerConfig()
    snapshot = store.record_snapshot(
        scope=scope,
        orders_match=False,
        fills_match=False,
        cash_match=False,
        positions_match=False,
        diff={
            "error": "broker_not_configured",
            "detail": (
                "no OANDA practice credentials; reconciliation cannot run "
                "and is recorded as not matching"
            ),
        },
    )
    freeze_raised = False
    if policy.should_freeze(scope):
        store.raise_freeze(
            reason="broker not configured; reconciliation cannot run",
            source="reconciler",
            related_snapshot_id=snapshot.snapshot_id,
        )
        freeze_raised = True
    report = ReconciliationReport(
        account_id="unconfigured",
        tolerance_version="n/a",
        diffs=(
            DiffRecord(
                kind="account_diff",
                source_id="unconfigured",
                severity="CRITICAL",
                detail="broker_not_configured",
            ),
        ),
        compared_at=datetime.now(UTC),
    )
    return LiveReconcileResult(
        report=report,
        cursor=None,
        facts_applied=0,
        gap_count=0,
        freeze_raised=freeze_raised,
    )


__all__ = [
    "ALLOWED_SCOPES",
    "PROJECTABLE_KINDS",
    "LiveReconcileResult",
    "LiveReconciler",
    "ReconcilerConfig",
    "explainable_facts",
    "facts_from_transactions",
    "record_broker_not_configured",
]
