"""API-side broker adapter singleton (read-only observability).

Phase 20 wires ONE :class:`BrokerAdapter` into the API process so the
``GET /api/v1/broker/positions`` and ``GET /api/v1/broker/account``
routes can return live reads from an external paper account instead of
the Phase 19 stubs. The singleton is **read-only**: the API never calls
``submit`` / ``cancel`` / ``get_order`` / ``list_orders`` / ``list_fills``
through it — order placement stays inside the operations scheduler and
behind a :class:`RiskDecision`. Account-level exposure *enforcement*
already lives in :class:`alphabrief_risk.RiskGate`; this module closes
the *observability* gap, not the enforcement path.

M01-W04: the API resolves the shared :mod:`alphabrief_execution.broker
.runtime` authority — the same fail-closed OANDA practice factory and
persistent data directory used by the CLI broker commands and the
scheduler, so no entry point can expose conflicting in-memory account
state. With no OANDA credentials the runtime resolves a not-ready null
adapter so the API boots and tests pass without broker credentials.

No credential is ever logged or echoed in an error path.
"""

from __future__ import annotations

from alphabrief_execution.broker.port import BrokerAdapter
from alphabrief_execution.broker.runtime import (
    ENV_BASE_URL_OVERRIDE as ENV_OANDA_BASE_URL,
)
from alphabrief_execution.broker.runtime import (
    NullBrokerAdapter,
    get_broker_runtime,
    reset_broker_runtime,
)

# ---------------------------------------------------------------------------
# Lazy singleton + reset hook
# ---------------------------------------------------------------------------


def get_broker_adapter() -> BrokerAdapter:
    """Return the process-wide broker adapter (shared OANDA runtime).

    The runtime adapter is built on first access, so :func:`create_app`
    (at ``apps.api.main:app = create_app()``) and every test import work
    without requiring credentials.
    """
    return get_broker_runtime().adapter


def has_live_broker() -> bool:
    """Return True when a real (non-null) broker adapter is wired.

    Lets routes and tests distinguish a live OANDA adapter from the
    dev/CI null fallback without leaking the concrete adapter type.
    """
    return not isinstance(get_broker_adapter(), NullBrokerAdapter)


def _reset_broker_adapter() -> None:
    """Clear the cached adapter (for test isolation).

    A cred-bearing test must call this (directly or via the autouse
    fixture in ``tests/test_api_server.py``) so its adapter does not
    leak into the next test.
    """
    reset_broker_runtime()


__all__ = [
    "ENV_OANDA_BASE_URL",
    "get_broker_adapter",
    "has_live_broker",
]
