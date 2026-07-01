"""CLI subcommands for the operations scheduler.

Commands
--------

- ``scheduler status``     — aggregate heartbeat / freeze / alert counts.
- ``scheduler heartbeats`` — list per-task heartbeat rows.
- ``scheduler alerts``     — list recent alerts (--limit N).
- ``scheduler tasks``      — list the static default task set.
- ``scheduler freezes``    — list currently-open broker freezes.
- ``scheduler run``        — start the scheduler as a foreground process.

The read-only commands proxy through the API when the server is
running and fall back to the local ``HeartbeatStore`` /
``BrokerReconStore`` otherwise. ``scheduler run`` is CLI-only and
launches the long-running async event loop in-process; it never
proxies through the API because that would block an API worker.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import typer
from alphabrief_core import (
    PaperExecutionPolicy,
    load_paper_execution_policy,
    load_settings,
)
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
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
from alphabrief_execution.broker.reconciliation import ReconciliationRunner
from alphabrief_execution.operations.scheduler import (
    AlertSink,
    HeartbeatStore,
    OperationsScheduler,
    SchedulerConfig,
    SchedulerStartupBlockedError,
    build_default_tasks,
)
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import (
    DailyTradingCycle,
    ExternalPaperExecutionBackend,
    StoredMarketSnapshotBuilder,
    TradingCommittee,
    build_ai_trading_committee,
    is_ai_external_paper_enabled,
    is_ai_trading_enabled,
)

from alphabrief_cli.api_client import (
    is_api_running,
    print_api_unavailable_hint,
)

scheduler_app = typer.Typer(help="Inspect and run the operations scheduler.")


# ---------------------------------------------------------------------------
# Local store helpers (used when the API is not running)
# ---------------------------------------------------------------------------


def _open_heartbeat_store() -> HeartbeatStore:
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return HeartbeatStore(db_path=db_dir / "alphabrief.db")
    return HeartbeatStore()


def _open_recon_store() -> BrokerReconStore:
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return BrokerReconStore(db_path=db_dir / "alphabrief.db")
    return BrokerReconStore()


def _dump(payload: object, *, pretty: bool, default: bool = False) -> None:
    """Write JSON to stdout, formatting Decimal/datetime as strings when needed."""
    json.dump(
        payload,
        sys.stdout,
        indent=2 if pretty else None,
        sort_keys=True,
        default=str if default else None,
    )
    sys.stdout.write("\n")


def _api_url(path: str) -> str:
    base = os.environ.get("ALPHABRIEF_API_URL", "http://127.0.0.1:8000")
    return f"{base}{path}"


def _read_api_json(path: str) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(_api_url(path), timeout=5) as response:
            return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"error: failed to reach {_api_url(path)}: {exc}", file=sys.stderr)
        print_api_unavailable_hint(command="scheduler status")
        sys.exit(1)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@scheduler_app.command("status")
def status_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Print aggregate scheduler state (heartbeats / freezes / alerts)."""
    if is_api_running():
        _dump(_read_api_json("/api/v1/scheduler/status"), pretty=pretty)
        return

    heartbeats = _open_heartbeat_store()
    recon = _open_recon_store()
    try:
        heartbeats_rows = heartbeats.list_heartbeats()
        open_freezes = recon.list_freezes(only_open=True)
        recent_alerts = heartbeats.list_alerts(limit=500)
        payload = {
            "heartbeat_count": len(heartbeats_rows),
            "open_freeze_count": len(open_freezes),
            "alerts_total": len(recent_alerts),
            "running": False,
        }
    finally:
        heartbeats.close()
        recon.close()
    _dump(payload, pretty=pretty)


# ---------------------------------------------------------------------------
# heartbeats
# ---------------------------------------------------------------------------


@scheduler_app.command("heartbeats")
def heartbeats_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """List one row per registered task with last-run state."""
    if is_api_running():
        _dump(_read_api_json("/api/v1/scheduler/heartbeats"), pretty=pretty)
        return
    heartbeats = _open_heartbeat_store()
    try:
        rows = heartbeats.list_heartbeats()
    finally:
        heartbeats.close()
    _dump({"heartbeats": rows}, pretty=pretty)


# ---------------------------------------------------------------------------
# alerts
# ---------------------------------------------------------------------------


