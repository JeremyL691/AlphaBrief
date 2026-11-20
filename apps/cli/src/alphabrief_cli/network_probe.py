"""Best-effort HTTPS diagnostics from the LaunchAgent process itself."""

from __future__ import annotations

import errno
import logging
import socket
import ssl
from http.client import HTTPException
from queue import Empty, Queue
from threading import Thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from alphabrief_core.http import ca_bundle_context
from alphabrief_execution.broker.oanda.config import DEFAULT_BASE_URL

_LOGGER = logging.getLogger("alphabrief.run")
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


def _probe_oanda() -> tuple[bool, str]:
    try:
        opener = build_opener(_NoRedirect(), HTTPSHandler(context=ca_bundle_context()))
        request = Request(DEFAULT_BASE_URL, method="HEAD")
        with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
            return True, f"HTTP {response.status}"
    except HTTPError as exc:
        exc.close()
        return True, f"HTTP {exc.code}"
    except (OSError, HTTPException, ValueError) as exc:
        return False, _failure_reason(exc)


def probe_launchd_network() -> None:
    """Check OANDA without credentials, holding startup at most five seconds."""
    completed: Queue[tuple[bool, str]] = Queue()

    def check() -> None:
        completed.put(_probe_oanda())

    # urllib's socket timeout does not bound DNS or the whole request.
    try:
        Thread(target=check, daemon=True).start()
        reachable, detail = completed.get(timeout=_TIMEOUT_SECONDS)
    except RuntimeError:
        reachable, detail = False, "could not start probe worker"
    except Empty:
        reachable, detail = False, "timed out"

    if reachable:
        _LOGGER.info("LaunchAgent startup network probe: OANDA practice: %s", detail)
    else:
        _LOGGER.warning(
            "LaunchAgent startup network probe: outbound HTTPS to "
            "api-fxpractice.oanda.com failed: %s. If the same host is reachable "
            "from Terminal, check macOS outbound firewall, VPN, or proxy rules "
            "for this LaunchAgent. Continuing startup.",
            detail,
        )
