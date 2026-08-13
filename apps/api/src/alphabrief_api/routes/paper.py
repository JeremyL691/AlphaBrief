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
from collections.abc import Callable
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
from alphabrief_execution.broker import (
    build_account_exposure_context_from_portfolio,
)
from alphabrief_execution.broker.risk_context import (
    AccountSourceDatum,
    FreshnessPolicy,
    build_broker_risk_context,
    project_risk_context_to_exposure,
)
from alphabrief_risk import RiskContextDecision
from alphabrief_risk.broker_context import (
    BrokerRiskContext,
    ConversionDatum,
    HealthState,
    PendingOrderDatum,
    PositionDatum,
    PriceDatum,
    ReconciliationState,
    TradeDatum,
)
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.db import PaperStore
from alphabrief_api.routes.data import _get_store as _get_market_data_store
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
    """Clear the persistent paper store (for test isolation).

    Closes and drops the singleton (not just ``clear()``) so the next
    access rebuilds it at the current ``ALPHABRIEF_DATA_DIR`` — matching
    the MarketDataStore isolation pattern. R21.3 persists equity snapshots
    across fills, so a stale singleton from a prior test would leak
    drawdown/daily-loss state otherwise.
    """
    global _paper_store
    if _paper_store is not None:
        _paper_store.close()
    _paper_store = None


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


class _MissingMarkPriceError(HTTPException):
    """Fail-closed signal raised when no stored mark price can be resolved.

    RiskGate's exposure and order-value checks only bind against a real
    reference price. Validating them against a hardcoded placeholder
    silently turns the $100/$300 caps into no-ops, so a missing price is
    a hard rejection rather than a fallback to a fiction.
    """


#: Venue policy for the legacy in-memory paper broker: the only price is
#: the latest stored daily close, so the venue defines no age ceiling
#: for it (the route fails closed when no bar exists at all). The other
#: authority sources have no independent timestamps in this venue.
_PAPER_FRESHNESS = FreshnessPolicy(
    {
        "prices": None,
        "catalog": None,
        "reconciliation": None,
        "health": None,
    }
)


class _PaperRiskSources:
    """Venue-truthful context sources for the legacy in-memory broker.

    The venue IS the local process: the portfolio is the account truth,
    the stored close is the mark, and there is no pending-order, trade,
    conversion, catalog, or reconciliation authority. No broker fact is
    synthesized — every value comes from the venue's own state.
    """

    def __init__(
        self,
        broker: PaperBroker,
        *,
        symbol: str,
        reference_price: Decimal,
        now: datetime,
    ) -> None:
        self._broker = broker
        self._symbol = symbol
        self._reference_price = reference_price
        self._now = now

    def fetch_account(self) -> AccountSourceDatum:
        portfolio = self._broker.portfolio
        nav = portfolio.cash + sum(
            position.quantity * position.average_price
            for position in portfolio.positions.values()
        )
        return AccountSourceDatum(
            account_id="paper_local",
            state="ACTIVE",
            tradeable=True,
            home_currency="USD",
            balance=portfolio.cash,
            nav=nav,
            margin_used=Decimal("0"),
            margin_available=nav,
            captured_at=self._now,
        )

    def fetch_positions(self) -> list[PositionDatum]:
        return [
            PositionDatum(
                symbol=symbol,
                long_units=position.quantity,
                short_units=Decimal("0"),
                average_price=position.average_price,
            )
            for symbol, position in sorted(
                self._broker.portfolio.positions.items()
            )
        ]

    def fetch_pending_orders(self) -> list[PendingOrderDatum]:
        # The venue's order authority is the portfolio state itself.
        return []

    def fetch_trades(self) -> list[TradeDatum]:
        # The venue's trade authority is the portfolio state itself.
        return []

    def fetch_prices(self) -> list[PriceDatum]:
        return [
            PriceDatum(
                symbol=self._symbol,
                bid=self._reference_price,
                ask=self._reference_price,
                captured_at=self._now,
            )
        ]

    def fetch_conversions(self) -> list[ConversionDatum]:
        return []  # the venue has no conversion authority

    def fetch_catalog_version(self) -> str | None:
        return None  # the venue has no catalog authority

    def fetch_reconciliation_state(self) -> ReconciliationState:
        return "unknown"  # the venue performs no external reconciliation

    def fetch_health(self) -> HealthState:
        # The in-memory venue is available whenever the process is.
        return "healthy"


def build_paper_risk_context(
    broker: PaperBroker,
    *,
    symbol: str,
    reference_price: Decimal,
    now: datetime,
    clock: Callable[[], datetime] | None = None,
) -> BrokerRiskContext:
    """Build the manual paper venue's broker-fresh risk context.

    Goes through the ONE shared context service
    (:func:`build_broker_risk_context`) with the venue's truthful
    sources, stamping the shared context and policy versions
    (AC-M08-W01-02). Fails closed on account mismatch or internally
    inconsistent state; never synthesizes broker facts.
    """
    return build_broker_risk_context(
        _PaperRiskSources(
            broker,
            symbol=symbol,
            reference_price=reference_price,
            now=now,
        ),
        expected_account_id="paper_local",
        freshness=_PAPER_FRESHNESS,
        require_price_coverage=False,
        clock=clock,
    )


