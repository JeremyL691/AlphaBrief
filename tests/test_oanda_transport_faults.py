"""M06-W06: OANDA failure classification and bounded retry rules.

Covers:
- auth, validation, broker reject, rate limit, transient server,
  transport timeout, disconnect, parse, and unknown-outcome failures map
  to stable typed classes with bounded retry eligibility (AC-M06-W06-01);
- a timeout or disconnect after submit raises ``UnknownOutcomeFailure``
  instead of an auto-retry; unresolved state freezes further submission
  instead of guessing (AC-M06-W06-02, transport half).
"""

from __future__ import annotations

import json
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from alphabrief_execution.broker.errors import (
    BrokerAuthError,
    BrokerNotFoundError,
    BrokerProtocolError,
    BrokerRejectError,
    BrokerTransientError,
)
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import OandaPaperConfig
from alphabrief_execution.broker.oanda.faults import (
    ClassifiedFailure,
    ClassifiedRequestExecutor,
    UnknownOutcomeFailure,
    classify_failure,
    classify_http,
    is_retriable,
    should_retry,
)

ACCOUNT_ID = "101-004-1234567-001"


def _http_client(
    failures: list[tuple[int | Exception, dict[str, Any] | None]],
    captured: list[dict[str, Any]],
) -> OandaHttpClient:
    def _send(request: Request, timeout_seconds: float) -> bytes:
        captured.append({"method": request.method, "url": request.full_url})
        failure = failures.pop(0) if failures else None
        if failure is None:
            return json.dumps({"ok": True}).encode("utf-8")
        code_or_exc, body = failure
        if isinstance(code_or_exc, int):
            raise HTTPError(
                request.full_url, code_or_exc, "boom", Message(), None
            )
        raise code_or_exc

    return OandaHttpClient(
        config=OandaPaperConfig(
            base_url="http://oanda.test",
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.001,
            allow_insecure_base_url=True,
        ),
        http_send=_send,
        token="secret-token",
        account_id=ACCOUNT_ID,
    )


def _executor(
    failures: list[tuple[int | Exception, dict[str, Any] | None]],
    captured: list[dict[str, Any]],
    *,
    max_attempts: int = 3,
) -> ClassifiedRequestExecutor:
    return ClassifiedRequestExecutor(
        _http_client(failures, captured),
        max_attempts=max_attempts,
        retry_backoff_seconds=0.001,
    )


# ---------------------------------------------------------------------------
# AC-M06-W06-01: stable typed classes with bounded retry eligibility
# ---------------------------------------------------------------------------


def test_classify_http_maps_stable_classes() -> None:
    assert classify_http(401).kind == "AUTH"
    assert classify_http(403).kind == "AUTH"
    assert classify_http(400).kind == "VALIDATION"
    assert classify_http(404).kind == "NOT_FOUND"
    assert classify_http(422).kind == "REJECT"
    assert classify_http(429).kind == "RATE_LIMIT"
    assert classify_http(500).kind == "TRANSIENT_SERVER"
    assert classify_http(503).kind == "TRANSIENT_SERVER"
    assert classify_http(599).kind == "TRANSIENT_SERVER"
    assert classify_http(299).kind == "PARSE"


def test_retry_eligibility_is_bounded() -> None:
    assert is_retriable("RATE_LIMIT") is True
    assert is_retriable("TRANSIENT_SERVER") is True
    assert is_retriable("TIMEOUT") is True
    assert is_retriable("DISCONNECT") is True
    assert is_retriable("AUTH") is False
    assert is_retriable("VALIDATION") is False
    assert is_retriable("REJECT") is False
    assert is_retriable("PARSE") is False
    assert is_retriable("NOT_FOUND") is False
    assert is_retriable("UNKNOWN_OUTCOME") is False
    # Bounded: attempts reaching the ceiling stops retrying.
    assert should_retry("RATE_LIMIT", attempts=1, max_attempts=3) is True
    assert should_retry("RATE_LIMIT", attempts=3, max_attempts=3) is False
    assert should_retry("AUTH", attempts=1, max_attempts=3) is False


def test_classify_broker_errors_map_to_classes() -> None:
    assert classify_failure(BrokerAuthError("nope")).kind == "AUTH"
    assert classify_failure(BrokerNotFoundError("missing")).kind == "NOT_FOUND"
    assert classify_failure(BrokerRejectError("bad order")).kind == "REJECT"
    assert classify_failure(BrokerProtocolError("bad json")).kind == "PARSE"


