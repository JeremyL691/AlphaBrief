"""Daily AI Trading cycle.

The daily cycle is the single operator-visible entry point of the
trading committee. One cycle = one calendar day, one universe, one
``DailyCycleRecord``. The cycle:

1. Loads a market snapshot for each symbol in the universe
   (``MarketDataProvider``-driven or supplied by the caller — the
   cycle never calls provider SDKs directly).
2. Builds a :class:`MarketSnapshot` per symbol and asks
   :class:`TradingCommittee` for a ``TradePlan``.
3. Applies the deterministic ``RiskGate`` to the synthesized
   ``OrderIntent`` candidate.
4. Submits approved, non-human-review intents to the configured
   :class:`PaperBroker`.
5. Persists the full ``DailyCycleRecord`` via :class:`AiTradingStore`.

The cycle is **paper-only** by default. ``ALPHABRIEF_AI_TRADING_ENABLED``
must be truthy to actually place orders; otherwise the cycle still
runs the committee, still records the plan, but never calls the
broker. ``ALPHABRIEF_LIVE_TRADING_ENABLED`` is independently locked —
a truthy value blocks every attempt with
``blocked_live_trading``.

Provider-shaped dependencies are injected so tests can pass
deterministic fakes:

* ``gateway: ModelGateway`` — the only model call boundary.
* ``risk_gate: RiskGate`` — the deterministic risk layer.
* ``broker: PaperBroker`` — paper execution.
* ``snapshot_loader: Callable[[str], MarketSnapshot | None]`` — turns a
  symbol into a snapshot. ``None`` skips the symbol.
* ``store: AiTradingStore`` — DuckDB persistence.
* ``enabled: bool`` — feature flag.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alphabrief_core import OrderIntent, OrderSide, RiskDecision
from alphabrief_execution import (
    PaperBroker,
)
from alphabrief_risk import RiskGate

from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.execution_backend import (
    ExecutionBackend,
    ExecutionBackendError,
    ExecutionBackendResult,
    LocalPaperExecutionBackend,
)
from alphabrief_trader.schemas import (
    CommitteeInput,
    CommitteeVote,
    CycleOutcome,
    DailyCycleRecord,
    MarketSnapshot,
    OrderAttempt,
    TradePlan,
)

SnapshotLoader = Callable[[str], MarketSnapshot | None]


def is_ai_trading_enabled() -> bool:
    """Return ``True`` when the AI trading feature flag is set."""
    raw = os.environ.get("ALPHABRIEF_AI_TRADING_ENABLED", "").lower().strip()
    return raw in {"1", "true", "yes", "on"}


def is_live_trading_unlocked() -> bool:
    """Return ``True`` when the system-wide live-trading lock is open."""
    raw = os.environ.get("ALPHABRIEF_LIVE_TRADING_ENABLED", "").lower().strip()
    return raw in {"1", "true", "yes", "on"}


class DailyTradingCycle:
    """One daily cycle: snapshot → committee → risk → paper → record.

    The cycle owns no mutable state. It is safe to construct once per
    request, then ``run()`` it.
    """

    def __init__(
        self,
        *,
        committee: TradingCommittee,
        risk_gate: RiskGate,
        broker: PaperBroker,
        store: AiTradingStore,
        snapshot_loader: SnapshotLoader,
        execution_backend: ExecutionBackend | None = None,
        enabled: bool | None = None,
        clock: Callable[[], datetime] | None = None,
        cycle_id_factory: Callable[[], str] | None = None,
        max_order_value: Decimal | None = None,
    ) -> None:
        if committee is None:
            raise TypeError("committee is required")
        if risk_gate is None:
            raise TypeError("risk_gate is required")
        if broker is None:
            raise TypeError("broker is required")
        if store is None:
            raise TypeError("store is required")
        if snapshot_loader is None:
            raise TypeError("snapshot_loader is required")
        self._committee = committee
        self._risk_gate = risk_gate
        self._broker = broker
        self._execution_backend = execution_backend or LocalPaperExecutionBackend(
            broker,
            max_order_value=max_order_value,
        )
        self._max_order_value = max_order_value
        self._store = store
        self._snapshot_loader = snapshot_loader
        self._enabled = (
            is_ai_trading_enabled() if enabled is None else bool(enabled)
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cycle_id_factory = cycle_id_factory or self._default_cycle_id

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        symbols: list[str],
        *,
        time_horizon: str = "5 trading days",
        reference_price_resolver: Callable[[str, MarketSnapshot], Decimal]
        | None = None,
    ) -> DailyCycleRecord:
        """Run one full daily cycle for the given symbols."""
        trading_day = self._trading_day()
        cycle_id = self._cycle_id_factory()
        now = self._clock()
        live_unlocked = is_live_trading_unlocked()

        all_votes: list[CommitteeVote] = []
        all_plans: list[TradePlan] = []
        all_attempts: list[OrderAttempt] = []
        committee_role_errors: list[str] = []
        overall_outcome: CycleOutcome = "skipped_no_intent"

        if not self._enabled:
            record = DailyCycleRecord(
                cycle_id=cycle_id,
                trading_day=trading_day,
                symbols=list(symbols),
                plans=[],
                votes=[],
                attempts=[],
                outcome="blocked_disabled",
                enabled=False,
                live_trading_enabled=live_unlocked,
                summary="AI trading disabled (ALPHABRIEF_AI_TRADING_ENABLED=false)",
                created_at=now,
            )
            self._store.save_cycle(record)
            return record

        if live_unlocked:
            record = DailyCycleRecord(
                cycle_id=cycle_id,
                trading_day=trading_day,
                symbols=list(symbols),
                plans=[],
                votes=[],
                attempts=[],
                outcome="blocked_live_trading",
                enabled=True,
                live_trading_enabled=True,
                summary=(
                    "ALPHABRIEF_LIVE_TRADING_ENABLED is set; "
                    "AI trading is paper-only and refused to run"
                ),
                created_at=now,
            )
            self._store.save_cycle(record)
            return record

        for symbol in symbols:
            snapshot = self._snapshot_loader(symbol)
            if snapshot is None:
                continue

            payload = CommitteeInput(snapshot=snapshot, time_horizon=time_horizon)
            result = self._committee.run(payload)
            all_votes.extend(result.votes)
            if not result.ok or result.plan is None:
                committee_role_errors.extend(result.role_errors)
                continue
            plan = result.plan
            all_plans.append(plan)

            if plan.blocked_by_ethics or plan.target_position_pct <= 0:
                # No order candidate at all — just record the plan.
                continue

            attempt = self._attempt_execution(
                plan=plan,
                snapshot=snapshot,
                now=now,
                reference_price_resolver=reference_price_resolver,
            )
            all_attempts.append(attempt)
            if attempt.outcome == "executed":
                overall_outcome = "executed"

        if overall_outcome != "executed":
            if any(a.outcome.startswith("blocked") for a in all_attempts):
                overall_outcome = next(
                    (
                        a.outcome
                        for a in all_attempts
                        if a.outcome.startswith("blocked")
                    ),
                    "skipped_no_intent",
                )
            elif all_plans:
                overall_outcome = "skipped_no_intent"
            elif committee_role_errors:
                overall_outcome = "provider_error"
            else:
                overall_outcome = "skipped_no_consensus"

        summary = self._build_summary(
            all_plans, all_attempts, overall_outcome, committee_role_errors
        )
        record = DailyCycleRecord(
            cycle_id=cycle_id,
            trading_day=trading_day,
            symbols=list(symbols),
            plans=all_plans,
            votes=all_votes,
            attempts=all_attempts,
            outcome=overall_outcome,
            enabled=True,
            live_trading_enabled=False,
            summary=summary,
            created_at=now,
        )
        self._store.save_cycle(record)
        return record

    # ------------------------------------------------------------------
    # Order attempt — single order, full audit
    # ------------------------------------------------------------------

    def _attempt_execution(
        self,
        *,
        plan: TradePlan,
        snapshot: MarketSnapshot,
        now: datetime,
        reference_price_resolver: Callable[[str, MarketSnapshot], Decimal]
        | None = None,
    ) -> OrderAttempt:
        intent_id = f"ai_{uuid4().hex[:12]}"
        intent = self._materialize_intent(
            plan=plan, snapshot=snapshot, intent_id=intent_id, now=now
        )
        price = (
            reference_price_resolver(plan.symbol, snapshot)
            if reference_price_resolver
            else snapshot.reference_price
        )
        try:
            estimated_quantity = self._execution_backend.estimate_quantity(
                intent,
                reference_price=price,
            )
        except ExecutionBackendError:
            estimated_quantity = None

        decision: RiskDecision = self._risk_gate.evaluate(
            intent,
            estimated_price=price,
            estimated_quantity=estimated_quantity,
            data_quality_passed=True,
        )

        if not decision.approved:
            return self._attempt_record(
                intent=intent,
                decision=decision,
                outcome="blocked_risk_gate",
                execution_result=None,
                now=now,
            )

        if decision.requires_human_review:
            return self._attempt_record(
                intent=intent,
                decision=decision,
                outcome="blocked_human_review",
                execution_result=None,
                now=now,
            )

        try:
            execution_result = self._execution_backend.submit(
                intent,
                decision,
                reference_price=price,
                now=now,
                estimated_quantity=estimated_quantity,
            )
        except ExecutionBackendError as exc:
            return self._attempt_record(
                intent=intent,
                decision=decision,
                outcome="error",
                execution_result=None,
                now=now,
                error_message=str(exc),
            )

        return self._attempt_record(
            intent=intent,
            decision=decision,
            outcome="executed",
            execution_result=execution_result,
            now=now,
        )

    @staticmethod
    def _materialize_intent(
        *,
        plan: TradePlan,
        snapshot: MarketSnapshot,
        intent_id: str,
        now: datetime,
    ) -> OrderIntent:
        side: OrderSide = "buy" if plan.side == "buy" else "sell"
        return OrderIntent(
            intent_id=intent_id,
            source="model",
            symbol=plan.symbol,
            side=side,
            order_type="market",
            target_position_pct=plan.target_position_pct,
            rationale=plan.rationale,
            created_at=now,
        )

    def _attempt_record(
        self,
        *,
        intent: OrderIntent,
        decision: RiskDecision,
        outcome: CycleOutcome,
        execution_result: ExecutionBackendResult | None,
        now: datetime,
        error_message: str | None = None,
    ) -> OrderAttempt:
        return OrderAttempt(
            intent_id=intent.intent_id,
            risk_decision_id=decision.decision_id,
            approved=decision.approved,
            reason=(
                error_message
                if error_message is not None
                else decision.reason or outcome
            ),
            requires_human_review=decision.requires_human_review,
            risk_tags=list(decision.risk_tags),
            max_quantity=decision.max_quantity,
            filled=execution_result.filled if execution_result is not None else False,
            order_id=(
                execution_result.order_id if execution_result is not None else None
            ),
            fill_price=(
                execution_result.fill_price
                if execution_result is not None
                else None
            ),
            fill_quantity=(
                execution_result.fill_quantity if execution_result is not None else None
            ),
            execution_backend=(
                execution_result.execution_backend
                if execution_result is not None
                else None
            ),
            client_order_id=(
                execution_result.client_order_id
                if execution_result is not None
                else None
            ),
            broker_order_id=(
                execution_result.broker_order_id
                if execution_result is not None
                else None
            ),
            broker_status=(
                execution_result.broker_status
                if execution_result is not None
                else None
            ),
            outcome=outcome,
            order_intent_json=intent.model_dump(mode="json"),
            risk_decision_json=decision.model_dump(mode="json"),
            fill_json=(
                execution_result.fill_json if execution_result is not None else None
            ),
            broker_result_json=(
                execution_result.broker_result_json
                if execution_result is not None
                else None
            ),
            created_at=now,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _trading_day(self) -> str:
        return self._clock().date().isoformat()

    def _default_cycle_id(self) -> str:
        return f"aic_{uuid4().hex[:12]}"

    def _build_summary(
        self,
        plans: list[TradePlan],
        attempts: list[OrderAttempt],
        outcome: CycleOutcome,
        role_errors: list[str] | None = None,
    ) -> str:
        executed = sum(1 for a in attempts if a.outcome == "executed")
        blocked = sum(1 for a in attempts if a.outcome.startswith("blocked"))
        suffix = ""
        if outcome == "provider_error" and role_errors:
            suffix = f"; roles=[{', '.join(role_errors)}]"
        return (
            f"outcome={outcome}; plans={len(plans)}; "
            f"executed={executed}; blocked={blocked}; "
            f"total_attempts={len(attempts)}{suffix}"
        )


__all__ = [
    "DailyTradingCycle",
    "SnapshotLoader",
    "is_ai_trading_enabled",
    "is_live_trading_unlocked",
]
