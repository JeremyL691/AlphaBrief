"""Zero-dependency API client for CLI commands that proxy through the API.

When the AlphaBrief API server is running, CLI commands that need the DuckDB
database can transparently route through HTTP endpoints instead of opening
their own DuckDB connection.  This avoids cross-process file-lock conflicts
(DuckDB's single-writer architecture).

Usage::

    from alphabrief_cli.api_client import is_api_running

    if is_api_running():
        # use HTTP
    else:
        # use direct DB

All functions use ``urllib.request`` (stdlib) — no external HTTP dependency.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# Defaults & helpers
# ---------------------------------------------------------------------------

_DEFAULT_BASE = "http://127.0.0.1:8000"


def _base_url() -> str:
    """Return the API base URL, overridable via ``ALPHABRIEF_API_URL``."""
    return os.environ.get("ALPHABRIEF_API_URL") or _DEFAULT_BASE


def is_api_running() -> bool:
    """Return ``True`` if the API server responds on ``/health``.

    When ``ALPHABRIEF_DATA_DIR`` is set (test isolation), always return
    ``False`` so the CLI never proxies through an external API server
    and uses the isolated test DB directly instead.
    """
    if os.environ.get("ALPHABRIEF_DATA_DIR"):
        return False
    url = f"{_base_url()}/health"
    try:
        resp = urllib.request.urlopen(url, timeout=2.0)
        return bool(resp.status == 200)
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


# ---------------------------------------------------------------------------
# Strategy spec CRUD
# ---------------------------------------------------------------------------


def api_strategy_create(
    spec: dict[str, Any],
    enabled: bool = False,
) -> dict[str, Any]:
    """POST /api/v1/strategies/specs — create or replace a spec.

    Returns the response dict on success, or raises ``SystemExit(1)``
    on error.
    """
    body = json.dumps({"spec": spec, "enabled": enabled}).encode()
    url = f"{_base_url()}/api/v1/strategies/specs"
    try:
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result: dict[str, Any] = _decode(resp)
            return result
    except urllib.error.HTTPError as exc:
        detail = _try_detail(exc)
        print(
            f"error: API rejected strategy save ({exc.code}): {detail}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"error: API unreachable: {exc}", file=sys.stderr)
        sys.exit(1)


def api_strategy_list(enabled_only: bool | None = None) -> list[dict[str, Any]]:
    """GET /api/v1/strategies/specs — list stored strategy summaries.

    Returns the ``strategies`` list.
    """
    params = ""
    if enabled_only is True:
        params = "?enabled=true"
    elif enabled_only is False:
        params = "?enabled=false"
    url = f"{_base_url()}/api/v1/strategies/specs{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = _decode(resp)
            raw = data.get("strategies", [])
            return list(raw) if isinstance(raw, list) else []
    except urllib.error.HTTPError as exc:
        detail = _try_detail(exc)
        print(
            f"error: API refused list ({exc.code}): {detail}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"error: API unreachable: {exc}", file=sys.stderr)
        sys.exit(1)


def api_strategy_get(strategy_id: str) -> dict[str, Any] | None:
    """GET /api/v1/strategies/specs/{id} — return the full record or ``None``."""
    url = f"{_base_url()}/api/v1/strategies/specs/{_ep(strategy_id)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            result: dict[str, Any] = _decode(resp)
            return result
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        detail = _try_detail(exc)
        print(
            f"error: API refused show ({exc.code}): {detail}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"error: API unreachable: {exc}", file=sys.stderr)
        sys.exit(1)


def api_strategy_set_enabled(strategy_id: str, enabled: bool) -> bool:
    """PATCH /api/v1/strategies/specs/{id} — flip the enabled flag.

    Returns ``True`` if the strategy existed, ``False`` otherwise.
    """
    body = json.dumps({"enabled": enabled}).encode()
    url = f"{_base_url()}/api/v1/strategies/specs/{_ep(strategy_id)}"
    try:
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        req.method = "PATCH"
        with urllib.request.urlopen(req, timeout=10) as resp:
            return bool(resp.status == 200)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        detail = _try_detail(exc)
        print(
            f"error: API refused enable/disable ({exc.code}): {detail}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"error: API unreachable: {exc}", file=sys.stderr)
        sys.exit(1)


def api_strategy_delete(strategy_id: str) -> bool:
    """DELETE /api/v1/strategies/specs/{id} — remove a strategy.

    Returns ``True`` if the strategy existed, ``False`` otherwise.
    """
    url = f"{_base_url()}/api/v1/strategies/specs/{_ep(strategy_id)}"
    try:
        req = urllib.request.Request(url, method="DELETE")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return bool(resp.status == 200)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        detail = _try_detail(exc)
        print(
            f"error: API refused delete ({exc.code}): {detail}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"error: API unreachable: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Strategy signal CRUD (via API)
# ---------------------------------------------------------------------------


def api_signal_create(signal: dict[str, Any], source: str = "other") -> str:
    """POST /api/v1/strategies/signals — persist a signal.

    Returns the ``signal_id`` on success.
    """
    body = json.dumps({"signal": signal, "source": source}).encode()
    url = f"{_base_url()}/api/v1/strategies/signals"
    try:
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _decode(resp)
            sid = data.get("signal_id", "")
            return str(sid) if sid else ""
    except urllib.error.HTTPError as exc:
        detail = _try_detail(exc)
        print(
            f"error: API refused signal save ({exc.code}): {detail}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"error: API unreachable: {exc}", file=sys.stderr)
        sys.exit(1)


def api_signal_list(
    strategy_id: str | None = None,
    symbol: str | None = None,
    source: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """GET /api/v1/strategies/signals — list signal summaries."""
    params_parts: list[str] = []
    if strategy_id is not None:
        params_parts.append(f"strategy_id={_ep(strategy_id)}")
    if symbol is not None:
        params_parts.append(f"symbol={_ep(symbol)}")
    if source is not None:
        params_parts.append(f"source={_ep(source)}")
    if limit is not None:
        params_parts.append(f"limit={int(limit)}")
    qs = ("?" + "&".join(params_parts)) if params_parts else ""
    url = f"{_base_url()}/api/v1/strategies/signals{qs}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = _decode(resp)
            raw = data.get("signals", [])
            return list(raw) if isinstance(raw, list) else []
    except urllib.error.HTTPError as exc:
        detail = _try_detail(exc)
        print(
            f"error: API refused signal list ({exc.code}): {detail}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"error: API unreachable: {exc}", file=sys.stderr)
        sys.exit(1)


def api_signal_get(signal_id: str) -> dict[str, Any] | None:
    """GET /api/v1/strategies/signals/{id} — return the full record."""
    url = f"{_base_url()}/api/v1/strategies/signals/{_ep(signal_id)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            result: dict[str, Any] = _decode(resp)
            return result
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        detail = _try_detail(exc)
        print(
            f"error: API refused signal show ({exc.code}): {detail}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"error: API unreachable: {exc}", file=sys.stderr)
        sys.exit(1)


def api_signal_count(strategy_id: str) -> int:
    """GET /api/v1/strategies/{strategy_id}/signals/count."""
    url = (
        f"{_base_url()}"
        f"/api/v1/strategies/{_ep(strategy_id)}/signals/count"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = _decode(resp)
            raw = data.get("count", 0)
            return int(raw) if raw else 0
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 0
        detail = _try_detail(exc)
        print(
            f"error: API refused signal count ({exc.code}): {detail}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"error: API unreachable: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ep(value: str) -> str:
    """URL-encode a path segment (safest for IDs that might have special chars)."""
    from urllib.parse import quote

    return quote(value, safe="")


def _decode(resp: Any) -> dict[str, Any]:
    """Decode a JSON response, handling edge cases."""
    raw = resp.read()
    if not raw:
        return {}
    result: dict[str, Any] = json.loads(raw.decode())
    return result


def _try_detail(exc: urllib.error.HTTPError) -> str:
    """Try to extract the ``detail`` field from an error response body."""
    try:
        body = exc.read()
        if body:
            data = json.loads(body.decode())
            detail = data.get("detail", "")
            if detail:
                return str(detail)
    except Exception:
        pass
    return str(exc)


# ---------------------------------------------------------------------------
# Operator-friendly error helpers
# ---------------------------------------------------------------------------


def print_api_unavailable_hint(*, command: str = "this command") -> None:
    """Print a helpful hint when the API server is not running.

    The CLI is runnable in two modes:
    - standalone, with the local DuckDB store (works without the API)
    - proxied, with the API server (reads/writes the same store via HTTP)

    Some commands only work in proxied mode. When the proxy mode is
    missing, this helper tells the operator the exact command to start
    the server so they do not have to dig through the docs.
    """
    base = _base_url()
    print(
        f"error: {command} could not reach the API server at {base}.",
        file=sys.stderr,
    )
    print(
        "hint: start the API server first, for example:",
        file=sys.stderr,
    )
    print(
        f"      alphabrief serve serve --host 127.0.0.1 --port {urlparse_port(base)}",
        file=sys.stderr,
    )


def urlparse_port(base: str) -> int:
    """Extract the port from a base URL like ``http://127.0.0.1:8000``.

    Falls back to 8000 when parsing fails so the hint always renders.
    """
    from urllib.parse import urlparse

    parsed = urlparse(base)
    if parsed.port is not None:
        return parsed.port
    return 8000


__all__ = [
    "api_signal_count",
    "api_signal_create",
    "api_signal_get",
    "api_signal_list",
    "api_strategy_create",
    "api_strategy_delete",
    "api_strategy_get",
    "api_strategy_list",
    "api_strategy_set_enabled",
    "is_api_running",
    "print_api_unavailable_hint",
]
