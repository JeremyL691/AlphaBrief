"""Reusable mock HTTP server helpers for broker adapter tests.

Two complementary helpers:

- :class:`MockAlpacaServer`: a thread-local ``http.server`` that
  serves canned Alpaca Paper responses. The server is fully
  deterministic: routes are programmed in advance and consumed in
  order, with a default "ok" fallback.

- :func:`start_mock_server`: returns ``(base_url, server, requests)``
  where ``requests`` records every call the server received.

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


class MockAlpacaServer:
    """A mock Alpaca Paper server."""

    def __init__(self) -> None:
        self.requests: list[MockRequest] = []
        self._routes: list[_RouteHandler] = []
        self._default: _RouteHandler | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0
        self.base_url: str = ""

    # ------------------------------------------------------------------
    # Programmable response surface
    # ------------------------------------------------------------------

    def on(self, method: str, path: str, *, status: int, body: Any) -> None:
        """Add a canned response. Consumed in insertion order."""
        if isinstance(body, (dict, list)):
            payload: dict[str, Any] | list[Any] | bytes = body
            content_type = "application/json"
        elif isinstance(body, bytes):
            payload = body
            content_type = "application/octet-stream"
        else:
            raise TypeError(f"unsupported body type: {type(body).__name__}")
        self._routes.append(
            _RouteHandler(
                method=method.upper(),
                path=path,
                status=status,
                body=payload,
                content_type=content_type,
            )
        )

    def set_default(self, *, status: int, body: Any) -> None:
        if isinstance(body, (dict, list)):
            payload: dict[str, Any] | list[Any] | bytes = body
            content_type = "application/json"
        else:
            payload = body if isinstance(body, bytes) else str(body).encode()
            content_type = "application/octet-stream"
        self._default = _RouteHandler(
            method="*", path="*", status=status, body=payload, content_type=content_type
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        server_self = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                # Silence stderr; tests assert on captured requests.
                return

            def _read_body(self) -> bytes:
                length = int(self.headers.get("Content-Length", "0") or "0")
                return self.rfile.read(length) if length else b""

            def _capture(self, method: str) -> None:
                server_self.requests.append(
                    MockRequest(
                        method=method,
                        path=self.path,
                        headers={k: v for k, v in self.headers.items()},
                        body=self._read_body(),
                    )
                )

            def _respond(self, method: str) -> None:
                for route in server_self._routes:
                    if route.method == method and route.path == self.path:
                        server_self._respond_route(self, route)
                        return
                if server_self._default is not None:
                    server_self._respond_route(self, server_self._default)
                    return
                self.send_response(404)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                self._capture("GET")
                self._respond("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._capture("POST")
                self._respond("POST")

            def do_DELETE(self) -> None:  # noqa: N802
                self._capture("DELETE")
                self._respond("DELETE")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self._server.server_address[1])
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    @staticmethod
    def _respond_route(handler: BaseHTTPRequestHandler, route: _RouteHandler) -> None:
        handler.send_response(route.status)
        handler.send_header("Content-Type", route.content_type)
        if isinstance(route.body, bytes):
            handler.send_header("Content-Length", str(len(route.body)))
            handler.end_headers()
            handler.wfile.write(route.body)
        else:
            encoded = json.dumps(route.body).encode("utf-8")
            handler.send_header("Content-Length", str(len(encoded)))
            handler.end_headers()
            handler.wfile.write(encoded)


def start_mock_server() -> tuple[MockAlpacaServer, str]:
    """Start a server and return ``(server, base_url)``."""
    server = MockAlpacaServer()
    server.start()
    return server, server.base_url


__all__ = ["MockAlpacaServer", "MockRequest", "start_mock_server"]