def test_classify_transient_messages() -> None:
    assert classify_failure(
        BrokerTransientError("oanda transient failure (HTTP 429)")
    ).kind == "RATE_LIMIT"
    assert classify_failure(
        BrokerTransientError("oanda transient failure (HTTP 503)")
    ).kind == "TRANSIENT_SERVER"
    assert classify_failure(
        BrokerTransientError("oanda transport error: urlopen error timed out")
    ).kind == "TIMEOUT"
    assert classify_failure(
        BrokerTransientError("oanda transport error: [Errno 54] Connection reset")
    ).kind == "DISCONNECT"
    assert classify_failure(
        BrokerTransientError("oanda ssl handshake error: bad handshake")
    ).kind == "DISCONNECT"


def test_executor_retries_read_bounded_then_succeeds() -> None:
    captured: list[dict[str, Any]] = []
    executor = _executor(
        [(429, None), (503, None)],
        captured,
        max_attempts=3,
    )
    response = executor.execute("GET", f"/v3/accounts/{ACCOUNT_ID}/orders")
    assert response.json_body == {"ok": True}
    assert len(captured) == 3


def test_executor_read_exhausts_retries_fail_closed() -> None:
    captured: list[dict[str, Any]] = []
    executor = _executor(
        [(503, None), (503, None), (503, None), (503, None)],
        captured,
        max_attempts=3,
    )
    with pytest.raises(ClassifiedFailure) as excinfo:
        executor.execute("GET", f"/v3/accounts/{ACCOUNT_ID}/orders")
    assert excinfo.value.kind == "TRANSIENT_SERVER"
    assert len(captured) == 3


def test_executor_non_retriable_never_retries() -> None:
    captured: list[dict[str, Any]] = []
    executor = _executor([(422, {"error": "bad"})], captured)
    with pytest.raises(ClassifiedFailure) as excinfo:
        executor.execute("POST", f"/v3/accounts/{ACCOUNT_ID}/orders")
    assert excinfo.value.kind == "REJECT"
    assert len(captured) == 1


def test_executor_auth_never_retries() -> None:
    captured: list[dict[str, Any]] = []
    executor = _executor([(401, None)], captured)
    with pytest.raises(ClassifiedFailure) as excinfo:
        executor.execute("GET", f"/v3/accounts/{ACCOUNT_ID}/summary")
    assert excinfo.value.kind == "AUTH"
    assert len(captured) == 1


# ---------------------------------------------------------------------------
# AC-M06-W06-02: never auto-retry an ambiguous submit
# ---------------------------------------------------------------------------


def test_submit_timeout_raises_unknown_outcome_without_retry() -> None:
    captured: list[dict[str, Any]] = []
    executor = _executor([(TimeoutError("timed out"), None)], captured)
    with pytest.raises(UnknownOutcomeFailure) as excinfo:
        executor.execute(
            "POST",
            f"/v3/accounts/{ACCOUNT_ID}/orders",
            json_body={"order": {"units": "1000"}},
            request_id="client-order-1",
        )
    assert "client-order-1" in str(excinfo.value)
    # Exactly one submit attempt: never an automatic duplicate.
    assert len(captured) == 1
    assert captured[0]["method"] == "POST"


def test_submit_disconnect_raises_unknown_outcome_without_retry() -> None:
    captured: list[dict[str, Any]] = []
    executor = _executor(
        [(ConnectionResetError("Connection reset by peer"), None)], captured
    )
    with pytest.raises(UnknownOutcomeFailure):
        executor.execute(
            "PUT",
            f"/v3/accounts/{ACCOUNT_ID}/trades/1/close",
            request_id="close-1",
        )
    assert len(captured) == 1


def test_submit_transient_server_is_ambiguous_no_retry() -> None:
    captured: list[dict[str, Any]] = []
    executor = _executor([(503, None)], captured)
    with pytest.raises(UnknownOutcomeFailure):
        executor.execute(
            "POST",
            f"/v3/accounts/{ACCOUNT_ID}/orders",
            request_id="client-order-2",
        )
    assert len(captured) == 1


def test_submit_rate_limit_retries_bounded() -> None:
    captured: list[dict[str, Any]] = []
    executor = _executor([(429, None), (429, None)], captured)
    # 429 is definitively unprocessed: bounded retry is safe.
    response = executor.execute(
        "POST", f"/v3/accounts/{ACCOUNT_ID}/orders", request_id="c3"
    )
    assert response.json_body == {"ok": True}
    assert len(captured) == 3


def test_unknown_outcome_kind_is_never_retriable() -> None:
    assert is_retriable("UNKNOWN_OUTCOME") is False
