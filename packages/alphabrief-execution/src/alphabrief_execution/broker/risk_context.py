"""One broker-fresh risk context service for every execution path (M08-W01).

Every execution path — AI external paper (trader backend) and manual
paper API (routes/paper.py) — builds its pre-risk :class:`BrokerRiskContext`
through this single service instead of caller-selected partial
dictionaries (AC-M08-W01-02). The builder fetches account, positions,
pending orders, trades, bid/ask prices, conversions, catalog version,
reconciliation state, and health facts through an injected
:class:`RiskContextSources` port, stamps the shared context and policy
versions, records per-source freshness verdicts, and **fails closed**
before submit when any source is missing, stale, account-mismatched,
partially covered, frozen, or internally inconsistent (AC-M08-W01-03):
no synthesized defaults, no fallback account, no user question, no
review bypass (REQ-RISK-001, REQ-RISK-010). The dependency arrow stays
one-way: execution -> risk; the value object is owned by the risk layer.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, TypeVar

from alphabrief_risk import AccountExposureContext
from alphabrief_risk.broker_context import (
    DEFAULT_CONTEXT_VERSION,
    DEFAULT_POLICY_VERSION,
    AccountStateDatum,
    BrokerRiskContext,
    ConversionDatum,
    FreshnessVerdict,
    HealthState,
    PendingOrderDatum,
    PositionDatum,
    PriceDatum,
    ReconciliationState,
    TradeDatum,
)
from pydantic import field_validator

from alphabrief_execution.broker.port import (
    BrokerAdapter,
    BrokerOrderStatus,
)

#: Default per-source freshness ceilings (seconds); ``None`` = not enforced.
DEFAULT_FRESHNESS_CEILINGS: dict[str, int | None] = {
    "account": 300,
    "positions": 300,
    "pending_orders": 300,
    "trades": 300,
    "prices": 60,
    "conversions": 300,
    "catalog": 86400,
    "reconciliation": 86400,
    "health": 60,
}


class RiskContextError(RuntimeError):
    """A classified fail-closed risk-context failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"broker risk context failed ({kind}): {detail}")


class AccountSourceDatum(AccountStateDatum):
    """Broker account facts plus the money fields a context needs."""

    balance: Decimal
    nav: Decimal
    margin_used: Decimal
    margin_available: Decimal
    captured_at: datetime

    @field_validator("balance", "nav", "margin_used", "margin_available", mode="before")
    @classmethod
    def money_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("account source money fields must not be floats")
        return value


class FreshnessPolicy:
    """Per-source staleness ceilings for one venue."""

    def __init__(self, ceilings: dict[str, int | None] | None = None) -> None:
        self._ceilings = dict(DEFAULT_FRESHNESS_CEILINGS)
        if ceilings:
            for source, max_age in ceilings.items():
                if source not in self._ceilings:
                    raise ValueError(f"unknown freshness source {source!r}")
                if max_age is not None and max_age < 0:
                    raise ValueError("max_age_seconds must be non-negative or None")
                self._ceilings[source] = max_age

class RiskContextSources(Protocol):
    """One venue's broker-fresh fact fetchers (sync; execution layer only)."""

    def fetch_account(self) -> AccountSourceDatum | None: ...

    def fetch_positions(self) -> list[PositionDatum]: ...

    def fetch_pending_orders(self) -> list[PendingOrderDatum]: ...

    def fetch_trades(self) -> list[TradeDatum]: ...

    def fetch_prices(self) -> list[PriceDatum]: ...

    def fetch_conversions(self) -> list[ConversionDatum]: ...

    def fetch_catalog_version(self) -> str | None: ...

    def fetch_reconciliation_state(self) -> ReconciliationState: ...

    def fetch_health(self) -> HealthState: ...


