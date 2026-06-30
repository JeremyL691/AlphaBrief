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
