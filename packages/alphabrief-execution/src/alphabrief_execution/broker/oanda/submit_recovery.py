"""Durable submit workflow and restart recovery (M07-W06).

Orchestrates every external submission transition through one durable
path — reserve -> bind approved decision -> submit attempt -> send ->
broker result -> fact commit -> cursor advance -> reconciliation — where
each transition is a compare-and-set over the append-only order ledger
(M07-W01). A crash at any named fault point leaves a deterministic
boundary; re-running the same ``(cycle_id, intent_id)`` from a fresh
process resumes from that boundary and never creates a second external
order.

An in-flight (``SUBMITTED``) outcome is always resolved by querying the
broker for the persisted client identity (REQ-EXEC-005) — never by
re-submitting and never by guessing. An unresolved or never-received
submit freezes both the ledger reservation and new exposure; blocking
reconciliation differences after a completed submit freeze new exposure
only, because the external order itself is an immutable terminal fact.

:class:`StartupSyncService` is the restart entry point (REQ-EXEC-011,
REQ-OPS-006): it resolves every in-flight reservation by query, restores
the durable ``submit_id -> broker_order_id`` mapping into the process
adapter, and reports the persisted transaction cursor so no restart ever
re-submits or re-consumes facts.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.oanda.freeze_policy import (
    ExposureFreezeStore,
)
from alphabrief_execution.broker.oanda.order_ledger import OrderLedger
from alphabrief_execution.broker.oanda.order_ops import OrderCreateResult
from alphabrief_execution.broker.oanda.reconcile import (
    ReconciliationReport,
)
from alphabrief_execution.broker.oanda.transaction_cursor import (
    AdvanceResult,
    TransactionCursorStore,
)
from alphabrief_execution.broker.oanda.unknown_outcome import (
    UnknownOutcomeResolver,
)

FaultPoint = Literal[
    "before_reserve",
    "after_reserve",
    "before_send",
    "after_send",
    "after_response",
    "during_fact_commit",
    "during_cursor_advance",
    "during_reconciliation",
]

#: The eight crash-injection points named by AC-M07-W06-01 across every
#: external submission transition.
FAULT_POINTS: tuple[FaultPoint, ...] = (
    "before_reserve",
    "after_reserve",
    "before_send",
    "after_send",
    "after_response",
    "during_fact_commit",
    "during_cursor_advance",
    "during_reconciliation",
)


class InjectedCrash(RuntimeError):
    """Raised by a fault hook to simulate a process crash at a named point."""


class SubmitRecoveryError(RuntimeError):
    """A classified submit-recovery failure (always fail-closed)."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        super().__init__(f"submit recovery failed ({kind}): {detail}")


