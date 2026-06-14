"""Daily and weekly review journal generation."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from alphabrief_review.schemas import ReviewCenterSnapshot, ReviewJournalEntry


def _default_clock() -> datetime:
    return datetime.now(UTC)


def generate_daily_review(
    snapshot: ReviewCenterSnapshot,
    *,
    trading_day: date,
    clock: Callable[[], datetime] = _default_clock,
) -> ReviewJournalEntry:
    """Generate a deterministic daily review entry from a snapshot."""

    briefs = [
        brief for brief in snapshot.daily_briefs if brief.trading_day == trading_day
    ]
    backtests = snapshot.backtests
    portfolio = snapshot.paper_portfolio
    rejected = snapshot.risk_dashboard.rejected_decisions
    highlights = [
        f"Research reports reviewed: {len(briefs)}",
        f"Backtest reports available: {len(backtests)}",
        f"Paper portfolio value: {portfolio.total_value}",
        f"Risk decisions rejected: {rejected}",
    ]
    action_items = _action_items(snapshot)
    headline = briefs[0].headline if briefs else "No daily brief available"
    return ReviewJournalEntry(
        entry_id=f"review_daily_{trading_day.isoformat()}",
        period="daily",
        period_start=trading_day,
        period_end=trading_day,
        generated_at=clock(),
        title=f"Daily Review {trading_day.isoformat()}",
        summary=headline,
        highlights=highlights,
        action_items=action_items,
    )


def generate_weekly_review(
    snapshot: ReviewCenterSnapshot,
    *,
    week_start: date,
    clock: Callable[[], datetime] = _default_clock,
) -> ReviewJournalEntry:
    """Generate a deterministic weekly review entry from a snapshot."""

    week_end = week_start + timedelta(days=6)
    briefs = [
        brief
        for brief in snapshot.daily_briefs
        if week_start <= brief.trading_day <= week_end
    ]
    highlights = [
        f"Research reports reviewed: {len(briefs)}",
        f"Backtest reports available: {len(snapshot.backtests)}",
        f"Model calls reviewed: {len(snapshot.model_calls)}",
        f"Audit events reviewed: {len(snapshot.order_audit_log)}",
    ]
    return ReviewJournalEntry(
        entry_id=f"review_weekly_{week_start.isoformat()}",
        period="weekly",
        period_start=week_start,
        period_end=week_end,
        generated_at=clock(),
        title=f"Weekly Review {week_start.isoformat()}",
        summary=(
            f"Reviewed {len(briefs)} daily briefs and "
            f"{len(snapshot.order_audit_log)} audit events."
        ),
        highlights=highlights,
        action_items=_action_items(snapshot),
    )


def _action_items(snapshot: ReviewCenterSnapshot) -> list[str]:
    items: list[str] = []
    if snapshot.risk_dashboard.rejected_decisions > 0:
        items.append("Review rejected risk decisions before enabling new strategies.")
    if snapshot.paper_portfolio.open_positions:
        items.append("Review open paper positions and update risk notes.")
    if not items:
        items.append("Continue monitoring research, backtests, and paper trading.")
    return items
