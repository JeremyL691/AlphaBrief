"""Tests for the API-side broker adapter singleton (Phase 20 R20.1).

Covers:
- no credentials -> null adapter; ``has_live_broker`` False.
- credentials set -> live AlpacaPaperAdapter; ``has_live_broker`` True.
- ``_reset_broker_adapter`` clears the cache (creds then unset -> null).
- null adapter read probes return the zero shape.
- module imports without credentials (no auth error at import).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from decimal import Decimal

import pytest
from alphabrief_api import broker_adapter
from alphabrief_execution.broker.routing import RoutingBrokerAdapter


@pytest.fixture(autouse=True)
def _reset_adapter() -> Iterator[None]:
    """Ensure each test starts with a fresh (uncached) adapter singleton."""
    broker_adapter._reset_broker_adapter()
    yield
    broker_adapter._reset_broker_adapter()


def test_no_credentials_returns_null_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_BASE_URL", raising=False)
    monkeypatch.delenv("ALPHABRIEF_ALPACA_KEY", raising=False)
    monkeypatch.delenv("ALPHABRIEF_ALPACA_SECRET", raising=False)
    adapter = broker_adapter.get_broker_adapter()
    assert isinstance(adapter, broker_adapter._NullBrokerAdapter)
    assert broker_adapter.has_live_broker() is False


def test_credentials_set_returns_live_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ensure OANDA credentials are not set, so Alpaca is selected.
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_BASE_URL", raising=False)
    # A mock base URL is required so the client does not dial the real
    # Alpaca endpoint; allow_insecure_base_url is applied by the factory.
    monkeypatch.setenv("ALPHABRIEF_ALPACA_KEY", "test-key")
    monkeypatch.setenv("ALPHABRIEF_ALPACA_SECRET", "test-secret")
    monkeypatch.setenv("ALPHABRIEF_ALPACA_BASE_URL", "http://127.0.0.1:1")
    adapter = broker_adapter.get_broker_adapter()
    assert isinstance(adapter, RoutingBrokerAdapter)
    assert adapter.venue_for_symbol("AAPL") == "alpaca_paper"
    assert adapter.venue_for_symbol("BTC-USD") == "alpaca_paper"
    assert broker_adapter.has_live_broker() is True

def test_oanda_credentials_are_routed_alongside_alpaca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With both credential sets present the routed adapter wires both
    # venues: FX/metals/index CFDs -> OANDA, equities/crypto -> Alpaca.
    monkeypatch.setenv("ALPHABRIEF_OANDA_TOKEN", "test-token")
    monkeypatch.setenv("ALPHABRIEF_OANDA_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("ALPHABRIEF_OANDA_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ALPHABRIEF_ALPACA_KEY", "test-key")
    monkeypatch.setenv("ALPHABRIEF_ALPACA_SECRET", "test-secret")
    monkeypatch.setenv("ALPHABRIEF_ALPACA_BASE_URL", "http://127.0.0.1:1")
    adapter = broker_adapter.get_broker_adapter()
    assert isinstance(adapter, RoutingBrokerAdapter)
    assert adapter.venue_for_symbol("EUR_USD") == "oanda_paper"
    assert adapter.venue_for_symbol("XAU_USD") == "oanda_paper"
    assert adapter.venue_for_symbol("US30_USD") == "oanda_paper"
    assert adapter.venue_for_symbol("AAPL") == "alpaca_paper"
    assert adapter.venue_for_symbol("BTC-USD") == "alpaca_paper"
    assert broker_adapter.has_live_broker() is True


def test_reset_clears_cached_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ensure OANDA credentials are not set, so Alpaca is selected.
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_BASE_URL", raising=False)
    monkeypatch.setenv("ALPHABRIEF_ALPACA_KEY", "test-key")
    monkeypatch.setenv("ALPHABRIEF_ALPACA_SECRET", "test-secret")
    monkeypatch.setenv("ALPHABRIEF_ALPACA_BASE_URL", "http://127.0.0.1:1")
    live = broker_adapter.get_broker_adapter()
    assert isinstance(live, RoutingBrokerAdapter)

    # Drop credentials and reset; the next access rebuilds a null adapter.
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_BASE_URL", raising=False)
    monkeypatch.delenv("ALPHABRIEF_ALPACA_KEY", raising=False)
    monkeypatch.delenv("ALPHABRIEF_ALPACA_SECRET", raising=False)
    monkeypatch.delenv("ALPHABRIEF_ALPACA_BASE_URL", raising=False)
    broker_adapter._reset_broker_adapter()
    rebuilt = broker_adapter.get_broker_adapter()
    assert isinstance(rebuilt, broker_adapter._NullBrokerAdapter)
    assert broker_adapter.has_live_broker() is False


def test_null_adapter_read_probes_return_zero_shape() -> None:
    adapter = broker_adapter._NullBrokerAdapter()
    positions = asyncio.run(adapter.get_positions())
    assert positions == []
    account = asyncio.run(adapter.get_account())
    assert account.account_id == "null-adapter"
    assert account.cash == Decimal("0")
    assert account.equity == Decimal("0")
    assert account.buying_power == Decimal("0")
    assert account.currency == "USD"
    health = asyncio.run(adapter.health())
    assert health.healthy is True


def test_module_imports_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Importing the module (and get_broker_adapter resolution) must not
    # raise when credentials are absent — the API has to boot in CI.
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_BASE_URL", raising=False)
    monkeypatch.delenv("ALPHABRIEF_ALPACA_KEY", raising=False)
    monkeypatch.delenv("ALPHABRIEF_ALPACA_SECRET", raising=False)
    broker_adapter._reset_broker_adapter()
    # Re-resolving the adapter exercises the no-creds factory path end to end.
    adapter = broker_adapter.get_broker_adapter()
    assert isinstance(adapter, broker_adapter._NullBrokerAdapter)