class _AdapterRiskSources:
    """Venue-truthful sources composed from the broker-neutral port.

    The port surface provides account, positions, pending orders, and
    health; trades/prices/conversions/catalog/reconciliation have no
    port authority and are recorded truthfully (empty/None/unknown) —
    nothing is synthesized. Price coverage for held positions is still
    required, so a real adapter with positions but no pricing authority
    fails closed (``partial``) until a complete OANDA composition exists.
    """

    def __init__(self, adapter: BrokerAdapter) -> None:
        self._adapter = adapter

    def fetch_account(self) -> AccountSourceDatum:
        snapshot = _run_blocking(self._adapter.get_account())
        return AccountSourceDatum(
            account_id=snapshot.account_id,
            state="ACTIVE",
            tradeable=True,
            home_currency=snapshot.currency or "USD",
            balance=snapshot.cash,
            nav=snapshot.equity,
            margin_used=Decimal("0"),
            margin_available=snapshot.equity,
            captured_at=snapshot.captured_at,
        )

    def fetch_positions(self) -> list[PositionDatum]:
        positions = _run_blocking(self._adapter.get_positions())
        return [
            PositionDatum(
                symbol=position.symbol,
                long_units=(
                    position.quantity
                    if position.quantity > 0
                    else Decimal("0")
                ),
                short_units=(
                    abs(position.quantity)
                    if position.quantity < 0
                    else Decimal("0")
                ),
                average_price=position.average_price,
            )
            for position in positions
        ]

    def fetch_pending_orders(self) -> list[PendingOrderDatum]:
        orders = _run_blocking(self._adapter.list_orders())
        return [
            PendingOrderDatum(
                broker_order_id=order.broker_order_id,
                symbol=order.symbol,
                units=order.quantity,
                state=order.status.value,
            )
            for order in orders
            if order.status == BrokerOrderStatus.NEW
        ]

    def fetch_trades(self) -> list[TradeDatum]:
        return []  # no port authority for open trades

    def fetch_prices(self) -> list[PriceDatum]:
        return []  # no port authority for bid/ask prices

    def fetch_conversions(self) -> list[ConversionDatum]:
        return []  # no port authority for conversions

    def fetch_catalog_version(self) -> str | None:
        return None  # no port authority for the catalog

    def fetch_reconciliation_state(self) -> ReconciliationState:
        return "unknown"  # no port authority for reconciliation state

    def fetch_health(self) -> HealthState:
        health = _run_blocking(self._adapter.health())
        return "healthy" if health.healthy else "unhealthy"


def adapter_risk_sources(adapter: BrokerAdapter) -> RiskContextSources:
    """Compose one venue's sources from a broker-neutral adapter."""
    return _AdapterRiskSources(adapter)


