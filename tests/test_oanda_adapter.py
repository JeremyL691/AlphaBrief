"""OANDA Paper adapter tests with an injected urllib transport."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any, cast
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.adapter import OandaPaperAdapter
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import (
    ENV_ACCOUNT_ID,
    ENV_TOKEN,
    OandaPaperConfig,
)
from alphabrief_execution.broker.port import (
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    SubmitRequest,
)


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_TOKEN, "test-token")
    monkeypatch.setenv(ENV_ACCOUNT_ID, "acct-1")


def _config() -> OandaPaperConfig:
    return OandaPaperConfig(
        base_url="http://oanda.test",
        timeout_seconds=1.0,
        max_retries=0,
        retry_backoff_seconds=0.001,
        allow_insecure_base_url=True,
    )


def test_submit_maps_oanda_payload_and_is_idempotent() -> None:
    calls: list[dict[str, Any]] = []

    def send(request: Request, timeout: float) -> bytes:
        body = cast(bytes, request.data or b"")
        calls.append(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "body": json.loads(body.decode("utf-8")) if body else None,
            }
        )
        if request.get_method() == "POST":
            return json.dumps(
                {
                    "orderCreateTransaction": {
                        "id": "broker-1",
                        "instrument": "EUR_USD",
                        "units": "1000",
                        "type": "MARKET",
                        "timeInForce": "FOK",
                        "time": "2026-01-01T00:00:00.000000000Z",
                    }
                }
            ).encode("utf-8")
        return json.dumps(
            {
                "order": {
                    "id": "broker-1",
                    "clientExtensions": {"id": "cli-1"},
                    "createTime": "2026-01-01T00:00:00.000000000Z",
                    "state": "PENDING",
                    "type": "MARKET",
                    "instrument": "EUR_USD",
                    "units": "1000",
                    "timeInForce": "FOK",
                }
            }
        ).encode("utf-8")

    adapter = OandaPaperAdapter(
        client=OandaHttpClient(config=_config(), http_send=send)
    )
    request = SubmitRequest(
        symbol="EUR_USD",
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.MARKET,
        quantity=Decimal("1000"),
    )

    first = asyncio.run(adapter.submit(request, client_order_id="cli-1"))
    second = asyncio.run(adapter.submit(request, client_order_id="cli-1"))

    assert first.broker_order_id == "broker-1"
    assert second.broker_order_id == "broker-1"
    assert second.status == BrokerOrderStatus.NEW
    post_calls = [call for call in calls if call["method"] == "POST"]
    assert len(post_calls) == 1
    assert post_calls[0]["body"] == {
        "order": {
            "type": "MARKET",
            "instrument": "EUR_USD",
            "units": "1000",
            "side": "buy",
            "timeInForce": "FOK",
            "clientExtensions": {"id": "cli-1"},
        }
    }


# ---------------------------------------------------------------------------
# Phase 30 task #4: SSL handshake errors must surface as
# BrokerTransientError so the retry path covers them and the final
# log line tells the operator to inspect their certifi bundle.
# ---------------------------------------------------------------------------


def test_ssl_error_is_treated_as_transient_and_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from alphabrief_execution.broker.errors import BrokerTransientError
    from alphabrief_execution.broker.oanda.client import (
        OandaHttpClient,
        looks_like_ssl_error,
    )
    from alphabrief_execution.broker.oanda.config import OandaPaperConfig

    attempts: list[int] = []

    def _explode(request: Request, timeout: float) -> bytes:
        attempts.append(len(attempts) + 1)
        import ssl as _ssl

        raise _ssl.SSLError("ssl handshake failed: certificate verify failed")

    config = OandaPaperConfig(
        base_url="http://oanda.test",
        timeout_seconds=1.0,
        max_retries=2,
        retry_backoff_seconds=0.001,
        allow_insecure_base_url=True,
    )
    client = OandaHttpClient(config=config, http_send=_explode)

    with caplog.at_level("WARNING"):
        with pytest.raises(BrokerTransientError) as excinfo:
            client.request("GET", "/v3/accounts")

    assert "ssl handshake error" in str(excinfo.value).lower()
    # 1 initial + 2 retries == 3 attempts
    assert len(attempts) == 3
    # SSL error log line must surface the certifi hint so the operator
    # can correlate it with their local Python install.
    log_blob = "\n".join(record.getMessage() for record in caplog.records)
    assert "certifi" in log_blob or "ssl handshake" in log_blob.lower()

    # The pure classifier must recognize SSL strings deterministically.
    assert looks_like_ssl_error("ssl handshake failed: certificate verify failed")
    assert not looks_like_ssl_error("connection refused")


def test_final_attempt_logs_giving_up_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After max_retries, the final attempt must log a 'giving up' line."""
    from alphabrief_execution.broker.errors import BrokerTransientError
    from alphabrief_execution.broker.oanda.client import OandaHttpClient
    from alphabrief_execution.broker.oanda.config import OandaPaperConfig

    def _explode(request: Request, timeout: float) -> bytes:
        raise OSError("connection refused")

    config = OandaPaperConfig(
        base_url="http://oanda.test",
        timeout_seconds=1.0,
        max_retries=1,
        retry_backoff_seconds=0.001,
        allow_insecure_base_url=True,
    )
    client = OandaHttpClient(config=config, http_send=_explode)

    with caplog.at_level("WARNING"):
        with pytest.raises(BrokerTransientError):
            client.request("GET", "/v3/accounts/abc/summary")

    log_blob = "\n".join(record.getMessage() for record in caplog.records)
    assert "giving up" in log_blob
