"""Automated tests for S7: Review daily CLI and reports.

Verifies:
- alphabrief review daily without --snapshot reads latest daily report from storage.
- alphabrief review daily with --snapshot generates journal entry.
- GET /api/v1/review/reports lists daily reports for the review page.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_cli.review_commands import review_app
from alphabrief_review import (
    BacktestReportSummary,
    DailyBriefSummary,
    PaperPortfolioSummary,
    ReviewCenterSnapshot,
    RiskDashboardSummary,
    StrategyListItem,
)
from fastapi.testclient import TestClient
from typer.testing import CliRunner

runner = CliRunner()


def _make_snapshot(
    snapshot_id: str = "snap_s7", day: date | None = None
) -> ReviewCenterSnapshot:
    now = datetime.now(UTC)
    td = day or now.date()
    return ReviewCenterSnapshot(
        snapshot_id=snapshot_id,
        generated_at=now,
        strategies=[
            StrategyListItem(
                strategy_id="momentum_s7",
                name="Momentum S7",
                version="1.0.0",
                status="active",
            )
        ],
        backtests=[
            BacktestReportSummary(
                report_id="bt_s7",
                strategy_id="momentum_s7",
                symbol="EUR_USD",
                generated_at=now,
                total_return=Decimal("0.02"),
                max_drawdown=Decimal("0.01"),
                trade_count=1,
                summary="Positive return on EUR_USD",
            )
        ],
        daily_briefs=[
            DailyBriefSummary(
                brief_id="brief_s7",
                trading_day=td,
                generated_at=now,
                headline="EUR_USD holds steady",
                executive_summary="Review entry for test",
                watchlist=["EUR_USD"],
                risk_notes=["Watch stop levels"],
            )
        ],
        model_calls=[],
        paper_portfolio=PaperPortfolioSummary(
            cash=Decimal("100000"),
            total_value=Decimal("100000"),
            realized_pnl=Decimal("0"),
            open_positions={},
            updated_at=now,
        ),
        order_audit_log=[],
        risk_dashboard=RiskDashboardSummary(
            total_decisions=1,
            approved_decisions=1,
            rejected_decisions=0,
            kill_switch_active=False,
            latest_risk_tags=["approved"],
            updated_at=now,
        ),
        review_journal=[],
    )


def test_review_daily_from_reports_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports_dir = tmp_path / "reports" / "daily"
    reports_dir.mkdir(parents=True)
    report_file = reports_dir / "2026-10-02.md"
    report_file.write_text(
        "# AlphaBrief daily report 2026-10-02\n\nTest daily report content.\n"
    )

    monkeypatch.setattr("alphabrief_core.paths.daily_reports_dir", lambda: reports_dir)

    result = runner.invoke(review_app, ["daily"])
    assert result.exit_code == 0
    assert "AlphaBrief daily report" in result.output
    assert "Test daily report content" in result.output


def test_review_daily_with_snapshot_file(tmp_path: Path) -> None:
    snap = _make_snapshot("snap_cli_test")
    snap_file = tmp_path / "snapshot.json"
    snap_file.write_text(snap.model_dump_json(indent=2))

    result = runner.invoke(review_app, ["daily", "--snapshot", str(snap_file)])
    assert result.exit_code == 0
    assert "EUR_USD holds steady" in result.output or "Highlights:" in result.output


def test_api_review_reports_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports_dir = tmp_path / "reports" / "daily"
    reports_dir.mkdir(parents=True)
    (reports_dir / "2026-10-02.md").write_text("# Report 2026-10-02")
    (reports_dir / "2026-10-02.json").write_text(
        json.dumps({"summary": "Summary 10-02", "nav": 100000})
    )

    monkeypatch.setattr("alphabrief_core.paths.daily_reports_dir", lambda: reports_dir)

    from alphabrief_api.main import app

    client = TestClient(app)
    resp = client.get("/api/v1/review/reports")
    assert resp.status_code == 200
    data = resp.json()
    assert "reports" in data
    assert len(data["reports"]) == 1
    assert data["reports"][0]["date"] == "2026-10-02"

    detail_resp = client.get("/api/v1/review/reports/2026-10-02")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["date"] == "2026-10-02"
    assert "Report 2026-10-02" in detail["markdown"]
