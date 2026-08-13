"""M06-W06 integration: order commands under transport faults.

Exercises the full command path — submit, unknown-outcome resolution by
persisted client identity, fail-closed gating, and scrubbed telemetry —
over one shared mock transport, proving that a timeout or disconnect
after submit never duplicates the order and that an unresolved state
freezes further submission instead of guessing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.faults import (
    ClassifiedRequestExecutor,
    UnknownOutcomeFailure,
)
from alphabrief_execution.broker.oanda.order_ops import OrderOpsClient
from alphabrief_execution.broker.oanda.telemetry import TelemetryRecorder
from alphabrief_execution.broker.oanda.unknown_outcome import (
    FrozenSubmissionError,
    SubmissionGate,
    UnknownOutcomeResolver,
)

ACCOUNT_ID = "101-004-1234567-001"
BASE = f"http://oanda.test/v3/accounts/{ACCOUNT_ID}"


class _FakeCommandBroker:
    """Deterministic in-memory broker with fault injection."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.next_id = 100
        self.absorb_submit = False
        self.drop_submit = False
        self.fail_list = False
        self.captured: list[dict[str, Any]] = []

    def _tx(self) -> str:
        value = str(self.next_id)
        self.next_id += 1
        return value

    def handle(self, request: Request) -> bytes:
        method = request.method
        url = request.full_url
        raw = request.data
        body = json.loads(raw.decode("utf-8")) if isinstance(raw, bytes) else {}
        self.captured.append({"method": method, "url": url, "body": body})
        path, _, _ = url.partition("?")

        if method == "POST" and path == f"{BASE}/orders":
            order = body["order"]
            order_id = self._tx()
            record = {
                "id": order_id,
                "instrument": order.get("instrument", ""),
                "units": order.get("units", "0"),
                "state": "PENDING",
                "createTime": "2026-08-04T12:00:00.000000000Z",
                "clientExtensions": order.get("clientExtensions", {}),
            }
            if self.drop_submit:
                # The broker never records the order before the timeout.
                raise TimeoutError("timed out")
            self.orders[order_id] = record
            if self.absorb_submit:
                # The broker accepts the order, then the response is lost.
                raise TimeoutError("timed out")
            return json.dumps(
                {
                    "orderCreateTransaction": {"id": order_id},
                    "orderFillTransaction": None,
                }
            ).encode("utf-8")
        if method == "GET" and path == f"{BASE}/orders":
            if self.fail_list:
                raise TimeoutError("timed out")
            ordered = [
                self.orders[oid]
                for oid in sorted(self.orders, key=lambda o: int(o))
            ]
            return json.dumps({"orders": ordered}).encode("utf-8")
        if method == "GET" and path.startswith(f"{BASE}/orders/"):
            order_id = path.split("/orders/", 1)[1]
            found = self.orders.get(order_id)
            if found is None:
                raise TimeoutError("timed out")
            return json.dumps({"order": found}).encode("utf-8")
        if method == "PUT" and path.endswith("/cancel"):
            order_id = path.split("/orders/", 1)[1].split("/", 1)[0]
            self.orders[order_id]["state"] = "CANCELLED"
            return json.dumps({}).encode("utf-8")
        raise AssertionError(f"unexpected request: {method} {path}")


def _make(broker: _FakeCommandBroker) -> tuple[OandaHttpClient, OrderOpsClient]:
    def _send(request: Request, timeout_seconds: float) -> bytes:
        return broker.handle(request)

    http = OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=_send,
        token="t",
        account_id=ACCOUNT_ID,
    )
    return http, OrderOpsClient(http)


def _submit_payload(client_order_id: str) -> dict[str, Any]:
    return {
        "order": {
            "type": "MARKET",
            "instrument": "EUR_USD",
            "units": "1000",
            "clientExtensions": {"id": client_order_id},
        }
    }


def test_timeout_after_submit_resolves_by_client_identity() -> None:
    broker = _FakeCommandBroker()
    broker.absorb_submit = True
    http, orders = _make(broker)
    executor = ClassifiedRequestExecutor(http, max_attempts=1)
    resolver = UnknownOutcomeResolver(orders)

    with pytest.raises(UnknownOutcomeFailure):
        executor.execute(
            "POST",
            http.account_path("/orders"),
            json_body=_submit_payload("client-order-1"),
            request_id="client-order-1",
        )

    # The outcome is resolved by querying, never by re-submitting.
    verdict = resolver.resolve("client-order-1")
    assert verdict.resolution == "RESOLVED_ACCEPTED"
    assert verdict.broker_order_id is not None
    assert verdict.state == "PENDING"
    posts = [c for c in broker.captured if c["method"] == "POST"]
    gets = [c for c in broker.captured if c["method"] == "GET"]
    assert len(posts) == 1
    assert any("/orders" in c["url"] for c in gets)


