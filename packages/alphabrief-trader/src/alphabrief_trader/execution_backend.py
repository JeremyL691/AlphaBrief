"""Execution backends for AI-approved paper orders.

The AI trading cycle decides *whether* an order candidate may proceed.
This module owns the final paper execution hop: an explicit paper-only
bridge to the broker-neutral ``BrokerAdapter`` port (OANDA practice).
"""


from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any, Literal, Protocol

from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_core import paths as _paths
from alphabrief_core.policy_version import PolicyVersionError, policy_version_hash
from alphabrief_execution.broker.errors import BrokerAdapterError
from alphabrief_execution.broker.oanda.faults import UnknownOutcomeFailure
from alphabrief_execution.broker.oanda.unknown_outcome import UnknownOutcomeResolver
from alphabrief_execution.broker.port import (
    BrokerAdapter,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerTimeInForce,
    SubmitRequest,
)
from alphabrief_execution.broker.risk_context import (
    BrokerRiskContextBuilder,
    RiskContextError,
    RiskContextSources,
    adapter_risk_sources,
)
from alphabrief_risk.broker_context import BrokerRiskContext
from alphabrief_risk.decision_binding import (
    DecisionBindingService,
    hash_inputs,
)
from alphabrief_risk.decision_store import RiskDecisionStore


class ExecutionBackendError(ValueError):
    """Raised when a paper execution backend refuses or fails an order."""


def snapshot_content_hash(context: BrokerRiskContext) -> str:
    """Hash the real broker snapshot a decision was approved against.

    The persisted decision must record *what* was true when it was
    approved (PROJECT_GUIDE 5.7): the account money, positions, orders,
    trades, quotes, conversions and capture time, serialized
    deterministically. A timestamp is not a content hash, so this value
    changes whenever any of those facts change.
    """
    payload = json.dumps(
        context.model_dump(mode="json"), sort_keys=True, default=str
    )
    return sha256(payload.encode()).hexdigest()


ExecutionBackendName = Literal["external_paper"]


@dataclass(frozen=True)
class ExecutionBackendResult:
    """Normalized result from an external paper backend."""

    execution_backend: ExecutionBackendName
    order_id: str
    filled: bool
    fill_price: Decimal | None
    fill_quantity: Decimal | None
    fill_json: dict[str, object] | None
    client_order_id: str | None = None
    broker_order_id: str | None = None
    broker_status: str | None = None
    broker_result_json: dict[str, object] | None = None
    risk_context_version: str | None = None


class ExecutionBackend(Protocol):
    """Small synchronous contract used by ``DailyTradingCycle``."""

    def estimate_quantity(
        self,
        intent: OrderIntent,
        *,
        reference_price: Decimal,
    ) -> Decimal | None:
        """Return a pre-risk quantity estimate, or ``None`` when unavailable."""

    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        reference_price: Decimal,
        now: datetime,
        estimated_quantity: Decimal | None,
    ) -> ExecutionBackendResult:
        """Submit an approved, non-human-review order candidate."""


