"""Paper trading routes — portfolio, orders, and audit."""

from __future__ import annotations

from decimal import Decimal

from alphabrief_execution import (
    ExecutionAuditLog,
    FillSimulator,
    PaperBroker,
    PortfolioState,
)
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Module-level paper broker
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


@router.get("/orders", response_model=AuditListResponse)
def list_orders(
    status: str | None = Query(None, description="Filter by event_type"),
) -> AuditListResponse:
    """Return the order history (audit log entries)."""
    broker = _get_broker()
    entries = broker.audit_log.entries

    if status is not None:
        entries = [e for e in entries if e.event_type == status]

    return AuditListResponse(
        entries=[
            AuditEntryResponse(
                event_id=e.event_id,
                event_type=e.event_type,
                intent_id=e.intent_id,
                risk_decision_id=e.risk_decision_id,
                order_id=e.order_id,
                fill_id=e.fill_id,
                message=e.message,
                created_at=e.created_at.isoformat(),
            )
            for e in entries
        ]
    )


@router.get("/audit", response_model=AuditListResponse)
def get_audit_log() -> AuditListResponse:
    """Return the complete execution audit log."""
    broker = _get_broker()
    return AuditListResponse(
        entries=[
            AuditEntryResponse(
                event_id=e.event_id,
                event_type=e.event_type,
                intent_id=e.intent_id,
                risk_decision_id=e.risk_decision_id,
                order_id=e.order_id,
                fill_id=e.fill_id,
                message=e.message,
                created_at=e.created_at.isoformat(),
            )
            for e in broker.audit_log.entries
        ]
    )


__all__ = [
    "AuditEntryResponse",
    "AuditListResponse",
    "PortfolioResponse",
    "router",
]
