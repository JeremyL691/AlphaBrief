"""M13-W03: end-to-end cycle traceability.

Covers AC-M13-W03-02: a cycle trace endpoint resolves evidence,
committee transcript, proposal or no-trade, intent, each risk rule,
OANDA transaction, and reconciliation through stable IDs.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db.paper import PaperStore
from alphabrief_api.main import create_app
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.schemas import (
    CommitteeVote,
    CycleOutcome,
    DailyCycleRecord,
    OrderAttempt,
    TradePlan,
)
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "alphabrief.db"


def _vote() -> CommitteeVote:
    return CommitteeVote.model_validate(
        {
            "role": "manager",
            "model_name": "fake-model",
            "analysis": "trend continues",
            "view": "bullish",
            "confidence": 0.7,
            "evidence": ["evidence-1"],
            "risks": [],
            "suggested_action": "buy",
            "target_position_pct": Decimal("0.10"),
            "veto": False,
            "needs_human_review": False,
            "created_at": datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
        }
    )


def _plan() -> TradePlan:
    return TradePlan.model_validate(
        {
            "symbol": "EUR_USD",
            "side": "buy",
            "target_position_pct": Decimal("0.10"),
            "confidence": 0.7,
            "consensus_level": "majority",
            "rationale": "trend",
            "needs_human_review": False,
            "blocked_by_ethics": False,
            "key_evidence": ["evidence-1", "news-42"],
            "key_risks": [],
            "assigned_roles": ["manager"],
        }
    )


def _attempt() -> OrderAttempt:
    return OrderAttempt.model_validate(
        {
            "intent_id": "intent-1",
            "risk_decision_id": "decision-1",
            "approved": True,
            "reason": "risk gate approved",
            "requires_human_review": False,
            "filled": True,
            "order_id": "order-1",
            "outcome": "executed",
            "order_intent_json": {"intent_id": "intent-1"},
            "risk_decision_json": {"decision_id": "decision-1"},
            "fill_json": None,
            "created_at": datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
        }
    )


def _cycle(
    *, cycle_id: str = "cycle-1", outcome: CycleOutcome = "executed"
) -> DailyCycleRecord:
    return DailyCycleRecord(
        cycle_id=cycle_id,
        trading_day="2026-08-14",
        symbols=["EUR_USD"],
        plans=[_plan()],
        votes=[_vote()],
        attempts=[_attempt()],
        outcome=outcome,
        enabled=True,
        live_trading_enabled=False,
        summary="one approved plan",
        cycle_key="2026-08-14:EUR_USD",
        snapshot_fingerprint="snap-abc123",
        created_at=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
    )


def _seed_chain(tmp_path: Path) -> None:
    ai = AiTradingStore(db_path=_db_path(tmp_path))
    try:
        ai.save_cycle(_cycle())
    finally:
        ai.close()
    paper = PaperStore(db_path=_db_path(tmp_path))
    try:
        paper.save_audit_event(
            "order_submitted",
            symbol="EUR_USD",
            details={
                "intent_id": "intent-1",
                "risk_decision_id": "decision-1",
                "order_id": "order-1",
                "message": "submitted",
            },
        )
    finally:
        paper.close()
    recon = BrokerReconStore(db_path=_db_path(tmp_path))
    try:
        recon.upsert_order_id_map(
            client_order_id="order-1",
            broker_order_id="oanda-1",
            status="FILLED",
        )
        recon.record_snapshot(
            scope="cycle-1",
            orders_match=True,
            fills_match=True,
            cash_match=True,
            positions_match=True,
            diff={},
            snapshot_id="recon-1",
        )
    finally:
        recon.close()


class TestCycleTrace:
    def test_trace_resolves_the_full_chain(
        self, tmp_path: Path, client: TestClient
    ) -> None:
        _seed_chain(tmp_path)
        response = client.get("/api/v1/trace/cycles/cycle-1")
        assert response.status_code == 200
        body = response.json()
        assert body["cycle_id"] == "cycle-1"
        assert body["outcome"] == "executed"
        # Evidence through stable IDs.
        assert body["evidence"]["snapshot_fingerprint"] == "snap-abc123"
        assert body["evidence"]["key_evidence"] == ["evidence-1", "news-42"]
        # Committee transcript.
        assert body["transcript"][0]["role"] == "manager"
        assert body["transcript"][0]["view"] == "bullish"
        # Proposal.
        assert body["proposal_or_no_trade"][0]["symbol"] == "EUR_USD"
        assert body["proposal_or_no_trade"][0]["side"] == "buy"
        # Intent with audit resolution.
        assert body["intents"][0]["intent_id"] == "intent-1"
        assert body["intents"][0]["resolution"] == "order_id=order-1"
        # Risk rule chain.
        assert body["risk_rules"][0]["risk_decision_id"] == "decision-1"
        assert body["risk_rules"][0]["intent_id"] == "intent-1"
        # OANDA transaction.
        assert body["oanda_transactions"] == [
            {
                "client_order_id": "order-1",
                "broker_order_id": "oanda-1",
                "status": "FILLED",
            }
        ]
        # Reconciliation.
        assert body["reconciliation"][0]["snapshot_id"] == "recon-1"
        assert body["reconciliation"][0]["orders_match"] is True

    def test_no_trade_cycle_reports_no_trade(
        self, tmp_path: Path, client: TestClient
    ) -> None:
        ai = AiTradingStore(db_path=_db_path(tmp_path))
        try:
            record = _cycle(cycle_id="cycle-nt", outcome="skipped_no_intent")
            ai.save_cycle(
                record.model_copy(update={"plans": [], "attempts": []})
            )
        finally:
            ai.close()
        body = client.get("/api/v1/trace/cycles/cycle-nt").json()
        assert body["outcome"] == "skipped_no_intent"
        assert body["proposal_or_no_trade"] == "no_trade"
        assert body["intents"] == []

    def test_missing_cycle_returns_404(self, client: TestClient) -> None:
        response = client.get("/api/v1/trace/cycles/does-not-exist")
        assert response.status_code == 404

    def test_chain_ids_are_stable_across_calls(
        self, tmp_path: Path, client: TestClient
    ) -> None:
        _seed_chain(tmp_path)
        first = client.get("/api/v1/trace/cycles/cycle-1").json()
        second = client.get("/api/v1/trace/cycles/cycle-1").json()
        assert first == second
