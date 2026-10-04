"""Outbound HTTPS transport shared by every AlphaBrief client.

macOS Python builds ship an OpenSSL that does not trust the system
keychain, so a bare :func:`urllib.request.urlopen` fails with
``CERTIFICATE_VERIFY_FAILED`` outside a repository checkout: the
LaunchAgent and the packaged backend have no ``SSL_CERT_FILE`` set.
Every outbound client must go through :func:`secure_urlopen` so the
certifi CA bundle travels with the installation.
"""

from __future__ import annotations

import ssl
from typing import Any
from urllib.request import HTTPSHandler, Request, build_opener

__all__ = ["ca_bundle_context", "secure_urlopen"]


def ca_bundle_context() -> ssl.SSLContext:
    """Default-verify TLS context pinned to the certifi CA bundle.

    Falls back to the interpreter default when certifi is unavailable so
    the failure mode stays a certificate error, never an unverified
    connection.
    """
    try:
        from certifi import where as certifi_where
    except ImportError:  # pragma: no cover - certifi ships with the deps
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi_where())


def secure_urlopen(request: Request, timeout: float) -> Any:
    """Open ``request`` over TLS verified against the certifi bundle."""
    return build_opener(HTTPSHandler(context=ca_bundle_context())).open(
        request, timeout=timeout
    )
