"""Tests for Phase 13 Round 2-5: risk_context wiring through CLI/API/PaperBroker/Audit.

Covers:
- R13.2: ``alphabrief risk check`` CLI and ``POST /api/v1/risk/check`` accept
  optional ``risk_context`` payloads.
- R13.3: ``PaperBroker.submit`` blocks when the decision requires human review.
- R13.4: ``ExecutionAuditEntry`` carries risk-context metadata and the
  ``/api/v1/paper/orders`` endpoint + audit log endpoints surface it.
- R13.5: ``alphabrief paper run`` accepts and applies ``risk_context``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import OrderIntent
from alphabrief_execution import (
    ExecutionAuditEntry,
    FillSimulator,
    PaperBroker,
    PaperBrokerError,
    PortfolioState,
)
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


def test_paper_broker_blocks_when_decision_requires_human_review() -> None:
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        fill_simulator=FillSimulator(),
    )
    decision = _gate().evaluate(_intent(), estimated_price=Decimal("100"))
    assert decision.approved is True

    ctx = _negative_context()
    merged = _gate().evaluate(
        _intent(), estimated_price=Decimal("100"), risk_context=ctx
    )
    assert merged.requires_human_review is True
    assert merged.approved is True

    with pytest.raises(PaperBrokerError, match="human review"):
        broker.submit(
            _intent(), merged, reference_price=Decimal("100")
        )

    rejected_events = [
        e for e in broker.audit_log.entries if e.event_type == "order_rejected"
    ]
    assert len(rejected_events) == 1
    assert "auto-execution blocked" in rejected_events[0].message


def test_paper_broker_executes_when_human_review_not_required() -> None:
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        fill_simulator=FillSimulator(),
    )
    decision = _gate().evaluate(_intent(), estimated_price=Decimal("100"))
    result = broker.submit(
        _intent(), decision, reference_price=Decimal("100")
    )
    assert result.order.symbol == "BTC-USD"
    types = [e.event_type for e in broker.audit_log.entries]
    assert "order_created" in types
    assert "fill_created" in types
    assert "portfolio_updated" in types


# ---------------------------------------------------------------------------
# R13.4
# ---------------------------------------------------------------------------


def test_audit_log_records_risk_context_metadata_on_success() -> None:
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        fill_simulator=FillSimulator(),
    )
    ctx = RiskContextDecision(
        requires_human_review=False,
        risk_tags=("macro_high_risk", "suggested_position_reduction"),
        suggested_max_position_multiplier=0.5,
        notes=("n",),
        source_summary_untrusted=True,
        decision_id="rctx_audit_1",
    )
    decision = _gate().evaluate(_intent(), estimated_price=Decimal("100"))
    broker.submit(
        _intent(), decision, reference_price=Decimal("100"), risk_context=ctx
    )

    business_events = [
        e
        for e in broker.audit_log.entries
        if e.event_type
        in (
            "risk_decision_recorded",
            "order_created",
            "fill_created",
            "portfolio_updated",
        )
    ]
    assert len(business_events) >= 4
    for e in business_events:
        assert e.risk_context_decision_id == "rctx_audit_1"
        assert "macro_high_risk" in e.risk_context_tags
        assert e.risk_context_multiplier == 0.5


def test_audit_log_records_risk_context_on_human_review_block() -> None:
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        fill_simulator=FillSimulator(),
    )
    ctx = _negative_context()
    merged = _gate().evaluate(
        _intent(), estimated_price=Decimal("100"), risk_context=ctx
    )

    with pytest.raises(PaperBrokerError):
        broker.submit(
            _intent(),
            merged,
            reference_price=Decimal("100"),
            risk_context=ctx,
        )

    rejected = [
        e for e in broker.audit_log.entries if e.event_type == "order_rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0].risk_context_decision_id == "rctx_test_neg"
    assert "negative_news_context" in rejected[0].risk_context_tags


def test_audit_log_optional_fields_default_to_none_and_empty() -> None:
    entry = ExecutionAuditEntry(
        event_id="audit_1",
        event_type="order_created",
        message="x",
        created_at=NOW,
    )
    assert entry.risk_context_decision_id is None
    assert entry.risk_context_tags == ()
    assert entry.risk_context_multiplier is None


# ---------------------------------------------------------------------------
# R13.2 CLI
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
            "--intent", str(intent_path),
            "--risk-context", json.dumps(ctx.model_dump(mode="json")),
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
    ctx_path.write_text(
        json.dumps(ctx.model_dump(mode="json")), encoding="utf-8"
    )

    result = CliRunner().invoke(
        risk_app,
        [
            "check",
            "--intent", str(intent_path),
            "--risk-context-file", str(ctx_path),
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
            "--intent", str(intent_path),
            "--risk-context", "{}",
            "--risk-context-file", str(intent_path),
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
            "--intent", str(intent_path),
            "--risk-context", "not-json",
        ],
    )
    assert result.exit_code != 0
    assert "invalid JSON" in result.stderr


def test_risk_check_cli_no_context_omits_applied_line(tmp_path: Path) -> None:
    from alphabrief_cli.risk_commands import risk_app
    from typer.testing import CliRunner

    intent_path = tmp_path / "intent.json"
    intent_path.write_text(_intent().model_dump_json(), encoding="utf-8")

    result = CliRunner().invoke(
        risk_app, ["check", "--intent", str(intent_path)]
    )
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


def test_api_paper_orders_blocked_on_human_review() -> None:
    from alphabrief_api.main import app
    from alphabrief_api.routes.paper import _reset_broker
    from alphabrief_api.routes.risk import _reset_risk_gate
    from fastapi.testclient import TestClient

    _reset_risk_gate(_api_test_limits())
    _reset_broker()
    client = TestClient(app)
    ctx = _negative_context()
    resp = client.post(
        "/api/v1/paper/orders",
        json={
            "symbol": "BTC-USD",
            "side": "buy",
            "order_type": "market",
            "quantity": "1",
            "risk_context": json.loads(ctx.model_dump_json()),
        },
    )
    assert resp.status_code == 422
    assert "human review" in resp.json()["detail"].lower()


def test_api_paper_orders_audit_records_risk_context() -> None:
    from alphabrief_api.main import app
    from alphabrief_api.routes.paper import _reset_broker
    from alphabrief_api.routes.risk import _reset_risk_gate
    from fastapi.testclient import TestClient

    _reset_risk_gate(_api_test_limits())
    _reset_broker()
    client = TestClient(app)
    ctx = RiskContextDecision(
        requires_human_review=False,
        risk_tags=("macro_high_risk",),
        suggested_max_position_multiplier=0.5,
        notes=("n",),
        source_summary_untrusted=True,
        decision_id="rctx_persisted",
    )
    resp = client.post(
        "/api/v1/paper/orders",
        json={
            "symbol": "BTC-USD",
            "side": "buy",
            "order_type": "market",
            "quantity": "1",
            "risk_context": json.loads(ctx.model_dump_json()),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["applied_risk_context"] == "rctx_persisted"

    audit = client.get("/api/v1/paper/audit").json()
    entries_with_ctx = [
        e for e in audit["entries"] if e.get("risk_context_decision_id")
    ]
    assert len(entries_with_ctx) >= 1
    assert entries_with_ctx[0]["risk_context_decision_id"] == "rctx_persisted"
    assert "macro_high_risk" in entries_with_ctx[0]["risk_context_tags"]


# ---------------------------------------------------------------------------
# R13.5 — paper run CLI
# ---------------------------------------------------------------------------


def test_paper_run_cli_blocks_on_human_review(tmp_path: Path) -> None:
    import csv as _csv

    from alphabrief_cli.paper_commands import paper_app
    from typer.testing import CliRunner

    csv_path = tmp_path / "data.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = _csv.writer(f)
        writer.writerow(
            ["timestamp", "open", "high", "low", "close", "volume"]
        )
        for i in range(5):
            writer.writerow(
                [f"2026-01-0{i + 1}T00:00:00Z", 100, 101, 99, 100, 1000]
            )

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "strategy_id": "ma_v1",
                "name": "MA",
                "version": "1.0",
                "universe": {"symbols": ["BTC-USD"]},
                "timeframe": "1d",
                "entry": {"condition": "close > sma_20"},
                "exit": {"condition": "close < sma_20"},
                "risk": {"max_position_pct": "0.1"},
                "costs": {"fee_bps": 5, "slippage_bps": 10},
                "evaluation": {
                    "train_period": {
                        "start": "2025-01-01",
                        "end": "2025-12-31",
                    },
                    "test_period": {
                        "start": "2026-01-01",
                        "end": "2026-12-31",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    ctx = _negative_context()
    result = CliRunner().invoke(
        paper_app,
        [
            "run",
            "--data", str(csv_path),
            "--spec", str(spec_path),
            "--price", "100",
            "--risk-context", json.dumps(ctx.model_dump(mode="json")),
        ],
    )
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "human review" in combined.lower()


def test_paper_run_cli_with_neutral_context_executes(tmp_path: Path) -> None:
    import csv as _csv

    from alphabrief_cli.paper_commands import paper_app
    from typer.testing import CliRunner

    csv_path = tmp_path / "data.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = _csv.writer(f)
        writer.writerow(
            ["timestamp", "open", "high", "low", "close", "volume"]
        )
        for i in range(5):
            writer.writerow(
                [f"2026-01-0{i + 1}T00:00:00Z", 100, 101, 99, 100, 1000]
            )

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "strategy_id": "ma_v1",
                "name": "MA",
                "version": "1.0",
                "universe": {"symbols": ["BTC-USD"]},
                "timeframe": "1d",
                "entry": {"condition": "close > sma_20"},
                "exit": {"condition": "close < sma_20"},
                "risk": {"max_position_pct": "0.1"},
                "costs": {"fee_bps": 5, "slippage_bps": 10},
                "evaluation": {
                    "train_period": {
                        "start": "2025-01-01",
                        "end": "2025-12-31",
                    },
                    "test_period": {
                        "start": "2026-01-01",
                        "end": "2026-12-31",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    neutral_ctx = RiskContextDecision(
        requires_human_review=False,
        risk_tags=(),
        suggested_max_position_multiplier=1.0,
        notes=(),
        source_summary_untrusted=True,
        decision_id="rctx_neutral",
    )
    result = CliRunner().invoke(
        paper_app,
        [
            "run",
            "--data", str(csv_path),
            "--spec", str(spec_path),
            "--price", "100",
            "--risk-context", json.dumps(neutral_ctx.model_dump(mode="json")),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Applied Risk Context: rctx_neutral" in result.stdout
