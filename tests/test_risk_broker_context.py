"""M08-W01: broker-fresh risk context value object and builder.

- the context carries source IDs, capture times, freshness verdicts,
  account state, balance, NAV, margin, positions, pending orders,
  trades, bid/ask prices, conversions, catalog version, reconciliation
  state, and health state (AC-M08-W01-01);
- missing, stale, account-mismatched, partially covered, frozen, or
  internally inconsistent contexts reject with classified errors — no
  synthesized defaults, no fallback account, no user question
  (AC-M08-W01-03).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alphabrief_execution.broker.risk_context import (
    AccountSourceDatum,
    FreshnessPolicy,
    RiskContextError,
    build_broker_risk_context,
)
from alphabrief_risk.broker_context import (
    DEFAULT_CONTEXT_VERSION,
    DEFAULT_POLICY_VERSION,
    ConversionDatum,
    HealthState,
    PendingOrderDatum,
    PositionDatum,
    PriceDatum,
    ReconciliationState,
    TradeDatum,
)

ACCOUNT = "101-004-1234567-001"
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Deterministic source fakes
# ---------------------------------------------------------------------------


class _FakeSources:
    """Configurable complete sources for the context builder."""

    def __init__(
        self,
        *,
        now: datetime = NOW,
        account_captured_at: datetime | None = None,
        positions: list[PositionDatum] | None = None,
        prices: list[PriceDatum] | None = None,
        conversions: list[ConversionDatum] | None = None,
        catalog_version: str | None = "catalog-2026-08-13",
        reconciliation: ReconciliationState = "clean",
        health: HealthState = "healthy",
        account: AccountSourceDatum | None = None,
        fail_account: Exception | None = None,
    ) -> None:
        self._now = now
        self._account: AccountSourceDatum | None = account or _account(
            captured_at=account_captured_at or now
        )
        self._positions = positions or []
        self._prices = prices or [
            PriceDatum(
                symbol="EUR_USD",
                bid=Decimal("1.10400"),
                ask=Decimal("1.10420"),
                captured_at=now,
            )
        ]
        self._conversions = conversions or []
        self._catalog = catalog_version
        self._reconciliation: ReconciliationState = reconciliation
        self._health: HealthState = health
        self._fail_account = fail_account

    def fetch_account(self) -> AccountSourceDatum | None:
        if self._fail_account is not None:
            raise self._fail_account
        return self._account

    def fetch_positions(self) -> list[PositionDatum]:
        return list(self._positions)

    def fetch_pending_orders(self) -> list[PendingOrderDatum]:
        return [
            PendingOrderDatum(
                broker_order_id="o-1",
                symbol="EUR_USD",
                units=Decimal("1000"),
                state="PENDING",
            )
        ]

    def fetch_trades(self) -> list[TradeDatum]:
        return [
            TradeDatum(
                broker_trade_id="t-1",
                symbol="EUR_USD",
                current_units=Decimal("1000"),
                state="OPEN",
            )
        ]

    def fetch_prices(self) -> list[PriceDatum]:
        return list(self._prices)

    def fetch_conversions(self) -> list[ConversionDatum]:
        return list(self._conversions)

    def fetch_catalog_version(self) -> str | None:
        return self._catalog

    def fetch_reconciliation_state(self) -> ReconciliationState:
        return self._reconciliation

    def fetch_health(self) -> HealthState:
        return self._health


def _account(
    *,
    account_id: str = ACCOUNT,
    captured_at: datetime = NOW,
    balance: Decimal = Decimal("10000"),
    nav: Decimal = Decimal("10000"),
    margin_used: Decimal = Decimal("0"),
) -> AccountSourceDatum:
    return AccountSourceDatum(
        account_id=account_id,
        state="ACTIVE",
        tradeable=True,
        home_currency="USD",
        balance=balance,
        nav=nav,
        margin_used=margin_used,
        margin_available=nav - margin_used,
        captured_at=captured_at,
    )


def _build(
    sources: _FakeSources,
    *,
    expected_account_id: str | None = ACCOUNT,
    freshness: FreshnessPolicy | None = None,
) -> Any:
    return build_broker_risk_context(
        sources,
        expected_account_id=expected_account_id,
        freshness=freshness,
        clock=lambda: NOW,
    )


# ---------------------------------------------------------------------------
# AC-M08-W01-01: the context carries every required fact
# ---------------------------------------------------------------------------


def test_full_context_carries_every_required_field() -> None:
    sources = _FakeSources()
    context = _build(sources)
    assert context.context_version == DEFAULT_CONTEXT_VERSION
    assert context.policy_version == DEFAULT_POLICY_VERSION
    # Source IDs and capture time (REQ-PLAT-009 traceability).
    assert context.source_ids[0] == f"account:{ACCOUNT}"
    assert context.captured_at == NOW
    # Account state and money fields.
    assert context.account.account_id == ACCOUNT
    assert context.account.state == "ACTIVE"
    assert context.account.tradeable is True
    assert context.balance == Decimal("10000")
    assert context.nav == Decimal("10000")
    assert context.margin_used == Decimal("0")
    assert context.margin_available == Decimal("10000")
    # Pending orders and trades.
    assert [o.broker_order_id for o in context.pending_orders] == ["o-1"]
    assert [t.broker_trade_id for t in context.trades] == ["t-1"]
    # Bid/ask prices with spread.
    price = context.prices[0]
    assert price.symbol == "EUR_USD"
    assert price.bid == Decimal("1.10400")
    assert price.ask == Decimal("1.10420")
    assert price.spread == Decimal("0.00020")
    # Conversions, catalog, reconciliation, health.
    assert context.conversions == ()
    assert context.catalog_version == "catalog-2026-08-13"
    assert context.reconciliation_state == "clean"
    assert context.health_state == "healthy"
    # Freshness verdicts cover every source.
    assert {v.source for v in context.freshness} == {
        "account", "positions", "pending_orders", "trades", "conversions",
        "prices", "catalog", "reconciliation", "health",
    }
    assert context.all_fresh is True
    assert context.internally_consistent is True


def test_context_rejects_float_money_fields() -> None:
    with pytest.raises(ValueError):
        _account(balance=10000.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        PriceDatum(
            symbol="EUR_USD",
            bid=Decimal("1.1"),
            ask=1.2,  # type: ignore[arg-type]
            captured_at=NOW,
        )


def test_positions_pending_orders_prices_round_trip() -> None:
    sources = _FakeSources(
        positions=[
            PositionDatum(
                symbol="EUR_USD",
                long_units=Decimal("1000"),
                short_units=Decimal("0"),
                average_price=Decimal("1.10000"),
            )
        ],
        conversions=[
            ConversionDatum(
                symbol="EUR_USD",
                quote_home=Decimal("1.0"),
                factor=Decimal("1.10420"),
            )
        ],
    )
    context = _build(sources)
    position = context.positions[0]
    assert position.long_units == Decimal("1000")
    assert context.conversions[0].factor == Decimal("1.10420")
    assert context.internally_consistent is True


# ---------------------------------------------------------------------------
# AC-M08-W01-03: fail closed before submit — never synthesized
# ---------------------------------------------------------------------------


def test_missing_account_source_rejects() -> None:
    sources = _FakeSources()
    sources._account = None  # noqa: SLF001 — simulate a missing source
    with pytest.raises(RiskContextError) as excinfo:
        _build(sources)
    assert excinfo.value.kind == "missing_source"
    assert "account" in excinfo.value.detail


def test_account_source_failure_is_classified() -> None:
    sources = _FakeSources(fail_account=TimeoutError("broker unreachable"))
    with pytest.raises(RiskContextError) as excinfo:
        _build(sources)
    assert excinfo.value.kind == "missing_source"


def test_account_mismatch_rejects() -> None:
    sources = _FakeSources()
    with pytest.raises(RiskContextError) as excinfo:
        _build(sources, expected_account_id="other-account")
    assert excinfo.value.kind == "account_mismatch"


@pytest.mark.parametrize(
    ("sources", "source_name"),
    [
        (
            _FakeSources(
                prices=[
                    PriceDatum(
                        symbol="EUR_USD",
                        bid=Decimal("1.10400"),
                        ask=Decimal("1.10420"),
                        captured_at=NOW - timedelta(seconds=300),
                    )
                ]
            ),
            "prices",
        ),
        (
            _FakeSources(account_captured_at=NOW - timedelta(seconds=600)),
            "account",
        ),
    ],
    ids=["stale-price", "stale-account"],
)
def test_stale_source_rejects(sources: _FakeSources, source_name: str) -> None:
    with pytest.raises(RiskContextError) as excinfo:
        _build(sources)
    assert excinfo.value.kind == "stale"
    assert source_name in excinfo.value.detail


def test_frozen_reconciliation_rejects() -> None:
    sources = _FakeSources(reconciliation="frozen")
    with pytest.raises(RiskContextError) as excinfo:
        _build(sources)
    assert excinfo.value.kind == "frozen"


def test_unhealthy_health_rejects() -> None:
    sources = _FakeSources(health="unhealthy")
    with pytest.raises(RiskContextError) as excinfo:
        _build(sources)
    assert excinfo.value.kind == "stale"


def test_missing_price_for_held_position_rejects() -> None:
    sources = _FakeSources(
        positions=[
            PositionDatum(
                symbol="XAU_USD",
                long_units=Decimal("10"),
                short_units=Decimal("0"),
                average_price=Decimal("4100"),
            )
        ],
        prices=[],  # the held symbol has no price
    )
    with pytest.raises(RiskContextError) as excinfo:
        _build(sources)
    assert excinfo.value.kind == "partial"
    assert "XAU_USD" in excinfo.value.detail


def test_missing_conversion_for_held_position_rejects() -> None:
    sources = _FakeSources(
        positions=[
            PositionDatum(
                symbol="EUR_USD",
                long_units=Decimal("1000"),
                short_units=Decimal("0"),
                average_price=Decimal("1.10000"),
            )
        ],
        conversions=[
            ConversionDatum(
                symbol="XAU_USD",
                quote_home=Decimal("1.0"),
                factor=Decimal("4100"),
            )
        ],
    )
    with pytest.raises(RiskContextError) as excinfo:
        _build(sources)
    assert excinfo.value.kind == "partial"
    assert "EUR_USD" in excinfo.value.detail


def test_inconsistent_margin_identity_rejects() -> None:
    sources = _FakeSources(
        account=_account(margin_used=Decimal("100"), nav=Decimal("10000"))
    )
    # margin_available = 9900 but nav - margin_used = 9900 -> consistent;
    # force a real violation by mis-stating margin_available.
    assert sources._account is not None
    sources._account = sources._account.model_copy(  # noqa: SLF001
        update={"margin_available": Decimal("9500")}
    )
    with pytest.raises(RiskContextError) as excinfo:
        _build(sources)
    assert excinfo.value.kind == "inconsistent"
    assert "margin" in excinfo.value.detail


def test_crossed_price_rejects() -> None:
    sources = _FakeSources(
        prices=[
            PriceDatum(
                symbol="EUR_USD",
                bid=Decimal("1.10420"),
                ask=Decimal("1.10400"),
                captured_at=NOW,
            )
        ]
    )
    with pytest.raises(RiskContextError) as excinfo:
        _build(sources)
    assert excinfo.value.kind == "inconsistent"
    assert "crossed" in excinfo.value.detail


def test_venue_without_authority_is_recorded_truthfully() -> None:
    """A venue without a catalog/reconciliation/health authority builds
    (venue truth): the verdicts record the absence or unknown state and
    no version is synthesized."""
    sources = _FakeSources(
        catalog_version=None, reconciliation="unknown", health="unknown"
    )
    context = _build(sources)
    assert context.catalog_version is None
    assert context.reconciliation_state == "unknown"
    assert context.health_state == "unknown"
    catalog = next(v for v in context.freshness if v.source == "catalog")
    assert catalog.fresh is False
    assert "no catalog version authority" in catalog.detail
    assert context.internally_consistent is True


def test_unknown_freshness_source_rejected() -> None:
    with pytest.raises(ValueError, match="unknown freshness source"):
        FreshnessPolicy({"bogus": 60})
