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

M01-W02: OANDA practice is the only execution venue. The adapter is a
real :class:`OandaPaperAdapter` when ``ALPHABRIEF_OANDA_TOKEN`` and
``ALPHABRIEF_OANDA_ACCOUNT_ID`` are set, otherwise a fail-closed
:class:`_NullBrokerAdapter` so the API boots and tests pass without
broker credentials.

The singleton is built lazily on first access so :func:`create_app`
(at ``apps.api.main:app = create_app()``) and every test import without
requiring credentials. A reset hook (:func:`_reset_broker_adapter`)
mirrors the ``_reset_broker`` pattern in ``routes/paper.py`` so a
cred-bearing test cannot leak its adapter into the next.

No credential is ever logged or echoed in an error path.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_execution.broker.errors import BrokerAuthError
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderStatus,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)

# ---------------------------------------------------------------------------
# Test / dev-only env override
# ---------------------------------------------------------------------------

#: When set, overrides the OANDA base URL used by the live adapter.
#: Intended for tests that point the adapter at a mock OANDA server.
ENV_OANDA_BASE_URL = "ALPHABRIEF_OANDA_BASE_URL"

# ---------------------------------------------------------------------------
# Null adapter (dev / CI fallback when no broker credentials are set)
# ---------------------------------------------------------------------------


class _NullBrokerAdapter(BrokerAdapter):
    """No-op broker adapter used when no OANDA credentials are configured.

    Read probes return empty / zero snapshots so the API boots and the
    scheduler stays healthy in dev and CI. The API only ever reads
    through this adapter — ``submit`` / ``cancel`` / ``get_order`` raise
    ``NotImplementedError`` to make accidental order placement impossible.
    """

    async def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=True,
            detail="null adapter (no broker credentials configured)",
            checked_at=datetime.now(UTC),
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        raise NotImplementedError("null adapter does not accept orders")

    async def cancel(self, broker_order_id: str) -> CancelResult:
        raise NotImplementedError("null adapter does not cancel orders")

    async def get_order(self, broker_order_id: str) -> OrderState:
        raise NotImplementedError("null adapter has no order state")

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        return []

    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        return []

    async def get_positions(self) -> list[Position]:
        return []

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="null-adapter",
            cash=Decimal("0"),
            equity=Decimal("0"),
            buying_power=Decimal("0"),
            currency="USD",
            captured_at=datetime.now(UTC),
        )


# ---------------------------------------------------------------------------
# Adapter factory
# ---------------------------------------------------------------------------


def _oanda_is_configured() -> bool:
    """Return True when both OANDA credentials are present in the environment."""
    return bool(
        os.environ.get("ALPHABRIEF_OANDA_TOKEN")
        and os.environ.get("ALPHABRIEF_OANDA_ACCOUNT_ID")
    )


def _build_broker_adapter() -> BrokerAdapter:
    """Build the OANDA practice adapter for the runtime environment.

    OANDA practice is the only execution venue (M01-W02). With no OANDA
    credentials the API resolves a fail-closed null adapter so it boots in
    dev / CI; the null adapter never submits or cancels orders.

    A live base URL override may be supplied via :data:`ENV_OANDA_BASE_URL`
    for tests pointing at mock servers; an ``http://`` scheme is permitted
    there (``allow_insecure_base_url``) and must not point at live trading.
    """
    if not _oanda_is_configured():
        return _NullBrokerAdapter()
    return _build_oanda_adapter()


def _build_oanda_adapter() -> BrokerAdapter:
    """Build an OANDA paper adapter from env credentials and YAML config."""
    from alphabrief_execution.broker.oanda.adapter import OandaPaperAdapter
    from alphabrief_execution.broker.oanda.client import OandaHttpClient
    from alphabrief_execution.broker.oanda.config import (
        DEFAULT_BASE_URL,
        DEFAULT_MAX_RETRIES,
        DEFAULT_RETRY_BACKOFF_SECONDS,
        DEFAULT_TIMEOUT_SECONDS,
        OandaPaperConfig,
        load_oanda_paper_config,
    )

    override = os.environ.get(ENV_OANDA_BASE_URL)
    if override:
        config = OandaPaperConfig(
            base_url=override,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            max_retries=DEFAULT_MAX_RETRIES,
            retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
            allow_insecure_base_url=True,
        )
    else:
        config_path = Path("config/oanda_paper.yaml")
        if config_path.exists():
            config = load_oanda_paper_config(config_path)
        else:
            config = OandaPaperConfig(
                base_url=DEFAULT_BASE_URL,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                max_retries=DEFAULT_MAX_RETRIES,
                retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
            )
    try:
        client = OandaHttpClient(config=config)
    except BrokerAuthError:
        return _NullBrokerAdapter()
    return OandaPaperAdapter(client=client)


# ---------------------------------------------------------------------------
# Lazy singleton + reset hook
# ---------------------------------------------------------------------------

_adapter: BrokerAdapter | None = None


def get_broker_adapter() -> BrokerAdapter:
    """Return the process-wide broker adapter, building it on first access."""
    global _adapter
    if _adapter is None:
        _adapter = _build_broker_adapter()
    return _adapter


def has_live_broker() -> bool:
    """Return True when a real (non-null) broker adapter is wired.

    Lets routes and tests distinguish a live OANDA adapter from the
    dev/CI null fallback without leaking the concrete adapter type.
    """
    return not isinstance(get_broker_adapter(), _NullBrokerAdapter)


def _reset_broker_adapter() -> None:
    """Clear the cached adapter (for test isolation).

    A cred-bearing test must call this (directly or via the autouse
    fixture in ``tests/test_api_server.py``) so its adapter does not
    leak into the next test.
    """
    global _adapter
    _adapter = None


__all__ = [
    "ENV_OANDA_BASE_URL",
    "get_broker_adapter",
    "has_live_broker",
]
