"""Unknown submit-outcome resolution and fail-closed gating (M06-W06).

After a timeout or disconnect on a submit, the broker may or may not
have accepted the order. This module resolves the outcome by querying
with the persisted client identity — never by guessing and never by
re-submitting. An unresolved outcome freezes further submission instead
of asking the user.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from alphabrief_execution.broker.errors import BrokerAdapterError
from alphabrief_execution.broker.oanda.order_ops import OrderOpsClient

SubmitResolution = Literal[
    "RESOLVED_ACCEPTED",
    "RESOLVED_NOT_SUBMITTED",
    "UNRESOLVED",
]

#: Bounded exhaustive search: never page forever.
MAX_SEARCH_PAGES = 1000


class FrozenSubmissionError(RuntimeError):
    """Raised when submission is frozen by an unresolved outcome."""


class SubmitResolutionResult(BaseModel):
    """One deterministic resolution verdict for an unknown submit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resolution: SubmitResolution
    broker_order_id: str | None = None
    state: str | None = None
    detail: str


class UnknownOutcomeResolver:
    """Resolves unknown submit outcomes by persisted client identity.

    The resolution is always a query, never a re-submit:
    - the order list is searched exhaustively (bounded pages) for the
      ``clientExtensions.id`` that was persisted before the submit;
    - a match means the broker accepted the order;
    - an exhaustive no-match means the submit never reached the broker;
    - a failed or truncated search means the outcome is unresolved.
    """

    def __init__(
        self,
        orders: OrderOpsClient,
        *,
        page_size: int = 50,
        max_pages: int = MAX_SEARCH_PAGES,
    ) -> None:
        self._orders = orders
        self._page_size = page_size
        self._max_pages = max_pages

    def resolve(
        self,
        client_order_id: str,
        *,
        request_id: str | None = None,
    ) -> SubmitResolutionResult:
        """Query the broker for the client identity and return a verdict."""
        if not client_order_id.strip():
            raise ValueError("client_order_id must not be empty")
        try:
            page = 1
            while True:
                if page > self._max_pages:
                    return SubmitResolutionResult(
                        resolution="UNRESOLVED",
                        detail=(
                            f"search exceeded {self._max_pages} pages; "
                            "outcome remains unknown"
                        ),
                    )
                listing = self._orders.list_orders(
                    page=page,
                    page_size=self._page_size,
                    request_id=request_id or f"resolve-{client_order_id}",
                )
                for order in listing.orders:
                    if order.client_order_id == client_order_id:
                        return SubmitResolutionResult(
                            resolution="RESOLVED_ACCEPTED",
                            broker_order_id=order.broker_order_id,
                            state=order.state,
                            detail="order accepted by the broker",
                        )
                if not listing.has_more:
                    return SubmitResolutionResult(
                        resolution="RESOLVED_NOT_SUBMITTED",
                        detail=(
                            f"no order with client identity {client_order_id!r} "
                            "exists at the broker"
                        ),
                    )
                page += 1
        except BrokerAdapterError as exc:
            return SubmitResolutionResult(
                resolution="UNRESOLVED",
                detail=f"resolution query failed: {exc}",
            )


class SubmissionGate:
    """Fail-closed gate: a frozen gate blocks every further submission."""

    def __init__(self) -> None:
        self._frozen = False
        self._reason: str | None = None

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def reason(self) -> str | None:
        return self._reason

    def freeze(self, reason: str) -> None:
        """Freeze all further submission with a durable reason."""
        self._frozen = True
        self._reason = reason

    def ensure_open(self) -> None:
        """Raise when the gate is frozen; safe to submit otherwise."""
        if self._frozen:
            raise FrozenSubmissionError(
                self._reason or "submission is frozen by an unresolved outcome"
            )


__all__ = [
    "FrozenSubmissionError",
    "MAX_SEARCH_PAGES",
    "SubmissionGate",
    "SubmitResolution",
    "SubmitResolutionResult",
    "UnknownOutcomeResolver",
]