class ExternalPaperExecutionBackend:
    """Execution backend that submits to a configured external paper adapter.

    M08-W01: every external submit first builds a broker-fresh risk
    context through the shared context service. For the OANDA practice
    adapter the default composition uses the live broker sources
    (account money, positions, pending orders, trades, bid/ask and
    home-currency conversions), so the gate sees the real account. A
    missing, stale, account-mismatched, partially covered, frozen, or
    internally inconsistent context rejects the order before any submit
    — no synthesized defaults, no fallback account, no review bypass.
    """

    def __init__(
        self,
        adapter: BrokerAdapter,
        *,
        max_order_value: Decimal | None = None,
        risk_context_builder: BrokerRiskContextBuilder | None = None,
        decision_binding: DecisionBindingService | None = None,
        risk_symbols: Sequence[str] = (),
        unknown_outcome_resolver: UnknownOutcomeResolver | None = None,
        policy_hash: str | None = None,
    ) -> None:
        self._adapter = adapter
        self._max_order_value = max_order_value
        # The persisted decision records the hash of the reviewed
        # configuration files it was approved under (PROJECT_GUIDE 5.7).
        # Computed once per backend; when the files cannot be read the
        # submit path fails closed rather than persisting a placeholder.
        self._policy_hash = policy_hash or self._compute_policy_hash()
        # Ambiguous submits are resolved by querying the broker for the
        # client identity that was persisted before the request; they are
        # never re-sent (PROJECT_GUIDE 5.8).
        self._unknown_outcome_resolver = unknown_outcome_resolver
        self._risk_context_builder: BrokerRiskContextBuilder = (
            risk_context_builder
            or BrokerRiskContextBuilder(
                _default_risk_sources(adapter, symbols=tuple(risk_symbols))
            )
        )
        # The persisted decision is the only executable contract: by
        # default the backend validates against the durable store in the
        # runtime data directory authority (M01-W04).
        self._decision_binding: DecisionBindingService = (
            decision_binding
            or DecisionBindingService(
                RiskDecisionStore(db_path=_paths.db_path())
            )
        )

    @staticmethod
    def _compute_policy_hash() -> str | None:
        """The hash of the reviewed config files, or ``None`` when unreadable."""
        try:
            return policy_version_hash()
        except PolicyVersionError:
            return None

    def _resolve_unknown_outcome(
        self,
        *,
        intent: OrderIntent,
        decision: RiskDecision,
        quantity: Decimal,
        reference_price: Decimal,
        failure: Exception,
    ) -> ExecutionBackendResult:
        """Resolve an ambiguous submit by querying, never by re-sending.

        ``RESOLVED_ACCEPTED`` means the broker did receive the order, so it
        is reported as submitted (unfilled as far as this response knows);
        ``RESOLVED_NOT_SUBMITTED`` means it never arrived and the caller may
        decide what to do; ``UNRESOLVED`` is surfaced explicitly so the
        runtime records ``SUBMIT_UNKNOWN`` and stops until it is settled.
        """
        del decision, reference_price  # evidence is already persisted
        resolver = self._unknown_outcome_resolver
        if resolver is None:
            resolver = _resolver_for(self._adapter)
        if resolver is None:
            raise ExecutionBackendError(
                f"SUBMIT_UNKNOWN: {failure} (no resolver available for this adapter)"
            )
        resolution = resolver.resolve(intent.intent_id)
        if resolution.resolution == "RESOLVED_ACCEPTED":
            return ExecutionBackendResult(
                execution_backend="external_paper",
                order_id=resolution.broker_order_id or intent.intent_id,
                client_order_id=intent.intent_id,
                broker_order_id=resolution.broker_order_id,
                broker_status=str(resolution.state or "UNKNOWN"),
                broker_result_json=resolution.model_dump(mode="json"),
                filled=False,
                fill_price=None,
                fill_quantity=None,
                fill_json=None,
            )
        if resolution.resolution == "RESOLVED_NOT_SUBMITTED":
            raise ExecutionBackendError(
                f"SUBMIT_NOT_ACCEPTED: {resolution.detail}"
            )
        raise ExecutionBackendError(
            f"SUBMIT_UNKNOWN: {resolution.detail or failure}"
        )

    def estimate_quantity(
        self,
        intent: OrderIntent,
        *,
        reference_price: Decimal,
    ) -> Decimal | None:
        if reference_price <= 0:
            raise ExecutionBackendError("reference_price must be positive")
        if intent.quantity is not None:
            return _clamp_quantity(
                intent.quantity,
                reference_price=reference_price,
                max_order_value=self._max_order_value,
            )
        if intent.target_position_pct is None:
            return None
        if intent.side == "buy":
            account = _run_blocking(self._adapter.get_account())
            estimated = (account.buying_power * intent.target_position_pct) / (
                reference_price
            )
            return _clamp_quantity(
                estimated,
                reference_price=reference_price,
                max_order_value=self._max_order_value,
            )
        if intent.target_position_pct == 0:
            positions = _run_blocking(self._adapter.get_positions())
            for position in positions:
                if position.symbol == intent.symbol:
                    return abs(position.quantity)
            return Decimal("0")
        raise ExecutionBackendError(
            "external paper sell requires an explicit quantity or flat target"
        )

    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        reference_price: Decimal,
        now: datetime,
        estimated_quantity: Decimal | None,
    ) -> ExecutionBackendResult:
        # M08-W01: a broker-fresh risk context is required before any
        # external submit. A missing, stale, account-mismatched, partial,
        # frozen, or inconsistent context rejects the order here — the
        # backend never submits without it (REQ-RISK-010).
        try:
            context = self._risk_context_builder.build()
        except RiskContextError as exc:
            raise ExecutionBackendError(
                f"broker-fresh risk context unavailable: {exc}"
            ) from exc
        if not context.internally_consistent:
            raise ExecutionBackendError(
                "broker-fresh risk context is internally inconsistent"
            )
        quantity = _resolve_external_quantity(
            decision=decision,
            estimated_quantity=estimated_quantity,
        )
        request = SubmitRequest(
            symbol=intent.symbol,
            side=(
                BrokerOrderSide.BUY
                if intent.side == "buy"
                else BrokerOrderSide.SELL
            ),
            order_type=(
                BrokerOrderType.MARKET
                if intent.order_type == "market"
                else BrokerOrderType.LIMIT
            ),
            quantity=quantity,
            limit_price=intent.limit_price,
            time_in_force=BrokerTimeInForce.DAY,
            # Protective orders ride along with the entry (5.6/5.8).
            stop_loss=intent.stop_loss,
            take_profit=intent.take_profit,
            cycle_id=intent.intent_id,
            reduce_only=intent.reduce_only,
        )

        # M08-W07: the approved decision is bound to the immutable
        # decision ledger BEFORE any network submit. When the decision
        # carries an approval-time inputs hash (M08-W02), the executable
        # request must still match it — a post-approval change of symbol,
        # units, or price rejects before persistence. The decision is
        # then persisted through the shared decision-binding service and
        # validated as the only executable contract: missing, rejected,
        # expired, consumed, account-mismatched, policy-mismatched,
        # intent-mismatched, inputs-mismatched, snapshot-mismatched, or
        # quantity-exceeding decisions reject before the network call
        # (AC-M08-W07-02). The backend never trusts a caller-supplied
        # approval flag (AC-M08-W07-03).
        request_inputs_hash = hash_inputs(
            symbol=request.symbol,
            units=request.quantity,
            price=request.limit_price,
        )
        if (
            decision.execution_input_hash is not None
            and decision.execution_input_hash != request_inputs_hash
        ):
            raise ExecutionBackendError(
                "execution inputs no longer match the approved "
                "RiskDecision"
            )
        if self._policy_hash is None:
            raise ExecutionBackendError(
                "the reviewed configuration files cannot be read, so the "
                "decision cannot be bound to a real policy version"
            )
        record = self._decision_binding.persist_decision(
            decision.decision_id,
            intent_id=intent.intent_id,
            account_id=context.account.account_id,
            approved=decision.approved,
            reason=decision.reason,
            max_quantity=decision.max_quantity,
            risk_tags=tuple(decision.risk_tags),
            policy_hash=self._policy_hash,
            inputs_hash=decision.execution_input_hash or request_inputs_hash,
            # A real content hash of the broker snapshot the decision was
            # approved against, never a timestamp.
            snapshot_hash=snapshot_content_hash(context),
            rule_results=(json.dumps({
                "tags": decision.risk_tags, "evidence": decision.rule_evidence,
            }, sort_keys=True) if decision.rule_evidence
                else ",".join(decision.risk_tags)),
            source_ids=(f"account:{context.account.account_id}",),
            # The context builder already rejected stale, missing, or
            # unhealthy evidence, so a successfully built context is
            # fresh at approval by construction.
            context_freshness=True,
        )
        validation = self._decision_binding.validate_before_submit(
            decision.decision_id,
            expected_intent_id=intent.intent_id,
            expected_account_id=record.account_id,
            expected_policy_hash=self._policy_hash,
            expected_inputs_hash=record.inputs_hash,
            expected_snapshot_hash=None,
            quantity=request.quantity,
        )
        if not validation.valid:
            raise ExecutionBackendError(
                f"RiskDecision not executable: {validation.kind}: "
                f"{validation.detail}"
            )

        try:
            result = _run_blocking(
                self._adapter.submit(request, client_order_id=intent.intent_id)
            )
        except UnknownOutcomeFailure as exc:
            return self._resolve_unknown_outcome(
                intent=intent,
                decision=decision,
                quantity=quantity,
                reference_price=reference_price,
                failure=exc,
            )
        except (BrokerAdapterError, NotImplementedError) as exc:
            raise ExecutionBackendError(str(exc)) from exc
        filled = result.status == BrokerOrderStatus.FILLED
        return ExecutionBackendResult(
            execution_backend="external_paper",
            order_id=result.broker_order_id,
            client_order_id=result.client_order_id,
            broker_order_id=result.broker_order_id,
            broker_status=str(result.status),
            broker_result_json=result.model_dump(mode="json"),
            filled=filled,
            fill_price=None,
            fill_quantity=quantity if filled else None,
            fill_json=None,
            risk_context_version=context.context_version,
        )