def _resolve_reference_price(symbol: str) -> Decimal:
    """Return the latest stored daily close for *symbol* as the mark price.

    Reads bars from the shared ``MarketDataStore`` (ascending by timestamp,
    so the last bar's close is the most recent). Fails closed with HTTP 422
    and a ``missing_mark_price`` detail when no bars are stored for the
    symbol — never falls back to a placeholder price.

    ponytail:mark_price_source: the mark is the latest *daily* close held in
    DuckDB, not a real-time quote. Ceiling: an intraday burst order is
    priced at the prior session close, so a market-open spike is validated
    against a stale mark. Upgrade path: a quote provider feeding the
    ``mark_prices`` dict already accepted by the exposure helper.
    """
    bars = _get_market_data_store().get_bar_models(symbol)
    if not bars:
        raise _MissingMarkPriceError(
            status_code=422,
            detail=(
                f"missing_mark_price: no stored bars for {symbol!r}; "
                "load market data before submitting an order"
            ),
        )
    return bars[-1].close


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
    return AuditListResponse(entries=[_audit_entry_from_dict(e) for e in raw])


@router.get("/audit", response_model=AuditListResponse)
def get_audit_log() -> AuditListResponse:
    """Return the complete execution audit log from persistent store."""
    store = _get_paper_store()
    raw = store.get_audit_events()
    return AuditListResponse(entries=[_audit_entry_from_dict(e) for e in raw])


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

    reference_price = _resolve_reference_price(intent.symbol)

    # M08-W01: the manual paper path builds its pre-risk context through
    # the SAME broker-fresh context service as the AI external execution
    # path (AC-M08-W01-02) — one versioned context type and one policy
    # version, never caller-selected partial dictionaries. The venue
    # sources are the legacy in-memory PaperBroker portfolio plus the
    # stored mark; the venue defines no age ceiling for that mark (the
    # route already fails closed when no bar exists at all). The context
    # is projected into the RiskGate exposure contract for the gate.
    risk_context = build_paper_risk_context(
        broker,
        symbol=intent.symbol,
        reference_price=reference_price,
        now=now,
    )
    account_context = project_risk_context_to_exposure(
        risk_context, mark_prices={intent.symbol: reference_price}
    )

    # R21.3: enrich the context with the drawdown high-water mark and
    # day-start equity read from the persistent equity-snapshot store so
    # the daily-loss / drawdown rules are restart-safe (an in-memory HWM
    # would reset on restart and silently widen the floor). The store may
    # be empty on the first order; the gate fails closed on the missing
    # inputs only when the corresponding rule is configured.
    hwm = store.get_high_water_mark(account_context.account_id)
    day_start = store.get_day_start_equity(account_context.account_id, now.date())
    account_context = account_context.model_copy(
        update={
            "equity_high_water_mark": hwm
            if hwm is not None
            else account_context.equity,
            "day_start_equity": (
                day_start if day_start is not None else account_context.equity
            ),
        }
    )

    decision = gate.evaluate(
        intent,
        estimated_price=reference_price,
        risk_context=body.risk_context,
        account_context=account_context,
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
            "reference_price": str(reference_price),
            "risk_context_decision_id": (
                body.risk_context.decision_id if body.risk_context is not None else None
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
            "account_total_exposure": str(account_context.current_total_exposure),
            "max_total_exposure": (
                str(gate.limits.max_total_exposure)
                if gate.limits.max_total_exposure is not None
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
        pos.quantity * pos.average_price for pos in portfolio.positions.values()
    )
    store.save_portfolio_snapshot(
        cash=str(portfolio.cash),
        realized_pnl=str(portfolio.realized_pnl),
        total_value=str(total_value),
        positions=positions_dict,
    )

    # R21.3: persist an equity snapshot after the fill so the daily-loss
    # and drawdown rules have restart-safe state. Equity is mark-based
    # (cash + sum(qty * mark)); for symbols without a stored mark we fall
    # back to cost basis (the exposure projection's ponytail ceiling).
    post_fill_context = build_account_exposure_context_from_portfolio(
        portfolio,
        account_id="paper_local",
        mark_prices={intent.symbol: reference_price},
    )
    if post_fill_context.equity is not None:
        store.save_equity_snapshot(
            account_id="paper_local",
            captured_at=now,
            equity=post_fill_context.equity,
            realized_pnl_day=portfolio.realized_pnl,
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
            body.risk_context.decision_id if body.risk_context is not None else None
        ),
    }


__all__ = [
    "AuditEntryResponse",
    "AuditListResponse",
    "OrderRequest",
    "PortfolioResponse",
    "_reset_broker",
    "_resolve_reference_price",
    "router",
]
