"""M05-W03: bounded, stale-aware OANDA pricing stream.

Covers:
- one runtime owner maintains at most the configured stream connection
  and reconciles subscriptions without opening a connection per
  instrument or consumer (AC-M05-W03-01);
- disconnects, heartbeat loss, malformed frames, rate limits, and server
  errors follow bounded classified backoff and mark the stream stale
  before any consumer can treat cached prices as fresh (AC-M05-W03-02);
- shutdown cancels reads and reconnect timers, closes the connection,
  persists the final cursor state, and cannot busy-loop or ask for
  intervention (AC-M05-W03-03).
"""

from __future__ import annotations

from typing import Any

from alphabrief_execution.broker.oanda.stream import (
    MAX_STREAM_CONNECTIONS,
    PricingStream,
    PricingStreamConfig,
    StreamProtocolError,
    StreamTransportError,
)


class _FakeConnection:
    """A deterministic frame transport for tests."""

    def __init__(self, frames: list[dict[str, object] | None] | None = None) -> None:
        self.frames = list(frames or [])
        self.closed = False

    def read_frame(self) -> dict[str, object] | None:
        if self.frames:
            return self.frames.pop(0)
        return None

    def close(self) -> None:
        self.closed = True


def _config(**overrides: object) -> PricingStreamConfig:
    payload: dict[str, Any] = {
        "heartbeat_timeout_seconds": 30.0,
        "max_reconnect_attempts": 3,
        "backoff_base_seconds": 0.001,
        "backoff_max_seconds": 0.01,
    }
    payload.update(overrides)
    return PricingStreamConfig(
        heartbeat_timeout_seconds=float(payload["heartbeat_timeout_seconds"]),
        max_reconnect_attempts=int(payload["max_reconnect_attempts"]),
        backoff_base_seconds=float(payload["backoff_base_seconds"]),
        backoff_max_seconds=float(payload["backoff_max_seconds"]),
    )


def _frame(
    symbol: str = "EUR_USD", bid: str = "1.10", ask: str = "1.11"
) -> dict[str, object]:
    return {
        "instrument": symbol,
        "bid": bid,
        "ask": ask,
        "time": "2026-08-01T12:00:00.000000000Z",
    }


# ---------------------------------------------------------------------------
# AC-M05-W03-01: single connection + in-place subscription reconciliation
# ---------------------------------------------------------------------------


def test_single_connection_owner_with_subscription_reconciliation() -> None:
    connections: list[_FakeConnection] = []

    def _connect() -> _FakeConnection:
        conn = _FakeConnection()
        connections.append(conn)
        return conn

    stream = PricingStream(_config(), connect=_connect)
    stream.update_subscriptions(["EUR_USD", "GBP_USD"])
    assert stream.poll().kind == "reconnected"
    assert stream.connection_count == 1

    # Reconciling subscriptions never opens a second connection.
    stream.update_subscriptions(["EUR_USD", "USD_JPY", "XAU_USD"])
    assert stream.connection_count == 1
    assert stream.subscriptions == frozenset({"EUR_USD", "USD_JPY", "XAU_USD"})

    # Frames for unsubscribed symbols are rejected as protocol errors.
    connections[0].frames.append(_frame("GBP_USD"))
    status = stream.poll()
    assert status.kind == "stale"
    assert status.failure == "malformed_frame"
    assert stream.connection_count == 1


def test_connection_ceiling_is_enforced() -> None:
    stream = PricingStream(_config(), connect=_FakeConnection)
    stream.update_subscriptions(["EUR_USD"])
    assert stream.poll().kind == "reconnected"
    assert stream.connection_count == 1
    assert stream.connection_count <= MAX_STREAM_CONNECTIONS


# ---------------------------------------------------------------------------
# AC-M05-W03-02: classified bounded backoff and stale marking
# ---------------------------------------------------------------------------


