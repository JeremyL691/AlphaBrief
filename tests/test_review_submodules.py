"""Unit tests for the review submodules (journal, viewers, io)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_review import (
    ReviewCenterSnapshot,
    ReviewJournalEntry,
)
from alphabrief_review.io import (
    ReviewSnapshotLoadError,
    load_review_snapshot,
    write_review_snapshot,
)
from alphabrief_review.journal import (
    generate_daily_review,
    generate_weekly_review,
)
from alphabrief_review.schemas import (
    DailyBriefSummary,
    PaperPortfolioSummary,
    RiskDashboardSummary,
    StrategyListItem,
)
from alphabrief_review.viewers import (
    render_backtest_report_view,
    render_model_call_history,
    render_order_audit_log,
    render_paper_portfolio,
    render_research_report,
    render_review_journal,
    render_risk_dashboard,
    render_strategy_list,
)

NOW = datetime(2026, 6, 20, 13, 30, tzinfo=UTC)


def _snapshot() -> ReviewCenterSnapshot:
    return ReviewCenterSnapshot(
        snapshot_id="snap_1",
        generated_at=NOW,
        strategies=[
            StrategyListItem(
                strategy_id="sma",
                version="1",
                name="SMA Trend",
                status="enabled",
            )
        ],
        backtests=[],
        daily_briefs=[
            DailyBriefSummary(
                brief_id="b1",
                trading_day=date(2026, 6, 20),
                generated_at=NOW,
                headline="H1",
                executive_summary="E1",
                watchlist=["SPY"],
                risk_notes=["elevated volatility"],
            )
        ],
        model_calls=[],
        paper_portfolio=PaperPortfolioSummary(
            cash=Decimal("1000"),
            total_value=Decimal("1000"),
            realized_pnl=Decimal("0"),
            open_positions={"SPY": Decimal("1")},
            updated_at=NOW,
        ),
        risk_dashboard=RiskDashboardSummary(
            total_decisions=2,
            approved_decisions=1,
            rejected_decisions=1,
            kill_switch_active=False,
            latest_risk_tags=["news_volatility"],
            updated_at=NOW,
        ),
        order_audit_log=[],
        review_journal=[],
    )


def test_render_strategy_list_includes_each_strategy() -> None:
    snapshot = _snapshot()
    out = render_strategy_list(snapshot)
    assert "sma" in out
    assert "SMA Trend" in out


def test_render_paper_portfolio_shows_positions() -> None:
    snapshot = _snapshot()
    out = render_paper_portfolio(snapshot)
    assert "SPY=1" in out
    assert "cash=1000" in out


def test_render_paper_portfolio_empty_positions_says_none() -> None:
    empty_portfolio = PaperPortfolioSummary(
        cash=Decimal("0"),
        total_value=Decimal("0"),
        realized_pnl=Decimal("0"),
        open_positions={},
        updated_at=NOW,
    )
    snapshot = _snapshot().model_copy(update={"paper_portfolio": empty_portfolio})
    out = render_paper_portfolio(snapshot)
    assert "positions=none" in out


def test_render_risk_dashboard_includes_tags() -> None:
    snapshot = _snapshot()
    out = render_risk_dashboard(snapshot)
    assert "kill_switch_active=False" in out
    assert "news_volatility" in out


def test_render_empty_viewers_are_safe() -> None:
    snapshot = _snapshot().model_copy(
        update={
            "backtests": [],
            "daily_briefs": [],
            "model_calls": [],
            "order_audit_log": [],
            "review_journal": [],
        }
    )
    assert "Backtest Reports" in render_backtest_report_view(snapshot)
    assert "Daily AlphaBriefs" in render_research_report(snapshot)
    assert "Model Calls" in render_model_call_history(snapshot)
    assert "Order Audit Log" in render_order_audit_log(snapshot)
    assert "Review Journal" in render_review_journal(snapshot)


def test_generate_daily_review_uses_snapshot_data() -> None:
    snapshot = _snapshot()
    entry = generate_daily_review(snapshot, trading_day=date(2026, 6, 20))
    assert isinstance(entry, ReviewJournalEntry)
    assert entry.period == "daily"
    assert "Research reports reviewed: 1" in entry.highlights


def test_generate_daily_review_emits_action_items_on_rejects() -> None:
    snapshot = _snapshot()
    entry = generate_daily_review(snapshot, trading_day=date(2026, 6, 20))
    assert any("risk decisions" in item.lower() for item in entry.action_items)


def test_generate_weekly_review_span_covers_seven_days() -> None:
    snapshot = _snapshot()
    entry = generate_weekly_review(snapshot, week_start=date(2026, 6, 16))
    assert entry.period == "weekly"
    assert entry.period_end == date(2026, 6, 22)


def test_write_and_load_review_snapshot_round_trip(tmp_path: Path) -> None:
    snapshot = _snapshot()
    path = tmp_path / "review.json"
    write_review_snapshot(snapshot, path)
    loaded = load_review_snapshot(path)
    assert loaded.paper_portfolio.cash == Decimal("1000")


def test_load_review_snapshot_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ReviewSnapshotLoadError):
        load_review_snapshot(path)


def test_load_review_snapshot_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    with pytest.raises(ReviewSnapshotLoadError):
        load_review_snapshot(path)
