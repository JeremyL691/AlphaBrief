"""Review Center routes — snapshot and journal generation.

Phase 7 Round 4: Review snapshots are now persisted in DuckDB via
``ReviewStore``, replacing the module-level default snapshot that
contained hardcoded sample data.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from alphabrief_core import paths as _paths
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

from alphabrief_api.db import ReviewStore

# ---------------------------------------------------------------------------
# Persistent store (DuckDB-backed)
# ---------------------------------------------------------------------------

_review_store: ReviewStore | None = None


def _get_review_store() -> ReviewStore:
    """Return the singleton ReviewStore, creating it on first access."""
    global _review_store
    if _review_store is None:
        _review_store = ReviewStore()
    return _review_store


def _clear_review_store() -> None:
    """Clear the persistent review store (for test isolation)."""
    global _review_store
    if _review_store is not None:
        _review_store.clear()


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
# Helpers
# ---------------------------------------------------------------------------


def _build_default_snapshot() -> ReviewCenterSnapshot:
    """Build a default ReviewCenterSnapshot with sample data.

    Used when no snapshot has been persisted yet.
    """
    _now = datetime.now(UTC)
    _today = _now.date()
    _snapshot_id = f"snapshot_{uuid4().hex[:12]}"
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


def _get_or_create_snapshot() -> ReviewCenterSnapshot:
    """Return the latest snapshot from the DB, or create a default one."""
    store = _get_review_store()
    latest = store.get_latest_snapshot()
    if latest is not None:
        try:
            return ReviewCenterSnapshot.model_validate(latest["snapshot"])
        except Exception:
            pass
    # Fall back to default snapshot
    snapshot = _build_default_snapshot()
    return snapshot


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/snapshot")
def get_snapshot() -> dict[str, object]:
    """Return the current complete ReviewCenterSnapshot."""
    return _get_or_create_snapshot().model_dump(mode="json")


@router.get("/journal", response_model=JournalEntriesResponse)
def list_journal() -> JournalEntriesResponse:
    """Return the review journal entries from the snapshot."""
    snapshot = _get_or_create_snapshot()
    entries = [e.model_dump(mode="json") for e in snapshot.review_journal]
    return JournalEntriesResponse(entries=entries)


@router.get("/journal/daily")
def get_daily_journal(
    trading_day: str | None = Query(
        None, description="Trading day in YYYY-MM-DD format"
    ),
) -> dict[str, object]:
    """Generate a daily review journal entry."""
    snapshot = _get_or_create_snapshot()
    if trading_day is not None:
        try:
            day = date.fromisoformat(trading_day)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid date format: {trading_day!r}. Use YYYY-MM-DD.",
            ) from exc
    else:
        day = datetime.now(UTC).date()

    entry = generate_daily_review(snapshot, trading_day=day)
    return entry.model_dump(mode="json")


@router.get("/journal/weekly")
def get_weekly_journal(
    week_start: str | None = Query(
        None, description="Week start date in YYYY-MM-DD format"
    ),
) -> dict[str, object]:
    """Generate a weekly review journal entry."""
    snapshot = _get_or_create_snapshot()
    if week_start is not None:
        try:
            start = date.fromisoformat(week_start)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=(f"Invalid date format: {week_start!r}. Use YYYY-MM-DD."),
            ) from exc
    else:
        start = datetime.now(UTC).date()

    entry = generate_weekly_review(snapshot, week_start=start)
    return entry.model_dump(mode="json")


@router.get("/reports")
def list_daily_reports() -> dict[str, Any]:
    """List available daily reports from storage."""
    daily_dir = _paths.daily_reports_dir()
    reports: list[dict[str, Any]] = []
    if daily_dir.is_dir():
        for json_file in sorted(daily_dir.glob("*.json"), reverse=True):
            date_str = json_file.stem
            md_file = daily_dir / f"{date_str}.md"
            summary_info: dict[str, Any] = {
                "date": date_str,
                "has_markdown": md_file.exists(),
            }
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                summary_info["summary"] = data.get("summary", "")
                summary_info["nav"] = data.get("nav")
                summary_info["cycles_count"] = len(data.get("cycles", []))
            except Exception:
                pass
            reports.append(summary_info)
    return {"reports": reports}


@router.get("/reports/{report_date}")
def get_daily_report(report_date: str) -> dict[str, Any]:
    """Get a specific daily report content."""
    daily_dir = _paths.daily_reports_dir()
    json_file = daily_dir / f"{report_date}.json"
    md_file = daily_dir / f"{report_date}.md"
    if not json_file.exists() and not md_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Report for {report_date} not found",
        )

    payload: dict[str, Any] = {"date": report_date}
    if json_file.exists():
        try:
            payload["data"] = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            payload["data"] = None
    if md_file.exists():
        payload["markdown"] = md_file.read_text(encoding="utf-8")
    return payload


__all__ = [
    "JournalEntriesResponse",
    "_clear_review_store",
    "router",
]