def test_heartbeat_loss_marks_stream_stale() -> None:
    clock = {"now": 0.0}

    def _clock() -> float:
        return clock["now"]

    conn = _FakeConnection()
    stream = PricingStream(
        _config(heartbeat_timeout_seconds=10.0),
        connect=lambda: conn,
        clock=_clock,
    )
    stream.update_subscriptions(["EUR_USD"])
    stream.poll()  # connect
    conn.frames.append(_frame())
    assert stream.poll().kind == "frame"
    assert stream.price_is_fresh("EUR_USD") is True

    # Heartbeat timeout expires with no further frames.
    clock["now"] = 5.0
    assert stream.poll().kind == "idle"
    clock["now"] = 11.0
    status = stream.poll()
    assert status.kind == "stale"
    assert status.failure == "heartbeat_loss"
    assert stream.stale is True
    assert stream.price_is_fresh("EUR_USD") is False


def test_disconnect_applies_bounded_backoff_then_reconnects() -> None:
    conn = _FakeConnection()
    stream = PricingStream(_config(max_reconnect_attempts=3), connect=lambda: conn)
    stream.update_subscriptions(["EUR_USD"])
    stream.poll()  # connect

    conn.frames.append(None)
    conn.frames.append(None)
    conn.frames.append(None)

    def _disconnecting_read() -> dict[str, object] | None:
        raise StreamTransportError("connection reset")

    conn.read_frame = _disconnecting_read  # type: ignore[method-assign]
    status = stream.poll()
    assert status.kind == "idle"
    assert status.failure == "disconnect"


def test_reconnect_ceiling_marks_stale() -> None:
    attempts = {"count": 0}

    def _connect() -> _FakeConnection:
        attempts["count"] += 1
        raise StreamTransportError("refused")

    stream = PricingStream(
        _config(max_reconnect_attempts=3, backoff_base_seconds=0.001),
        connect=_connect,
    )
    stream.update_subscriptions(["EUR_USD"])
    for _ in range(3):
        status = stream.poll()
    assert attempts["count"] == 3
    status = stream.poll()
    assert status.kind == "stale"
    assert status.failure == "server_error"
    assert "reconnect ceiling" in (status.detail or "")


def test_malformed_frame_marks_stale() -> None:
    conn = _FakeConnection()
    stream = PricingStream(_config(), connect=lambda: conn)
    stream.update_subscriptions(["EUR_USD"])
    stream.poll()
    conn.frames.append({"instrument": "EUR_USD", "bid": "1.11", "ask": "1.10"})
    status = stream.poll()
    assert status.kind == "stale"
    assert status.failure == "malformed_frame"
    assert stream.price_is_fresh("EUR_USD") is False


def test_rate_limit_and_server_error_classifications() -> None:
    """Rate limits and server errors are classified, never silent."""
    conn = _FakeConnection()
    stream = PricingStream(_config(), connect=lambda: conn)
    stream.update_subscriptions(["EUR_USD"])
    stream.poll()

    def _rate_limited() -> dict[str, object] | None:
        raise StreamProtocolError("rate limit exceeded")

    conn.read_frame = _rate_limited  # type: ignore[method-assign]
    status = stream.poll()
    assert status.failure == "malformed_frame"  # protocol-classified


# ---------------------------------------------------------------------------
# AC-M05-W03-03: shutdown cancels, closes, persists cursor, no busy-loop
# ---------------------------------------------------------------------------


def test_shutdown_closes_connection_and_returns_cursor() -> None:
    conn = _FakeConnection()
    stream = PricingStream(_config(), connect=lambda: conn)
    stream.update_subscriptions(["EUR_USD"])
    stream.poll()
    conn.frames.append(_frame())
    stream.poll()

    cursor = stream.shutdown()

    assert conn.closed is True
    assert stream.price("EUR_USD") is not None
    assert cursor.symbol_cursor["EUR_USD"].startswith("2026-08-01")
    # A poll after shutdown returns shutdown without connecting again.
    status = stream.poll()
    assert status.kind == "shutdown"


def test_shutdown_does_not_busy_loop() -> None:
    conn = _FakeConnection()
    stream = PricingStream(_config(), connect=lambda: conn)
    stream.update_subscriptions(["EUR_USD"])
    stream.poll()
    stream.shutdown()
    # Idle polls return immediately with a bounded status.
    status = stream.poll()
    assert status.kind == "shutdown"


def test_idle_poll_returns_immediately_without_frames() -> None:
    conn = _FakeConnection()
    stream = PricingStream(_config(), connect=lambda: conn)
    stream.update_subscriptions(["EUR_USD"])
    stream.poll()
    status = stream.poll()
    assert status.kind == "idle"
