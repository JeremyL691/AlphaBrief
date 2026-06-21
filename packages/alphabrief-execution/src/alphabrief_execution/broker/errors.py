"""Error taxonomy for external broker adapters.

All broker adapters MUST raise only these types (or ``BrokerAdapterError``)
so callers can switch on a stable hierarchy without depending on SDK or
HTTP details.
"""

from __future__ import annotations


class BrokerAdapterError(Exception):
    """Base error for any broker adapter failure."""


class BrokerAuthError(BrokerAdapterError):
    """Raised when credentials are missing or rejected (HTTP 401/403)."""


class BrokerNotFoundError(BrokerAdapterError):
    """Raised when the broker does not know the requested resource (HTTP 404)."""


class BrokerRejectError(BrokerAdapterError):
    """Raised when the broker refuses an order (HTTP 422 or business reject).

    Carries a stable ``reason`` so callers can audit.
    """

    def __init__(self, reason: str, *, broker_code: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.broker_code = broker_code


class BrokerTransientError(BrokerAdapterError):
    """Raised on retryable transport failures (HTTP 5xx, timeout, 429)."""


class BrokerProtocolError(BrokerAdapterError):
    """Raised when the broker response cannot be parsed into the port schema."""


__all__ = [
    "BrokerAdapterError",
    "BrokerAuthError",
    "BrokerNotFoundError",
    "BrokerProtocolError",
    "BrokerRejectError",
    "BrokerTransientError",
]
