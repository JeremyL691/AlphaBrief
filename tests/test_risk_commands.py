"""Tests for the risk CLI commands.

The risk CLI is **read-only**: it never modifies risk limits, never
places orders, and never writes to any persistent store. The
``context`` subcommand must only emit audit-friendly JSON that
mirrors what the ``/api/v1/risk/context`` endpoint would surface
when given the same input.
"""

from __future__ import annotations

import json
from pathlib import Path

from alphabrief_cli.risk_commands import risk_app
from typer.testing import CliRunner

runner = CliRunner()


def _negative_headlines_payload() -> list[dict[str, object]]:
    return [
        {
            "headline_id": "h_cli_1",
            "published_at": "2026-06-14T09:00:00+00:00",
            "symbols": ["AAPL"],
            "category": "earnings",
            "source": "unit-test",
            "title": "AAPL faces lawsuit",
            "sentiment": "negative",
            "data_version": "news-v1",
        },
        {
            "headline_id": "h_cli_2",
            "published_at": "2026-06-14T10:00:00+00:00",
            "symbols": ["AAPL"],
            "category": "earnings",
            "source": "unit-test",
            "title": "AAPL misses estimates",
            "sentiment": "negative",
            "data_version": "news-v1",
        },
    ]


def _high_macro_payload(count: int = 6) -> list[dict[str, object]]:
    return [
        {
            "indicator_id": f"fred:I{i}",
            "name": f"Indicator {i}",
            "country": "US",
            "released_at": "2026-06-14T09:00:00+00:00",
            "period": "2026-05",
            "value": "1",
            "unit": "index",
            "source": "unit-test",
            "data_version": "macro-v1",
        }
        for i in range(count)
    ]


def test_risk_status_prints_placeholder() -> None:
    result = runner.invoke(risk_app, ["status"])

    assert result.exit_code == 0
    # ponytail: ``risk status`` now reports real RiskGate / KillSwitch
    # state, not a placeholder string. The output is JSON with the
    # expected shape.
    payload = json.loads(result.output)
    assert payload["trading_enabled"] is True
    assert payload["live_trading_enabled"] is False
    assert payload["kill_switch_active"] is False


# ---------------------------------------------------------------------------
# Phase 21 R21.x — risk check CLI flags for the new account-context fields
# ---------------------------------------------------------------------------