@scheduler_app.command("alerts")
def alerts_cmd(
    limit: int = typer.Option(  # noqa: B008
        50,
        "--limit",
        min=1,
        max=500,
        help="Maximum number of alerts to return (clamped to [1, 500]).",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """List recent alerts (newest-first)."""
    if is_api_running():
        _dump(
            _read_api_json(f"/api/v1/scheduler/alerts?limit={limit}"),
            pretty=pretty,
        )
        return
    heartbeats = _open_heartbeat_store()
    try:
        rows = heartbeats.list_alerts(limit=limit)
    finally:
        heartbeats.close()
    _dump({"alerts": rows}, pretty=pretty)


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------


@scheduler_app.command("tasks")
def tasks_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """List the static default task set the scheduler would run."""
    if is_api_running():
        _dump(_read_api_json("/api/v1/scheduler/tasks"), pretty=pretty)
        return

    async def _noop_handler(scope: str) -> None:
        return None

    tasks = build_default_tasks(on_reconcile=_noop_handler)
    _dump(
        {
            "tasks": [
                {
                    "name": task.name,
                    "interval_seconds": task.interval_seconds,
                    "timeout_seconds": task.timeout_seconds,
                    "max_retries": task.max_retries,
                    "enabled": task.enabled,
                }
                for task in tasks
            ]
        },
        pretty=pretty,
    )


# ---------------------------------------------------------------------------
# freezes
# ---------------------------------------------------------------------------


@scheduler_app.command("freezes")
def freezes_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """List currently-open broker freezes."""
    if is_api_running():
        _dump(_read_api_json("/api/v1/scheduler/freezes"), pretty=pretty)
        return
    recon = _open_recon_store()
    try:
        rows = recon.list_freezes(only_open=True)
    finally:
        recon.close()
    _dump(
        {
            "open_freezes": [
                {
                    "event_id": f.event_id,
                    "raised_at": f.raised_at,
                    "scope": f.scope,
                    "reason": f.reason,
                    "source": f.source,
                }
                for f in rows
            ]
        },
        pretty=pretty,
    )


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


class _NullBrokerAdapter(BrokerAdapter):
    """Phase 18 dev-mode adapter used when no broker credentials are set.

    Every probe returns an empty result so the reconcile task succeeds
    and the scheduler stays running. The scheduler never places orders
    through this adapter — ``ReconciliationRunner`` only calls
    ``list_orders`` / ``get_positions`` / ``get_account``.
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


def _build_adapter() -> BrokerAdapter:
    """Pick the appropriate broker adapter for the runtime environment.

    OANDA credentials win over Alpaca credentials so non-US operators can
    use the OANDA demo account without unsetting Alpaca keys. If neither
    credential set is present, fall back to :class:`_NullBrokerAdapter`,
    which lets the scheduler run in dev / CI without a live broker
    connection.
    """
    if _oanda_is_configured():
        from pathlib import Path as _Path

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

        config_path = _Path("config/oanda_paper.yaml")
        if config_path.exists():
            oanda_config = load_oanda_paper_config(config_path)
        else:
            oanda_config = OandaPaperConfig(
                base_url=DEFAULT_BASE_URL,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                max_retries=DEFAULT_MAX_RETRIES,
                retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
            )
        client = OandaHttpClient(config=oanda_config)
        return OandaPaperAdapter(client=client)

    if _alpaca_is_configured():
        # Local import so the CLI doesn't require Alpaca config to be
        # present at module import time. The config file is loaded
        # from the default path; tests that exercise the live path
        # should set the env vars and the config file location.
        from pathlib import Path as _Path

        from alphabrief_execution.broker.alpaca.adapter import (
            AlpacaPaperAdapter,
        )
        from alphabrief_execution.broker.alpaca.client import (
            AlpacaHttpClient,
        )
        from alphabrief_execution.broker.alpaca.config import (
            DEFAULT_BASE_URL,
            DEFAULT_MAX_RETRIES,
            DEFAULT_RETRY_BACKOFF_SECONDS,
            DEFAULT_TIMEOUT_SECONDS,
            AlpacaPaperConfig,
            load_alpaca_paper_config,
        )

        config_path = _Path("config/alpaca_paper.yaml")
        if config_path.exists():
            alpaca_config = load_alpaca_paper_config(config_path)
        else:
            # Dev fallback: explicit defaults rather than a default
            # constructor because AlpacaPaperConfig fields are
            # required (no default values).
            alpaca_config = AlpacaPaperConfig(
                base_url=DEFAULT_BASE_URL,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                max_retries=DEFAULT_MAX_RETRIES,
                retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
            )
        alpaca_client = AlpacaHttpClient(config=alpaca_config)
        return AlpacaPaperAdapter(client=alpaca_client)
    return _NullBrokerAdapter()


def _refuse_if_live_trading_unlocked() -> None:
    """Refuse to run the scheduler if the risk layer would unlock live trading.

    The scheduler process itself never places orders, but the system
    rule remains: live trading must remain independently locked. We
    inspect :class:`alphabrief_risk.gate.RiskLimitConfig` and bail out
    if any caller-supplied env var has flipped the default to
    ``live_trading_enabled=True``.
    """
    if os.environ.get("ALPHABRIEF_LIVE_TRADING_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        print(
            "scheduler: refused — ALPHABRIEF_LIVE_TRADING_ENABLED is set; "
            "the scheduler is paper-only and refuses to run with live "
            "trading unlocked",
            file=sys.stderr,
        )
        sys.exit(3)


def _configure_logging() -> None:
    """Wire the root logger to the operator's ``ALPHABRIEF_LOG_LEVEL``.

    The scheduler run is intended to run under a process supervisor for
    days at a time; the operator must be able to see at least INFO
    traffic on stderr without configuring Python logging by hand. The
    default level is INFO when ``ALPHABRIEF_LOG_LEVEL`` is unset or
    invalid, which matches the runbook's "logs visible" expectation.
    """
    import logging

    raw = os.environ.get("ALPHABRIEF_LOG_LEVEL", "INFO").upper().strip()
    level = getattr(logging, raw, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _build_ai_committee() -> TradingCommittee:
    """Build the configured AI committee for the scheduler."""
    return build_ai_trading_committee()


_AI_SCHEDULER_UNIVERSE = ("SPY", "QQQ", "IVV")
_AI_SCHEDULER_UNIVERSE_ENV = "ALPHABRIEF_AI_SCHEDULER_UNIVERSE"
_AI_PRE_CYCLE_INGEST_ENV = "ALPHABRIEF_AI_PRE_CYCLE_INGEST_ENABLED"
_AI_MARKET_DATA_SOURCE_ENV = "ALPHABRIEF_AI_MARKET_DATA_SOURCE"
_AI_MARKET_DATA_INTERVAL_ENV = "ALPHABRIEF_AI_MARKET_DATA_INTERVAL"
_AI_MARKET_DATA_LOOKBACK_DAYS_ENV = "ALPHABRIEF_AI_MARKET_DATA_LOOKBACK_DAYS"
_AI_NEWS_SOURCE_ENV = "ALPHABRIEF_AI_NEWS_SOURCE"
_AI_NEWS_FEEDS_ENV = "ALPHABRIEF_AI_NEWS_FEEDS"
_AI_NEWS_LOOKBACK_HOURS_ENV = "ALPHABRIEF_AI_NEWS_LOOKBACK_HOURS"
_AI_NEWS_LIMIT_ENV = "ALPHABRIEF_AI_NEWS_LIMIT"
_AI_NEWS_DEFAULT_FEEDS = ("marketwatch-rss", "reuters-rss", "bloomberg-atom")


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        print(
            f"scheduler: ignoring invalid {name}={raw!r}; expected integer",
            file=sys.stderr,
        )
        return default
    return max(minimum, value)


def _is_ai_pre_cycle_ingest_enabled() -> bool:
    """Return whether the AI cycle should refresh local data first."""

    return _env_bool(_AI_PRE_CYCLE_INGEST_ENV, default=True)


def _ai_scheduler_universe() -> tuple[str, ...]:
    """Return the operator-curated AI universe for scheduler cycles."""

    raw = os.environ.get(_AI_SCHEDULER_UNIVERSE_ENV)
    if raw is None or raw.strip() == "":
        return _AI_SCHEDULER_UNIVERSE
    symbols = tuple(symbol.strip().upper() for symbol in raw.split(","))
    symbols = tuple(symbol for symbol in symbols if symbol)
    if not symbols:
        return _AI_SCHEDULER_UNIVERSE
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"{_AI_SCHEDULER_UNIVERSE_ENV} must not contain duplicates")
    return symbols


def _build_market_data_provider(source: str) -> Any:
    """Build the configured provider for scheduler market-data refreshes."""

    from alphabrief_data import AlphaVantageProvider, YahooFinanceProvider

    if source == "yahoo":
        return YahooFinanceProvider()
    if source == "alphavantage":
        return AlphaVantageProvider()
    raise ValueError(
        "ALPHABRIEF_AI_MARKET_DATA_SOURCE must be one of yahoo, "
        "alphavantage, none"
    )


def _build_news_provider(source: str) -> Any:
    """Build the configured provider for scheduler news refreshes."""

    from alphabrief_news.providers import RssNewsProvider

    if source == "rss":
        return RssNewsProvider()
    raise ValueError("ALPHABRIEF_AI_NEWS_SOURCE must be one of rss, none")


def _run_ai_pre_cycle_ingestion(
    *,
    market_store: Any,
    news_store: Any,
    symbols: tuple[str, ...],
    now: datetime | None = None,
) -> dict[str, int]:
    """Refresh local market/news stores before building AI snapshots.

    Provider failures are logged and swallowed so the daily AI cycle can
    still use any previously persisted bars/headlines. A total lack of
    local bars remains handled by ``StoredMarketSnapshotBuilder`` as a
    symbol skip rather than a synthetic price.
    """

    if not _is_ai_pre_cycle_ingest_enabled():
        return {"bars": 0, "headlines": 0}

    captured_at = now or datetime.now(UTC)
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        captured_at = captured_at.replace(tzinfo=UTC)
    else:
        captured_at = captured_at.astimezone(UTC)

    bars = _ingest_ai_market_data(
        market_store=market_store,
        symbols=symbols,
        now=captured_at,
    )
    headlines = _ingest_ai_news(
        news_store=news_store,
        symbols=symbols,
        now=captured_at,
    )
    return {"bars": bars, "headlines": headlines}


def _ingest_ai_market_data(
    *,
    market_store: Any,
    symbols: tuple[str, ...],
    now: datetime,
) -> int:
    source = os.environ.get(_AI_MARKET_DATA_SOURCE_ENV, "yahoo").strip().lower()
    if source in {"", "none", "off", "disabled"}:
        return 0

    interval = os.environ.get(_AI_MARKET_DATA_INTERVAL_ENV, "1d").strip() or "1d"
    lookback_days = _env_int(
        _AI_MARKET_DATA_LOOKBACK_DAYS_ENV,
        default=10,
        minimum=1,
    )
    start = now - timedelta(days=lookback_days)
    data_version = f"ai-precycle-{source}-{interval}"

    from alphabrief_data import MarketDataProviderError

    try:
        provider = _build_market_data_provider(source)
    except (MarketDataProviderError, ValueError) as exc:
        print(
            f"scheduler: market data pre-cycle ingest disabled: {exc}",
            file=sys.stderr,
        )
        return 0

    inserted_total = 0
    for symbol in symbols:
        try:
            bars = provider.fetch_ohlcv(
                symbol=symbol,
                start=start,
                end=now,
                interval=interval,
            )
        except MarketDataProviderError as exc:
            print(
                f"scheduler: market data pre-cycle ingest failed for "
                f"{symbol}: [{exc.code}] {exc}",
                file=sys.stderr,
            )
            continue
        if not bars:
            print(
                f"scheduler: market data pre-cycle ingest returned 0 bars "
                f"for {symbol}",
                file=sys.stderr,
            )
            continue
        inserted_total += int(
            market_store.insert_bars(
                bars,
                source=getattr(provider, "provider_name", source),
                data_version=data_version,
            )
        )
    return inserted_total


def _ingest_ai_news(
    *,
    news_store: Any,
    symbols: tuple[str, ...],
    now: datetime,
) -> int:
    source = os.environ.get(_AI_NEWS_SOURCE_ENV, "rss").strip().lower()
    if source in {"", "none", "off", "disabled"}:
        return 0

    lookback_hours = _env_int(
        _AI_NEWS_LOOKBACK_HOURS_ENV,
        default=24,
        minimum=1,
    )
    limit = _env_int(_AI_NEWS_LIMIT_ENV, default=30, minimum=1)
    feeds = _configured_news_feeds()
    start = now - timedelta(hours=lookback_hours)
    data_version = f"ai-precycle-{source}-v1"

    from alphabrief_news.providers import NewsProviderError
    from alphabrief_news.types import NewsFetchQuery

    try:
        provider = _build_news_provider(source)
    except (NewsProviderError, ValueError) as exc:
        print(f"scheduler: news pre-cycle ingest disabled: {exc}", file=sys.stderr)
        return 0

    inserted_total = 0
    for feed in feeds:
        query = NewsFetchQuery(
            symbols=[feed],
            start=start,
            end=now,
            limit=limit,
            data_version=data_version,
        )
        try:
            headlines = provider.fetch_headlines(query)
        except NewsProviderError as exc:
            print(
                f"scheduler: news pre-cycle ingest failed for {feed}: "
                f"[{exc.code}] {exc}",
                file=sys.stderr,
            )
            continue
        tagged = [
            _tag_ai_news_headline(
                headline,
                feed=feed,
                symbols=symbols,
                data_version=data_version,
            )
            for headline in headlines
        ]
        inserted_total += int(news_store.insert_headlines(tagged))
    return inserted_total


def _configured_news_feeds() -> tuple[str, ...]:
    raw = os.environ.get(_AI_NEWS_FEEDS_ENV)
    if raw is None or raw.strip() == "":
        return _AI_NEWS_DEFAULT_FEEDS
    feeds = tuple(feed.strip() for feed in raw.split(",") if feed.strip())
    return feeds or _AI_NEWS_DEFAULT_FEEDS


def _tag_ai_news_headline(
    headline: Any,
    *,
    feed: str,
    symbols: tuple[str, ...],
    data_version: str,
) -> Any:
    from alphabrief_news.types import NewsHeadline

    typed = cast(NewsHeadline, headline)
    fingerprint = "|".join(
        [
            feed,
            typed.url or "",
            typed.title,
            typed.published_at.astimezone(UTC).isoformat(),
        ]
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return typed.model_copy(
        update={
            "headline_id": f"ai-precycle-{feed}-{digest}",
            "symbols": list(symbols),
            "data_version": data_version,
        }
    )


def _configured_broker_provider_name() -> str | None:
    if _oanda_is_configured():
        return "oanda_paper"
    if _alpaca_is_configured():
        return "alpaca_paper"
    return None


def _assert_external_policy_matches_broker(
    policy: PaperExecutionPolicy,
) -> None:
    """Fail closed when external AI paper config is internally inconsistent."""

    configured = _configured_broker_provider_name()
    if configured is None:
        raise RuntimeError(
            "ALPHABRIEF_AI_EXTERNAL_PAPER_ENABLED=true requires OANDA or "
            "Alpaca paper credentials"
        )
    if policy.provider != configured:
        raise RuntimeError(
            "external AI paper policy/provider mismatch: "
            f"policy provider is {policy.provider!r}, but configured broker "
            f"credentials select {configured!r}"
        )


def _ai_cycle_factory(
    *, db_path: Path
) -> Callable[[], Awaitable[None]]:
    """Build an ``on_ai_cycle`` coroutine bound to ``db_path``.

    The cycle runs the AI Trading Committee for the operator-curated
    paper universe. The handler is registered but disabled by default;
    ``scheduler run`` enables the task only when
    ``ALPHABRIEF_AI_TRADING_ENABLED`` is truthy.
    """
    from alphabrief_api.db import (
        AiTradingStore as _Store,
    )
    from alphabrief_api.db import (
        MarketDataStore as _MarketDataStore,
    )
    from alphabrief_api.db import (
        NewsStore as _NewsStore,
    )

    async def _handler() -> None:
        # The store is opened and closed per-call so a long-running
        # scheduler can survive a DuckDB single-writer lock between
        # cycles (the AI store is currently the same DB as the broker
        # recon store). ponytail:scheduler_ai_duckdb_lock — see
        # upgrade path note in
        # docs/development_plans/0057-phase-26-ai-trader-closeout.md.
        database = db_path / "alphabrief.db"
        store = _Store(db_path=database)
        market_store = _MarketDataStore(db_path=database)
        news_store = _NewsStore(db_path=database)
        try:
            universe = _ai_scheduler_universe()
            _run_ai_pre_cycle_ingestion(
                market_store=market_store,
                news_store=news_store,
                symbols=universe,
            )
            snapshot_builder = StoredMarketSnapshotBuilder(
                bar_loader=market_store.get_bar_models,
                headline_loader=lambda symbol, start, end, limit: (
                    news_store.list_headlines(
                        symbol=symbol,
                        start=start,
                        end=end,
                        limit=limit,
                    )
                ),
            )
            committee = _build_ai_committee()
            broker = PaperBroker(
                portfolio=PortfolioState(cash=Decimal("100000")),
                router=OrderRouter(),
                fill_simulator=FillSimulator(),
            )
            policy = load_paper_execution_policy(
                load_settings().execution_policy_file
            )
            if is_ai_external_paper_enabled():
                _assert_external_policy_matches_broker(policy)
            risk_gate = RiskGate(
                limits=RiskLimitConfig(
                    trading_enabled=True,
                    symbol_allowlist=frozenset(universe),
                    max_order_value=policy.max_order_notional,
                )
            )
            execution_backend = (
                ExternalPaperExecutionBackend(_build_adapter())
                if is_ai_external_paper_enabled()
                else None
            )
            cycle = DailyTradingCycle(
                committee=committee,
                risk_gate=risk_gate,
                broker=broker,
                store=store,
                snapshot_loader=lambda symbol: snapshot_builder.build(symbol)
                if symbol in universe
                else None,
                execution_backend=execution_backend,
                enabled=is_ai_trading_enabled(),
            )
            cycle.run(list(universe))
        finally:
            news_store.close()
            market_store.close()
            store.close()

    return _handler


@scheduler_app.command("run")
def run_cmd(
    reconcile_interval_seconds: float = typer.Option(  # noqa: B008
        300.0,
        "--reconcile-interval",
        min=1.0,
        help="Interval between reconcile cycles (default: 300s).",
    ),
    max_consecutive_failures: int = typer.Option(  # noqa: B008
        3,
        "--max-failures",
        min=1,
        help="Freeze after this many consecutive task failures.",
    ),
) -> None:
    """Start the scheduler as a foreground process (Ctrl-C to stop)."""
    _refuse_if_live_trading_unlocked()
    _configure_logging()
    import logging

    _LOGGER = logging.getLogger(__name__)
    _LOGGER.info(
        "scheduler: starting (reconcile_interval=%.1fs, max_failures=%d, "
        "ai_trading=%s, external_paper=%s, universe=%s)",
        reconcile_interval_seconds,
        max_consecutive_failures,
        is_ai_trading_enabled(),
        is_ai_external_paper_enabled(),
        ",".join(_ai_scheduler_universe()),
    )

    heartbeats = _open_heartbeat_store()
    recon_store = _open_recon_store()
    try:
        adapter = _build_adapter()
        runner = ReconciliationRunner(adapter=adapter, store=recon_store)
        alert_sink = AlertSink(heartbeat_store=heartbeats)

        async def _on_reconcile(scope: str) -> None:
            await runner.reconcile(scope=scope)

        db_dir_env = os.environ.get("ALPHABRIEF_DATA_DIR")
        db_path = (
            Path(db_dir_env)
            if db_dir_env
            else Path.home() / ".alphabrief" / "data"
        )
        ai_handler = _ai_cycle_factory(db_path=db_path)

        tasks = build_default_tasks(
            on_reconcile=_on_reconcile,
            on_ai_cycle=ai_handler,
        )
        # Override the reconcile task interval if the user asked for a
        # different value. This rebuilds the list so the rest of the
        # default tasks (ai_daily_cycle) stay intact.
        tasks = [
            (
                replace(task, interval_seconds=reconcile_interval_seconds)
                if task.name == "reconcile"
                else task
            )
            for task in tasks
        ]
        # Activate the AI cycle task only when the feature flag is on;
        # otherwise it stays a registered-but-disabled entry so the
        # operator can see the task in `scheduler tasks`.
        if is_ai_trading_enabled():
            tasks = [
                replace(task, enabled=True) if task.name == "ai_daily_cycle" else task
                for task in tasks
            ]

        scheduler = OperationsScheduler(
            tasks=tasks,
            heartbeat_store=heartbeats,
            alert_sink=alert_sink,
            recon_runner=runner,
            recon_store=recon_store,
            config=SchedulerConfig(
                reconcile_on_start=True,
                max_consecutive_failures=max_consecutive_failures,
            ),
        )

        def _on_sigint(signum: int, frame: object) -> None:
            scheduler.request_stop()

        signal.signal(signal.SIGINT, _on_sigint)
        signal.signal(signal.SIGTERM, _on_sigint)

        try:
            asyncio.run(scheduler.run())
        except SchedulerStartupBlockedError as exc:
            print(f"scheduler: startup blocked: {exc}", file=sys.stderr)
            sys.exit(2)
        except KeyboardInterrupt:
            scheduler.request_stop()
            print("scheduler: stopped")
    finally:
        heartbeats.close()
        recon_store.close()


__all__ = ["scheduler_app"]
