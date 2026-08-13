"""OANDA failure classification and bounded retry rules (M06-W06).

Auth, validation, broker reject, rate limit, transient server, transport
timeout, disconnect, parse, and unknown-outcome failures map to stable
typed classes with bounded retry eligibility. Mutating requests are never
auto-retried on ambiguous outcomes: a timeout or disconnect after submit
raises ``UnknownOutcomeFailure`` so the caller resolves the outcome by
persisted client identity before anything else.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Literal

from alphabrief_execution.broker.errors import (
    BrokerAdapterError,
    BrokerAuthError,
    BrokerNotFoundError,
    BrokerProtocolError,
    BrokerRejectError,
    BrokerTransientError,
)
from alphabrief_execution.broker.oanda.client import OandaHttpClient

FailureKind = Literal[
    "AUTH",
    "VALIDATION",
    "NOT_FOUND",
    "REJECT",
    "RATE_LIMIT",
    "TRANSIENT_SERVER",
    "TIMEOUT",
    "DISCONNECT",
    "PARSE",
    "UNKNOWN_OUTCOME",
    "TRANSPORT",
]

#: Kinds that are eligible for bounded retry.
_RETRIABLE_KINDS: frozenset[str] = frozenset(
    {"RATE_LIMIT", "TRANSIENT_SERVER", "TIMEOUT", "DISCONNECT"}
)

#: Methods that mutate broker state; their ambiguous outcomes are never
#: auto-retried — they must be resolved by querying the broker.
_MUTATING_METHODS: frozenset[str] = frozenset({"POST", "PUT", "DELETE"})

_HTTP_CLASSIFICATION: dict[int, str] = {
    400: "VALIDATION",
    401: "AUTH",
    403: "AUTH",
    404: "NOT_FOUND",
    422: "REJECT",
    429: "RATE_LIMIT",
}

_HTTP_5XX = re.compile(r"^5\d\d$")

#: Marker phrases inside BrokerTransientError messages.
_TIMEOUT_MARKERS = ("timed out", "timeout")
_DISCONNECT_MARKERS = (
    "ssl handshake",
    "connection reset",
    "connection refused",
    "connection aborted",
    "broken pipe",
)
_RATE_LIMIT_MARKER = "http 429"
_TRANSIENT_HTTP = re.compile(r"http (5\d\d)")


@dataclass(frozen=True)
class FailureClassification:
    """One stable typed failure classification."""

    kind: FailureKind
    retriable: bool
    detail: str


class ClassifiedFailure(RuntimeError):
    """A classified, non-retriable-or-exhausted broker failure."""

    def __init__(self, classification: FailureClassification) -> None:
        self.classification = classification
        self.kind = classification.kind
        super().__init__(
            f"oanda failure ({classification.kind}): {classification.detail}"
        )


class UnknownOutcomeFailure(RuntimeError):
    """A submit outcome that is unknown after a timeout or disconnect.

    The request may or may not have been accepted by the broker. It is
    never re-submitted blindly: the caller must resolve the outcome by
    querying with the persisted client identity first.
    """

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        super().__init__(
            f"submit outcome unknown for request {request_id}: "
            "resolve by client identity before retrying"
        )


def classify_http(status_code: int, body_text: str = "") -> FailureClassification:
    """Classify a raw HTTP status code."""
    if status_code in _HTTP_CLASSIFICATION:
        kind: FailureKind = _HTTP_CLASSIFICATION[status_code]  # type: ignore[assignment]
        return FailureClassification(
            kind=kind,
            retriable=kind == "RATE_LIMIT",
            detail=f"http {status_code}: {_snippet(body_text)}",
        )
    if _HTTP_5XX.match(str(status_code)):
        return FailureClassification(
            kind="TRANSIENT_SERVER",
            retriable=True,
            detail=f"http {status_code}: {_snippet(body_text)}",
        )
    return FailureClassification(
        kind="PARSE",
        retriable=False,
        detail=f"unexpected http {status_code}",
    )


def classify_failure(exc: Exception) -> FailureClassification:
    """Classify one broker/transport exception into a stable typed class."""
    if isinstance(exc, BrokerAuthError):
        return FailureClassification("AUTH", False, str(exc))
    if isinstance(exc, BrokerNotFoundError):
        return FailureClassification("NOT_FOUND", False, str(exc))
    if isinstance(exc, BrokerRejectError):
        return FailureClassification("REJECT", False, exc.reason)
    if isinstance(exc, BrokerProtocolError):
        return FailureClassification("PARSE", False, str(exc))
    if isinstance(exc, BrokerTransientError):
        return _classify_transient(str(exc))
    if isinstance(exc, TimeoutError):
        return FailureClassification("TIMEOUT", True, str(exc))
    if isinstance(exc, (ConnectionError, OSError)):
        return FailureClassification("DISCONNECT", True, str(exc))
    if isinstance(exc, BrokerAdapterError):
        return FailureClassification("TRANSIENT_SERVER", True, str(exc))
    return FailureClassification(
        "TRANSPORT", False, f"unclassified failure: {exc!r}"
    )


def is_retriable(kind: FailureKind) -> bool:
    """Return ``True`` when the kind is eligible for bounded retry."""
    return kind in _RETRIABLE_KINDS


def should_retry(kind: FailureKind, attempts: int, max_attempts: int) -> bool:
    """Return ``True`` when a bounded retry is still allowed."""
    if attempts >= max_attempts:
        return False
    return is_retriable(kind)


def _classify_transient(message: str) -> FailureClassification:
    lowered = message.lower()
    if _RATE_LIMIT_MARKER in lowered:
        return FailureClassification(
            "RATE_LIMIT", True, "rate limit (HTTP 429)"
        )
    match = _TRANSIENT_HTTP.search(lowered)
    if match is not None:
        return FailureClassification(
            "TRANSIENT_SERVER", True, f"transient server (HTTP {match.group(1)})"
        )
    if any(marker in lowered for marker in _TIMEOUT_MARKERS):
        return FailureClassification("TIMEOUT", True, "transport timeout")
    if any(marker in lowered for marker in _DISCONNECT_MARKERS):
        return FailureClassification("DISCONNECT", True, "transport disconnect")
    return FailureClassification("TRANSIENT_SERVER", True, message)


def _snippet(body_text: str) -> str:
    return body_text[:200]


class ClassifiedRequestExecutor:
    """Executes requests with classification, bounded retry, and telemetry.

    Retry rules:
    - read methods retry bounded times on rate limit, transient server,
      timeout, and disconnect;
    - rate limit (429) on a mutating method is definitively unprocessed
      and retried bounded times;
    - timeout, disconnect, or transient-server on a mutating method is
      ambiguous: ``UnknownOutcomeFailure`` is raised instead of an
      auto-retry, so the caller resolves by persisted client identity.
    """

    def __init__(
        self,
        client: OandaHttpClient,
        *,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
        telemetry: Any | None = None,
    ) -> None:
        self._client = client
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._telemetry = telemetry

    def execute(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> Any:
        """Run one request under the bounded classification rules."""
        method = method.upper()
        attempts = 0
        while True:
            attempts += 1
            started = time.monotonic()
            try:
                response = self._client.request(
                    method, path, json_body=json_body, params=params
                )
                self._record(
                    method,
                    path,
                    status="200",
                    latency_ms=_latency_ms(started),
                    attempts=attempts,
                    error_class=None,
                    request_id=request_id,
                    json_body=json_body,
                )
                return response
            except BrokerAdapterError as exc:
                classification = classify_failure(exc)
                latency = _latency_ms(started)
                if (
                    method in _MUTATING_METHODS
                    and classification.kind
                    in ("TIMEOUT", "DISCONNECT", "TRANSIENT_SERVER")
                ):
                    self._record(
                        method,
                        path,
                        status=classification.kind,
                        latency_ms=latency,
                        attempts=attempts,
                        error_class=classification.kind,
                        request_id=request_id,
                        json_body=json_body,
                    )
                    raise UnknownOutcomeFailure(request_id or path) from exc
                if should_retry(
                    classification.kind, attempts, self._max_attempts
                ):
                    time.sleep(
                        self._retry_backoff_seconds * (2 ** (attempts - 1))
                    )
                    continue
                self._record(
                    method,
                    path,
                    status=classification.kind,
                    latency_ms=latency,
                    attempts=attempts,
                    error_class=classification.kind,
                    request_id=request_id,
                    json_body=json_body,
                )
                raise ClassifiedFailure(classification) from exc

    def _record(
        self,
        method: str,
        path: str,
        *,
        status: str,
        latency_ms: int,
        attempts: int,
        error_class: str | None,
        request_id: str | None,
        json_body: dict[str, Any] | None,
    ) -> None:
        if self._telemetry is None:
            return
        try:
            self._telemetry.record(
                method=method,
                path=path,
                status=status,
                latency_ms=latency_ms,
                attempts=attempts,
                error_class=error_class,
                correlation_id=request_id,
                had_body=json_body is not None,
            )
        except Exception:  # noqa: BLE001 — telemetry must never break execution
            pass


def _latency_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


__all__ = [
    "ClassifiedFailure",
    "ClassifiedRequestExecutor",
    "FailureClassification",
    "FailureKind",
    "UnknownOutcomeFailure",
    "classify_failure",
    "classify_http",
    "is_retriable",
    "should_retry",
]
