"""urllib-based HTTP client for the Alpaca Paper API.

Only the paper endpoint is supported. The base URL is validated at
construction time (must be https:// and must not contain "live").

Concurrency: one client may be shared across many concurrent
``request`` calls because :func:`urllib.request.urlopen` is not
reentrant but the underlying socket pool serializes naturally under
asyncio when each call awaits ``loop.run_in_executor``. Callers must
NOT mutate the client between concurrent awaits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from alphabrief_execution.broker.alpaca.config import (
    AlpacaPaperConfig,
    read_alpaca_credentials,
)
from alphabrief_execution.broker.errors import (
    BrokerAuthError,
    BrokerNotFoundError,
    BrokerProtocolError,
    BrokerRejectError,
    BrokerTransientError,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlpacaHttpResponse:
    """Raw HTTP response, decoded JSON when the body is JSON."""

    status_code: int
    body: bytes
    json_body: dict[str, Any] | list[Any] | None
    headers: dict[str, str]


# Methods that may be retried on transient failure. POST is never retried
# because we cannot guarantee the broker has not already accepted the order.
_RETRIABLE_METHODS: frozenset[str] = frozenset({"GET"})


class AlpacaHttpClient:
    """Synchronous HTTP client for Alpaca Paper. Wrap calls in ``run`` for asyncio."""

    def __init__(
        self,
        *,
        config: AlpacaPaperConfig,
        http_send: Callable[[Request, float], bytes] | None = None,
    ) -> None:
        self._config = config
        self._http_send = http_send or _default_http_send
        self._api_key, self._api_secret = read_alpaca_credentials()

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> AlpacaHttpResponse:
        """Issue one HTTP request and return the decoded response."""
        url = self._build_url(path, params)
        request = self._build_request(method, url, json_body=json_body)
        attempts = self._config.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return self._send_once(request)
            except BrokerTransientError as exc:
                last_error = exc
                if method not in _RETRIABLE_METHODS:
                    raise
                if attempt == attempts - 1:
                    raise
                backoff = self._config.retry_backoff_seconds * (2**attempt)
                _LOGGER.warning(
                    "alpaca transient error on %s %s attempt=%d backoff=%.3fs: %s",
                    method,
                    path,
                    attempt + 1,
                    backoff,
                    exc,
                )
                time.sleep(backoff)
        # Unreachable, but mypy needs it.
        if last_error is not None:
            raise last_error
        raise BrokerTransientError("alpaca request failed without recorded error")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_url(self, path: str, params: dict[str, Any] | None) -> str:
        base = self._config.base_url.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        if not params:
            return f"{base}{path}"
        pieces: list[str] = []
        for key, value in params.items():
            if value is None:
                continue
            pieces.append(f"{_encode(key)}={_encode(str(value))}")
        if not pieces:
            return f"{base}{path}"
        return f"{base}{path}?{'&'.join(pieces)}"

    def _build_request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None,
    ) -> Request:
        data: bytes | None = None
        headers = {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._api_secret,
            "Accept": "application/json",
            "User-Agent": "alphabrief/0.0.0",
        }
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return Request(url, data=data, method=method.upper(), headers=headers)

    def _send_once(self, request: Request) -> AlpacaHttpResponse:
        try:
            raw = self._http_send(request, self._config.timeout_seconds)
        except HTTPError as exc:
            raise _http_error_to_broker_error(exc, request) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise BrokerTransientError(f"alpaca transport error: {exc}") from exc

        decoded = _safe_decode(raw) if raw else None
        return AlpacaHttpResponse(
            status_code=200,
            body=raw,
            json_body=decoded,
            headers={},
        )


async def run_async(
    client: AlpacaHttpClient,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> AlpacaHttpResponse:
    """Awaitable wrapper around the synchronous ``request`` method."""

    return await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.request(method, path, json_body=json_body, params=params),
    )


# ---------------------------------------------------------------------------
# Free helpers
# ---------------------------------------------------------------------------


def _default_http_send(request: Request, timeout_seconds: float) -> bytes:
    from urllib.request import urlopen

    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _encode(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _safe_decode(raw: bytes) -> dict[str, Any] | list[Any] | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BrokerProtocolError(f"alpaca response is not valid UTF-8: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise BrokerProtocolError(f"alpaca response is not valid JSON: {exc}") from exc


def _http_error_to_broker_error(exc: HTTPError, request: Request) -> Exception:
    code = exc.code
    body_text = ""
    try:
        body_text = exc.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — best-effort body capture
        body_text = ""
    if code in (401, 403):
        return BrokerAuthError(
            f"alpaca auth rejected (HTTP {code}): {body_text or exc.reason}"
        )
    if code == 404:
        return BrokerNotFoundError(
            f"alpaca resource not found (HTTP 404) at {request.full_url}"
        )
    if code == 422 or code == 400:
        reason = body_text or exc.reason or "alpaca rejected the request"
        return BrokerRejectError(reason, broker_code=str(code))
    if code == 429 or 500 <= code < 600:
        return BrokerTransientError(
            f"alpaca transient failure (HTTP {code}): {body_text or exc.reason}"
        )
    return BrokerProtocolError(
        f"alpaca unexpected HTTP {code}: {body_text or exc.reason}"
    )


__all__ = ["AlpacaHttpClient", "AlpacaHttpResponse", "run_async"]