def _resolver_for(adapter: BrokerAdapter) -> UnknownOutcomeResolver | None:
    """Build the resolver for an OANDA practice adapter, if it is one."""
    from alphabrief_execution.broker.oanda.adapter import OandaPaperAdapter
    from alphabrief_execution.broker.oanda.order_ops import OrderOpsClient

    if isinstance(adapter, OandaPaperAdapter):
        return UnknownOutcomeResolver(OrderOpsClient(adapter.client))
    return None


def _default_risk_sources(
    adapter: BrokerAdapter, *, symbols: tuple[str, ...]
) -> RiskContextSources:
    """Compose the venue sources the risk context is built from.

    For the OANDA practice adapter the sources are the live broker
    endpoints (real money fields, positions, prices and conversions);
    any other adapter keeps the port-only composition.
    """
    from alphabrief_execution.broker.oanda.adapter import OandaPaperAdapter
    from alphabrief_execution.broker.oanda.risk_sources import (
        OandaRiskContextSources,
    )
    from alphabrief_execution.broker.recon_store import BrokerReconStore

    if isinstance(adapter, OandaPaperAdapter):
        return OandaRiskContextSources(
            adapter.client,
            symbols=symbols,
            recon_store=BrokerReconStore(db_path=_paths.db_path()),
        )
    return adapter_risk_sources(adapter)


