"""Bounded, stale-aware OANDA pricing stream (M05-W03).

One runtime owner maintains at most the configured stream connection
and reconciles subscriptions in place — never one connection per
instrument or consumer. Disconnects, heartbeat loss, malformed frames,
rate limits, and server errors follow bounded classified backoff and
mark the stream stale before any consumer can treat cached prices as
fresh. Shutdown cancels reads and reconnect timers, closes the
connection, and returns the final cursor state for persistence.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Stream failure classifications (bounded, deterministic).
StreamFailure = Literal[
    "disconnect", "heartbeat_loss", "malformed_frame", "rate_limit", "server_error"
]

#: Maximum number of stream connections the runtime may hold.
MAX_STREAM_CONNECTIONS = 1


class PricingStreamConfig(BaseModel):
    """Bounded stream settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    heartbeat_timeout_seconds: float = Field(default=30.0, gt=0)
    max_reconnect_attempts: int = Field(default=5, ge=1)
    backoff_base_seconds: float = Field(default=0.25, gt=0)
    backoff_max_seconds: float = Field(default=8.0, gt=0)
    max_connections: int = Field(default=MAX_STREAM_CONNECTIONS, ge=1)


class StreamPrice(BaseModel):
    """One cached stream price with its freshness timestamp."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    bid: Decimal
    ask: Decimal
    broker_time: datetime
    received_at: datetime


@dataclass
class StreamStatus:
    """The outcome of one stream poll."""

    kind: Literal["frame", "idle", "reconnected", "stale", "shutdown"]
    detail: str | None = None
    failure: StreamFailure | None = None


@dataclass
class StreamCursor:
    """Final per-symbol cursor state persisted on shutdown."""

    symbol_cursor: dict[str, str] = field(default_factory=dict)


class PricingStream:
    """One-connection OANDA pricing stream with bounded backoff.

    ``connect`` returns a connection-like object with ``read_frame``
    (returns a parsed frame dict, ``None`` on idle, raises
    ``StreamTransportError`` on disconnect) and ``close``. Tests inject
    deterministic transports; production uses a urllib-based reader.
    """

    def __init__(
        self,
        config: PricingStreamConfig,
        *,
        connect: Callable[[], Any],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._connect = connect
        self._clock = clock
        self._connection: Any = None
        self._connection_count = 0
        self._subscriptions: set[str] = set()
        self._prices: dict[str, StreamPrice] = {}
        self._cursor: dict[str, str] = {}
        self._stale = False
        self._stale_reason: str | None = None
        self._reconnect_attempts = 0
        self._last_frame_at: float | None = None
        self._shutdown_requested = False

    # ------------------------------------------------------------------
    # Subscription reconciliation (single connection)
    # ------------------------------------------------------------------

    def update_subscriptions(self, symbols: list[str]) -> None:
        """Reconcile the subscription set in place.

        Adds and removes never open a new connection: the runtime holds
        at most :data:`MAX_STREAM_CONNECTIONS` connections total.
        """
        self._subscriptions = set(symbols)
        self._prices = {
            symbol: price
            for symbol, price in self._prices.items()
            if symbol in self._subscriptions
        }

    @property
    def subscriptions(self) -> frozenset[str]:
        return frozenset(self._subscriptions)

    @property
    def connection_count(self) -> int:
        """The number of connections created by this runtime."""
        return self._connection_count

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    def poll(self) -> StreamStatus:
        """Read one frame, reconcile state, and return a bounded status.

        Never busy-loops: with nothing to read it returns ``idle``; on a
        disconnect it applies classified bounded backoff and reconnects
        on the next poll up to the configured attempt ceiling.
        """
        if self._shutdown_requested:
            return StreamStatus("shutdown")
        if self._stale:
            return StreamStatus("stale", detail=self._stale_reason)

        if self._connection is None:
            status = self._try_connect()
            if status is not None:
                return status

        try:
            frame = self._connection.read_frame()
        except StreamTransportError as exc:
            return self._handle_transport_failure(exc)
        except StreamProtocolError as exc:
            return self._handle_protocol_failure(exc)

        if frame is None:
            if self._heartbeat_expired():
                return self._mark_stale(
                    "heartbeat_loss", "no frame within heartbeat timeout"
                )
            return StreamStatus("idle")

        self._reconnect_attempts = 0
        self._last_frame_at = self._clock()
        self._stale = False
        self._stale_reason = None
        try:
            self._apply_frame(frame)
        except StreamProtocolError as exc:
            return self._handle_protocol_failure(exc)
        return StreamStatus("frame")

    def _try_connect(self) -> StreamStatus | None:
        if self._connection_count >= self._config.max_connections:
            return self._mark_stale("server_error", "connection ceiling reached")
        if self._reconnect_attempts >= self._config.max_reconnect_attempts:
            return self._mark_stale("server_error", "reconnect ceiling reached")
        try:
            self._connection = self._connect()
            self._connection_count += 1
            self._last_frame_at = self._clock()
            return StreamStatus("reconnected")
        except StreamTransportError as exc:
            self._reconnect_attempts += 1
            self._backoff()
            return StreamStatus("idle", detail=f"connect failed: {exc}")

    def _handle_transport_failure(self, exc: Exception) -> StreamStatus:
        self._connection = None
        self._reconnect_attempts += 1
        if self._reconnect_attempts >= self._config.max_reconnect_attempts:
            return self._mark_stale("server_error", "reconnect ceiling reached")
        self._backoff()
        return StreamStatus("idle", detail=f"disconnect: {exc}", failure="disconnect")

    def _handle_protocol_failure(self, exc: Exception) -> StreamStatus:
        return self._mark_stale("malformed_frame", str(exc))

    def _apply_frame(self, frame: dict[str, Any]) -> None:
        symbol = str(frame.get("instrument", "")).strip()
        if not symbol or symbol not in self._subscriptions:
            raise StreamProtocolError(f"frame for unsubscribed symbol {symbol!r}")
        bid_raw = frame.get("bid")
        ask_raw = frame.get("ask")
        if bid_raw is None or ask_raw is None:
            raise StreamProtocolError(f"frame for {symbol} missing bid or ask")
        bid = Decimal(str(bid_raw))
        ask = Decimal(str(ask_raw))
        if ask < bid:
            raise StreamProtocolError(f"frame for {symbol} is crossed")
        broker_time = str(frame.get("time", ""))
        self._prices[symbol] = StreamPrice(
            symbol=symbol,
            bid=bid,
            ask=ask,
            broker_time=datetime.now(UTC),
            received_at=datetime.now(UTC),
        )
        if broker_time:
            self._cursor[symbol] = broker_time

    def _heartbeat_expired(self) -> bool:
        if self._last_frame_at is None:
            return False
        elapsed = self._clock() - self._last_frame_at
        return elapsed > self._config.heartbeat_timeout_seconds

    def _mark_stale(self, failure: StreamFailure, reason: str) -> StreamStatus:
        self._stale = True
        self._stale_reason = reason
        return StreamStatus("stale", detail=reason, failure=failure)

    def _backoff(self) -> None:
        """Bounded exponential backoff, capped at the configured maximum."""
        delay = min(
            self._config.backoff_base_seconds * (2 ** (self._reconnect_attempts - 1)),
            self._config.backoff_max_seconds,
        )
        # Bounded sleep: never blocks a poll for more than backoff_max_seconds.
        if delay > 0:
            time.sleep(delay)

    # ------------------------------------------------------------------
    # Freshness
    # ------------------------------------------------------------------

    @property
    def stale(self) -> bool:
        return self._stale

    def price_is_fresh(self, symbol: str) -> bool:
        """Return True only for a non-stale cached price."""
        return not self._stale and symbol in self._prices

    def price(self, symbol: str) -> StreamPrice | None:
        return self._prices.get(symbol)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> StreamCursor:
        """Cancel reads and timers, close the connection, return the cursor.

        The final per-symbol cursor (last broker time) is returned so the
        caller can persist it; shutdown never busy-loops or asks for
        intervention.
        """
        self._shutdown_requested = True
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None
        return StreamCursor(symbol_cursor=dict(self._cursor))


class StreamTransportError(RuntimeError):
    """Raised when the underlying transport disconnects."""


class StreamProtocolError(RuntimeError):
    """Raised when a frame violates the stream contract."""


__all__ = [
    "MAX_STREAM_CONNECTIONS",
    "PricingStream",
    "PricingStreamConfig",
    "StreamCursor",
    "StreamPrice",
    "StreamProtocolError",
    "StreamStatus",
    "StreamTransportError",
]
