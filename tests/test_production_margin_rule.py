"""Production margin limits, broker parsing, and durable rule evidence."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alphabrief_core import OrderIntent
from alphabrief_execution.broker.oanda.account_ops import (
    AccountOperationError,
    AccountOpsClient,
)
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.risk_sources import OandaRiskContextSources
from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.gate import RiskGate, RiskLimitConfig
from test_oanda_account_changes import _account_payload

NOW = datetime(2026, 10, 2, 3, tzinfo=UTC)


def _client(payload: dict[str, Any]) -> OandaHttpClient:
    return OandaHttpClient(config=OandaPaperConfig(
        base_url="https://api-fxpractice.oanda.com", timeout_seconds=5,
        max_retries=0, retry_backoff_seconds=0.1,
    ), token="test-token", account_id="test-account",
        http_send=lambda request, timeout: json.dumps({"account": payload}).encode())


def _context(used: Decimal | None, age: int = 0) -> AccountExposureContext:
    return AccountExposureContext(
        current_total_exposure=Decimal(0), cash=Decimal(1000), equity=Decimal(1000),
        margin_used=used, account_id="test", captured_at=NOW-timedelta(seconds=age),
    )


def _gate() -> RiskGate:
    return RiskGate(limits=RiskLimitConfig(
        max_margin_utilization_pct=Decimal("0.30"), margin_warning_pct=Decimal("0.20"),
    ), clock=lambda: NOW)


def _intent(side: str, close: bool = False) -> OrderIntent:
    return OrderIntent.model_validate({
        "intent_id": "margin-test", "source": "model", "symbol": "EUR_USD",
        "side": side, "order_type": "market", "quantity": Decimal(1),
        "rationale": "test", "created_at": NOW, "reduce_only": close,
    })


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("used,approved,warning", [
    ("0", True, False), ("200", True, False), ("200.001", True, True),
    ("300", True, True), ("300.001", False, True), (None, False, False),
])
def test_margin_boundaries_apply_to_long_and_short_entries(
    side: str, used: str | None, approved: bool, warning: bool,
) -> None:
    result = _gate().evaluate(_intent(side), account_context=_context(
        None if used is None else Decimal(used),
    ))
    assert result.approved is approved
    assert ("MARGIN_WARNING" in result.risk_tags) is warning
    assert ("MARGIN" in result.risk_tags) is (not approved)
    assert result.rule_evidence["margin"]["passed"] == str(approved)
    assert "account_id" not in json.dumps(result.rule_evidence)


@pytest.mark.parametrize("age,approved", [(60, True), (61, False), (-1, False)])
def test_margin_account_freshness(age: int, approved: bool) -> None:
    result = _gate().evaluate(
        _intent("sell"), account_context=_context(Decimal(0), age)
    )
    assert result.approved is approved


def test_missing_context_rejects_entries_but_margin_does_not_block_closes() -> None:
    assert not _gate().evaluate(_intent("buy")).approved
    for side in ("buy", "sell"):
        result = _gate().evaluate(_intent(side, close=True))
        assert result.approved and result.rule_evidence == {}
    gate = _gate()
    gate.kill_switch.activate(reason="stop")
    result = gate.evaluate(_intent("sell", close=True))
    assert result.approved and "kill_switch_reduce_only" in result.risk_tags
    entry = gate.evaluate(_intent("sell"))
    assert not entry.approved and "kill_switch" in entry.risk_tags


@pytest.mark.parametrize("value", [Decimal(0), Decimal("1.1"), Decimal("NaN"), 0.3])
def test_invalid_margin_limit_is_rejected(value: Any) -> None:
    with pytest.raises(ValueError):
        RiskLimitConfig(max_margin_utilization_pct=value)


@pytest.mark.parametrize("bad", [None, 1000.0, "NaN", "Infinity", "invalid", "-1"])
def test_native_summary_never_invents_margin_used(bad: object) -> None:
    payload = _account_payload()
    if bad is None:
        del payload["marginUsed"]
    else:
        payload["marginUsed"] = bad
    client = _client(payload)
    with pytest.raises(AccountOperationError):
        AccountOpsClient(client).account_summary()


def test_real_shaped_broker_margin_reaches_both_input_projections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _account_payload()
    client = _client(payload)
    source = OandaRiskContextSources(client, symbols=("EUR_USD",))
    monkeypatch.setattr(source, "fetch_positions", lambda: [])
    monkeypatch.setattr(source, "fetch_pending_orders", lambda: [])
    monkeypatch.setattr(source, "_prices_by_symbol", lambda: {})
    context = source.account_exposure_context()
    facts = source.decision_input_facts("EUR_USD")
    assert context.margin_used == facts.margin_used == Decimal("1000.00")


def test_default_cli_policy_enables_margin_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_cli.cycle_commands import _risk_gate

    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    gate = _risk_gate(("EUR_USD",), nav=Decimal(1000), require_nav=True)
    assert gate.limits.max_margin_utilization_pct == Decimal("0.30")
    assert gate.limits.margin_warning_pct == Decimal("0.20")


def test_margin_rule_evidence_is_durable_before_the_order_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_execution.broker.port import SubmitRequest, SubmitResult
    from alphabrief_risk.decision_store import RiskDecisionStore
    from alphabrief_trader.execution_backend import ExternalPaperExecutionBackend
    from test_ai_trader_execution_backend import _decision, _FakeAdapter
    from test_ai_trader_execution_backend import _intent as execution_intent

    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    evidence = _gate().evaluate(
        _intent("buy"), account_context=_context(Decimal(250)),
    ).rule_evidence
    decision = _decision().model_copy(update={"rule_evidence": evidence})

    class Adapter(_FakeAdapter):
        async def submit(
            self, request: SubmitRequest, *, client_order_id: str,
        ) -> SubmitResult:
            store = RiskDecisionStore(tmp_path / "alphabrief.duckdb")
            try:
                saved = store.get(decision.decision_id)
                assert saved is not None
                assert json.loads(saved.rule_results)["evidence"] == evidence
            finally:
                store.close()
            return await super().submit(request, client_order_id=client_order_id)

    adapter = Adapter()
    ExternalPaperExecutionBackend(adapter).submit(
        execution_intent(), decision, reference_price=Decimal(50),
        now=datetime.now(UTC), estimated_quantity=Decimal(2),
    )
    assert len(adapter.requests) == 1