def _intent_payload(tmp_path: Path) -> Path:
    intent_path = tmp_path / "intent.json"
    intent_path.write_text(
        json.dumps(
            {
                "intent_id": "intent_cli_r21",
                "source": "manual",
                "symbol": "SPY",
                "side": "buy",
                "order_type": "market",
                "quantity": "1",
                "rationale": "r21 cli check",
                "created_at": "2026-06-23T10:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return intent_path


def test_risk_check_help_lists_phase21_flags() -> None:
    """The Phase 21 R21.x flags must be present on ``risk check --help``
    so operators discover them."""
    result = runner.invoke(risk_app, ["check", "--help"])
    assert result.exit_code == 0
    for flag in (
        "--equity",
        "--reference-mark-prices",
        "--equity-hwm",
        "--day-start-equity",
        "--day-realized-pnl",
    ):
        assert flag in result.output, f"missing flag {flag} in risk check --help"


def test_risk_check_accepts_equity_flag(tmp_path: Path) -> None:
    """Passing ``--equity`` alone must not error (the field is
    forwarded into AccountExposureContext and reaches the gate)."""
    intent_path = _intent_payload(tmp_path)
    result = runner.invoke(
        risk_app,
        ["check", "--intent", str(intent_path), "--equity", "1000"],
    )
    assert result.exit_code == 0
    assert "approved: True" in result.output


def test_risk_check_accepts_reference_mark_prices_json(tmp_path: Path) -> None:
    """``--reference-mark-prices`` takes a JSON object of symbol→price."""
    intent_path = _intent_payload(tmp_path)
    result = runner.invoke(
        risk_app,
        [
            "check",
            "--intent",
            str(intent_path),
            "--reference-mark-prices",
            '{"SPY": "100"}',
        ],
    )
    assert result.exit_code == 0


def test_risk_check_rejects_invalid_mark_prices_json(tmp_path: Path) -> None:
    intent_path = _intent_payload(tmp_path)
    result = runner.invoke(
        risk_app,
        [
            "check",
            "--intent",
            str(intent_path),
            "--reference-mark-prices",
            "not json",
        ],
    )
    assert result.exit_code == 1
    assert "invalid JSON" in result.output


def test_risk_check_accepts_hwm_and_day_start(tmp_path: Path) -> None:
    """The drawdown + daily-loss rules' required inputs can be
    supplied via the new flags."""
    intent_path = _intent_payload(tmp_path)
    result = runner.invoke(
        risk_app,
        [
            "check",
            "--intent",
            str(intent_path),
            "--equity",
            "950",
            "--equity-hwm",
            "1000",
            "--day-start-equity",
            "1000",
        ],
    )
    assert result.exit_code == 0


def test_risk_check_rejects_invalid_decimal_flag(tmp_path: Path) -> None:
    intent_path = _intent_payload(tmp_path)
    result = runner.invoke(
        risk_app,
        ["check", "--intent", str(intent_path), "--equity", "not-a-number"],
    )
    assert result.exit_code == 1
    assert "invalid decimal" in result.output


def test_risk_context_with_no_inputs_returns_neutral_decision() -> None:
    result = runner.invoke(risk_app, ["context"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["headline_count"] == 0
    assert payload["summary"]["untrusted"] is True
    assert payload["decision"]["requires_human_review"] is False
    assert payload["decision"]["risk_tags"] == []
    assert payload["decision"]["suggested_max_position_multiplier"] == 1.0
    assert payload["decision"]["source_summary_untrusted"] is True
    assert payload["decision"]["decision_id"] == "rctx_cli"


def test_risk_context_with_negative_news_flips_human_review(
    tmp_path: Path,
) -> None:
    headlines_path = tmp_path / "headlines.json"
    headlines_path.write_text(
        json.dumps(_negative_headlines_payload()),
        encoding="utf-8",
    )

    result = runner.invoke(
        risk_app,
        [
            "context",
            "--headlines",
            str(headlines_path),
            "--decision-id",
            "rctx_cli_neg",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["headline_count"] == 2
    assert payload["summary"]["negative_count"] == 2
    assert payload["decision"]["requires_human_review"] is True
    assert "negative_news_context" in payload["decision"]["risk_tags"]
    assert "requires_human_review" in payload["decision"]["risk_tags"]
    assert payload["decision"]["decision_id"] == "rctx_cli_neg"


def test_risk_context_with_high_macro_suggests_position_reduction(
    tmp_path: Path,
) -> None:
    indicators_path = tmp_path / "indicators.json"
    indicators_path.write_text(
        json.dumps(_high_macro_payload(count=6)),
        encoding="utf-8",
    )

    result = runner.invoke(
        risk_app,
        [
            "context",
            "--indicators",
            str(indicators_path),
            "--decision-id",
            "rctx_cli_macro",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["decision"]["suggested_max_position_multiplier"] == 0.5
    assert "macro_high_risk" in payload["decision"]["risk_tags"]
    assert "suggested_position_reduction" in payload["decision"]["risk_tags"]


def test_risk_context_with_single_macro_indicator_does_not_trigger(
    tmp_path: Path,
) -> None:
    indicators_path = tmp_path / "indicators.json"
    indicators_path.write_text(
        json.dumps(_high_macro_payload(count=1)),
        encoding="utf-8",
    )

    result = runner.invoke(
        risk_app,
        [
            "context",
            "--indicators",
            str(indicators_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "macro_high_risk" not in payload["decision"]["risk_tags"]
    assert payload["decision"]["suggested_max_position_multiplier"] == 1.0


def test_risk_context_rejects_invalid_headlines_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not a json list", encoding="utf-8")

    result = runner.invoke(
        risk_app,
        ["context", "--headlines", str(bad)],
    )

    assert result.exit_code != 0


def test_risk_context_rejects_invalid_indicators_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"oops": "missing fields"}]), encoding="utf-8")

    result = runner.invoke(
        risk_app,
        ["context", "--indicators", str(bad)],
    )

    assert result.exit_code != 0


def test_risk_context_does_not_emit_api_keys_or_prompts() -> None:
    """Security: the context command must never echo secrets or raw
    prompts in its output. Only audit metadata is allowed."""

    result = runner.invoke(risk_app, ["context"])

    assert result.exit_code == 0
    assert "api_key" not in result.output.lower()
    assert "prompt" not in result.output.lower()
    assert "secret" not in result.output.lower()
