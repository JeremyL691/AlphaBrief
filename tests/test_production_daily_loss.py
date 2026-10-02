"""Broker-complete daily P&L, both entry sides, and restart-safe rule 10."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alphabrief_core import OrderIntent
from alphabrief_execution.broker.oanda.risk_sources import OandaRiskContextSources
from alphabrief_execution.broker.oanda.transaction_ops import (
    TransactionOperationError,
    TransactionOpsClient,
)
from alphabrief_risk import AccountExposureContext, RiskGate, RiskLimitConfig
from alphabrief_risk.loss_state import LossStateStore

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
D = Decimal


def context(**changes: Any) -> AccountExposureContext:
    facts: dict[str, Any] = dict(
        account_id="test",
        cash=D(1000),
        equity=D(1000),
        captured_at=NOW,
        current_total_exposure=D(0),
        day_realized_pnl=D(-4),
        day_unrealized_pnl=D(-5),
        daily_loss_captured_at=NOW,
        daily_loss_blocked=False,
    )
    facts.update(changes)
    return AccountExposureContext(**facts)


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize(
    "realized,unrealized,approved",
    [
        ("-4", "-5", True),
        ("-5", "-5", False),
        ("-6", "-5", False),
        ("10", "-15", True),
        ("-15", "10", True),
    ],
)
def test_current_nav_loss_boundary(
    side: str, realized: str, unrealized: str, approved: bool
) -> None:
    gate = RiskGate(
        limits=RiskLimitConfig(max_daily_loss_pct=D(".01")), clock=lambda: NOW
    )
    intent = OrderIntent.model_validate(
        dict(
            intent_id="test",
            source="manual",
            symbol="EUR_USD",
            side=side,
            order_type="market",
            quantity=D(1),
            rationale="test",
            created_at=NOW,
        )
    )
    decision = gate.evaluate(
        intent,
        estimated_price=D(1),
        account_context=context(
            day_realized_pnl=D(realized),
            day_unrealized_pnl=D(unrealized),
        ),
    )
    assert decision.approved is approved
    assert ("DAILY_LOSS" in decision.risk_tags) is (not approved)
    assert decision.rule_evidence["daily_loss"]["realized_pnl"] == realized


@pytest.mark.parametrize(
    "changes",
    [
        {"day_realized_pnl": None},
        {"day_unrealized_pnl": None},
        {"equity": None},
        {"equity": D(0)},
        {"daily_loss_blocked": None},
        {"daily_loss_blocked": True},
        {"daily_loss_error": "network"},
        {"daily_loss_captured_at": None},
        {"daily_loss_captured_at": NOW - timedelta(seconds=61)},
        {"daily_loss_captured_at": NOW + timedelta(seconds=1)},
        {"daily_loss_captured_at": NOW - timedelta(days=1)},
    ],
)
def test_incomplete_or_latched_loss_blocks(changes: dict[str, Any]) -> None:
    gate = RiskGate(
        limits=RiskLimitConfig(max_daily_loss_pct=D(".01")), clock=lambda: NOW
    )
    intent = OrderIntent.model_validate(
        dict(
            intent_id="test",
            source="manual",
            symbol="EUR_USD",
            side="sell",
            order_type="market",
            quantity=D(1),
            rationale="test",
            created_at=NOW,
        )
    )
    decision = gate.evaluate(
        intent, estimated_price=D(1), account_context=context(**changes)
    )
    assert not decision.approved
    assert "DAILY_LOSS" in decision.risk_tags


def test_latch_survives_recovery_restart_and_expires_on_next_utc_day(
    tmp_path: Path,
) -> None:
    database = tmp_path / "loss.duckdb"
    store = LossStateStore(database)
    assert store.observe_daily_loss(
        "test",
        observed_at=NOW,
        realized_pnl=D(-5),
        unrealized_pnl=D(-5),
        nav=D(1000),
        ceiling_pct=D(".01"),
    )
    store.close()
    restarted = LossStateStore(database)
    try:
        assert restarted.observe_daily_loss(
            "test",
            observed_at=NOW,
            realized_pnl=D(20),
            unrealized_pnl=D(0),
            nav=D(1000),
            ceiling_pct=D(".01"),
        )
        assert not restarted.observe_daily_loss(
            "other",
            observed_at=NOW,
            realized_pnl=D(0),
            unrealized_pnl=D(0),
            nav=D(1000),
            ceiling_pct=D(".01"),
        )
        assert not restarted.observe_daily_loss(
            "test",
            observed_at=NOW + timedelta(days=1),
            realized_pnl=D(0),
            unrealized_pnl=D(0),
            nav=D(1000),
            ceiling_pct=D(".01"),
        )
        assert restarted.daily_loss_blocked("test", NOW.date())
    finally:
        restarted.close()


class Client:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = [
            dict(
                id=str(i),
                type="ORDER_FILL",
                time=NOW.isoformat(),
                instrument="EUR_USD",
                pl="-2",
                financing="-.1",
                commission=".2",
            )
            for i in (10, 11, 12)
        ]
        self.pages = [self.page(10, 11), self.page(12, 12)]
        self.count = 3
        self.watermark = "12"
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def account_path(self, suffix: str) -> str:
        return "/v3/accounts/test" + suffix

    def page(self, first: int, last: int) -> str:
        return "https://api-fxpractice.oanda.com" + self.account_path(
            f"/transactions/idrange?from={first}&to={last}"
        )

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        assert method == "GET"
        params = kwargs.get("params", {})
        self.calls.append((path, params))
        if path.endswith("/summary"):
            return SimpleNamespace(
                json_body={
                    "account": dict(
                        id="test",
                        currency="USD",
                        balance="1000",
                        NAV="1000",
                        unrealizedPL="-4",
                        marginUsed="0",
                        marginAvailable="1000",
                        lastTransactionID="12",
                    )
                }
            )
        if path.endswith("/transactions"):
            return SimpleNamespace(
                json_body=dict(
                    count=self.count, pages=self.pages, lastTransactionID=self.watermark
                )
            )
        assert path.endswith("/transactions/idrange")
        first, last = int(params["from"]), int(params["to"])
        return SimpleNamespace(
            json_body={
                "transactions": [r for r in self.rows if first <= int(r["id"]) <= last]
            }
        )


def test_time_query_reads_every_page() -> None:
    client: Any = Client()
    result = TransactionOpsClient(client).transactions_between(NOW.replace(hour=0), NOW)
    assert [t.transaction_id for t in result.transactions] == ["10", "11", "12"]
    assert result.last_transaction_id == "12"
    assert len(client.calls) == 3
    assert client.calls[0][1]["from"] == NOW.replace(hour=0).isoformat()


@pytest.mark.parametrize(
    "failure",
    [
        "count",
        "missing",
        "duplicate_page",
        "foreign",
        "old_time",
        "missing_time",
        "float",
        "nonfinite",
    ],
)
def test_partial_or_invalid_day_history_never_becomes_zero(failure: str) -> None:
    client: Any = Client()
    if failure == "count":
        client.count = 4
    elif failure == "missing":
        client.rows.pop()
    elif failure == "duplicate_page":
        client.pages.append(client.pages[0])
    elif failure == "foreign":
        client.pages[0] = client.pages[0].replace(
            "api-fxpractice.oanda.com", "example.com"
        )
    elif failure == "old_time":
        client.rows[0]["time"] = (NOW - timedelta(days=1)).isoformat()
    elif failure == "missing_time":
        client.rows[0].pop("time")
    elif failure == "float":
        client.rows[0]["pl"] = -2.0
    else:
        client.rows[0]["pl"] = "NaN"
    with pytest.raises((TransactionOperationError, ValueError)):
        TransactionOpsClient(client).transactions_between(NOW.replace(hour=0), NOW)


@pytest.mark.parametrize("failure", [None, "watermark", "fill_pl"])
def test_native_context_uses_full_day_net_pnl(
    monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    client: Any = Client()
    if failure == "watermark":
        client.watermark = "13"
    if failure == "fill_pl":
        client.rows[0].pop("pl")
    source = OandaRiskContextSources(client, symbols=())
    monkeypatch.setattr(source, "fetch_positions", lambda: [])
    monkeypatch.setattr(source, "fetch_pending_orders", lambda: [])
    monkeypatch.setattr(source, "_prices_by_symbol", lambda: {})
    monkeypatch.setattr(source, "fetch_reconciliation_state", lambda: "clean")
    facts = source.account_exposure_context(now=NOW, include_daily_loss=True)
    if failure is None:
        assert facts.day_realized_pnl == D("-6.9")
        assert facts.day_unrealized_pnl == D(-4)
        assert facts.daily_loss_captured_at == NOW
        assert facts.daily_loss_error is None
    else:
        assert facts.day_realized_pnl is None
        assert facts.daily_loss_blocked is None
        assert facts.daily_loss_error is not None