def test_unprocessed_submit_is_safe_to_retry() -> None:
    broker = _FakeCommandBroker()
    broker.drop_submit = True
    http, orders = _make(broker)
    executor = ClassifiedRequestExecutor(http, max_attempts=1)
    resolver = UnknownOutcomeResolver(orders)

    with pytest.raises(UnknownOutcomeFailure):
        executor.execute(
            "POST",
            http.account_path("/orders"),
            json_body=_submit_payload("client-order-2"),
            request_id="client-order-2",
        )
    verdict = resolver.resolve("client-order-2")
    assert verdict.resolution == "RESOLVED_NOT_SUBMITTED"
    assert verdict.broker_order_id is None

    # The verdict is deterministic: the submit never reached the broker,
    # so a single bounded retry is safe and must not duplicate.
    broker.drop_submit = False
    response = executor.execute(
        "POST",
        http.account_path("/orders"),
        json_body=_submit_payload("client-order-2"),
        request_id="client-order-2",
    )
    assert response.json_body is not None
    posts = [c for c in broker.captured if c["method"] == "POST"]
    assert len(posts) == 2
    assert len(broker.orders) == 1


def test_unresolved_outcome_freezes_further_submission() -> None:
    broker = _FakeCommandBroker()
    broker.absorb_submit = True
    broker.fail_list = True
    http, orders = _make(broker)
    executor = ClassifiedRequestExecutor(http, max_attempts=1)
    resolver = UnknownOutcomeResolver(orders)
    gate = SubmissionGate()

    with pytest.raises(UnknownOutcomeFailure):
        executor.execute(
            "POST",
            http.account_path("/orders"),
            json_body=_submit_payload("client-order-3"),
            request_id="client-order-3",
        )
    verdict = resolver.resolve("client-order-3")
    assert verdict.resolution == "UNRESOLVED"
    gate.freeze(verdict.detail)

    # Frozen: every further submission is blocked, no guessing.
    assert gate.frozen is True
    with pytest.raises(FrozenSubmissionError):
        gate.ensure_open()
    posts = [c for c in broker.captured if c["method"] == "POST"]
    assert len(posts) == 1


def test_resolver_is_idempotent_and_bounded() -> None:
    broker = _FakeCommandBroker()
    broker.absorb_submit = True
    http, orders = _make(broker)
    resolver = UnknownOutcomeResolver(orders, max_pages=1)
    first = resolver.resolve("missing-client")
    second = resolver.resolve("missing-client")
    assert first.resolution == second.resolution
    assert first.resolution == "RESOLVED_NOT_SUBMITTED"
    assert len(broker.captured) == 2


def test_commands_record_scrubbed_telemetry(tmp_path: Path) -> None:
    broker = _FakeCommandBroker()
    http, orders = _make(broker)
    recorder = TelemetryRecorder(db_path=tmp_path / "telemetry.db")
    try:
        executor = ClassifiedRequestExecutor(
            http, max_attempts=1, telemetry=recorder
        )
        executor.execute(
            "POST",
            http.account_path("/orders"),
            json_body=_submit_payload("client-order-4"),
            request_id="client-order-4",
        )
        order_id = next(iter(broker.orders))
        executor.execute(
            "GET", http.account_path(f"/orders/{order_id}"), request_id="get-4"
        )
        executor.execute(
            "PUT",
            http.account_path(f"/orders/{order_id}/cancel"),
            request_id="cancel-4",
        )
        rows = recorder.recent()
        families = [row["method_family"] for row in rows]
        assert families == ["order.cancel", "order.get", "order.create"]
        for row in rows:
            assert ACCOUNT_ID not in " ".join(str(v) for v in row.values())
        assert all(row["status"] == "200" for row in rows)
    finally:
        recorder.close()


def test_failed_consumer_after_resolution_retries_same_window() -> None:
    broker = _FakeCommandBroker()
    http, orders = _make(broker)
    executor = ClassifiedRequestExecutor(http, max_attempts=1)
    executor.execute(
        "POST",
        http.account_path("/orders"),
        json_body=_submit_payload("client-order-5"),
        request_id="client-order-5",
    )
    resolver = UnknownOutcomeResolver(orders)
    first = resolver.resolve("client-order-5")
    assert first.resolution == "RESOLVED_ACCEPTED"
    # A consumer failure between verdict and persistence changes nothing:
    # the next resolution query sees the same broker state.
    second = resolver.resolve("client-order-5")
    assert second.broker_order_id == first.broker_order_id
    assert len(broker.orders) == 1