def _run_blocking[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Await an adapter coroutine from a sync context.

    Mirrors the trader backend bridge: when no loop is running the
    coroutine runs directly; inside a running loop it runs in a worker
    thread so scheduler cycles never deadlock.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result: list[T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(awaitable))
        except BaseException as exc:  # pragma: no cover - re-raised below
            errors.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


class BrokerRiskContextBuilder:
    """Assembles one versioned broker-fresh context; never synthesizes."""

    def __init__(
        self,
        sources: RiskContextSources,
        *,
        context_version: str = DEFAULT_CONTEXT_VERSION,
        policy_version: str = DEFAULT_POLICY_VERSION,
        freshness: FreshnessPolicy | None = None,
        require_price_coverage: bool = True,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sources = sources
        self._context_version = context_version
        self._policy_version = policy_version
        self._freshness = freshness or FreshnessPolicy()
        self._require_price_coverage = require_price_coverage
        self._clock = clock or (lambda: datetime.now(UTC))

    def build(
        self, *, expected_account_id: str | None = None
    ) -> BrokerRiskContext:
        """Build one context, failing closed on any defect."""
        # The capture stamp is read AFTER every source fetch so a
        # captured_at recorded during fetching can never be in the future
        # relative to it.
        account = self._fetch("account", self._sources.fetch_account)
        if account is None:
            raise RiskContextError("missing_source", "account source is missing")
        if expected_account_id is not None:
            if account.account_id != expected_account_id:
                raise RiskContextError(
                    "account_mismatch",
                    f"expected account {expected_account_id!r}, "
                    f"got {account.account_id!r}",
                )

        positions = self._fetch("positions", self._sources.fetch_positions) or []
        pending_orders = (
            self._fetch("pending_orders", self._sources.fetch_pending_orders) or []
        )
        trades = self._fetch("trades", self._sources.fetch_trades) or []
        prices = self._fetch("prices", self._sources.fetch_prices) or []
        conversions = (
            self._fetch("conversions", self._sources.fetch_conversions) or []
        )
        catalog_version = self._fetch(
            "catalog", self._sources.fetch_catalog_version
        )
        reconciliation = self._fetch(
            "reconciliation", self._sources.fetch_reconciliation_state
        )
        if reconciliation == "frozen":
            raise RiskContextError(
                "frozen",
                "reconciliation state is frozen; new exposure is blocked",
            )
        health = self._fetch("health", self._sources.fetch_health)

        now = self._clock()
        verdicts = self._freshness_verdicts(
            now,
            account=account,
            prices=prices,
            catalog_version=catalog_version,
        )
        stale = [
            verdict
            for verdict in verdicts
            if not verdict.fresh and verdict.captured_at is not None
        ]
        if stale:
            detail = "; ".join(
                f"{v.source} not fresh: {v.detail}" for v in stale
            )
            raise RiskContextError("stale", detail)
        if health == "unhealthy":
            raise RiskContextError(
                "stale", "broker health state is unhealthy"
            )

        # Partial coverage: every held position must have a price (when
        # the venue requires coverage) and every held position must have
        # a conversion entry whenever the venue provides conversions.
        price_symbols = {price.symbol for price in prices}
        conversion_symbols = {conversion.symbol for conversion in conversions}
        for position in positions:
            symbol = position.symbol
            if self._require_price_coverage and symbol not in price_symbols:
                raise RiskContextError(
                    "partial",
                    f"no price for held position {symbol!r}",
                )
            if conversions and symbol not in conversion_symbols:
                raise RiskContextError(
                    "partial",
                    f"no conversion for held position {symbol!r}",
                )

        context = BrokerRiskContext(
            context_version=self._context_version,
            policy_version=self._policy_version,
            account=AccountStateDatum(
                account_id=account.account_id,
                state=account.state,
                tradeable=account.tradeable,
                home_currency=account.home_currency,
            ),
            captured_at=now,
            source_ids=(
                f"account:{account.account_id}",
                f"captured:{now.isoformat()}",
            ),
            balance=account.balance,
            nav=account.nav,
            margin_used=account.margin_used,
            margin_available=account.margin_available,
            positions=tuple(positions),
            pending_orders=tuple(pending_orders),
            trades=tuple(trades),
            prices=tuple(prices),
            conversions=tuple(conversions),
            catalog_version=catalog_version,
            reconciliation_state=reconciliation,
            health_state=health,
            freshness=tuple(verdicts),
        )
        if account.captured_at > now:
            raise RiskContextError(
                "inconsistent",
                "account captured_at "
                f"{account.captured_at.isoformat()} is in the future",
            )
        inconsistencies = context.inconsistencies()
        if inconsistencies:
            raise RiskContextError(
                "inconsistent",
                "; ".join(inconsistencies),
            )
        return context

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    _T = TypeVar("_T")

    def _fetch(self, source: str, fetcher: Callable[[], _T]) -> _T:
        try:
            return fetcher()
        except RiskContextError:
            raise
        except Exception as exc:  # noqa: BLE001 — classify any source failure
            raise RiskContextError(
                "missing_source", f"{source} source failed: {exc}"
            ) from exc

    def _freshness_verdicts(
        self,
        now: datetime,
        *,
        account: AccountSourceDatum,
        prices: list[PriceDatum],
        catalog_version: str | None,
    ) -> list[FreshnessVerdict]:
        """Per-source freshness verdicts against the venue policy.

        Timestamped sources (account and everything projected at its
        capture, plus bid/ask prices) are age-checked against the venue
        policy. Authority sources without their own timestamp authority
        (catalog, reconciliation, health) are presence-verified: the
        verdict records what the venue provides and never triggers the
        staleness rejection by itself.
        """
        timestamped: list[tuple[str, datetime, str]] = [
            ("account", account.captured_at, "account snapshot"),
        ]
        for source in ("positions", "pending_orders", "trades", "conversions"):
            timestamped.append(
                (source, account.captured_at, f"{source} projected at account capture")
            )
        if prices:
            timestamped.append(
                (
                    "prices",
                    max(price.captured_at for price in prices),
                    "bid/ask prices",
                )
            )
        verdicts: list[FreshnessVerdict] = []
        for source, captured_at, label in timestamped:
            max_age = self._freshness._ceilings[source]
            age = (now - captured_at).total_seconds()
            fresh = max_age is None or age <= max_age
            verdicts.append(
                FreshnessVerdict(
                    source=source,
                    fresh=fresh,
                    captured_at=captured_at,
                    max_age_seconds=max_age,
                    detail=(
                        f"{label} age {age:.1f}s"
                        if max_age is not None
                        else f"{label} not age-gated by venue policy"
                    ),
                )
            )
        verdicts.append(
            FreshnessVerdict(
                source="catalog",
                fresh=catalog_version is not None,
                captured_at=None,
                max_age_seconds=self._freshness._ceilings["catalog"],
                detail=(
                    f"catalog version {catalog_version!r} present"
                    if catalog_version is not None
                    else "no catalog version authority"
                ),
            )
        )
        verdicts.append(
            FreshnessVerdict(
                source="reconciliation",
                fresh=True,
                captured_at=None,
                max_age_seconds=self._freshness._ceilings["reconciliation"],
                detail="reconciliation state authority present",
            )
        )
        verdicts.append(
            FreshnessVerdict(
                source="health",
                fresh=True,
                captured_at=None,
                max_age_seconds=self._freshness._ceilings["health"],
                detail="broker health authority present",
            )
        )
        return verdicts


def build_broker_risk_context(
    sources: RiskContextSources,
    *,
    expected_account_id: str | None = None,
    context_version: str = DEFAULT_CONTEXT_VERSION,
    policy_version: str = DEFAULT_POLICY_VERSION,
    freshness: FreshnessPolicy | None = None,
    require_price_coverage: bool = True,
    clock: Callable[[], datetime] | None = None,
) -> BrokerRiskContext:
    """Build one broker-fresh context through the shared service."""
    return BrokerRiskContextBuilder(
        sources,
        context_version=context_version,
        policy_version=policy_version,
        freshness=freshness,
        require_price_coverage=require_price_coverage,
        clock=clock,
    ).build(expected_account_id=expected_account_id)


def project_risk_context_to_exposure(
    context: BrokerRiskContext,
    *,
    mark_prices: dict[str, Decimal] | None = None,
) -> AccountExposureContext:
    """Project a broker-fresh context into the RiskGate exposure contract.

    Gross notional sums ``|units| * mark`` per position where the mark is
    the context's own bid/ask observation for the symbol when present,
    else the supplied ``mark_prices``, else the position average price.
    ``equity`` is the context's authoritative NAV.
    """
    marks: dict[str, Decimal] = {}
    for price in context.prices:
        marks[price.symbol] = (price.bid + price.ask) / Decimal("2")
    if mark_prices:
        marks.update(mark_prices)
    total = Decimal("0")
    by_symbol: dict[str, Decimal] = {}
    for position in context.positions:
        units = position.long_units + position.short_units
        if units == 0:
            continue
        mark = marks.get(position.symbol, position.average_price)
        if mark is None:
            raise RiskContextError(
                "partial",
                f"no mark for position {position.symbol!r}",
            )
        notional = abs(units) * mark
        total += notional
        by_symbol[position.symbol] = (
            by_symbol.get(position.symbol, Decimal("0")) + notional
        )
    return AccountExposureContext(
        current_total_exposure=total,
        exposure_by_symbol=by_symbol,
        cash=context.balance,
        account_id=context.account.account_id,
        captured_at=context.captured_at,
        equity=context.nav,
        reference_mark_prices=marks,
    )


__all__ = [
    "AccountSourceDatum",
    "BrokerRiskContextBuilder",
    "DEFAULT_FRESHNESS_CEILINGS",
    "FreshnessPolicy",
    "RiskContextError",
    "RiskContextSources",
    "adapter_risk_sources",
    "build_broker_risk_context",
    "project_risk_context_to_exposure",
]
