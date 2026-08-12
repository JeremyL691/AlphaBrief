"""Process-scoped OANDA practice broker runtime (M01-W04).

The API lifespan, CLI broker commands, and the scheduler resolve the
same runtime factory and persistent data directory authority, so
in-memory idempotency state cannot diverge between entry points.

The runtime owns the single OANDA practice adapter per process. Missing
OANDA credentials fail closed to a not-ready :class:`NullBrokerAdapter`
that can never place, cancel, or read orders. On shutdown, the runtime
flushes the adapter's client-order idempotency mapping into the durable
broker recon store so durable mappings are never discarded.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_execution.broker.errors import BrokerAuthError
from alphabrief_execution.broker.oanda.adapter import OandaPaperAdapter
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    ENV_ACCOUNT_ID,
    ENV_TOKEN,
    OandaPaperConfig,
    load_oanda_paper_config,
)
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
from alphabrief_execution.broker.recon_store import BrokerReconStore

#: Test / dev-only override for the OANDA base URL (mock servers).
ENV_BASE_URL_OVERRIDE = "ALPHABRIEF_OANDA_BASE_URL"

#: Environment variable naming the persistent data directory.
ENV_DATA_DIR = "ALPHABRIEF_DATA_DIR"

#: Default OANDA adapter configuration path (non-secret YAML).
_DEFAULT_CONFIG_PATH = Path("config/oanda_paper.yaml")

#: Default persistent data directory when no env var is set.
_DEFAULT_DATA_DIR = Path.home() / ".alphabrief" / "data"


class NullBrokerAdapter(BrokerAdapter):
    """Fail-closed adapter used when no OANDA credentials are configured.

    The runtime reports not ready and can never place, cancel, or read
    orders; read probes return empty / zero snapshots so observability
    surfaces stay usable in dev and CI.
    """

    async def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=False,
            detail="broker runtime not configured (no OANDA credentials)",
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


def oanda_is_configured(environ: dict[str, str] | None = None) -> bool:
    """Return True when both OANDA credentials are present."""
    source = os.environ if environ is None else environ
    return bool(
        source.get(ENV_TOKEN, "").strip()
        and source.get(ENV_ACCOUNT_ID, "").strip()
    )


def resolve_data_dir(environ: dict[str, str] | None = None) -> Path:
    """Resolve the persistent data directory authority.

    ``ALPHABRIEF_DATA_DIR`` wins; otherwise the default under the user's
    home directory is used. Every application entry point resolves the
    same authority through this function.
    """
    source = os.environ if environ is None else environ
    raw = source.get(ENV_DATA_DIR)
    if raw:
        return Path(raw)
    return _DEFAULT_DATA_DIR


def build_oanda_paper_adapter(
    *,
    config_path: Path | str | None = None,
) -> BrokerAdapter:
    """Build one OANDA practice adapter, fail-closed on missing credentials.

    A live base URL override may be supplied via
    :data:`ENV_BASE_URL_OVERRIDE` for tests pointing at mock servers; an
    ``http://`` scheme is permitted there (``allow_insecure_base_url``)
    and must not point at live trading.
    """
    override = os.environ.get(ENV_BASE_URL_OVERRIDE)
    if override:
        config = OandaPaperConfig(
            base_url=override,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            max_retries=DEFAULT_MAX_RETRIES,
            retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
            allow_insecure_base_url=True,
        )
    else:
        path = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH
        if path.is_file():
            config = load_oanda_paper_config(path)
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
        return NullBrokerAdapter()
    return OandaPaperAdapter(client=client)


class BrokerRuntime:
    """One fail-closed OANDA practice runtime per process."""

    def __init__(
        self,
        *,
        data_dir: Path | str | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self._data_dir = (
            resolve_data_dir() if data_dir is None else Path(data_dir)
        )
        self._config_path = Path(config_path) if config_path is not None else None
        self._adapter: BrokerAdapter | None = None
        self._store: BrokerReconStore | None = None

    @property
    def data_dir(self) -> Path:
        """The persistent data directory authority for this runtime."""
        return self._data_dir

    @property
    def adapter(self) -> BrokerAdapter:
        """The process-scoped broker adapter, built once per runtime."""
        if self._adapter is None:
            if oanda_is_configured():
                self._adapter = build_oanda_paper_adapter(
                    config_path=self._config_path
                )
            else:
                self._adapter = NullBrokerAdapter()
        return self._adapter

    def flush_idempotency(self) -> None:
        """Persist the adapter's client-order mapping into the durable store.

        Durable mappings are never discarded: on shutdown (and on demand)
        the in-memory mapping is upserted into the broker recon store so a
        later process can reconcile against the same client-order IDs.
        """
        adapter = self._adapter
        if not isinstance(adapter, OandaPaperAdapter):
            return
        mappings = adapter.known_mappings()
        if not mappings:
            return
        store = self._open_store()
        for client_order_id, broker_order_id in sorted(mappings.items()):
            store.upsert_order_id_map(
                client_order_id=client_order_id,
                broker_order_id=broker_order_id,
                status="confirmed",
            )

    def close(self) -> None:
        """Flush durable mappings and close the runtime's store.

        The adapter's HTTP client is stateless (urllib per request) and
        needs no explicit close; the recon store connection is closed so
        the process can exit without discarding persisted state.
        """
        try:
            self.flush_idempotency()
        finally:
            if self._store is not None:
                self._store.close()
                self._store = None
            self._adapter = None

    def _open_store(self) -> BrokerReconStore:
        if self._store is None:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._store = BrokerReconStore(
                db_path=self._data_dir / "alphabrief.db"
            )
        return self._store


_runtime: BrokerRuntime | None = None


def get_broker_runtime(*, data_dir: Path | str | None = None) -> BrokerRuntime:
    """Return the process-scoped broker runtime, building it once.

    The first call fixes the runtime for the process; later calls return
    the same instance regardless of arguments. Tests must call
    :func:`reset_broker_runtime` to rebuild with different settings.
    """
    global _runtime
    if _runtime is None:
        _runtime = BrokerRuntime(data_dir=data_dir)
    return _runtime


def reset_broker_runtime() -> None:
    """Close and clear the process-scoped runtime (test isolation)."""
    global _runtime
    if _runtime is not None:
        _runtime.close()
        _runtime = None


__all__ = [
    "BrokerRuntime",
    "ENV_BASE_URL_OVERRIDE",
    "ENV_DATA_DIR",
    "NullBrokerAdapter",
    "build_oanda_paper_adapter",
    "get_broker_runtime",
    "oanda_is_configured",
    "reset_broker_runtime",
    "resolve_data_dir",
]
