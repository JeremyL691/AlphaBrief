"""Reconciliation runner for external paper broker.

Three reconciliation scopes are supported:

- ``startup``: called by the scheduler before the main loop. Any
  diff raises a freeze.
- ``cycle``: called at the end of each cycle. Diff-only logs; the
  freeze decision is delegated to a configurable policy.
- ``eod``: end-of-day run, always writes a snapshot, never raises
  freeze on transient empty positions (start of trading day).

The runner is **fail-closed**: any exception during a reconciliation
pass records a non-matching snapshot and raises a freeze. The one
exception is :class:`BrokerTransientError` (timeout, 5xx, 429): it
records the failed snapshot for observability, then re-raises so the
scheduler's per-task failure counter drives retries and only freezes
after ``max_consecutive_failures``. It does not swallow errors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from alphabrief_execution.broker.errors import BrokerTransientError
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    OrderState,
    Position,
)
from alphabrief_execution.broker.recon_store import BrokerReconStore, ReconSnapshot
from alphabrief_execution.broker.runtime import NullBrokerAdapter

_LOGGER = logging.getLogger(__name__)

# Allowed scope names. Anything else is rejected at construction time.
ALLOWED_SCOPES: frozenset[str] = frozenset({"startup", "cycle", "eod"})


@dataclass(frozen=True)
class ReconResult:
    """Result of one reconciliation pass."""

    snapshot: ReconSnapshot
    freeze_raised: bool


@dataclass
class ReconcilerConfig:
    """Per-scope freeze policy pending the M07 reconciliation redesign."""

    # When True, a snapshot with any match=False raises a freeze.
    freeze_on_diff: dict[str, bool] = field(
        default_factory=lambda: {
            "startup": True,
            "cycle": True,
            "eod": False,
        }
    )

    def should_freeze(self, scope: str, snapshot: ReconSnapshot) -> bool:
        if scope not in self.freeze_on_diff:
            raise ValueError(f"unknown reconciliation scope: {scope!r}")
        return self.freeze_on_diff[scope] and not snapshot.all_match


class ReconciliationRunner:
    """Run reconciliation passes and persist snapshots + freeze events."""

    def __init__(
        self,
        *,
        adapter: BrokerAdapter,
        store: BrokerReconStore,
        config: ReconcilerConfig | None = None,
    ) -> None:
        self._adapter = adapter
        self._store = store
        self._config = config or ReconcilerConfig()

    async def reconcile(self, *, scope: str) -> ReconResult:
        if scope not in ALLOWED_SCOPES:
            raise ValueError(f"unknown reconciliation scope: {scope!r}")

        if isinstance(self._adapter, NullBrokerAdapter):
            # Fail closed (AC-M07-W06-03): with no OANDA practice broker
            # configured, a pass can never record a vacuous all-match
            # placeholder. The snapshot is explicitly non-matching and the
            # per-scope freeze policy still applies.
            snapshot = self._store.record_snapshot(
                scope=scope,
                orders_match=False,
                fills_match=False,
                cash_match=False,
                positions_match=False,
                diff={
                    "error": "broker_not_configured",
                    "detail": (
                        "no OANDA practice credentials; reconciliation "
                        "cannot run and is recorded as not matching"
                    ),
                },
            )
            freeze_raised = self._maybe_raise_freeze(
                scope, snapshot, source="reconciler"
            )
            return ReconResult(snapshot=snapshot, freeze_raised=freeze_raised)

        try:
            orders = await self._adapter.list_orders()
            positions = await self._adapter.get_positions()
            account = await self._adapter.get_account()
            known = self._store.list_order_id_map()
        except BrokerTransientError as exc:
            # A single transient blip must not halt the run; record the
            # failed snapshot for observability, then re-raise so the
            # scheduler retries and only freezes after
            # max_consecutive_failures.
            self._store.record_snapshot(
                scope=scope,
                orders_match=False,
                fills_match=False,
                cash_match=False,
                positions_match=False,
                diff={
                    "error": "reconciliation probe failed (transient)",
                    "detail": str(exc),
                },
            )
            raise
        except Exception as exc:  # noqa: BLE001 — fail closed
            snapshot = self._store.record_snapshot(
                scope=scope,
                orders_match=False,
                fills_match=False,
                cash_match=False,
                positions_match=False,
                diff={
                    "error": "reconciliation probe failed",
                    "detail": str(exc),
                },
            )
            freeze_raised = self._maybe_raise_freeze(
                scope, snapshot, source="reconciler"
            )
            return ReconResult(snapshot=snapshot, freeze_raised=freeze_raised)

        diff = _diff(orders=orders, positions=positions, account=account, known=known)
        orders_match = not diff["orders"]
        fills_match = not diff["fills"]
        cash_match = not diff["cash"]
        positions_match = not diff["positions"]

        snapshot = self._store.record_snapshot(
            scope=scope,
            orders_match=orders_match,
            fills_match=fills_match,
            cash_match=cash_match,
            positions_match=positions_match,
            diff=diff,
        )

        freeze_raised = self._maybe_raise_freeze(scope, snapshot, source="reconciler")
        return ReconResult(snapshot=snapshot, freeze_raised=freeze_raised)

    # ------------------------------------------------------------------
    # Freeze policy
    # ------------------------------------------------------------------

    def _maybe_raise_freeze(
        self, scope: str, snapshot: ReconSnapshot, *, source: str
    ) -> bool:
        if not self._config.should_freeze(scope, snapshot):
            return False
        reason = (
            f"reconciliation diff in scope={scope}: "
            f"orders={snapshot.orders_match} fills={snapshot.fills_match} "
            f"cash={snapshot.cash_match} positions={snapshot.positions_match}"
        )
        self._store.raise_freeze(
            reason=reason, source=source, related_snapshot_id=snapshot.snapshot_id
        )
        _LOGGER.warning("broker freeze raised: %s", reason)
        return True


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------


def _diff(
    *,
    orders: list[OrderState],
    positions: list[Position],
    account: AccountSnapshot,
    known: list[dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    """Compute a structured diff between local store and remote broker.

    The diff is shaped as four lists keyed by the four reconciliation
    dimensions. An empty list means "matches". Each entry is a small
    JSON-serializable dict so the snapshot can be persisted as JSON.
    """
    known_by_client = {row["client_order_id"]: row["broker_order_id"] for row in known}
    known_by_broker = {row["broker_order_id"]: row["client_order_id"] for row in known}

    orders_diff: list[dict[str, Any]] = []
    for order in orders:
        if order.broker_order_id not in known_by_broker:
            orders_diff.append(
                {
                    "kind": "unknown_broker_order",
                    "broker_order_id": order.broker_order_id,
                    "client_order_id": order.client_order_id,
                    "status": order.status.value,
                }
            )
    for client_id, broker_id in known_by_client.items():
        if not any(order.broker_order_id == broker_id for order in orders):
            if not any(order.status.value == "filled" for order in orders):
                orders_diff.append(
                    {
                        "kind": "missing_broker_order",
                        "broker_order_id": broker_id,
                        "client_order_id": client_id,
                    }
                )

    positions_diff: list[dict[str, Any]] = []
    for position in positions:
        positions_diff.append(
            {
                "kind": "remote_position_present",
                "symbol": position.symbol,
                "quantity": str(position.quantity),
                "average_price": str(position.average_price),
            }
        )

    fills_diff: list[dict[str, Any]] = []
    cash_diff: list[dict[str, Any]] = []
    if account.cash < 0:
        cash_diff.append(
            {
                "kind": "negative_cash",
                "account_id": account.account_id,
                "cash": str(account.cash),
            }
        )

    return {
        "orders": orders_diff,
        "fills": fills_diff,
        "cash": cash_diff,
        "positions": positions_diff,
    }


__all__ = ["ALLOWED_SCOPES", "ReconcilerConfig", "ReconciliationRunner", "ReconResult"]
