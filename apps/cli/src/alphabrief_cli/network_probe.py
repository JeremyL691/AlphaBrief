"""Best-effort HTTPS diagnostics from the LaunchAgent process itself."""

from __future__ import annotations

import errno
import logging
import socket
import ssl
from http.client import HTTPException
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from alphabrief_core.http import ca_bundle_context
from alphabrief_execution.broker.oanda.config import DEFAULT_BASE_URL

_LOGGER = logging.getLogger("alphabrief.run")
_TARGETS = {"OANDA practice": DEFAULT_BASE_URL, "control": "https://example.com/"}
_TIMEOUT_SECONDS = 5.0


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def _failure_reason(exc: Exception) -> str:
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, TimeoutError):
        return "timed out"
    if isinstance(reason, socket.gaierror):
        return "DNS resolution failed"
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "TLS certificate verification failed"
    if isinstance(reason, ssl.SSLError):
        return "TLS handshake failed"
    if isinstance(reason, OSError) and reason.errno is not None:
        return f"{errno.errorcode.get(reason.errno, 'OS error')} (errno {reason.errno})"
    # Raw transport errors may contain proxy details or URLs.
    return type(reason).__name__


def _probe(url: str) -> tuple[bool, str]:
    try:
        opener = build_opener(_NoRedirect(), HTTPSHandler(context=ca_bundle_context()))
        request = Request(url, method="HEAD")
        with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
            return True, f"HTTP {response.status}"
    except HTTPError as exc:
        exc.close()
        return True, f"HTTP {exc.code}"
    except (OSError, HTTPException, ValueError) as exc:
        return False, _failure_reason(exc)


def probe_launchd_network() -> None:
    """Check both origins without credentials, holding startup at most five seconds."""
    results: dict[str, tuple[bool, str]] = {}
    completed: Queue[tuple[str, tuple[bool, str]]] = Queue()

    def check(name: str, url: str) -> None:
        completed.put((name, _probe(url)))

    # DNS is not bounded by urllib's socket timeout. Share one startup
    # deadline and let daemon workers finish independently if it expires.
    deadline = monotonic() + _TIMEOUT_SECONDS
    for name, url in _TARGETS.items():
        try:
            Thread(target=check, args=(name, url), daemon=True).start()
        except RuntimeError:
            results[name] = (False, "could not start probe worker")
    while len(results) < len(_TARGETS):
        try:
            name, result = completed.get(timeout=max(0, deadline - monotonic()))
        except Empty:
            break
        results[name] = result

    oanda_ok, oanda = results.get("OANDA practice", (False, "timed out"))
    control_ok, control = results.get("control", (False, "timed out"))
    summary = f"OANDA practice: {oanda}; example.com: {control}"
    if oanda_ok:
        _LOGGER.info("LaunchAgent startup network probe: %s", summary)
    elif control_ok:
        _LOGGER.warning(
            "LaunchAgent startup network probe: %s. General HTTPS works; "
            "check access to api-fxpractice.oanda.com from the LaunchAgent. "
            "Continuing startup.",
            summary,
        )
    else:
        _LOGGER.warning(
            "LaunchAgent startup network probe: %s. Outbound HTTPS failed for "
            "both targets; compare from Terminal and check macOS outbound "
            "firewall, VPN, or proxy rules for this LaunchAgent. Continuing startup.",
            summary,
        )
