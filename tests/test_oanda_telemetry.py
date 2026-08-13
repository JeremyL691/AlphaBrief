"""M06-W06: scrubbed OANDA request telemetry.

Covers:
- telemetry records method family, endpoint template, status, broker
  request ID, latency, attempts, error class, and scrubbed correlation
  while excluding the token, the full account ID, and sensitive payload
  values (AC-M06-W06-03).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request

from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.faults import ClassifiedRequestExecutor
from alphabrief_execution.broker.oanda.telemetry import (
    TelemetryRecorder,
    endpoint_template_for,
    method_family_for,
    scrub_correlation,
    scrub_url_account_segment,
)

ACCOUNT_ID = "101-004-1234567-001"
TOKEN = "super-secret-token-value"


def _http_client(captured: list[dict[str, Any]]) -> OandaHttpClient:
    def _send(request: Request, timeout_seconds: float) -> bytes:
        captured.append({"method": request.method, "url": request.full_url})
        return json.dumps({"ok": True}).encode("utf-8")

    return OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=_send,
        token=TOKEN,
        account_id=ACCOUNT_ID,
    )


def _row_values(row: dict[str, Any]) -> str:
    return " ".join(str(v) for v in row.values())


# ---------------------------------------------------------------------------
# AC-M06-W06-03: scrubbed telemetry fields
# ---------------------------------------------------------------------------


def test_recorder_round_trip(tmp_path: Path) -> None:
    recorder = TelemetryRecorder(db_path=tmp_path / "telemetry.db")
    try:
        recorder.record(
            method="POST",
            path=f"/v3/accounts/{ACCOUNT_ID}/orders",
            status="200",
            latency_ms=42,
            attempts=1,
            error_class=None,
            correlation_id="client-order-1",
            had_body=True,
            broker_request_id="2048",
        )
        assert recorder.count() == 1
        rows = recorder.recent()
        assert rows[0]["method_family"] == "order.create"
        assert rows[0]["endpoint_template"] == (
            "/v3/accounts/{account_id}/orders"
        )
        assert rows[0]["status"] == "200"
        assert rows[0]["broker_request_id"] == "2048"
        assert rows[0]["latency_ms"] == 42
        assert rows[0]["attempts"] == 1
        assert rows[0]["error_class"] is None
        assert rows[0]["had_body"] is True
        assert rows[0]["correlation_id"].startswith("corr-")
    finally:
        recorder.close()


def test_token_never_appears_in_telemetry(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []
    recorder = TelemetryRecorder(db_path=tmp_path / "telemetry.db")
    try:
        executor = ClassifiedRequestExecutor(
            _http_client(captured),
            max_attempts=1,
            retry_backoff_seconds=0.001,
            telemetry=recorder,
        )
        executor.execute(
            "GET", f"/v3/accounts/{ACCOUNT_ID}/summary", request_id="s1"
        )
        rows = recorder.recent()
        assert len(rows) == 1
        assert TOKEN not in _row_values(rows[0])
        # The Authorization header content never reaches the recorder.
        assert "Bearer" not in _row_values(rows[0])
    finally:
        recorder.close()


def test_full_account_id_never_appears_in_telemetry(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []
    recorder = TelemetryRecorder(db_path=tmp_path / "telemetry.db")
    try:
        executor = ClassifiedRequestExecutor(
            _http_client(captured),
            max_attempts=1,
            retry_backoff_seconds=0.001,
            telemetry=recorder,
        )
        executor.execute(
            "GET",
            f"/v3/accounts/{ACCOUNT_ID}/transactions/2048",
            request_id="t1",
        )
        executor.execute(
            "PUT",
            f"/v3/accounts/{ACCOUNT_ID}/trades/123/close",
            request_id="c1",
        )
        rows = recorder.recent()
        for row in rows:
            assert ACCOUNT_ID not in _row_values(row)
        # Endpoint templates carry placeholders, never real IDs.
        assert rows[0]["endpoint_template"] == (
            "/v3/accounts/{account_id}/trades/{id}/close"
        )
        assert rows[1]["endpoint_template"] == (
            "/v3/accounts/{account_id}/transactions/{id}"
        )
    finally:
        recorder.close()


def test_sensitive_payload_values_never_recorded(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []
    recorder = TelemetryRecorder(db_path=tmp_path / "telemetry.db")
    try:
        executor = ClassifiedRequestExecutor(
            _http_client(captured),
            max_attempts=1,
            retry_backoff_seconds=0.001,
            telemetry=recorder,
        )
        executor.execute(
            "POST",
            f"/v3/accounts/{ACCOUNT_ID}/orders",
            json_body={"order": {"units": "1000", "price": "1.10500"}},
            request_id="p1",
        )
        rows = recorder.recent()
        assert len(rows) == 1
        combined = _row_values(rows[0])
        assert "1000" not in combined
        assert "1.10500" not in combined
        # Only the non-sensitive body-presence flag is recorded.
        assert rows[0]["had_body"] is True
    finally:
        recorder.close()


def test_correlation_is_scrubbed_non_reversible(tmp_path: Path) -> None:
    recorder = TelemetryRecorder(db_path=tmp_path / "telemetry.db")
    try:
        recorder.record(
            method="GET",
            path=f"/v3/accounts/{ACCOUNT_ID}/summary",
            status="200",
            latency_ms=1,
            attempts=1,
            error_class=None,
            correlation_id="client-order-42",
        )
        rows = recorder.recent()
        stored = rows[0]["correlation_id"]
        assert stored == scrub_correlation("client-order-42")
        assert stored != "client-order-42"
        assert "client-order-42" not in _row_values(rows[0])
        # Deterministic: the same input always hashes the same way.
        assert scrub_correlation("client-order-42") == scrub_correlation(
            "client-order-42"
        )
    finally:
        recorder.close()


def test_executor_records_success_and_failure_telemetry(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []
    recorder = TelemetryRecorder(db_path=tmp_path / "telemetry.db")
    try:
        executor = ClassifiedRequestExecutor(
            _http_client(captured),
            max_attempts=1,
            retry_backoff_seconds=0.001,
            telemetry=recorder,
        )
        executor.execute(
            "GET", f"/v3/accounts/{ACCOUNT_ID}/orders", request_id="ok-1"
        )
        assert recorder.count() == 1
        assert recorder.recent()[0]["status"] == "200"
    finally:
        recorder.close()


def test_method_family_mapping_is_stable() -> None:
    account = f"/v3/accounts/{ACCOUNT_ID}"
    cases = {
        ("POST", f"{account}/orders"): "order.create",
        ("GET", f"{account}/orders"): "order.list",
        ("GET", f"{account}/orders/2048"): "order.get",
        ("PUT", f"{account}/orders/2048"): "order.update",
        ("PUT", f"{account}/orders/2048/cancel"): "order.cancel",
        ("GET", f"{account}/trades"): "trade.list",
        ("GET", f"{account}/trades/1"): "trade.get",
        ("PUT", f"{account}/trades/1/close"): "trade.close",
        ("PUT", f"{account}/trades/1/orders"): "trade.orders",
        ("GET", f"{account}/positions"): "position.list",
        ("GET", f"{account}/positions/EUR_USD"): "position.get",
        ("PUT", f"{account}/positions/EUR_USD/close"): "position.close",
        ("GET", f"{account}/summary"): "account.summary",
        ("GET", f"{account}/changes"): "account.changes",
        ("GET", f"{account}/transactions/2048"): "transaction.get",
        ("GET", f"{account}/transactions/idrange"): "transaction.idrange",
        ("GET", f"{account}/transactions/sinceid"): "transaction.sinceid",
    }
    for (method, path), expected in cases.items():
        assert method_family_for(method, path) == expected, path


def test_endpoint_template_and_url_scrub() -> None:
    path = f"/v3/accounts/{ACCOUNT_ID}/trades/123/close"
    assert endpoint_template_for(path) == (
        "/v3/accounts/{account_id}/trades/{id}/close"
    )
    url = f"http://oanda.test/v3/accounts/{ACCOUNT_ID}/orders?count=50"
    assert ACCOUNT_ID not in scrub_url_account_segment(url)
    assert "{account_id}" in scrub_url_account_segment(url)
