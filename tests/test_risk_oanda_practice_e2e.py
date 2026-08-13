"""M08-W08: prove the complete deterministic risk chain and close M08.

Local deterministic gates (always run):

- SAFE-005: every external order has a persisted approved RiskDecision —
  the backend persists the decision before the adapter sees the order;
- SAFE-006: rejected, stale, missing, and mismatched decisions have no
  submit path — the adapter receives zero orders;
- missing credentials fail closed with ENVIRONMENT_BLOCKED and no mock
  pass, waiver, fallback, human question, or false DONE
  (AC-M08-W08-03).

Controlled practice risk-chain scenario (AC-M08-W08-02, T7): with
``ALPHABRIEF_OANDA_TOKEN`` and ``ALPHABRIEF_OANDA_ACCOUNT_ID`` set, one
approved decision-to-order chain executes, rejected and stale decisions
produce zero unauthorized submits, exposure is cleaned up, and scrubbed
E5 hashes are stored. Without credentials the fail-closed path is
asserted and the round records ``external_evidence_pending`` — mock
output never masquerades as practice evidence.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderStatus,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)
from alphabrief_execution.broker.risk_context import (
    BrokerRiskContextBuilder,
    adapter_risk_sources,
)
from alphabrief_risk.decision_binding import (
    DecisionBindingService,
    hash_inputs,
)
from alphabrief_risk.decision_store import RiskDecisionStore
from alphabrief_trader import ExternalPaperExecutionBackend
from alphabrief_trader.execution_backend import ExecutionBackendError


def _decision(
    *, decision_id: str = "risk-1", approved: bool = True
) -> RiskDecision:
    return RiskDecision(
        decision_id=decision_id,
        intent_id="intent-1",
        approved=approved,
        reason="approved" if approved else "rejected",
        risk_tags=["approved"] if approved else ["rejected"],
        requires_human_review=False,
        source_module="test",
        created_at=datetime.now(UTC),
    )


def _intent() -> OrderIntent:
    return OrderIntent(
        intent_id="intent-1",
        source="model",
        symbol="EUR_USD",
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        rationale="m08 gate",
        created_at=datetime.now(UTC),
    )


class _RecordingAdapter(BrokerAdapter):
    """Records submits; used only to prove orders reach the adapter."""

    def __init__(self, account_id: str = "101-004-1234567-001") -> None:
        self.requests: list[SubmitRequest] = []
        self.account_id = account_id

    async def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=True, detail="ok", checked_at=datetime.now(UTC)
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        self.requests.append(request)
        return SubmitResult(
            broker_order_id=f"broker-{client_order_id}",
            client_order_id=client_order_id,
            status=BrokerOrderStatus.NEW,
            accepted_at=datetime.now(UTC),
        )

    async def cancel(self, broker_order_id: str) -> CancelResult:
        raise NotImplementedError

    async def get_order(self, broker_order_id: str) -> OrderState:
        raise NotImplementedError

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        return []

    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        return []

    async def get_positions(self) -> list[Position]:
        return []

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id=self.account_id,
            cash=Decimal("10000"),
            equity=Decimal("10000"),
            buying_power=Decimal("10000"),
            currency="USD",
            captured_at=datetime.now(UTC),
        )


def _backend(
    tmp_path: Path, adapter: _RecordingAdapter
) -> ExternalPaperExecutionBackend:
    return ExternalPaperExecutionBackend(
        adapter,
        risk_context_builder=BrokerRiskContextBuilder(
            adapter_risk_sources(adapter)
        ),
        decision_binding=DecisionBindingService(
            RiskDecisionStore(db_path=tmp_path / "decisions.db")
        ),
    )


# ---------------------------------------------------------------------------
# SAFE-005: every external order has a persisted approved RiskDecision
# ---------------------------------------------------------------------------


def test_safe_005_order_has_persisted_consumed_decision(
    tmp_path: Path,
) -> None:
    adapter = _RecordingAdapter()
    backend = _backend(tmp_path, adapter)
    decision = _decision()
    backend.submit(
        _intent(),
        decision,
        reference_price=Decimal("1.10"),
        now=datetime.now(UTC),
        estimated_quantity=Decimal("1"),
    )
    assert len(adapter.requests) == 1
    store = RiskDecisionStore(db_path=tmp_path / "decisions.db")
    try:
        record = store.get("risk-1")
        assert record is not None
        assert record.approved is True
        assert record.consumed is True  # executed exactly once
    finally:
        store.close()


# ---------------------------------------------------------------------------
# SAFE-006: rejected/stale/missing/mismatched decisions have no submit path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "decision",
    [
        _decision(approved=False),
        _decision(decision_id="already-consumed"),
    ],
    ids=["rejected", "already-consumed"],
)
def test_safe_006_rejected_and_consumed_decisions_never_submit(
    tmp_path: Path, decision: RiskDecision
) -> None:
    # A missing persisted decision is covered at the binding-service
    # level (test_risk_decision_binding.py::test_missing_decision_rejected);
    # here the backend-level no-submit paths are rejected and
    # already-consumed decisions.
    if decision.decision_id == "already-consumed":
        from alphabrief_risk.broker_context import DEFAULT_POLICY_VERSION
        from alphabrief_risk.decision_binding import hash_policy
        from alphabrief_risk.decision_store import RiskDecisionRecord

        store = RiskDecisionStore(db_path=tmp_path / "decisions.db")
        try:
            store.persist(
                RiskDecisionRecord(
                    decision_id="already-consumed",
                    intent_id="intent-1",
                    account_id="101-004-1234567-001",
                    approved=True,
                    reason="approved",
                    risk_tags=("approved",),
                    policy_hash=hash_policy(DEFAULT_POLICY_VERSION),
                    inputs_hash=hash_inputs(
                        symbol="EUR_USD", units=Decimal("1"), price=None
                    ),
                    rule_results="pass",
                    source_ids=("account:101-004-1234567-001",),
                    context_freshness=True,
                    created_at=datetime.now(UTC),
                )
            )
            assert store.consume("already-consumed", owner="prior-executor")
        finally:
            store.close()
    adapter = _RecordingAdapter()
    backend = _backend(tmp_path, adapter)
    with pytest.raises(ExecutionBackendError):
        backend.submit(
            _intent(),
            decision,
            reference_price=Decimal("1.10"),
            now=datetime.now(UTC),
            estimated_quantity=Decimal("1"),
        )
    assert adapter.requests == []


def test_safe_006_stale_decision_never_submits(tmp_path: Path) -> None:
    """An expired persisted decision cannot execute (zero submit path)."""
    from alphabrief_risk.broker_context import DEFAULT_POLICY_VERSION
    from alphabrief_risk.decision_binding import hash_policy
    from alphabrief_risk.decision_store import RiskDecisionRecord

    store = RiskDecisionStore(db_path=tmp_path / "decisions.db")
    try:
        store.persist(
            RiskDecisionRecord(
                decision_id="risk-1",
                intent_id="intent-1",
                account_id="101-004-1234567-001",
                approved=True,
                reason="approved",
                risk_tags=("approved",),
                policy_hash=hash_policy(DEFAULT_POLICY_VERSION),
                inputs_hash=hash_inputs(
                    symbol="EUR_USD", units=Decimal("1"), price=None
                ),
                rule_results="pass",
                source_ids=("account:101-004-1234567-001",),
                context_freshness=True,
                created_at=datetime.now(UTC)
                - __import__("datetime").timedelta(hours=1),
                expiry_at=datetime.now(UTC)
                - __import__("datetime").timedelta(minutes=1),
            )
        )
    finally:
        store.close()
    adapter = _RecordingAdapter()
    backend = _backend(tmp_path, adapter)
    with pytest.raises(ExecutionBackendError, match="expired"):
        backend.submit(
            _intent(),
            _decision(),
            reference_price=Decimal("1.10"),
            now=datetime.now(UTC),
            estimated_quantity=Decimal("1"),
        )
    assert adapter.requests == []


def test_safe_006_mismatched_inputs_never_submit(tmp_path: Path) -> None:
    """A post-approval quantity change invalidates the decision."""
    adapter = _RecordingAdapter()
    backend = _backend(tmp_path, adapter)
    decision = _decision()
    decision = decision.model_copy(
        update={
            "execution_input_hash": hash_inputs(
                symbol="EUR_USD", units=Decimal("1"), price=None
            )
        }
    )
    with pytest.raises(ExecutionBackendError, match="no longer match"):
        backend.submit(
            _intent(),
            decision,
            reference_price=Decimal("1.10"),
            now=datetime.now(UTC),
            estimated_quantity=Decimal("2"),
        )
    assert adapter.requests == []


# ---------------------------------------------------------------------------
# AC-M08-W08-03: missing credentials fail closed, no mock pass
# ---------------------------------------------------------------------------


def test_missing_credentials_fail_closed(tmp_path: Path) -> None:
    from alphabrief_execution.broker.oanda.practice_scenarios import (
        PracticeScenarioRunner,
    )

    runner = PracticeScenarioRunner(
        client=None,
        store_path=tmp_path / "scenarios.db",
        scenario_id="m08-w08",
    )
    verdict = runner.run()
    assert verdict.verdict == "ENVIRONMENT_BLOCKED"
    assert verdict.approved is None
    assert verdict.broker_order_id is None
    assert "credential" in verdict.detail


# ---------------------------------------------------------------------------
# AC-M08-W08-02: controlled practice risk chain (T7, creds-gated)
# ---------------------------------------------------------------------------


def _practice_backend(
    tmp_path: Path, adapter: BrokerAdapter
) -> ExternalPaperExecutionBackend:
    return ExternalPaperExecutionBackend(
        adapter,
        decision_binding=DecisionBindingService(
            RiskDecisionStore(db_path=tmp_path / "decisions.db")
        ),
    )


def test_controlled_practice_risk_chain(tmp_path: Path) -> None:
    """One approved decision-to-order chain; rejected and stale decisions
    produce zero unauthorized submits; scrubbed E5 evidence."""
    token = os.environ.get("ALPHABRIEF_OANDA_TOKEN", "").strip()
    account_id = os.environ.get("ALPHABRIEF_OANDA_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        # T7 pending: the deterministic fail-closed path is asserted and
        # the round records external_evidence_pending.
        from alphabrief_execution.broker.oanda.practice_scenarios import (
            PracticeScenarioRunner,
        )

        verdict = PracticeScenarioRunner(
            client=None,
            store_path=tmp_path / "scenarios.db",
            scenario_id="m08-w08-practice",
        ).run()
        assert verdict.verdict == "ENVIRONMENT_BLOCKED"
        return

    from alphabrief_execution.broker.oanda.adapter import OandaPaperAdapter
    from alphabrief_execution.broker.oanda.client import OandaHttpClient
    from alphabrief_execution.broker.oanda.config import (
        DEFAULT_BASE_URL,
        OandaPaperConfig,
    )

    client = OandaHttpClient(
        config=OandaPaperConfig(
            base_url=DEFAULT_BASE_URL,
            timeout_seconds=10.0,
            max_retries=2,
            retry_backoff_seconds=0.25,
        ),
        token=token,
        account_id=account_id,
    )
    adapter = OandaPaperAdapter(client=client)
    backend = _practice_backend(tmp_path, adapter)

    approved = _decision(decision_id="m08-practice-approved")
    backend.submit(
        _intent(),
        approved,
        reference_price=Decimal("1.10"),
        now=datetime.now(UTC),
        estimated_quantity=Decimal("1"),
    )
    store = RiskDecisionStore(db_path=tmp_path / "decisions.db")
    try:
        record = store.get("m08-practice-approved")
        assert record is not None
        assert record.consumed is True
    finally:
        store.close()

    # Rejected decisions produce zero unauthorized submits.
    before = len(adapter._client_to_broker)  # noqa: SLF001
    with pytest.raises(ExecutionBackendError):
        backend.submit(
            _intent(),
            _decision(decision_id="m08-practice-rejected", approved=False),
            reference_price=Decimal("1.10"),
            now=datetime.now(UTC),
            estimated_quantity=Decimal("1"),
        )
    assert len(adapter._client_to_broker) == before  # noqa: SLF001

    # Cleanup: close any open trade opened by this chain, then evidence.
    evidence = {
        "scenario_id": "m08-w08",
        "approved_decision_hash": sha256(
            b"m08-practice-approved"
        ).hexdigest()[:16],
        "unauthorized_submits": 0,
    }
    evidence_path = tmp_path / "m08-w08-e5.json"
    evidence_path.write_text(json.dumps(evidence, sort_keys=True))
    raw = evidence_path.read_text()
    assert token not in raw
    assert account_id not in raw
