"""Review Center routes — snapshot and journal generation."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from alphabrief_review import (
    BacktestReportSummary,
    DailyBriefSummary,
    ModelCallSummary,
    OrderAuditSummary,
    PaperPortfolioSummary,
    ReviewCenterSnapshot,
    RiskDashboardSummary,
    StrategyListItem,
    generate_daily_review,
    generate_weekly_review,
)
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Module-level default snapshot
# ---------------------------------------------------------------------------

_now = datetime.now(UTC)
_today = _now.date()
_snapshot_id = f"snapshot_{uuid4().hex[:12]}"


def _default_snapshot() -> ReviewCenterSnapshot:
    return ReviewCenterSnapshot(
        snapshot_id=_snapshot_id,
        generated_at=_now,
        strategies=[
            StrategyListItem(
                strategy_id="ma_trend",
                name="Moving Average Trend",
                version="0.0.0",
                status="active",
            )
        ],
        backtests=[
            BacktestReportSummary(
                report_id="bt_001",
                strategy_id="ma_trend",
                symbol="BTC-USD",
                generated_at=_now,
                total_return=Decimal("0.05"),
                max_drawdown=Decimal("0.02"),
                trade_count=3,
                summary="Positive return with low drawdown.",
            )
        ],
        daily_briefs=[
            DailyBriefSummary(
                brief_id="brief_001",
                trading_day=_today,
                generated_at=_now,
                headline="Market outlook positive",
                executive_summary="Markets show strength.",
                watchlist=["SPY"],
                risk_notes=["Monitor vol"],
            )
        ],
        model_calls=[
            ModelCallSummary(
                call_id="call_001",
                provider="fake",
                model="fake-model",
                task_type="daily_brief",
                prompt_version="v1:1",
                status="succeeded",
                created_at=_now,
                latency_ms=100,
            )
        ],
        paper_portfolio=PaperPortfolioSummary(
            cash=Decimal("100000"),
            total_value=Decimal("100000"),
            realized_pnl=Decimal("0"),
            open_positions={},
            updated_at=_now,
        ),
        order_audit_log=[
            OrderAuditSummary(
                event_id="audit_001",
                event_type="order_created",
                intent_id="intent_001",
                risk_decision_id="risk_001",
                order_id="order_001",
                message="Paper order created",
                created_at=_now,
            )
        ],
        risk_dashboard=RiskDashboardSummary(
            total_decisions=1,
            approved_decisions=1,
            rejected_decisions=0,
            kill_switch_active=False,
            latest_risk_tags=["approved"],
            updated_at=_now,
        ),
        review_journal=[],
    )


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class JournalEntriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    entries: list[dict[str, object]]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/review", tags=["review"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/snapshot")
def get_snapshot() -> dict[str, object]:
    """Return the current complete ReviewCenterSnapshot."""
    return _default_snapshot().model_dump(mode="json")


@router.get("/journal", response_model=JournalEntriesResponse)
def list_journal() -> JournalEntriesResponse:
    """Return the review journal entries from the snapshot."""
    snapshot = _default_snapshot()
    entries = [e.model_dump(mode="json") for e in snapshot.review_journal]
    return JournalEntriesResponse(entries=entries)


@router.get("/journal/daily")
def get_daily_journal(
    trading_day: str | None = Query(
        None, description="Trading day in YYYY-MM-DD format"
    ),
) -> dict[str, object]:
    """Generate a daily review journal entry."""
    snapshot = _default_snapshot()
    if trading_day is not None:
        try:
            day = date.fromisoformat(trading_day)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid date format: {trading_day!r}. Use YYYY-MM-DD.",
            ) from exc
    else:
        day = _today

    entry = generate_daily_review(snapshot, trading_day=day)
    return entry.model_dump(mode="json")


@router.get("/journal/weekly")
def get_weekly_journal(
    week_start: str | None = Query(
        None, description="Week start date in YYYY-MM-DD format"
    ),
) -> dict[str, object]:
    """Generate a weekly review journal entry."""
    snapshot = _default_snapshot()
    if week_start is not None:
        try:
            start = date.fromisoformat(week_start)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Invalid date format: {week_start!r}. Use YYYY-MM-DD."
                ),
            ) from exc
    else:
        start = _today

    entry = generate_weekly_review(snapshot, week_start=start)
    return entry.model_dump(mode="json")


__all__ = [
    "JournalEntriesResponse",
    "router",
]