class SubmitWorkflowResult(BaseModel):
    """One deterministic terminal verdict for a durable submit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    submit_id: str = Field(min_length=1)
    state: Literal["COMPLETED", "FROZEN"]
    reused: bool
    broker_order_id: str | None = None
    detail: str = ""


class SubmitWorkflow:
    """One durable external submission, resumable across crashes.

    The ledger compare-and-set transitions guarantee that any crash
    leaves either the old complete state or the new complete state, so
    the workflow is safe to re-run from a fresh process with the same
    parameters. A ``fault`` hook lets tests inject :class:`InjectedCrash`
    at each of the eight named transition boundaries.
    """

    def __init__(
        self,
        *,
        ledger: OrderLedger,
        account_id: str,
        owner: str,
        resolve: UnknownOutcomeResolver | None = None,
        freeze_store: ExposureFreezeStore | None = None,
        fault: Callable[[FaultPoint], None] | None = None,
    ) -> None:
        self._ledger = ledger
        self._account_id = account_id
        self._owner = owner
        self._resolve = resolve
        self._freeze_store = freeze_store
        self._fault = fault or (lambda point: None)

    def run(
        self,
        *,
        cycle_id: str,
        intent_id: str,
        decision_id: str,
        payload_hash: str,
        submit: Callable[[], OrderCreateResult],
        commit_facts: Callable[[], AdvanceResult] | None = None,
        reconcile: Callable[[], ReconciliationReport] | None = None,
    ) -> SubmitWorkflowResult:
        """Run the durable submit; idempotent across crashes and restarts.

        ``submit`` performs the actual external send and must be bound to
        the persisted client identity (``cycle:intent``). ``commit_facts``
        and ``reconcile`` are the optional post-completion steps; both
        are idempotent (the cursor store deduplicates facts and
        reconciliation is read-only), so replays re-run them safely.
        """
        self._fault("before_reserve")
        outcome = self._ledger.reserve(
            cycle_id=cycle_id,
            intent_id=intent_id,
            decision_id=decision_id,
            payload_hash=payload_hash,
            owner=self._owner,
        )
        submit_id = outcome.submit_id
        if outcome.status == "FROZEN":
            return SubmitWorkflowResult(
                submit_id=submit_id,
                state="FROZEN",
                reused=True,
                detail="reservation frozen by a prior run",
            )

        broker_order_id: str | None = None
        if outcome.status != "COMPLETED":
            self._fault("after_reserve")
            if outcome.status in ("RESERVED", "BOUND"):
                # Idempotent: a BOUND replay returns without a new event.
                self._ledger.bind_decision(
                    submit_id,
                    decision_id=decision_id,
                    payload_hash=payload_hash,
                    owner=self._owner,
                )
            self._fault("before_send")
            current = self._ledger.status(submit_id)
            if current == "SUBMITTED":
                # A prior process crashed after the send: resolve by
                # query, never by re-submitting.
                resolved = resolve_in_flight(
                    self._ledger,
                    self._resolve,
                    submit_id,
                    owner=self._owner,
                    account_id=self._account_id,
                    freeze_store=self._freeze_store,
                    reason="in-flight submit recovered after restart",
                )
                if resolved is None:
                    return SubmitWorkflowResult(
                        submit_id=submit_id,
                        state="FROZEN",
                        reused=True,
                        detail="in-flight submit outcome unresolved; frozen",
                    )
                broker_order_id = resolved
            elif current in ("RESERVED", "BOUND"):
                self._ledger.record_submit_attempt(
                    submit_id, payload_hash=payload_hash, owner=self._owner
                )
                try:
                    result = submit()
                except Exception as exc:  # noqa: BLE001 — fail closed
                    # The broker may or may not have accepted the order;
                    # query the persisted client identity before deciding.
                    resolved = resolve_in_flight(
                        self._ledger,
                        self._resolve,
                        submit_id,
                        owner=self._owner,
                        account_id=self._account_id,
                        freeze_store=self._freeze_store,
                        reason=f"submit outcome unknown after failure: {exc}",
                    )
                    if resolved is None:
                        return SubmitWorkflowResult(
                            submit_id=submit_id,
                            state="FROZEN",
                            reused=True,
                            detail="submit outcome unresolved; frozen",
                        )
                    broker_order_id = resolved
                else:
                    self._fault("after_send")
                    self._ledger.record_broker_result(
                        submit_id,
                        broker_order_id=result.broker_order_id,
                        state=result.state,
                        transaction_id=None,
                        owner=self._owner,
                    )
                    broker_order_id = result.broker_order_id
            elif current == "FROZEN":
                return SubmitWorkflowResult(
                    submit_id=submit_id,
                    state="FROZEN",
                    reused=True,
                    detail="reservation frozen by a prior run",
                )
            else:
                raise SubmitRecoveryError(
                    "state_conflict",
                    f"submit {submit_id} in unexpected state {current!r}",
                )
        else:
            reservation = self._ledger.reservation(submit_id)
            broker_order_id = (
                reservation["broker_order_id"] if reservation else None
            )

        self._fault("after_response")
        if commit_facts is not None:
            self._fault("during_fact_commit")
            commit_facts()
            self._fault("during_cursor_advance")
        if reconcile is not None:
            self._fault("during_reconciliation")
            report = reconcile()
            if not report.clean:
                blocking = ", ".join(
                    f"{diff.kind}:{diff.source_id}" for diff in report.diffs
                )
                detail = (
                    f"submit completed but reconciliation reports blocking "
                    f"differences: {blocking}"
                )
                return self._freeze_exposure(
                    submit_id, broker_order_id=broker_order_id, detail=detail
                )
        return SubmitWorkflowResult(
            submit_id=submit_id,
            state="COMPLETED",
            reused=outcome.reused,
            broker_order_id=broker_order_id,
            detail="external submit completed",
        )

    def _freeze_exposure(
        self,
        submit_id: str,
        *,
        broker_order_id: str | None,
        detail: str,
    ) -> SubmitWorkflowResult:
        """Freeze new exposure only; the completed submit stays immutable."""
        if self._freeze_store is not None:
            self._freeze_store.freeze_new_exposure(
                self._account_id,
                reason="blocking_diff",
                detail=detail,
                evidence_refs=(f"ledger:{submit_id}",),
            )
        return SubmitWorkflowResult(
            submit_id=submit_id,
            state="FROZEN",
            reused=True,
            broker_order_id=broker_order_id,
            detail=detail,
        )


def resolve_in_flight(
    ledger: OrderLedger,
    resolver: UnknownOutcomeResolver | None,
    submit_id: str,
    *,
    owner: str,
    account_id: str,
    freeze_store: ExposureFreezeStore | None,
    reason: str,
) -> str | None:
    """Resolve one in-flight submit by query; freeze when it cannot settle.

    Returns the ``broker_order_id`` when the broker accepted the order
    (the ledger is completed), or ``None`` after freezing both the
    ledger reservation and new exposure with an immutable reason. The
    resolution is always a query for the persisted client identity —
    never a re-submit and never a guess.
    """
    if resolver is None:
        _freeze_submit(
            ledger,
            submit_id,
            owner=owner,
            account_id=account_id,
            freeze_store=freeze_store,
            reason=reason,
            detail="no resolver configured; submit outcome unknown",
        )
        return None
    try:
        resolution = resolver.resolve(submit_id)
    except Exception as exc:  # noqa: BLE001 — fail closed on any query failure
        _freeze_submit(
            ledger,
            submit_id,
            owner=owner,
            account_id=account_id,
            freeze_store=freeze_store,
            reason=reason,
            detail=f"resolution query failed: {exc}",
        )
        return None
    if resolution.resolution == "RESOLVED_ACCEPTED":
        ledger.record_broker_result(
            submit_id,
            broker_order_id=resolution.broker_order_id or "",
            state=resolution.state or "PENDING",
            transaction_id=None,
            owner=owner,
        )
        return resolution.broker_order_id
    _freeze_submit(
        ledger,
        submit_id,
        owner=owner,
        account_id=account_id,
        freeze_store=freeze_store,
        reason=reason,
        detail=resolution.detail,
    )
    return None


def _freeze_submit(
    ledger: OrderLedger,
    submit_id: str,
    *,
    owner: str,
    account_id: str,
    freeze_store: ExposureFreezeStore | None,
    reason: str,
    detail: str,
) -> None:
    """Freeze the ledger reservation and new exposure durably."""
    ledger.freeze(submit_id, reason=reason, owner=owner)
    if freeze_store is not None:
        freeze_store.freeze_new_exposure(
            account_id,
            reason="unresolved_gap",
            detail=detail,
            evidence_refs=(f"ledger:{submit_id}",),
        )


class StartupSyncResult(BaseModel):
    """One deterministic startup-sync verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1)
    in_flight_found: int
    completed: tuple[str, ...] = ()
    frozen: tuple[str, ...] = ()
    mappings_restored: int
    cursor: str | None = None
    frozen_exposure: bool = False


