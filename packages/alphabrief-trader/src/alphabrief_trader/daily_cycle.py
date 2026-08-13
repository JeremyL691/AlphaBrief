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

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from alphabrief_core import OrderIntent, OrderSide, RiskDecision
from alphabrief_execution import (
    PaperBroker,
)
from alphabrief_risk import RiskGate

from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.cycle_execution import (
    CorrelationChain,
    IdempotencyMap,
    ReconciliationEvidence,
)
from alphabrief_trader.cycle_schedule import CatchUpPolicy, CatchUpVerdict
from alphabrief_trader.cycle_state import CYCLE_PHASE_ORDER, CycleStateMachine
from alphabrief_trader.db_store import AiTradingStore, CycleStateStore
from alphabrief_trader.execution_backend import (
    ExecutionBackend,
    ExecutionBackendError,
    ExecutionBackendResult,
    LocalPaperExecutionBackend,
)
from alphabrief_trader.execution_gate import (
    ExecutionGate,
    ExecutionMode,
    PreflightFacts,
)
from alphabrief_trader.runtime_truth import RuntimeTruthStore
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


def _snapshot_fingerprint(snapshots: dict[str, MarketSnapshot]) -> str:
    """Deterministic fingerprint of the exact snapshots used by a run.

    The fingerprint covers symbol, data version, capture time, reference
    price, recent return/volume, and the bounded news/macro context, so
    identical (cycle key, snapshot) pairs hash identically while any
    content change produces a different fingerprint.
    """
    payload: list[str] = []
    for symbol in sorted(snapshots):
        snapshot = snapshots[symbol]
        payload.append(
            "|".join(
                [
                    symbol,
                    snapshot.data_version,
                    snapshot.captured_at.isoformat(),
                    format(snapshot.reference_price, "f"),
                    (
                        format(snapshot.recent_return_pct, "f")
                        if snapshot.recent_return_pct is not None
                        else ""
                    ),
                    (
                        format(snapshot.recent_volume, "f")
                        if snapshot.recent_volume is not None
                        else ""
                    ),
                    snapshot.news_context or "",
                    snapshot.macro_context or "",
                ]
            )
        )
    return sha256("\n".join(payload).encode("utf-8")).hexdigest()


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
        cycle_key: str | None = None,
    ) -> DailyCycleRecord:
        """Run one full daily cycle for the given symbols.

        When ``cycle_key`` is provided the cycle is idempotent: a
        previously persisted terminal record with the same cycle key AND
        the same deterministic snapshot fingerprint is returned as-is —
        no committee run, no new proposal or OrderIntent can be created
        for the same (cycle key, snapshot) pair (REQ-AI-009).
        """
        trading_day = self._trading_day()
        cycle_id = self._cycle_id_factory()
        now = self._clock()
        live_unlocked = is_live_trading_unlocked()

        snapshots = self._load_snapshots(symbols)
        fingerprint = _snapshot_fingerprint(snapshots)
        if cycle_key is not None:
            existing = self._store.get_cycle_by_key(cycle_key)
            if existing is not None:
                rehydrated = DailyCycleRecord.model_validate(existing)
                if rehydrated.snapshot_fingerprint == fingerprint:
                    return rehydrated

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
                cycle_key=cycle_key,
                snapshot_fingerprint=fingerprint,
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
                cycle_key=cycle_key,
                snapshot_fingerprint=fingerprint,
                created_at=now,
            )
            self._store.save_cycle(record)
            return record

        for symbol in symbols:
            snapshot = snapshots.get(symbol)
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
            cycle_key=cycle_key,
            snapshot_fingerprint=fingerprint,
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

    def _load_snapshots(self, symbols: list[str]) -> dict[str, MarketSnapshot]:
        """Load one snapshot per symbol (skipping symbols without one)."""
        loaded: dict[str, MarketSnapshot] = {}
        for symbol in symbols:
            snapshot = self._snapshot_loader(symbol)
            if snapshot is not None:
                loaded[symbol] = snapshot
        return loaded

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


