"""End-to-end cycle traceability resource.

``GET /api/v1/trace/cycles/{cycle_id}`` resolves one daily cycle's full
evidence chain through stable IDs — cycle record, evidence, committee
transcript, proposal or no-trade, intents, each risk rule, OANDA
transactions, and reconciliation — read-only from the shared runtime
stores (REQ-EXEC-010, REQ-UI-006). Missing links resolve to explicit
``not_found`` entries, never fabricated values.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from alphabrief_execution.broker.recon_store import BrokerReconStore
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from alphabrief_api.db.ai_trading import AiTradingStore
from alphabrief_api.db.paper import PaperStore

router = APIRouter(prefix="/api/v1/trace", tags=["trace"])


class TraceEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_fingerprint: str | None
    key_evidence: list[str]


class TraceTranscriptRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    model_name: str
    view: str
    confidence: float


class TraceProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    side: str
    target_position_pct: str
    confidence: float
    needs_human_review: bool
    rationale: str


class TraceIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent_id: str
    status: str
    resolution: str | None


class TraceRiskRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    risk_decision_id: str
    intent_id: str | None
    status: str


class TraceTransaction(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_order_id: str
    broker_order_id: str
    status: str


class TraceReconciliation(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    scope: str
    orders_match: bool
    captured_at: str


class TraceChain(BaseModel):
    """One cycle's full evidence chain through stable IDs."""

    model_config = ConfigDict(frozen=True)

    cycle_id: str
    outcome: str
    trading_day: str | None
    symbols: list[str]
    summary: str | None
    created_at: str | None
    evidence: TraceEvidence
    transcript: list[TraceTranscriptRow]
    proposal_or_no_trade: list[TraceProposal] | str
    intents: list[TraceIntent]
    risk_rules: list[TraceRiskRule]
    oanda_transactions: list[TraceTransaction]
    reconciliation: list[TraceReconciliation]


def _db_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    db_dir = Path(env_dir) if env_dir else Path("~/.alphabrief").expanduser()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "alphabrief.db"


def _open_paper_store() -> PaperStore:
    return PaperStore(db_path=_db_path())


def _open_recon() -> BrokerReconStore:
    return BrokerReconStore(db_path=_db_path())


def _open_ai_store() -> AiTradingStore:
    return AiTradingStore(db_path=_db_path())


@router.get("/cycles/{cycle_id}", response_model=TraceChain)
def trace_cycle(cycle_id: str) -> TraceChain:
    """Resolve the full evidence chain for one cycle."""
    store = _open_ai_store()
    try:
        record = store.get_cycle(cycle_id)
    finally:
        store.close()
    if record is None:
        raise HTTPException(status_code=404, detail=f"cycle {cycle_id!r} not found")

    paper = _open_paper_store()
    try:
        audit = paper.get_audit_events()
    finally:
        paper.close()
    recon = _open_recon()
    try:
        order_rows = recon.list_order_id_map()
        recon_rows = recon._conn.execute(
            """SELECT snapshot_id, captured_at, scope, orders_match
               FROM broker_recon_snapshots ORDER BY captured_at DESC LIMIT 5"""
        ).fetchall()
    finally:
        recon.close()

    plans = record.get("plans", [])
    votes = record.get("votes", [])
    attempts = record.get("attempts", [])

    intent_ids = {
        str(attempt.get("intent_id"))
        for attempt in attempts
        if attempt.get("intent_id")
    }
    risk_decision_ids = {
        decision_id
        for decision_id in (
            _detail_str(entry, "risk_decision_id") for entry in audit
        )
        if decision_id is not None
    }
    order_ids = {
        order_id
        for order_id in (_detail_str(entry, "order_id") for entry in audit)
        if order_id is not None
    }

    return TraceChain(
        cycle_id=cycle_id,
        outcome=str(record.get("outcome", "")),
        trading_day=(
            str(record["trading_day"]) if record.get("trading_day") else None
        ),
        symbols=[str(s) for s in record.get("symbols", [])],
        summary=str(record["summary"]) if record.get("summary") else None,
        created_at=(
            str(record["created_at"]) if record.get("created_at") else None
        ),
        evidence=TraceEvidence(
            snapshot_fingerprint=(
                str(record["snapshot_fingerprint"])
                if record.get("snapshot_fingerprint")
                else None
            ),
            key_evidence=_key_evidence(plans),
        ),
        transcript=[
            TraceTranscriptRow(
                role=str(vote.get("role", "")),
                model_name=str(vote.get("model_name", "")),
                view=str(vote.get("view", "")),
                confidence=float(vote.get("confidence", 0.0)),
            )
            for vote in votes
        ],
        proposal_or_no_trade=(
            [TraceProposal(**plan) for plan in plans]
            if plans
            else "no_trade"
        ),
        intents=[
            TraceIntent(
                intent_id=intent_id,
                status=_attempt_status(attempts, intent_id),
                resolution=_audit_resolution(audit, intent_id),
            )
            for intent_id in sorted(intent_ids)
        ],
        risk_rules=[
            TraceRiskRule(
                risk_decision_id=decision_id,
                intent_id=_audit_intent_for_decision(audit, decision_id),
                status="recorded",
            )
            for decision_id in sorted(risk_decision_ids)
        ],
        oanda_transactions=[
            TraceTransaction(
                client_order_id=str(row.get("client_order_id", "")),
                broker_order_id=str(row.get("broker_order_id", "")),
                status=str(row.get("status", "")),
            )
            for row in order_rows
            if str(row.get("client_order_id", "")) in order_ids
        ],
        reconciliation=[
            TraceReconciliation(
                snapshot_id=str(row[0]),
                captured_at=str(row[1]),
                scope=str(row[2]),
                orders_match=bool(row[3]),
            )
            for row in recon_rows
        ],
    )


def _key_evidence(plans: list[dict[str, Any]]) -> list[str]:
    evidence: list[str] = []
    for plan in plans:
        for item in plan.get("key_evidence", []):
            if isinstance(item, str) and item not in evidence:
                evidence.append(item)
    return sorted(evidence)


def _attempt_status(
    attempts: list[dict[str, Any]], intent_id: str
) -> str:
    for attempt in attempts:
        if str(attempt.get("intent_id", "")) == intent_id:
            return str(attempt.get("status", "recorded"))
    return "recorded"


def _audit_resolution(
    audit: list[dict[str, Any]], intent_id: str
) -> str | None:
    for entry in audit:
        if _detail_str(entry, "intent_id") == intent_id:
            order_id = _detail_str(entry, "order_id")
            return f"order_id={order_id}" if order_id else "recorded"
    return None


def _audit_intent_for_decision(
    audit: list[dict[str, Any]], decision_id: str
) -> str | None:
    for entry in audit:
        if str(entry.get("id", "")) == decision_id:
            return _detail_str(entry, "intent_id")
        if _detail_str(entry, "risk_decision_id") == decision_id:
            return _detail_str(entry, "intent_id")
    return None


def _detail_str(entry: dict[str, Any], key: str) -> str | None:
    details = entry.get("details", {})
    if not isinstance(details, dict):
        return None
    value = details.get(key)
    return str(value) if value is not None else None
