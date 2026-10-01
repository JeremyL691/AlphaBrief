"""Tests for the daily report (PROJECT_GUIDE 5.12)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from alphabrief_trader.daily_report import (
    DailyReportData,
    render_markdown,
    write_daily_report,
)

NOW = datetime(2026, 10, 1, 21, 30, tzinfo=UTC)


def _data(**overrides: object) -> DailyReportData:
    payload: dict[str, object] = {
        "trading_day": "2026-10-01",
        "generated_at": NOW,
        "cycles": [
            {
                "cycle_id": "aic_1",
                "trading_day": "2026-10-01",
                "outcome": "blocked_risk_gate",
                "plan_count": 1,
                "attempt_count": 1,
                "executed_count": 0,
                "blocked_count": 1,
                "summary": "outcome=blocked_risk_gate",
                "created_at": "2026-10-01T12:00:00+00:00",
            }
        ],
        "attempts": [
            {
                "cycle_id": "aic_1",
                "intent_id": "ai_1",
                "outcome": "blocked_risk_gate",
                "filled": False,
                "broker_order_id": None,
                "reason": "data quality check failed",
                "risk_tags": ["data_quality", "DAILY_INTENT_CAP"],
            },
            {
                "cycle_id": "aic_1",
                "intent_id": "ai_2",
                "outcome": "executed",
                "filled": True,
                "broker_order_id": "4",
                "reason": "approved",
                "risk_tags": ["approved"],
            },
        ],
        "model_calls": [
            {
                "provider": "chatgpt_plan",
                "status": "succeeded",
                "input_tokens": 100,
                "output_tokens": 20,
                "cost_estimate": None,
            },
            {
                "provider": "chatgpt_plan",
                "status": "failed",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_estimate": None,
            },
        ],
        "shadow_decisions": [{"benchmark": "momentum"}],
        "shadow_stats": {
            "4h": [
                {
                    "benchmark": "momentum",
                    "samples": 1,
                    "mean_return_pct": "0.5",
                    "win_rate": "1",
                    "ci_low_pct": "0.5",
                    "ci_high_pct": "0.5",
                    "caveat": "14 days is not enough",
                }
            ]
        },
        "reconciliation": {"snapshots": 2, "clean": 2, "unclean": 0},
        "freezes": [],
        "equity": {"latest_equity": "100000"},
        "market_freshness": [
            {
                "symbol": "EUR_USD",
                "latest_bar_at": "2026-10-01T19:45:00+00:00",
                "data_version": "oanda-candles-v1:M:M15",
            }
        ],
    }
    payload.update(overrides)
    return DailyReportData(**payload)  # type: ignore[arg-type]


class TestDerivedViews:
    def test_rejection_counts_skip_executed_attempts(self) -> None:
        counts = _data().rejection_counts()

        assert counts == {"DAILY_INTENT_CAP": 1, "data_quality": 1}
        assert "approved" not in counts

    def test_execution_counts_cover_every_outcome(self) -> None:
        assert _data().execution_counts() == {
            "blocked_risk_gate": 1,
            "executed": 1,
        }

    def test_model_usage_sums_tokens_and_failures(self) -> None:
        usage = _data().model_usage()

        assert usage["chatgpt_plan"]["calls"] == 2
        assert usage["chatgpt_plan"]["failed"] == 1
        assert usage["chatgpt_plan"]["input_tokens"] == 100
        assert usage["chatgpt_plan"]["cost_usd"] == "0"


class TestRendering:
    def test_markdown_contains_every_section(self) -> None:
        markdown = render_markdown(_data())

        for heading in (
            "# AlphaBrief daily report — 2026-10-01",
            "## Cycles",
            "## Orders, fills and closes",
            "## Risk rejections",
            "## P&L, NAV and drawdown",
            "## Reconciliation and freezes",
            "## Model usage",
            "## Data freshness",
            "## Shadow evaluation",
            "## Doctor",
        ):
            assert heading in markdown
        assert "aic_1" in markdown
        assert "ai_2" in markdown
        assert "oanda-candles-v1:M:M15" in markdown
        # The doctor section states plainly that it is not available yet.
        assert "Not available until S5" in markdown

    def test_empty_sections_say_so_instead_of_inventing_numbers(self) -> None:
        markdown = render_markdown(
            _data(cycles=[], attempts=[], model_calls=[], market_freshness=[])
        )

        assert "_no rows_" in markdown
        assert "Decisions recorded this day: 1" in markdown

    def test_payload_is_json_serializable(self) -> None:
        payload = _data().to_payload()

        encoded = json.dumps(payload, default=str)
        assert "risk_rejections" in encoded
        assert payload["shadow"]["stats"]["4h"][0]["samples"] == 1


class TestWriting:
    def test_both_files_are_written(self, tmp_path: Path) -> None:
        markdown_path, json_path = write_daily_report(_data(), directory=tmp_path)

        assert markdown_path.name == "2026-10-01.md"
        assert json_path.name == "2026-10-01.json"
        assert "AlphaBrief daily report" in markdown_path.read_text()
        payload = json.loads(json_path.read_text())
        assert payload["trading_day"] == "2026-10-01"
        assert payload["execution"]["counts"]["executed"] == 1
