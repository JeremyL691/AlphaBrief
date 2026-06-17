"""Paper trading routes — portfolio, orders, and audit.

Phase 7 Round 4: Module-level broker state is now DuckDB-persisted
through ``PaperStore``.  The broker still runs the in-memory execution
logic, but all data is saved to and read from the database.

Phase 13 Round 4: ``POST /api/v1/paper/orders`` accepts an optional
``risk_context`` (a :class:`RiskContextDecision`). When present, the
context tightens the gate (tags merged, ``requires_human_review`` OR-ed,
``max_quantity`` reduced). The merged decision's metadata is recorded
in the audit log. If the merged decision requires human review, the
broker blocks auto-execution and returns 422.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from alphabrief_core import OrderIntent, OrderSide, OrderType
from alphabrief_execution import (
    ExecutionAuditLog,
    FillSimulator,
    PaperBroker,
    PaperBrokerError,
    PortfolioState,
)
from alphabrief_risk import RiskContextDecision
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.db import PaperStore
from alphabrief_api.routes.risk import _get_risk_gate

# ---------------------------------------------------------------------------
# Persistent store (DuckDB-backed)
# ---------------------------------------------------------------------------

_paper_store: PaperStore | None = None


def _get_paper_store() -> PaperStore:
    """Return the singleton PaperStore, creating it on first access."""
    global _paper_store
    if _paper_store is None:
        _paper_store = PaperStore()
    return _paper_store


def _reset_paper_store() -> None:
    """Clear the persistent paper store (for test isolation)."""
    global _paper_store
    if _paper_store is not None:
        _paper_store.clear()


# ---------------------------------------------------------------------------
# Module-level paper broker (in-memory execution logic)
# ---------------------------------------------------------------------------

_default_portfolio = PortfolioState(cash=Decimal("100000"))
_default_broker = PaperBroker(
    portfolio=_default_portfolio,
    fill_simulator=FillSimulator(),
    audit_log=ExecutionAuditLog(),
)


def _get_broker() -> PaperBroker:
    return _default_broker


def _reset_broker() -> None:
    """Reset broker state for test isolation."""
    global _default_broker
    _default_broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        fill_simulator=FillSimulator(),
        audit_log=ExecutionAuditLog(),
    )
    _reset_paper_store()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class OrderRequest(BaseModel):
    """Request body for POST /api/v1/paper/orders."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1)
    side: OrderSide
    order_type: OrderType = "market"
    quantity: Decimal | None = None
    target_position_pct: Decimal | None = None
    limit_price: Decimal | None = None
    rationale: str = "Paper order via API"
    risk_context: RiskContextDecision | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PositionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    quantity: str
    average_price: str


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    cash: str
    positions: list[PositionResponse]
    realized_pnl: str


class AuditEntryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str
    event_type: str
    intent_id: str | None
    risk_decision_id: str | None
    order_id: str | None
    fill_id: str | None
    message: str
    created_at: str
    risk_context_decision_id: str | None = None
    risk_context_tags: list[str] = Field(default_factory=list)
    risk_context_multiplier: float | None = None


class AuditListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    entries: list[AuditEntryResponse]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/paper", tags=["paper"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio() -> PortfolioResponse:
    """Return the current PaperBroker portfolio state."""
    broker = _get_broker()
    portfolio = broker.portfolio
    positions = [
        PositionResponse(
            symbol=pos.symbol,
            quantity=str(pos.quantity),
            average_price=str(pos.average_price),
        )
        for pos in portfolio.positions.values()
    ]
    return PortfolioResponse(
        cash=str(portfolio.cash),
        positions=positions,
        realized_pnl=str(portfolio.realized_pnl),
    )


