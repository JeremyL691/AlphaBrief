"""Alpaca Paper adapter end-to-end tests using a mock HTTP server.

Scenarios:
- successful submit + idempotency
- rejection (422) — ``BrokerRejectError`` with reason
- cancel returns CANCELLED; cancel 404 -> BrokerNotFoundError
- list_orders / list_fills parsing
- transient GET failure is retried then succeeds
- POST is NOT retried (no duplicate orders)
- missing credentials -> BrokerAuthError
- service restart with seeded mapping does not duplicate POST
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from alphabrief_execution.broker.alpaca.adapter import AlpacaPaperAdapter
from alphabrief_execution.broker.alpaca.client import AlpacaHttpClient, _safe_decode
from alphabrief_execution.broker.alpaca.config import (
    DEFAULT_BASE_URL,
    ENV_KEY,
    ENV_SECRET,
    AlpacaPaperConfig,
)
from alphabrief_execution.broker.errors import (
    BrokerAuthError,
    BrokerNotFoundError,
    BrokerProtocolError,
    BrokerRejectError,
    BrokerTransientError,
)
from alphabrief_execution.broker.port import (
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    SubmitRequest,
)

# ---------------------------------------------------------------------------
# Mock HTTP server (deterministic, single-threaded)
# ---------------------------------------------------------------------------


class _MockState:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.response_factory: Callable[[str, str, bytes], tuple[int, Any]] | None = (
            None
        )
        self._lock = threading.Lock()
        self.submit_count = 0


def _make_server(state: _MockState) -> ThreadingHTTPServer:
    outer_state = state

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _read(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0") or "0")
            return self.rfile.read(length) if length else b""

        def _capture(self, method: str) -> bytes:
            body = self._read()
            with outer_state._lock:
                outer_state.requests.append(
                    {
                        "method": method,
                        "path": self.path,
                        "headers": {k: v for k, v in self.headers.items()},
                        "body": body,
                    }
                )
            return body

        def _respond_with(self, status: int, payload: Any) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if not isinstance(payload, bytes):
                payload = json.dumps(payload).encode("utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _dispatch(self, method: str) -> None:
            body = self._capture(method)
            with outer_state._lock:
                factory = outer_state.response_factory
            assert factory is not None, "tests must set response_factory before start"
            status, payload = factory(method, self.path, body)
            if method == "POST" and self.path == "/v2/orders" and status == 200:
                with outer_state._lock:
                    outer_state.submit_count += 1
            self._respond_with(status, payload)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch("DELETE")

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


class _MockHandle:
    def __init__(self) -> None:
        self.state = _MockState()
        self.server = _make_server(self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> _MockHandle:
        self.thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"


# ---------------------------------------------------------------------------
# Sync adapter helper
# ---------------------------------------------------------------------------


def _make_adapter(client: AlpacaHttpClient, **kwargs: Any) -> AlpacaPaperAdapter:
    adapter = AlpacaPaperAdapter(client=client, **kwargs)

    def _run(coro: Any) -> Any:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    adapter._run = _run  # type: ignore[attr-defined]
    return adapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_KEY, "test-key")
    monkeypatch.setenv(ENV_SECRET, "test-secret")


def _config(base_url: str, **overrides: Any) -> AlpacaPaperConfig:
    defaults: dict[str, Any] = {
        "base_url": base_url,
        "timeout_seconds": 1.0,
        "max_retries": 1,
        "retry_backoff_seconds": 0.001,
        "allow_insecure_base_url": True,
    }
    defaults.update(overrides)
    return AlpacaPaperConfig(**defaults)


def _client(base_url: str, **overrides: Any) -> AlpacaHttpClient:
    return AlpacaHttpClient(config=_config(base_url, **overrides))


def _submit_payload(order_id: str, status: str = "new") -> dict[str, Any]:
    return {
        "id": order_id,
        "client_order_id": "test-cli",
        "status": status,
        "submitted_at": "2026-06-20T13:30:00Z",
        "updated_at": "2026-06-20T13:30:00Z",
    }


def _order_state_payload(
    *,
    order_id: str,
    client_order_id: str = "test-cli",
    status: str = "filled",
    qty: str = "1",
    filled_qty: str = "1",
) -> dict[str, Any]:
    return {
        "id": order_id,
        "client_order_id": client_order_id,
        "status": status,
        "symbol": "SPY",
        "side": "buy",
        "type": "market",
        "qty": qty,
        "filled_qty": filled_qty,
        "submitted_at": "2026-06-20T13:30:00Z",
        "updated_at": "2026-06-20T13:30:00Z",
    }


def _account_payload() -> dict[str, Any]:
    return {
        "account_number": "A1",
        "cash": "1000",
        "equity": "1000",
        "buying_power": "2000",
        "currency": "USD",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_submit_returns_broker_order_id_and_idempotent_on_repeat() -> None:
    def factory(method: str, path: str, body: bytes) -> tuple[int, Any]:
        if method == "POST" and path == "/v2/orders":
            return 200, _submit_payload("broker-1", "new")
        if method == "GET" and path == "/v2/orders/broker-1":
            return 200, _order_state_payload(order_id="broker-1", status="new")
        return 404, {"message": "no route"}

    with _MockHandle() as mock:
        mock.state.response_factory = factory
        adapter = _make_adapter(_client(mock.base_url))
        request = SubmitRequest(
            symbol="SPY",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("1"),
        )
        first = adapter._run(adapter.submit(request, client_order_id="cli-1"))  # type: ignore[attr-defined]
        assert first.broker_order_id == "broker-1"
        assert mock.state.submit_count == 1

        second = adapter._run(adapter.submit(request, client_order_id="cli-1"))  # type: ignore[attr-defined]
        assert second.broker_order_id == "broker-1"
        assert mock.state.submit_count == 1


def test_submit_rejection_surfaces_broker_reject_error() -> None:
    def factory(method: str, path: str, body: bytes) -> tuple[int, Any]:
        if method == "POST" and path == "/v2/orders":
            return 422, {"message": "insufficient buying power"}
        return 404, {"message": "no"}

    with _MockHandle() as mock:
        mock.state.response_factory = factory
        adapter = _make_adapter(_client(mock.base_url))
        request = SubmitRequest(
            symbol="SPY",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("1"),
        )
        with pytest.raises(BrokerRejectError) as exc_info:
            adapter._run(adapter.submit(request, client_order_id="cli-2"))  # type: ignore[attr-defined]
        assert "buying power" in str(exc_info.value).lower()


def test_cancel_returns_cancelled_status() -> None:
    def factory(method: str, path: str, body: bytes) -> tuple[int, Any]:
        if method == "DELETE" and path == "/v2/orders/broker-9":
            return 200, _order_state_payload(order_id="broker-9", status="canceled")
        if method == "GET" and path == "/v2/orders/broker-9":
            return 200, _order_state_payload(order_id="broker-9", status="canceled")
        return 404, {"message": "no"}

    with _MockHandle() as mock:
        mock.state.response_factory = factory
        adapter = _make_adapter(_client(mock.base_url))
        result = adapter._run(adapter.cancel("broker-9"))  # type: ignore[attr-defined]
        assert result.status == BrokerOrderStatus.CANCELLED


def test_cancel_unknown_order_raises_not_found() -> None:
    def factory(method: str, path: str, body: bytes) -> tuple[int, Any]:
        if method == "DELETE":
            return 404, {"message": "order not found"}
        return 404, {"message": "no"}

    with _MockHandle() as mock:
        mock.state.response_factory = factory
        adapter = _make_adapter(_client(mock.base_url))
        with pytest.raises(BrokerNotFoundError):
            adapter._run(adapter.cancel("missing"))  # type: ignore[attr-defined]


def test_list_orders_parses_each_item() -> None:
    def factory(method: str, path: str, body: bytes) -> tuple[int, Any]:
        if method == "GET" and path.startswith("/v2/orders"):
            return 200, [
                _order_state_payload(order_id="b-1", status="new"),
                _order_state_payload(order_id="b-2", status="filled"),
            ]
        return 404, {"message": "no"}

    with _MockHandle() as mock:
        mock.state.response_factory = factory
        adapter = _make_adapter(_client(mock.base_url))
        orders = adapter._run(adapter.list_orders())  # type: ignore[attr-defined]
        assert [o.broker_order_id for o in orders] == ["b-1", "b-2"]


def test_transient_get_failure_then_success() -> None:
    attempts = {"n": 0}

    def factory(method: str, path: str, body: bytes) -> tuple[int, Any]:
        if method == "GET" and path == "/v2/account":
            attempts["n"] += 1
            if attempts["n"] == 1:
                return 503, {"message": "server error"}
            return 200, _account_payload()
        return 404, {"message": "no"}

    with _MockHandle() as mock:
        mock.state.response_factory = factory
        adapter = _make_adapter(_client(mock.base_url, max_retries=2))
        account = adapter._run(adapter.get_account())  # type: ignore[attr-defined]
        assert account.account_id == "A1"
        assert attempts["n"] == 2


def test_post_is_not_retried_on_transient_failure() -> None:
    """POST must never auto-retry — the broker may have already accepted it."""

    def factory(method: str, path: str, body: bytes) -> tuple[int, Any]:
        if method == "POST" and path == "/v2/orders":
            return 503, {"message": "server error"}
        return 404, {"message": "no"}

    with _MockHandle() as mock:
        mock.state.response_factory = factory
        adapter = _make_adapter(_client(mock.base_url, max_retries=3))
        request = SubmitRequest(
            symbol="SPY",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("1"),
        )
        with pytest.raises(BrokerTransientError):
            adapter._run(adapter.submit(request, client_order_id="cli-3"))  # type: ignore[attr-defined]
        assert len(mock.state.requests) == 1


def test_missing_credentials_raise_broker_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env vars -> ``BrokerAuthError`` at client construction."""
    monkeypatch.delenv(ENV_KEY, raising=False)
    monkeypatch.delenv(ENV_SECRET, raising=False)
    with pytest.raises(BrokerAuthError):
        AlpacaHttpClient(config=_config(DEFAULT_BASE_URL))