def _resolve_external_quantity(
    *,
    decision: RiskDecision,
    estimated_quantity: Decimal | None,
) -> Decimal:
    if estimated_quantity is None or estimated_quantity <= 0:
        raise ExecutionBackendError("external paper requires a positive quantity")
    if decision.max_quantity is not None:
        if decision.max_quantity <= 0:
            raise ExecutionBackendError("risk decision max_quantity is zero")
        return min(estimated_quantity, decision.max_quantity)
    return estimated_quantity


def _clamp_quantity(
    quantity: Decimal,
    *,
    reference_price: Decimal,
    max_order_value: Decimal | None,
) -> Decimal:
    """Clamp an estimated quantity to the USD notional cap (tighten-only).

    The RiskGate rejects orders whose notional exceeds the policy
    ``max_order_notional``; clamping the *estimate* to the cap before
    risk evaluation keeps auto-execution functional instead of blocked.
    """
    if max_order_value is None or max_order_value <= 0:
        return quantity
    if reference_price <= 0:
        return quantity
    cap_quantity = max_order_value / reference_price
    return min(quantity, cap_quantity)


def _run_blocking[T](awaitable: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result: list[T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(awaitable))
        except BaseException as exc:  # pragma: no cover - re-raised below
            errors.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


__all__ = [
    "ExecutionBackend",
    "ExecutionBackendError",
    "ExecutionBackendResult",
    "ExternalPaperExecutionBackend",
]
