from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_review import (
    BacktestReportSummary,
    DailyBriefSummary,
    ModelCallSummary,
    OrderAuditSummary,
    PaperPortfolioSummary,
    ReviewCenterSnapshot,
    ReviewJournalEntry,
    ReviewSnapshotLoadError,
    RiskDashboardSummary,
    StrategyListItem,
    generate_daily_review,
    generate_weekly_review,
    load_review_snapshot,
    render_backtest_report_view,
    render_model_call_history,
    render_order_audit_log,
    render_paper_portfolio,
    render_research_report,
    render_review_journal,
    render_risk_dashboard,
    render_strategy_list,
    write_review_snapshot,
)
from pydantic import ValidationError

NOW = datetime(2026, 6, 14, 16, 0, tzinfo=UTC)
TRADING_DAY = date(2026, 6, 14)


def _snapshot() -> ReviewCenterSnapshot:
    return ReviewCenterSnapshot(
        snapshot_id="snapshot_1",
        generated_at=NOW,
        strategies=[
            StrategyListItem(
                strategy_id="sma_v1",
                name="SMA Trend",
                version="v1",
                status="paper_enabled",
            )
        ],
        backtests=[
            BacktestReportSummary(
                report_id="bt_1",
                strategy_id="sma_v1",
                symbol="BTC-USD",
                generated_at=NOW,
                total_return=Decimal("0.12"),
                max_drawdown=Decimal("0.03"),
                trade_count=2,
                summary="SMA strategy outperformed baseline.",
            )
        ],
        daily_briefs=[
            DailyBriefSummary(
                brief_id="daily_1",
                trading_day=TRADING_DAY,
                generated_at=NOW,
                headline="Risk assets consolidate",
                executive_summary="Market remained orderly.",
                watchlist=["BTC-USD"],
                risk_notes=["Watch sizing."],
            )
        ],
        model_calls=[
            ModelCallSummary(
                call_id="call_1",
                provider="fake",
                model="fake-model",
                task_type="daily_brief",
                prompt_version="daily_alpha_brief:v1",
                status="succeeded",
                created_at=NOW,
                latency_ms=12,
            )
        ],
        paper_portfolio=PaperPortfolioSummary(
            cash=Decimal("9000"),
            total_value=Decimal("10100"),
            realized_pnl=Decimal("100"),
            open_positions={"BTC-USD": Decimal("1")},
            updated_at=NOW,
        ),
        order_audit_log=[
            OrderAuditSummary(
                event_id="audit_1",
                event_type="risk_decision_recorded",
                intent_id="intent_1",
                risk_decision_id="risk_1",
                order_id=None,
                message="risk decision received",
                created_at=NOW,
            )
        ],
        risk_dashboard=RiskDashboardSummary(
            total_decisions=2,
            approved_decisions=1,
            rejected_decisions=1,
            kill_switch_active=False,
            latest_risk_tags=["approved", "max_quantity"],
            updated_at=NOW,
        ),
        review_journal=[
            ReviewJournalEntry(
                entry_id="review_daily_2026-06-14",
                period="daily",
                period_start=TRADING_DAY,
                period_end=TRADING_DAY,
                generated_at=NOW,
                title="Daily Review 2026-06-14",
                summary="Reviewed paper trading and research.",
                highlights=["Research reports reviewed: 1"],
                action_items=["Review rejected risk decisions."],
            )
        ],
    )


def test_review_center_snapshot_accepts_valid_data() -> None:
    snapshot = _snapshot()

    assert snapshot.snapshot_id == "snapshot_1"
    assert snapshot.strategies[0].strategy_id == "sma_v1"
    assert snapshot.paper_portfolio.total_value == Decimal("10100")
    assert snapshot.risk_dashboard.rejected_decisions == 1


def test_review_schemas_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StrategyListItem.model_validate(
            {
                "strategy_id": "sma_v1",
                "name": "SMA",
                "version": "v1",
                "status": "enabled",
                "unexpected": True,
            }
        )


def test_review_schemas_reject_naive_datetime_and_float_decimal() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        BacktestReportSummary(
            report_id="bt_1",
            strategy_id="sma_v1",
            symbol="BTC-USD",
            generated_at=datetime(2026, 6, 14, 16, 0),
            total_return=Decimal("0.1"),
            max_drawdown=Decimal("0.01"),
            trade_count=1,
            summary="ok",
        )

    with pytest.raises(ValidationError, match="float"):
        PaperPortfolioSummary.model_validate(
            {
                "cash": 100.0,
                "total_value": "100",
                "realized_pnl": "0",
                "open_positions": {},
                "updated_at": NOW,
            }
        )


def test_review_schemas_reject_blank_strings_and_list_items() -> None:
    with pytest.raises(ValidationError, match="blank"):
        DailyBriefSummary(
            brief_id="daily_1",
            trading_day=TRADING_DAY,
            generated_at=NOW,
            headline=" ",
            executive_summary="summary",
            watchlist=[],
            risk_notes=[],
        )

    with pytest.raises(ValidationError, match="blank"):
        RiskDashboardSummary(
            total_decisions=1,
            approved_decisions=1,
            rejected_decisions=0,
            kill_switch_active=False,
            latest_risk_tags=[" "],
            updated_at=NOW,
        )


def test_review_snapshot_json_round_trip(tmp_path: Path) -> None:
    snapshot = _snapshot()
    path = tmp_path / "review_snapshot.json"

    write_review_snapshot(snapshot, path)
    loaded = load_review_snapshot(path)

    assert loaded == snapshot


def test_load_review_snapshot_reports_missing_or_invalid_files(tmp_path: Path) -> None:
    with pytest.raises(ReviewSnapshotLoadError, match="failed to read"):
        load_review_snapshot(tmp_path / "missing.json")

    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json", encoding="utf-8")
    with pytest.raises(ReviewSnapshotLoadError, match="invalid"):
        load_review_snapshot(invalid)


def test_viewers_render_all_phase_five_surfaces() -> None:
    snapshot = _snapshot()

    assert "sma_v1" in render_strategy_list(snapshot)
    assert "bt_1" in render_backtest_report_view(snapshot)
    assert "Risk assets consolidate" in render_research_report(snapshot)
    assert "call_1" in render_model_call_history(snapshot)
    assert "total_value=10100" in render_paper_portfolio(snapshot)
    assert "risk=risk_1" in render_order_audit_log(snapshot)
    assert "rejected=1" in render_risk_dashboard(snapshot)
    assert "Daily Review" in render_review_journal(snapshot)


def test_generate_daily_review_from_snapshot() -> None:
    entry = generate_daily_review(
        _snapshot(),
        trading_day=TRADING_DAY,
        clock=lambda: NOW,
    )

    assert entry.period == "daily"
    assert entry.period_start == TRADING_DAY
    assert entry.period_end == TRADING_DAY
    assert "Risk assets consolidate" in entry.summary
    assert any("Risk decisions rejected: 1" == item for item in entry.highlights)
    assert any("Review rejected" in item for item in entry.action_items)


def test_generate_weekly_review_from_snapshot() -> None:
    entry = generate_weekly_review(
        _snapshot(),
        week_start=date(2026, 6, 8),
        clock=lambda: NOW,
    )

    assert entry.period == "weekly"
    assert entry.period_start == date(2026, 6, 8)
    assert entry.period_end == date(2026, 6, 14)
    assert "1 daily briefs" in entry.summary
    assert any("Audit events reviewed: 1" == item for item in entry.highlights)