class StartupSyncService:
    """Restart recovery for the durable broker authority.

    Resolves every in-flight (``SUBMITTED``) reservation by querying the
    broker for the persisted client identity, restores the completed
    ``submit_id -> broker_order_id`` mapping into the process adapter so
    a replay can never double-submit, and reports the durable
    transaction cursor. Unresolved outcomes freeze the reservation and
    new exposure; nothing is ever re-submitted or guessed.
    """

    def __init__(
        self,
        *,
        ledger: OrderLedger,
        account_id: str,
        resolve: UnknownOutcomeResolver | None = None,
        freeze_store: ExposureFreezeStore | None = None,
        cursor_store: TransactionCursorStore | None = None,
    ) -> None:
        self._ledger = ledger
        self._account_id = account_id
        self._resolve = resolve
        self._freeze_store = freeze_store
        self._cursor_store = cursor_store

    def sync(
        self,
        *,
        restore_mapping: Callable[[dict[str, str]], None] | None = None,
    ) -> StartupSyncResult:
        """Run one restart recovery pass over the durable authority."""
        in_flight = self._ledger.in_flight_reservations()
        completed: list[str] = []
        frozen: list[str] = []
        for reservation in in_flight:
            submit_id = str(reservation["submit_id"])
            # The ledger compare-and-set requires the owner recorded on
            # the reservation: the sync is the recovery of that same
            # logical runner, never a takeover by a different owner.
            owner = str(reservation["owner"])
            resolved = resolve_in_flight(
                self._ledger,
                self._resolve,
                submit_id,
                owner=owner,
                account_id=self._account_id,
                freeze_store=self._freeze_store,
                reason="startup sync recovered an in-flight submit",
            )
            if resolved is not None:
                completed.append(submit_id)
            else:
                frozen.append(submit_id)
        mappings = self._ledger.completed_mappings()
        if restore_mapping is not None and mappings:
            restore_mapping(mappings)
        cursor: str | None = None
        if self._cursor_store is not None:
            cursor = self._cursor_store.cursor(self._account_id)
        return StartupSyncResult(
            account_id=self._account_id,
            in_flight_found=len(in_flight),
            completed=tuple(completed),
            frozen=tuple(frozen),
            mappings_restored=len(mappings),
            cursor=cursor,
            frozen_exposure=bool(frozen),
        )


__all__ = [
    "FAULT_POINTS",
    "FaultPoint",
    "InjectedCrash",
    "StartupSyncResult",
    "StartupSyncService",
    "SubmitRecoveryError",
    "SubmitWorkflow",
    "SubmitWorkflowResult",
    "resolve_in_flight",
]
