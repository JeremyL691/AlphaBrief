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

Adapter selection reuses the same logic the CLI ``scheduler run`` command
uses (``apps/cli/src/alphabrief_cli/scheduler_commands.py``): prefer a
real :class:`OandaPaperAdapter` when ``ALPHABRIEF_OANDA_TOKEN`` and
``ALPHABRIEF_OANDA_ACCOUNT_ID`` are set, otherwise build
:class:`AlpacaPaperAdapter` when ``ALPHABRIEF_ALPACA_KEY`` and
``ALPHABRIEF_ALPACA_SECRET`` are set, otherwise fall back to a
:class:`_NullBrokerAdapter` so the API boots and tests pass without
broker credentials. This selection logic is intentionally duplicated
here rather than imported from the CLI — importing the CLI into the API
would invert the layering. ``ponytail:duplicated-adapter-factory``: the
upgrade path is to promote the factory into
``alphabrief_execution.broker`` and have both the API and the CLI call
it; deferred until a second caller justifies the move.

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

#: When set, overrides the Alpaca base URL used by the live adapter.
#: Intended for tests that point the adapter at a mock Alpaca server
#: without writing a YAML config. The value is only read when credentials
#: are present and must still satisfy the paper-only validation in
#: :class:`AlpacaPaperConfig` (an ``http://`` mock requires
#: ``allow_insecure_base_url=True``, which the factory sets for it).
ENV_ALPACA_BASE_URL = "ALPHABRIEF_ALPACA_BASE_URL"

# ---------------------------------------------------------------------------
# Null adapter (dev / CI fallback when no broker credentials are set)
# ---------------------------------------------------------------------------


class _NullBrokerAdapter(BrokerAdapter):
    """No-op broker adapter used when no Alpaca credentials are configured.

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


def _alpaca_is_configured() -> bool:
    """Return True when both Alpaca credentials are present in the environment."""
    return bool(
        os.environ.get("ALPHABRIEF_ALPACA_KEY")
        and os.environ.get("ALPHABRIEF_ALPACA_SECRET")
    )


def _build_broker_adapter() -> BrokerAdapter:
    """Build the routed broker adapter for the runtime environment.

    FX / metals / index CFDs route to OANDA practice and US equities /
    crypto route to Alpaca paper when their credentials are present;
    venues without credentials fall back to the built-in simulated
    adapter. With no credentials at all, fall back to
    :class:`_NullBrokerAdapter` so the API boots in dev / CI.

    Live base URL overrides may be supplied via :data:`ENV_OANDA_BASE_URL`
    or :data:`ENV_ALPACA_BASE_URL` for tests pointing at mock servers; an
    ``http://`` scheme is permitted there (``allow_insecure_base_url``)
    and must not point at live trading.
    """
    from alphabrief_execution.broker.routing import RoutingBrokerAdapter

    oanda = _build_oanda_adapter() if _oanda_is_configured() else None
    alpaca = _build_alpaca_adapter() if _alpaca_is_configured() else None
    if oanda is None and alpaca is None:
        return _NullBrokerAdapter()
    return RoutingBrokerAdapter(oanda=oanda, alpaca=alpaca)


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


def _build_alpaca_adapter() -> BrokerAdapter:
    """Build an Alpaca paper adapter from env credentials and YAML config."""
    # Local imports so the module imports cleanly without Alpaca config
    # present and without constructing the client (which reads creds) at
    # import time.
    from alphabrief_execution.broker.alpaca.adapter import AlpacaPaperAdapter
    from alphabrief_execution.broker.alpaca.client import AlpacaHttpClient
    from alphabrief_execution.broker.alpaca.config import (
        DEFAULT_BASE_URL,
        DEFAULT_MAX_RETRIES,
        DEFAULT_RETRY_BACKOFF_SECONDS,
        DEFAULT_TIMEOUT_SECONDS,
        AlpacaPaperConfig,
        load_alpaca_paper_config,
    )

    override = os.environ.get(ENV_ALPACA_BASE_URL)
    if override:
        # Test / dev mock override. allow_insecure_base_url permits an
        # http:// mock; the paper-only "live" check still applies.
        config = AlpacaPaperConfig(
            base_url=override,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            max_retries=DEFAULT_MAX_RETRIES,
            retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
            allow_insecure_base_url=True,
        )
    else:
        config_path = Path("config/alpaca_paper.yaml")
        if config_path.exists():
            config = load_alpaca_paper_config(config_path)
        else:
            # Dev fallback: explicit defaults rather than a default
            # constructor because AlpacaPaperConfig fields are required.
            config = AlpacaPaperConfig(
                base_url=DEFAULT_BASE_URL,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                max_retries=DEFAULT_MAX_RETRIES,
                retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
            )
    try:
        client = AlpacaHttpClient(config=config)
    except BrokerAuthError:
        # Credentials were present but rejected at client construction.
        # Degrade to the null adapter rather than failing to boot the API.
        return _NullBrokerAdapter()
    return AlpacaPaperAdapter(client=client)


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

    Lets routes and tests distinguish a live Alpaca adapter from the
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
    "ENV_ALPACA_BASE_URL",
    "ENV_OANDA_BASE_URL",
    "get_broker_adapter",
    "has_live_broker",
]