def _audit_entry_from_dict(e: dict[str, object]) -> AuditEntryResponse:
    details_obj = e.get("details", {})
    details_dict: dict[str, object] = (
        details_obj if isinstance(details_obj, dict) else {}
    )

    def _str_or_none(key: str) -> str | None:
        value = details_dict.get(key)
        return value if isinstance(value, str) else None

    def _tags() -> list[str]:
        tags_raw = details_dict.get("risk_context_tags", [])
        return [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []

    def _mult() -> float | None:
        mult_raw = details_dict.get("risk_context_multiplier")
        if isinstance(mult_raw, (int, float)):
            return float(mult_raw)
        return None

    return AuditEntryResponse(
        event_id=str(e["id"]),
        event_type=str(e["event_type"]),
        intent_id=_str_or_none("intent_id"),
        risk_decision_id=_str_or_none("risk_decision_id"),
        order_id=_str_or_none("order_id"),
        fill_id=_str_or_none("fill_id"),
        message=str(details_dict.get("message", "")),
        created_at=str(e["created_at"]),
        risk_context_decision_id=_str_or_none("risk_context_decision_id"),
        risk_context_tags=_tags(),
        risk_context_multiplier=_mult(),
    )


@router.get("/orders", response_model=AuditListResponse)
def list_orders(
    status: str | None = Query(None, description="Filter by event_type"),
) -> AuditListResponse:
    """Return the order history (audit log entries) from persistent store."""
    store = _get_paper_store()
    if status is not None:
        raw = store.get_audit_events(event_type=status)
    else:
        raw = store.get_audit_events()
    return AuditListResponse(
        entries=[_audit_entry_from_dict(e) for e in raw]
    )


@router.get("/audit", response_model=AuditListResponse)
def get_audit_log() -> AuditListResponse:
    """Return the complete execution audit log from persistent store."""
    store = _get_paper_store()
    raw = store.get_audit_events()
    return AuditListResponse(
        entries=[_audit_entry_from_dict(e) for e in raw]
    )


@router.post("/orders", status_code=201)
def submit_order(body: OrderRequest) -> dict[str, object]:
    """Submit a paper order: risk check → broker execution → persist.

    The OrderIntent is evaluated by RiskGate, and if approved the
    PaperBroker executes it.  All audit events and the resulting
    portfolio snapshot are persisted to DuckDB.

    An optional ``risk_context`` (a
    :class:`alphabrief_risk.RiskContextDecision`) is applied in a
    **tighten-only** manner to the gate. If the merged decision
    requires human review, auto-execution is blocked and a 422 is
    returned.
    """
    broker = _get_broker()
    gate = _get_risk_gate()
    store = _get_paper_store()
    now = datetime.now(UTC)

    intent = OrderIntent(
        intent_id=f"intent_{uuid.uuid4().hex[:12]}",
        source="manual",
        symbol=body.symbol,
        side=body.side,
        order_type=body.order_type,
        quantity=body.quantity,
        target_position_pct=body.target_position_pct,
        limit_price=body.limit_price,
        rationale=body.rationale,
        created_at=now,
    )

    reference_price = Decimal("100")

    decision = gate.evaluate(
        intent,
        estimated_price=reference_price,
        risk_context=body.risk_context,
    )
    store.save_audit_event(
        event_type="risk_decision_recorded",
        symbol=intent.symbol,
        details={
            "intent_id": intent.intent_id,
            "risk_decision_id": decision.decision_id,
            "approved": decision.approved,
            "reason": decision.reason,
            "message": "risk decision recorded",
            "risk_context_decision_id": (
                body.risk_context.decision_id
                if body.risk_context is not None
                else None
            ),
            "risk_context_tags": (
                list(body.risk_context.risk_tags)
                if body.risk_context is not None
                else []
            ),
            "risk_context_multiplier": (
                body.risk_context.suggested_max_position_multiplier
                if body.risk_context is not None
                else None
            ),
        },
    )

    if not decision.approved:
        raise HTTPException(
            status_code=422,
            detail=f"RiskGate rejected: {decision.reason}",
        )

    if decision.requires_human_review:
        raise HTTPException(
            status_code=422,
            detail=(
                "RiskGate requires human review; auto-execution blocked. "
                "Approve the decision manually or remove the risk_context."
            ),
        )

    reference_price = Decimal("100")  # Placeholder — will be fed from market data
    try:
        result = broker.submit(
            intent,
            decision,
            reference_price=reference_price,
            risk_context=body.risk_context,
        )
    except PaperBrokerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    for entry in broker.audit_log.entries:
        store.save_audit_event(
            event_type=entry.event_type,
            symbol=result.order.symbol,
            details={
                "intent_id": entry.intent_id,
                "risk_decision_id": entry.risk_decision_id,
                "order_id": entry.order_id,
                "fill_id": entry.fill_id,
                "message": entry.message,
                "risk_context_decision_id": entry.risk_context_decision_id,
                "risk_context_tags": list(entry.risk_context_tags),
                "risk_context_multiplier": entry.risk_context_multiplier,
            },
        )

    portfolio = result.portfolio
    positions_dict = {
        sym: {
            "symbol": pos.symbol,
            "quantity": str(pos.quantity),
            "average_price": str(pos.average_price),
        }
        for sym, pos in portfolio.positions.items()
    }
    total_value = portfolio.cash + sum(
        pos.quantity * pos.average_price
        for pos in portfolio.positions.values()
    )
    store.save_portfolio_snapshot(
        cash=str(portfolio.cash),
        realized_pnl=str(portfolio.realized_pnl),
        total_value=str(total_value),
        positions=positions_dict,
    )

    return {
        "order_id": result.order.order_id,
        "fill_id": result.fill.fill_id,
        "symbol": result.order.symbol,
        "side": result.order.side,
        "quantity": str(result.order.quantity),
        "status": "filled",
        "price": str(result.fill.price),
        "applied_risk_context": (
            body.risk_context.decision_id
            if body.risk_context is not None
            else None
        ),
    }


__all__ = [
    "AuditEntryResponse",
    "AuditListResponse",
    "OrderRequest",
    "PortfolioResponse",
    "_reset_broker",
    "router",
]
