"""Tests for soak report generator (PROJECT_GUIDE S11)."""


from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from alphabrief_trader.soak_evaluator import SoakStatus
from alphabrief_trader.soak_report import (
    SoakReportData,
    generate_soak_report_data,
    render_soak_markdown,
    write_soak_report,
)
from alphabrief_trader.soak_store import SoakStore


def _sample_data() -> SoakReportData:
    status = SoakStatus(
        soak_started=True,
        run_index=0,
        started_at=datetime(2026, 10, 4, 4, 0, tzinfo=UTC),
        state="active",
        qualified_days=1,
        extension_days=0,
        target_days=14,
        is_complete=False,
        days=[],
        extensions=[],
        resets=[],
    )
    return SoakReportData(
        status=status,
        generated_at=datetime(2026, 10, 5, 4, 0, tzinfo=UTC),
        masked_account_id="...0001",
        equity_metrics={
            "start_nav": "100000.00",
            "end_nav": "100150.25",
            "realized_pnl": "150.25",
            "max_drawdown_pct": "0.45%",
            "total_trades": 2,
            "win_rate_pct": "100.00%",
        },
        order_metrics={
            "submitted": 2,
            "filled": 2,
            "rejected": 0,
            "submit_unknown_resolved": 0,
        },
        risk_metrics={
            "rejections_by_rule": {"spread_filter": 1},
            "freezes": [],
        },
        model_metrics={
            "by_channel": {
                "chatgpt_plan": {
                    "calls": 10,
                    "failed": 0,
                    "input_tokens": 12000,
                    "output_tokens": 800,
                    "cost_usd": "0.00",
                }
            }
        },
        shadow_metrics={
            "scoreboard": [
                {
                    "benchmark": "momentum",
                    "horizon": "4h",
                    "samples": 5,
                    "mean_return_pct": "0.15",
                    "ci_low_pct": "-0.05",
                    "ci_high_pct": "0.35",
                    "win_rate": 0.6,
                    "caveat": "Sample size too small to infer edge",
                }
            ]
        },
        hotfixes=[],
        version="1.0.0-rc.1",
    )


def test_render_soak_markdown_headings_and_structure() -> None:
    data = _sample_data()
    md = render_soak_markdown(data)

    expected_sections = [
        "# AlphaBrief v1.0.0-rc.1 Soak Report",
        "## Period & Qualification",
        "## Runtime & Operations",
        "## Account & Performance",
        "## Orders & Execution",
        "## Risk Gate & Safety",
        "## Model Gateways & Costs",
        "## Shadow Evaluation",
        "## Safety Invariants Verification",
        "## Known Limitations",
        "## Disclaimer",
    ]
    for section in expected_sections:
        assert section in md

    # Check key facts in output
    assert "`...0001`" in md
    assert "1 / 14" in md
    assert "100150.25" in md
    assert "chatgpt_plan" in md
    assert "momentum" in md
    assert "Sample size too small to infer edge" in md
    assert "Duplicate orders across all runs" in md
    assert "PASSED" in md


def test_write_soak_report_custom_and_final(tmp_path: Path) -> None:
    data = _sample_data()

    # Custom path
    custom_md = tmp_path / "custom-report.md"
    md_path, json_path = write_soak_report(data, out_file=custom_md, final=False)
    assert md_path == custom_md
    assert json_path == tmp_path / "custom-report.json"
    assert custom_md.is_file()
    assert json_path.is_file()
    assert "# AlphaBrief v1.0.0-rc.1 Soak Report" in custom_md.read_text(
        encoding="utf-8"
    )

    # Final mode writes to repo reports directory
    with patch("alphabrief_trader.soak_report.project_root", return_value=tmp_path):
        final_md, final_json = write_soak_report(data, final=True)
        assert final_md == tmp_path / "reports" / f"soak-report-v{data.version}.md"
        assert final_json == tmp_path / "reports" / f"soak-report-v{data.version}.json"
        assert final_md.is_file()
        assert final_json.is_file()


def test_generate_soak_report_data_from_db(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"
    soak = SoakStore(db_path=db)
    soak.start_soak()
    soak.close()

    report_data = generate_soak_report_data(db_path=db)
    assert report_data.status.soak_started
    assert report_data.status.target_days == 14
    assert report_data.version is not None
    assert isinstance(report_data.order_metrics, dict)
    assert isinstance(report_data.risk_metrics, dict)
