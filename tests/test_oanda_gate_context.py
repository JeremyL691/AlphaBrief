"""Risk context uses the requested symbol and original broker quote time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from alphabrief_execution.broker.oanda import risk_sources as module
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import DEFAULT_BASE_URL, OandaPaperConfig
from alphabrief_execution.broker.oanda.risk_sources import OandaRiskContextSources

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def price(symbol: str, *, age: int, tradeable: bool) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol, bids=[SimpleNamespace(price=Decimal("1.1"))],
        asks=[SimpleNamespace(price=Decimal("1.1002"))],
        broker_time=NOW - timedelta(seconds=age), tradeable=tradeable,
        conversion_factor=Decimal("1"),
    )


def source(monkeypatch: pytest.MonkeyPatch) -> OandaRiskContextSources:
    client = OandaHttpClient(config=OandaPaperConfig(
        base_url=DEFAULT_BASE_URL, timeout_seconds=1, max_retries=0,
        retry_backoff_seconds=0.01,
    ), token="test-token", account_id="test-account")
    sources = OandaRiskContextSources(client, symbols=("EUR_USD", "GBP_USD"))

    class AccountOps:
        def __init__(self, client: OandaHttpClient) -> None:
            pass

        def account_summary(self, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                balance=Decimal("1000"), nav=Decimal("1000"),
                account_id="test-account", open_position_count=0,
            )

    monkeypatch.setattr(module, "AccountOpsClient", AccountOps)
    monkeypatch.setattr(sources, "fetch_positions", lambda: [])
    monkeypatch.setattr(sources, "fetch_conversions", lambda: [])
    monkeypatch.setattr(sources, "fetch_reconciliation_state", lambda: "clean")
    return sources


def test_quote_status_and_timestamp_belong_to_requested_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = source(monkeypatch)
    prices = {
        "EUR_USD": price("EUR_USD", age=1, tradeable=True),
        "GBP_USD": price("GBP_USD", age=120, tradeable=False),
    }
    monkeypatch.setattr(sources, "_prices_by_symbol", lambda: prices)
    context = sources.account_exposure_context(now=NOW, symbol="GBP_USD")
    assert context.quote_tradeable is False
    assert context.quote_captured_at == NOW - timedelta(seconds=120)
    assert context.captured_at == NOW


def test_missing_order_symbol_does_not_borrow_another_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = source(monkeypatch)
    monkeypatch.setattr(sources, "_prices_by_symbol", lambda: {
        "EUR_USD": price("EUR_USD", age=0, tradeable=True),
    })
    context = sources.account_exposure_context(now=NOW, symbol="GBP_USD")
    assert context.quote_tradeable is None
    assert context.quote_captured_at is None


def test_persisted_drawdown_verdict_reaches_gate_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = source(monkeypatch)
    monkeypatch.setattr(sources, "_prices_by_symbol", lambda: {})
    context = sources.account_exposure_context(
        now=NOW, symbol="EUR_USD", drawdown_block_reason="48h drawdown block",
    )
    assert context.drawdown_block_reason == "48h drawdown block"


def test_pricing_cache_expires_without_rewriting_broker_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = source(monkeypatch)
    clock = [NOW]
    fetched: list[datetime] = []
    stale = price("EUR_USD", age=120, tradeable=True)

    def pricing(*args: Any, **kwargs: Any) -> SimpleNamespace:
        fetched.append(clock[0])
        return SimpleNamespace(prices=[stale])

    monkeypatch.setattr(sources, "_symbols_to_price", lambda: ("EUR_USD",))
    monkeypatch.setattr(sources, "_captured_at", lambda: clock[0])
    monkeypatch.setattr(module, "fetch_pricing", pricing)
    assert sources.fetch_prices()[0].captured_at == stale.broker_time
    clock[0] += timedelta(seconds=4)
    assert sources.fetch_prices()[0].captured_at == stale.broker_time
    assert len(fetched) == 1
    clock[0] += timedelta(seconds=1)
    assert sources.fetch_prices()[0].captured_at == stale.broker_time
    assert len(fetched) == 2
