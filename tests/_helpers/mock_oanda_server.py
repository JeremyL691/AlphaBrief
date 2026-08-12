"""Reusable mock OANDA v20 practice HTTP server for broker adapter tests.

A thread-local ``http.server`` that serves canned OANDA v20 responses.
The server is fully deterministic: routes are programmed in advance and
consumed in order, with a default "ok" fallback. ``requests`` records
every call the server received so tests can assert what the adapter sent.

The server is intentionally minimal: it does not validate the path;
tests assert on ``requests`` to inspect what the adapter sent.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class MockRequest:
    """One captured HTTP request."""

    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class _RouteHandler:
    method: str
    path: str
    status: int
    body: dict[str, Any] | list[Any] | bytes
    content_type: str = "application/json"


class _MockHttpServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying a reference to its mock server."""

    mock_server: MockOandaServer | None = None


class MockOandaServer:
    """A mock OANDA v20 practice server."""

    def __init__(self) -> None:
        self.requests: list[MockRequest] = []
        self._routes: list[_RouteHandler] = []
        self._lock = threading.Lock()
        self._server: _MockHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._host: str | None = None
        self._port: int | None = None

    def on(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        body: dict[str, Any] | list[Any] | bytes,
        content_type: str = "application/json",
    ) -> None:
        """Program one response; routes are consumed in registration order."""
        with self._lock:
            self._routes.append(
                _RouteHandler(
                    method=method.upper(),
                    path=path,
                    status=status,
                    body=body,
                    content_type=content_type,
                )
            )

    def consume(
        self,
        request: MockRequest,
    ) -> _RouteHandler | None:
        """Record one request and return its programmed route.

        Routes are matched by method and path and consumed in registration
        order; an unmatched request falls back to ``{"ok": True}`` at the
        handler level.
        """
        with self._lock:
            self.requests.append(request)
            route = next(
                (
                    candidate
                    for candidate in self._routes
                    if candidate.method == request.method
                    and candidate.path == request.path
                ),
                None,
            )
            if route is not None:
                self._routes.remove(route)
            return route

    def start(self) -> None:
        """Start the server on an ephemeral localhost port in a daemon thread."""
        self._server = _MockHttpServer(("127.0.0.1", 0), _Handler)
        self._server.mock_server = self
        self._host = "127.0.0.1"
        self._port = int(self._server.server_address[1])
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Shut the server down and join its thread."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        self._host = None
        self._port = None

    @property
    def base_url(self) -> str:
        """Return the base URL (without trailing slash) of the running server."""
        if self._host is None or self._port is None:
            raise RuntimeError("mock server is not started")
        return f"http://{self._host}:{self._port}"


class _Handler(BaseHTTPRequestHandler):
    """Serve programmed routes and record every request."""

    def do_GET(self) -> None:
        self._serve()

    def do_POST(self) -> None:
        self._serve()

    def do_PUT(self) -> None:
        self._serve()

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _serve(self) -> None:
        mock = getattr(self.server, "mock_server", None)
        if mock is None:
            self.send_error(500)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        request = MockRequest(
            method=self.command,
            path=self.path,
            headers={key: value for key, value in self.headers.items()},
            body=body,
        )
        route = mock.consume(request)
        if route is None:
            payload = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        payload = (
            route.body
            if isinstance(route.body, bytes)
            else json.dumps(route.body).encode("utf-8")
        )
        self.send_response(route.status)
        self.send_header("Content-Type", route.content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


__all__ = ["MockOandaServer", "MockRequest"]
