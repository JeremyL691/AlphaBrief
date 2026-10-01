"""Risk-context wiring through the risk CLI and API.

Covers R13.2: ``alphabrief risk check`` and ``POST /api/v1/risk/check``
accept optional ``risk_context`` payloads and apply them tighten-only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_core import OrderIntent
from alphabrief_risk import (
    RiskContextDecision,
    RiskGate,
    RiskLimitConfig,
)

NOW = datetime(2026, 6, 17, 10, 0, tzinfo=UTC)


def _intent(**overrides: object) -> OrderIntent:
    payload: dict[str, object] = {
        "intent_id": "intent_1",
        "source": "manual",
        "symbol": "BTC-USD",
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("1"),
        "rationale": "r13 test",
        "created_at": NOW,
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


def _gate() -> RiskGate:
    return RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True,
            symbol_allowlist=frozenset({"BTC-USD"}),
            max_order_quantity=Decimal("10"),
        ),
        clock=lambda: NOW,
    )


def _api_test_limits() -> RiskLimitConfig:
    """Legacy-compatible limits for tests that isolate context wiring."""

    return RiskLimitConfig(
        trading_enabled=True,
        symbol_allowlist=frozenset({"BTC-USD"}),
        max_order_quantity=Decimal("10"),
        max_order_value=Decimal("1000"),
    )


def _isolate_market_data_store(tmp_path: Path) -> None:
    """Point the MarketDataStore singleton at a tmp dir (no env leakage).

    R21.1: the paper order route resolves a mark price from stored bars,
    so API-level paper tests must seed BTC-USD bars in an isolated
    DuckDB before submitting. Sets ``ALPHABRIEF_DATA_DIR`` and closes the
    process-wide store singleton so the next access rebuilds it at the
    new path.
    """
    import os

    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    from alphabrief_api.routes.data import _close_store

    _close_store()


def _load_btc_bars(client: object, tmp_path: Path) -> None:
    """Load a minimal BTC-USD bar so the paper route can resolve a mark.

    R21.1: the paper route fails closed without stored bars. These r13
    tests exercise risk_context wiring, not pricing, so the close matches
    the historical $100 assumption the tests were written against.
    """
    csv_path = tmp_path / "btc.csv"
    csv_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-06-17T09:30:00,100.0,105.0,98.0,100.0,1.0\n",
        encoding="utf-8",
    )
    resp = client.post(  # type: ignore[attr-defined]
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "BTC-USD", "source": "test"},
    )
    assert resp.status_code == 201, resp.text


def _negative_context() -> RiskContextDecision:
    return RiskContextDecision(
        requires_human_review=True,
        risk_tags=("negative_news_context", "requires_human_review"),
        suggested_max_position_multiplier=1.0,
        notes=("n",),
        source_summary_untrusted=True,
        decision_id="rctx_test_neg",
    )


# ---------------------------------------------------------------------------
# R13.3
# ---------------------------------------------------------------------------


def test_risk_check_cli_accepts_inline_risk_context(tmp_path: Path) -> None:
    from alphabrief_cli.risk_commands import risk_app
    from typer.testing import CliRunner

    intent_path = tmp_path / "intent.json"
    intent_path.write_text(_intent().model_dump_json(), encoding="utf-8")

    ctx = _negative_context()
    result = CliRunner().invoke(
        risk_app,
        [
            "check",
            "--intent",
            str(intent_path),
            "--risk-context",
            json.dumps(ctx.model_dump(mode="json")),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "approved: True" in result.stdout
    assert "requires_human_review: True" in result.stdout
    assert "applied_risk_context: rctx_test_neg" in result.stdout
    assert "negative_news_context" in result.stdout


def test_risk_check_cli_accepts_risk_context_file(tmp_path: Path) -> None:
    from alphabrief_cli.risk_commands import risk_app
    from typer.testing import CliRunner

    intent_path = tmp_path / "intent.json"
    intent_path.write_text(_intent().model_dump_json(), encoding="utf-8")
    ctx_path = tmp_path / "ctx.json"
    ctx = _negative_context()
    ctx_path.write_text(json.dumps(ctx.model_dump(mode="json")), encoding="utf-8")

    result = CliRunner().invoke(
        risk_app,
        [
            "check",
            "--intent",
            str(intent_path),
            "--risk-context-file",
            str(ctx_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "applied_risk_context: rctx_test_neg" in result.stdout


def test_risk_check_cli_rejects_both_risk_context_options(tmp_path: Path) -> None:
    from alphabrief_cli.risk_commands import risk_app
    from typer.testing import CliRunner

    intent_path = tmp_path / "intent.json"
    intent_path.write_text(_intent().model_dump_json(), encoding="utf-8")

    result = CliRunner().invoke(
        risk_app,
        [
            "check",
            "--intent",
            str(intent_path),
            "--risk-context",
            "{}",
            "--risk-context-file",
            str(intent_path),
        ],
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.stderr


def test_risk_check_cli_rejects_invalid_risk_context_json(tmp_path: Path) -> None:
    from alphabrief_cli.risk_commands import risk_app
    from typer.testing import CliRunner

    intent_path = tmp_path / "intent.json"
    intent_path.write_text(_intent().model_dump_json(), encoding="utf-8")

    result = CliRunner().invoke(
        risk_app,
        [
            "check",
            "--intent",
            str(intent_path),
            "--risk-context",
            "not-json",
        ],
    )
    assert result.exit_code != 0
    assert "invalid JSON" in result.stderr


def test_risk_check_cli_no_context_omits_applied_line(tmp_path: Path) -> None:
    from alphabrief_cli.risk_commands import risk_app
    from typer.testing import CliRunner

    intent_path = tmp_path / "intent.json"
    intent_path.write_text(_intent().model_dump_json(), encoding="utf-8")

    result = CliRunner().invoke(risk_app, ["check", "--intent", str(intent_path)])
    assert result.exit_code == 0, result.stdout
    assert "applied_risk_context" not in result.stdout


# ---------------------------------------------------------------------------
# R13.2 API
# ---------------------------------------------------------------------------


def test_api_risk_check_accepts_risk_context() -> None:
    from alphabrief_api.main import app
    from alphabrief_api.routes.risk import _reset_risk_gate
    from fastapi.testclient import TestClient

    _reset_risk_gate(_api_test_limits())
    client = TestClient(app)
    ctx = _negative_context()
    resp = client.post(
        "/api/v1/risk/check",
        json={
            "intent": json.loads(_intent().model_dump_json()),
            "estimated_price": "100",
            "risk_context": json.loads(ctx.model_dump_json()),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["approved"] is True
    assert body["requires_human_review"] is True
    assert body["applied_risk_context"] == "rctx_test_neg"
    assert "negative_news_context" in body["risk_tags"]


def test_api_risk_check_works_without_risk_context() -> None:
    from alphabrief_api.main import app
    from alphabrief_api.routes.risk import _reset_risk_gate
    from fastapi.testclient import TestClient

    _reset_risk_gate(_api_test_limits())
    client = TestClient(app)
    resp = client.post(
        "/api/v1/risk/check",
        json={
            "intent": json.loads(_intent().model_dump_json()),
            "estimated_price": "100",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied_risk_context"] is None
    assert body["approved"] is True
