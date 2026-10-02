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
        base_url="https://api-fxpractice.oanda.com",
        timeout_seconds=1.0,
        max_retries=0,
        retry_backoff_seconds=0.001,
    )


_INSTRUMENTS_PAYLOAD = {
    "instruments": [
        {
            "name": "EUR_USD",
            "displayName": "EUR/USD",
            "type": "CURRENCY",
            "displayPrecision": 5,
            "tradeUnitsPrecision": 0,
            "pipLocation": -4,
            "minimumTradeSize": "1",
            "maximumOrderUnits": "100000000",
            "maximumPositionSize": "0",
            "maximumOrderValue": "100000000",
            "marginRate": "0.02",
        }
    ]
}


def _order_payload(
    *, units: str = "1000", order_type: str = "MARKET", tif: str = "FOK"
) -> dict[str, Any]:
    return {
        "orderCreateTransaction": {
            "id": "broker-1",
            "instrument": "EUR_USD",
            "units": units,
            "type": order_type,
            "timeInForce": tif,
            "time": "2026-01-01T00:00:00.000000000Z",
        }
    }


def _routing_sender(
    calls: list[dict[str, Any]],
    *,
    order_payload: dict[str, Any] | None = None,
    order_response: dict[str, Any] | None = None,
) -> Any:
    """Serve the instruments catalog, order creation and order lookup."""

    def send(request: Request, timeout: float) -> bytes:
        del timeout
        body = cast(bytes, request.data or b"")
        calls.append(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "body": json.loads(body.decode("utf-8")) if body else None,
            }
        )
        url = request.full_url
        if "/instruments" in url:
            return json.dumps(_INSTRUMENTS_PAYLOAD).encode("utf-8")
        if request.get_method() == "POST":
            if order_response is not None:
                return json.dumps(order_response).encode("utf-8")
            return json.dumps(order_payload or _order_payload()).encode("utf-8")
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

    return send


def _submitted_order(calls: list[dict[str, Any]]) -> dict[str, Any]:
    post_calls = [call for call in calls if call["method"] == "POST"]
    assert post_calls, "no order was submitted"
    return cast(dict[str, Any], post_calls[0]["body"]["order"])


def test_submit_maps_oanda_payload_and_is_idempotent() -> None:
    calls: list[dict[str, Any]] = []
    adapter = OandaPaperAdapter(
        client=OandaHttpClient(config=_config(), http_send=_routing_sender(calls))
    )
    request = SubmitRequest(
        symbol="EUR_USD",
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.MARKET,
        quantity=Decimal("1000"),
        cycle_id="cyc-1",
    )

    first = asyncio.run(adapter.submit(request, client_order_id="cli-1"))
    second = asyncio.run(adapter.submit(request, client_order_id="cli-1"))

    assert first.broker_order_id == "broker-1"
    assert second.broker_order_id == "broker-1"
    assert second.status == BrokerOrderStatus.NEW
    post_calls = [call for call in calls if call["method"] == "POST"]
    assert len(post_calls) == 1, "the second submit must not create a second order"
    # Signed units, no `side` field, FOK, and full clientExtensions.
    assert _submitted_order(calls) == {
        "type": "MARKET",
        "instrument": "EUR_USD",
        "units": "1000",
        "timeInForce": "FOK",
        "positionFill": "DEFAULT",
        "clientExtensions": {
            "id": "cli-1",
            "tag": "alphabrief",
            "comment": "cyc-1",
        },
    }


def test_sell_submit_sends_negative_units_without_a_side_field() -> None:
    calls: list[dict[str, Any]] = []
    adapter = OandaPaperAdapter(
        client=OandaHttpClient(config=_config(), http_send=_routing_sender(calls))
    )

    asyncio.run(
        adapter.submit(
            SubmitRequest(
                symbol="EUR_USD",
                side=BrokerOrderSide.SELL,
                order_type=BrokerOrderType.MARKET,
                quantity=Decimal("1500"),
            ),
            client_order_id="cli-sell",
        )
    )

    order = _submitted_order(calls)
    assert order["units"] == "-1500"
    assert "side" not in order


def test_protective_orders_are_attached_on_fill() -> None:
    calls: list[dict[str, Any]] = []
    adapter = OandaPaperAdapter(
        client=OandaHttpClient(config=_config(), http_send=_routing_sender(calls))
    )

    asyncio.run(
        adapter.submit(
            SubmitRequest(
                symbol="EUR_USD",
                side=BrokerOrderSide.BUY,
                order_type=BrokerOrderType.MARKET,
                quantity=Decimal("1000"),
                stop_loss=Decimal("1.0950"),
                take_profit=Decimal("1.1100"),
            ),
            client_order_id="cli-protected",
        )
    )

    order = _submitted_order(calls)
    assert order["stopLossOnFill"] == {"timeInForce": "GTC", "price": "1.0950"}
    assert order["takeProfitOnFill"] == {"timeInForce": "GTC", "price": "1.1100"}


def test_unknown_instrument_fails_closed_before_submitting() -> None:
    calls: list[dict[str, Any]] = []
    adapter = OandaPaperAdapter(
        client=OandaHttpClient(config=_config(), http_send=_routing_sender(calls))
    )

    with pytest.raises(Exception, match="not in the account's instrument catalog"):
        asyncio.run(
            adapter.submit(
                SubmitRequest(
                    symbol="XAU_USD",
                    side=BrokerOrderSide.BUY,
                    order_type=BrokerOrderType.MARKET,
                    quantity=Decimal("1"),
                ),
                client_order_id="cli-unknown",
            )
        )

    assert not [call for call in calls if call["method"] == "POST"]


def test_resting_limit_order_requires_an_explicit_time_in_force() -> None:
    from alphabrief_execution.broker.errors import BrokerRejectError

    calls: list[dict[str, Any]] = []
    adapter = OandaPaperAdapter(
        client=OandaHttpClient(config=_config(), http_send=_routing_sender(calls))
    )

    with pytest.raises(BrokerRejectError, match="explicit GTC/IOC/FOK"):
        asyncio.run(
            adapter.submit(
                SubmitRequest(
                    symbol="EUR_USD",
                    side=BrokerOrderSide.BUY,
                    order_type=BrokerOrderType.LIMIT,
                    quantity=Decimal("1000"),
                    limit_price=Decimal("1.0900"),
                ),
                client_order_id="cli-limit",
            )
        )

    assert not [call for call in calls if call["method"] == "POST"]


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
        base_url="https://api-fxpractice.oanda.com",
        timeout_seconds=1.0,
        max_retries=2,
        retry_backoff_seconds=0.001,
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
        base_url="https://api-fxpractice.oanda.com",
        timeout_seconds=1.0,
        max_retries=1,
        retry_backoff_seconds=0.001,
    )
    client = OandaHttpClient(config=config, http_send=_explode)

    with caplog.at_level("WARNING"):
        with pytest.raises(BrokerTransientError):
            client.request("GET", "/v3/accounts/abc/summary")

    log_blob = "\n".join(record.getMessage() for record in caplog.records)
    assert "giving up" in log_blob