class DurableDailyCycle:
    """Persisted compare-and-set daily cycle (M11-W01).

    Runs the daily cycle as a durable state machine: preflight, ingest,
    snapshot, discuss, propose, risk, execute (or no-trade), reconcile,
    report, complete. Every phase's side effect runs exactly once per
    committed gate — the state row advances only after the side effect
    completes, so a restart resumes from the phase after the last
    committed gate and never repeats a completed side effect (in
    particular, broker submissions in the execute phase are never
    repeated). Each phase persists its artifacts (votes, plans,
    attempts, outcome) in the committed transition rows, so the final
    report rebuilds the complete ``DailyCycleRecord`` from durable
    facts after any number of restarts.
    """

    def __init__(
        self,
        *,
        committee: TradingCommittee,
        risk_gate: RiskGate,
        broker: PaperBroker,
        store: AiTradingStore,
        state_store: CycleStateStore,
        snapshot_loader: SnapshotLoader,
        execution_backend: ExecutionBackend | None = None,
        enabled: bool | None = None,
        clock: Callable[[], datetime] | None = None,
        max_order_value: Decimal | None = None,
        preflight_facts_provider: Callable[[], PreflightFacts] | None = None,
        runtime_store: RuntimeTruthStore | None = None,
        catchup_window_hours: int = 24,
        idempotency_map: IdempotencyMap | None = None,
        reconciler: Callable[[list[dict[str, object]]], ReconciliationEvidence]
        | None = None,
    ) -> None:
        if state_store is None:
            raise TypeError("state_store is required")
        self._state_machine = CycleStateMachine(state_store)
        self._execution_gate = ExecutionGate()
        self._runtime_store = runtime_store
        self._preflight_facts_provider = (
            preflight_facts_provider
            or _default_preflight_facts(enabled, risk_gate)
        )
        self._catchup_window_hours = catchup_window_hours
        self._expired = False
        self._scheduled_at: datetime | None = None
        self._idempotency_map = idempotency_map
        self._reconciler = reconciler
        self._trading = DailyTradingCycle(
            committee=committee,
            risk_gate=risk_gate,
            broker=broker,
            store=store,
            snapshot_loader=snapshot_loader,
            execution_backend=execution_backend,
            enabled=enabled,
            clock=clock,
            max_order_value=max_order_value,
        )
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    def run(
        self,
        symbols: list[str],
        *,
        time_horizon: str = "5 trading days",
        cycle_key: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> DailyCycleRecord:
        """Run or resume one durable cycle and return its terminal record."""
        self._scheduled_at = scheduled_at
        cycle_id = self._cycle_id(cycle_key, symbols)
        machine = self._state_machine
        machine.begin(cycle_id)
        resume = machine.resume_phase(cycle_id)
        if resume is None:
            return self._stored_record(cycle_id)

        start = CYCLE_PHASE_ORDER.index(resume)
        for phase in CYCLE_PHASE_ORDER[start:]:
            handler = getattr(self, f"_phase_{phase}")
            handler(cycle_id, symbols, time_horizon=time_horizon)
        return self._stored_record(cycle_id)

    # ------------------------------------------------------------------
    # Phase handlers — each advances the state machine after its side
    # effect and persists its artifacts in the committed transition.
    # ------------------------------------------------------------------

    def _phase_preflight(
        self, cycle_id: str, symbols: list[str], *, time_horizon: str
    ) -> None:
        readiness = self._execution_gate.evaluate(
            self._preflight_facts_provider()
        )
        self._execution_readiness = readiness
        if self._runtime_store is not None:
            self._runtime_store.set_execution_mode(
                readiness.mode.value, list(readiness.reasons)
            )
        catchup = CatchUpVerdict(allowed=True, reason="no_schedule")
        if self._scheduled_at is not None:
            policy = CatchUpPolicy(
                window_hours=self._catchup_window_hours, clock=self._clock
            )
            catchup = policy.evaluate(self._scheduled_at)
        self._expired = not catchup.allowed
        input_hashes = {"symbols": _symbols_hash(symbols)}
        self._state_machine.advance(
            cycle_id,
            expected_phase="preflight",
            next_phase="ingest",
            input_hashes=input_hashes,
            output_ids={
                "execution_mode": readiness.mode.value,
                "execution_reasons": json.dumps(
                    list(readiness.reasons), sort_keys=True
                ),
                "catchup": catchup.reason,
                "catchup_age_seconds": str(catchup.age_seconds),
            },
        )

    def _phase_ingest(
        self, cycle_id: str, symbols: list[str], *, time_horizon: str
    ) -> None:
        output_ids = (
            {"catchup": "expired_without_chase"} if self._expired else None
        )
        self._state_machine.advance(
            cycle_id,
            expected_phase="ingest",
            next_phase="snapshot",
            input_hashes={"symbols": _symbols_hash(symbols)},
            output_ids=output_ids,
        )

    def _phase_snapshot(
        self, cycle_id: str, symbols: list[str], *, time_horizon: str
    ) -> None:
        if self._expired:
            self._state_machine.advance(
                cycle_id,
                expected_phase="snapshot",
                next_phase="discuss",
                output_ids={"catchup": "expired_without_chase"},
            )
            return
        snapshots = self._trading._load_snapshots(symbols)
        fingerprint = _snapshot_fingerprint(snapshots)
        output_ids = {
            "snapshot_fingerprint": fingerprint,
            "symbols": json.dumps(sorted(snapshots), sort_keys=True),
        }
        self._snapshots = snapshots
        self._state_machine.advance(
            cycle_id,
            expected_phase="snapshot",
            next_phase="discuss",
            input_hashes={"snapshot_fingerprint": fingerprint},
            output_ids=output_ids,
        )

    def _phase_discuss(
        self, cycle_id: str, symbols: list[str], *, time_horizon: str
    ) -> None:
        if self._expired:
            self._state_machine.advance(
                cycle_id,
                expected_phase="discuss",
                next_phase="propose",
                output_ids={"catchup": "expired_without_chase"},
            )
            return
        # Snapshot loading is a read-only, idempotent side effect: on a
        # resumed run this phase loads them itself instead of depending
        # on instance state left by an earlier (possibly skipped) phase.
        snapshots = self._trading._load_snapshots(symbols)
        votes: list[dict[str, object]] = []
        plans: list[dict[str, object]] = []
        role_errors: list[str] = []
        for symbol in sorted(snapshots):
            payload = CommitteeInput(
                snapshot=snapshots[symbol],
                time_horizon=time_horizon,
            )
            result = self._trading._committee.run(payload)
            votes.extend(v.model_dump(mode="json") for v in result.votes)
            role_errors.extend(result.role_errors)
            if result.plan is not None:
                plans.append(result.plan.model_dump(mode="json"))
        transcript_id = (
            sha256(json.dumps(votes, sort_keys=True).encode()).hexdigest()[:16]
            if votes
            else None
        )
        output_ids = {
            "votes": json.dumps(votes, sort_keys=True),
            "plans": json.dumps(plans, sort_keys=True),
            "role_errors": json.dumps(role_errors, sort_keys=True),
            "transcript_id": transcript_id or "",
            "transcript_skip_reason": (
                "" if transcript_id is not None else "no_committee_votes"
            ),
        }
        self._state_machine.advance(
            cycle_id,
            expected_phase="discuss",
            next_phase="propose",
            output_ids=output_ids,
        )

    def _phase_propose(
        self, cycle_id: str, symbols: list[str], *, time_horizon: str
    ) -> None:
        if self._expired:
            self._state_machine.advance(
                cycle_id,
                expected_phase="propose",
                next_phase="risk",
                output_ids={"catchup": "expired_without_chase"},
            )
            return
        # The committee synthesized one TradePlan per symbol; the propose
        # phase converts them into evidence-grounded proposals.
        discuss = self._transitions(cycle_id, "discuss")
        proposals: list[str] = []
        for plan_json in json.loads(str(discuss.get("plans", "[]"))):
            proposals.append(
                f"proposal_{sha256(str(plan_json).encode('utf-8')).hexdigest()[:12]}"
            )
        self._state_machine.advance(
            cycle_id,
            expected_phase="propose",
            next_phase="risk",
            output_ids={"proposals": json.dumps(proposals, sort_keys=True)},
        )

    def _phase_risk(
        self, cycle_id: str, symbols: list[str], *, time_horizon: str
    ) -> None:
        if self._expired:
            self._state_machine.advance(
                cycle_id,
                expected_phase="risk",
                next_phase="execute",
                output_ids={"catchup": "expired_without_chase"},
            )
            return
        discuss = self._transitions(cycle_id, "discuss")
        plans = [
            TradePlan.model_validate(item)
            for item in json.loads(str(discuss.get("plans", "[]")))
        ]
        snapshots = self._trading._load_snapshots(symbols)
        decision_ids: list[str] = []
        for plan in plans:
            snapshot = snapshots.get(plan.symbol)
            if snapshot is None:
                continue
            intent = self._trading._materialize_intent(
                plan=plan,
                snapshot=snapshot,
                intent_id=f"ai_{uuid4().hex[:12]}",
                now=self._clock(),
            )
            decision = self._trading._risk_gate.evaluate(
                intent,
                estimated_price=snapshot.reference_price,
                estimated_quantity=None,
                data_quality_passed=True,
            )
            decision_ids.append(decision.decision_id)
        self._state_machine.advance(
            cycle_id,
            expected_phase="risk",
            next_phase="execute",
            output_ids={"decisions": json.dumps(decision_ids, sort_keys=True)},
        )

    def _phase_execute(
        self, cycle_id: str, symbols: list[str], *, time_horizon: str
    ) -> None:
        if self._expired:
            self._state_machine.advance(
                cycle_id,
                expected_phase="execute",
                next_phase="reconcile",
                output_ids={
                    "attempts": "[]",
                    "catchup": "expired_without_chase",
                },
                outcome="no_trade",
            )
            return
        readiness = self._execution_gate.evaluate(
            self._preflight_facts_provider()
        )
        mode = readiness.mode
        if mode != ExecutionMode.EXECUTABLE:
            # Research phases already completed; execution is prevented
            # before any broker invocation and the gate reasons persist.
            self._state_machine.advance(
                cycle_id,
                expected_phase="execute",
                next_phase="reconcile",
                output_ids={
                    "attempts": "[]",
                    "execution_mode": mode.value,
                    "execution_reasons": json.dumps(
                        list(readiness.reasons), sort_keys=True
                    ),
                },
                outcome="blocked",
            )
            return
        discuss = self._transitions(cycle_id, "discuss")
        plans = [
            TradePlan.model_validate(item)
            for item in json.loads(str(discuss.get("plans", "[]")))
        ]
        snapshots = self._trading._load_snapshots(symbols)
        attempts: list[dict[str, object]] = []
        outcome: str = "no_trade"
        chain = CorrelationChain(
            cycle_id=cycle_id,
            trading_date=self._clock().date().isoformat(),
            proposal_ids=json.loads(
                str(self._transitions(cycle_id, "propose").get("proposals", "[]"))
            ),
        )
        for plan in plans:
            snapshot = snapshots.get(plan.symbol)
            if snapshot is None:
                continue
            if plan.blocked_by_ethics or plan.target_position_pct <= 0:
                continue
            intent = self._trading._materialize_intent(
                plan=plan,
                snapshot=snapshot,
                intent_id=f"ai_{sha256(f'{cycle_id}:{plan.symbol}'.encode()).hexdigest()[:12]}",
                now=self._clock(),
            )
            chain.intent_ids.append(intent.intent_id)
            decision = self._trading._risk_gate.evaluate(
                intent,
                estimated_price=snapshot.reference_price,
                estimated_quantity=None,
                data_quality_passed=True,
            )
            chain.decision_ids.append(decision.decision_id)
            if not decision.approved:
                attempts.append(
                    self._trading._attempt_record(
                        intent=intent,
                        decision=decision,
                        outcome="blocked_risk_gate",
                        execution_result=None,
                        now=self._clock(),
                    ).model_dump(mode="json")
                )
                continue
            if decision.requires_human_review:
                attempts.append(
                    self._trading._attempt_record(
                        intent=intent,
                        decision=decision,
                        outcome="blocked_human_review",
                        execution_result=None,
                        now=self._clock(),
                    ).model_dump(mode="json")
                )
                continue

            client_order_id = f"cyc_{cycle_id[:12]}_{intent.intent_id[:12]}"
            chain.client_order_ids.append(client_order_id)
            existing = (
                self._idempotency_map.existing(client_order_id)
                if self._idempotency_map is not None
                else None
            )
            if existing is not None:
                # At-most-once: a previously submitted order is reused.
                chain.broker_order_ids.append(
                    str(existing.get("broker_order_id") or "")
                )
                attempts.append(
                    {
                        "intent_id": intent.intent_id,
                        "risk_decision_id": decision.decision_id,
                        "approved": True,
                        "requires_human_review": False,
                        "outcome": "executed",
                        "filled": True,
                        "client_order_id": client_order_id,
                        "order_id": existing.get("broker_order_id"),
                        "created_at": self._clock().isoformat(),
                        "reused_idempotent": True,
                    }
                )
                outcome = "executed"
                continue

            try:
                execution_result = self._trading._execution_backend.submit(
                    intent,
                    decision,
                    reference_price=snapshot.reference_price,
                    now=self._clock(),
                    estimated_quantity=None,
                )
            except Exception as exc:
                attempts.append(
                    self._trading._attempt_record(
                        intent=intent,
                        decision=decision,
                        outcome="error",
                        execution_result=None,
                        now=self._clock(),
                        error_message=str(exc),
                    ).model_dump(mode="json")
                )
                continue
            if self._idempotency_map is not None:
                self._idempotency_map.register(
                    client_order_id=client_order_id,
                    cycle_id=cycle_id,
                    intent_id=intent.intent_id,
                    broker_order_id=execution_result.order_id,
                )
            chain.broker_order_ids.append(
                str(execution_result.order_id or "")
            )
            attempts.append(
                self._trading._attempt_record(
                    intent=intent,
                    decision=decision,
                    outcome="executed" if execution_result.filled else "error",
                    execution_result=execution_result,
                    now=self._clock(),
                ).model_dump(mode="json")
            )
            if execution_result.filled:
                outcome = "executed"
            else:
                outcome = "error"
        if outcome != "executed" and any(
            str(a.get("outcome", "")) == "error" for a in attempts
        ):
            outcome = "error"
        elif outcome != "executed" and any(
            str(a.get("outcome", "")).startswith("blocked") for a in attempts
        ):
            outcome = "blocked"
        self._state_machine.advance(
            cycle_id,
            expected_phase="execute",
            next_phase="reconcile",
            output_ids={
                "attempts": json.dumps(attempts, sort_keys=True),
                "correlation_chain": chain.to_json(),
            },
            outcome=outcome,
        )

    def _phase_reconcile(
        self, cycle_id: str, symbols: list[str], *, time_horizon: str
    ) -> None:
        if self._expired:
            self._state_machine.advance(
                cycle_id,
                expected_phase="reconcile",
                next_phase="report",
                output_ids={"catchup": "expired_without_chase"},
            )
            return
        execute = self._transitions(cycle_id, "execute")
        attempts_raw = json.loads(str(execute.get("attempts", "[]")))
        output_ids: dict[str, str] = {}
        if self._reconciler is not None:
            evidence = self._reconciler(attempts_raw)
            output_ids["reconciliation_evidence"] = evidence.model_dump_json()
        self._state_machine.advance(
            cycle_id,
            expected_phase="reconcile",
            next_phase="report",
            output_ids=output_ids,
        )

    def _phase_report(
        self, cycle_id: str, symbols: list[str], *, time_horizon: str
    ) -> None:
        record = self._rebuild_record(cycle_id, symbols)
        self._store.save_cycle(record)
        if self._runtime_store is not None:
            current = self._runtime_store.read()
            self._runtime_store.update(
                leader_id=current.get("leader_id") if current else None,
                running_phase="report",
                last_outcome=record.outcome,
            )
        self._state_machine.advance(
            cycle_id,
            expected_phase="report",
            next_phase="complete",
            output_ids={
                "cycle_record_id": cycle_id,
                "terminal_outcome": record.outcome,
            },
        )

    def _phase_complete(
        self, cycle_id: str, symbols: list[str], *, time_horizon: str
    ) -> None:
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cycle_id(self, cycle_key: str | None, symbols: list[str]) -> str:
        if cycle_key is not None:
            return f"cyc_{sha256(cycle_key.encode('utf-8')).hexdigest()[:16]}"
        return f"aic_{uuid4().hex[:12]}"

    def _transitions(self, cycle_id: str, phase: str) -> dict[str, object]:
        # A phase's artifacts live on the transition that leaves it
        # (committed after the phase's side effect completed).
        for transition in self._state_machine.transitions(cycle_id):
            if transition.prior_phase == phase:
                return {
                    **transition.output_ids,
                    "_outcome": transition.outcome,
                }
        return {}

    def _rebuild_record(
        self, cycle_id: str, symbols: list[str]
    ) -> DailyCycleRecord:
        machine = self._state_machine
        state = machine.state(cycle_id)
        if state is None:
            raise ValueError(f"no state for cycle {cycle_id!r}")
        discuss = self._transitions(cycle_id, "discuss")
        execute = self._transitions(cycle_id, "execute")
        votes = [
            CommitteeVote.model_validate(item)
            for item in json.loads(str(discuss.get("votes", "[]")))
        ]
        plans = [
            TradePlan.model_validate(item)
            for item in json.loads(str(discuss.get("plans", "[]")))
        ]
        attempts = [
            OrderAttempt.model_validate(item)
            for item in json.loads(str(execute.get("attempts", "[]")))
        ]
        preflight = self._transitions(cycle_id, "preflight")
        catchup = str(preflight.get("catchup", ""))
        if catchup == "expired_without_chase":
            return DailyCycleRecord(
                cycle_id=cycle_id,
                trading_day=self._clock().date().isoformat(),
                symbols=list(symbols),
                plans=[],
                votes=[],
                attempts=[],
                outcome="expired_without_chase",
                enabled=True,
                live_trading_enabled=False,
                summary=(
                    "cycle expired without chase: the scheduled run fell "
                    "outside its catch-up window"
                ),
                created_at=self._clock(),
            )

        execute_outcome = state.get("outcome")
        outcome: CycleOutcome
        terminal_reason = "no_trade"
        evidence_ids: list[str] = []
        if execute_outcome == "executed":
            outcome = "executed"
            terminal_reason = "executed"
        elif execute_outcome == "error":
            outcome = "error"
            terminal_reason = "broker_rejected"
        elif execute_outcome == "blocked":
            outcome = "blocked_risk_gate"
            terminal_reason = "risk_rejection"
        elif plans:
            outcome = "skipped_no_intent"
            terminal_reason = "no_trade"
        elif votes:
            outcome = "skipped_no_consensus"
            terminal_reason = "insufficient_evidence"
        else:
            outcome = "provider_error"
            terminal_reason = "budget_exhaustion"
        if execute_outcome == "blocked":
            reasons = json.loads(str(preflight.get("execution_reasons", "[]")))
            if "stale_data" in reasons:
                terminal_reason = "stale_data"
            elif "missing_credentials" in reasons:
                terminal_reason = "blocked"
            elif any(
                marker in reasons
                for marker in ("market_closed", "stale_account_truth")
            ):
                terminal_reason = (
                    "market_closed"
                    if "market_closed" in reasons
                    else "blocked"
                )
        summary = (
            f"outcome={outcome}; reason={terminal_reason}; "
            f"plans={len(plans)}; votes={len(votes)}; "
            f"attempts={len(attempts)}; evidence={len(evidence_ids)}"
        )
        return DailyCycleRecord(
            cycle_id=cycle_id,
            trading_day=self._clock().date().isoformat(),
            symbols=list(symbols),
            plans=plans,
            votes=votes,
            attempts=attempts,
            outcome=outcome,
            enabled=True,
            live_trading_enabled=False,
            summary=summary,
            created_at=self._clock(),
        )

    def _stored_record(self, cycle_id: str) -> DailyCycleRecord:
        raw = self._store.get_cycle(cycle_id)
        if raw is None:
            raise ValueError(f"no stored record for cycle {cycle_id!r}")
        return DailyCycleRecord.model_validate(raw)


def _symbols_hash(symbols: list[str]) -> str:
    return sha256(",".join(sorted(symbols)).encode("utf-8")).hexdigest()


def _default_preflight_facts(
    enabled: bool | None, risk_gate: RiskGate
) -> Callable[[], PreflightFacts]:
    """Fail-closed default facts: execution is blocked unless every
    gate condition is explicitly proven by the environment."""

    def _facts() -> PreflightFacts:
        return PreflightFacts(
            trading_enabled=(
                is_ai_trading_enabled() if enabled is None else bool(enabled)
            ),
            credentials_present=bool(
                os.environ.get("ALPHABRIEF_OANDA_TOKEN")
                and os.environ.get("ALPHABRIEF_OANDA_ACCOUNT_ID")
            ),
            account_truth_fresh=False,
            reconciliation_clean=False,
            data_fresh=False,
            backup_ok=False,
            model_healthy=False,
            kill_switch_active=bool(risk_gate.kill_switch.active),
        )

    return _facts


__all__ = [
    "DailyTradingCycle",
    "DurableDailyCycle",
    "SnapshotLoader",
    "is_ai_trading_enabled",
    "is_live_trading_unlocked",
]