def test_service_restart_does_not_duplicate_orders() -> None:
    def factory(method: str, path: str, body: bytes) -> tuple[int, Any]:
        if method == "POST" and path == "/v2/orders":
            return 200, _submit_payload("broker-restart", "new")
        if method == "GET" and path == "/v2/orders/broker-restart":
            return 200, _order_state_payload(order_id="broker-restart")
        return 404, {"message": "no"}

    with _MockHandle() as mock:
        mock.state.response_factory = factory
        adapter_a = _make_adapter(_client(mock.base_url))
        request = SubmitRequest(
            symbol="SPY",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("1"),
        )
        first = adapter_a._run(  # type: ignore[attr-defined]
            adapter_a.submit(request, client_order_id="cli-restart")
        )
        assert first.broker_order_id == "broker-restart"
        assert mock.state.submit_count == 1

        adapter_b = _make_adapter(
            _client(mock.base_url),
            known_client_order_ids={"cli-restart": "broker-restart"},
        )
        again = adapter_b._run(  # type: ignore[attr-defined]
            adapter_b.submit(request, client_order_id="cli-restart")
        )
        assert again.broker_order_id == "broker-restart"
        assert mock.state.submit_count == 1


def test_list_fills_returns_empty_on_null_body() -> None:
    def factory(method: str, path: str, body: bytes) -> tuple[int, Any]:
        if method == "GET" and path.startswith("/v2/account/activities"):
            return 200, []
        return 404, {"message": "no"}

    with _MockHandle() as mock:
        mock.state.response_factory = factory
        adapter = _make_adapter(_client(mock.base_url))
        fills = adapter._run(adapter.list_fills())  # type: ignore[attr-defined]
        assert fills == []


def test_client_rejects_scalar_json_response() -> None:
    with pytest.raises(BrokerProtocolError, match="JSON object, array, or null"):
        _safe_decode(b'"unexpected scalar"')


def test_status_mapping_normalizes_cancelled() -> None:
    from alphabrief_execution.broker.alpaca.adapter import _to_broker_status

    assert _to_broker_status("canceled") == BrokerOrderStatus.CANCELLED
    assert _to_broker_status("partially_filled") == BrokerOrderStatus.PARTIALLY_FILLED
    assert _to_broker_status("filled") == BrokerOrderStatus.FILLED
    assert _to_broker_status("rejected") == BrokerOrderStatus.REJECTED
