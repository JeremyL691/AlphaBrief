"""M08-W02: instrument, precision, size, session, and freshness rules.

Covers:
- boundary and property tests for allowed and unknown instruments,
  active and inactive catalog state, tradeable false, units and price
  precision, minimum size, maximum order units, maximum position size,
  and normalized-zero quantity (AC-M08-W02-01);
- closed session, holiday, stale quote, stale catalog, incomplete
  candle, excessive gap, missing conversion, and partial pricing
  coverage reject new exposure with stable rule results
  (AC-M08-W02-02);
- instrument normalization occurs before final risk evaluation and any
  post-decision change of units, price, instrument version, or snapshot
  hash invalidates the decision (AC-M08-W02-03, REQ-RISK-010).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TypedDict, cast

import pytest
from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
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
from alphabrief_execution.broker.risk_context import (
    AccountSourceDatum,
    BrokerRiskContextBuilder,
)
from alphabrief_risk.broker_context import (
    ConversionDatum,
    HealthState,
    PendingOrderDatum,
    PositionDatum,
    PriceDatum,
    ReconciliationState,
    TradeDatum,
)
from alphabrief_risk.decision_binding import hash_inputs
from alphabrief_risk.instrument_rules import (
    InstrumentConstraintError,
    MarketEvidence,
    bind_execution_inputs,
    evaluate_instrument_rules,
    normalize_instrument_price,
    normalize_instrument_units,
    validate_execution_inputs,
)
from alphabrief_trader import ExternalPaperExecutionBackend
from alphabrief_trader.execution_backend import ExecutionBackendError

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

@pytest.fixture(autouse=True)
def _isolated_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point the runtime data directory at tmp so the decision-binding
    store (M08-W07) never touches the developer's real data directory."""
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))

ACCOUNT = "101-004-1234567-001"


def _metadata(**overrides: object) -> InstrumentMetadata:
    payload: dict[str, object] = {
        "name": "EUR_USD",
        "display_name": "EUR/USD",
        "raw_type": "CURRENCY",
        "display_precision": 5,
        "trade_units_precision": 0,
        "minimum_trade_size": Decimal("1"),
        "maximum_order_units": Decimal("0"),
        "maximum_position_size": Decimal("0"),
        "margin_rate": Decimal("0.05"),
        "pip_location": -4,
    }
    payload.update(overrides)
    return InstrumentMetadata.model_validate(payload)


def _evidence(**overrides: object) -> MarketEvidence:
    return MarketEvidence.model_validate(overrides)


_UNSET = object()


def _evaluate(
    *,
    symbol: str = "EUR_USD",
    units: Decimal = Decimal("1000"),
    price: Decimal | None = Decimal("1.10500"),
    metadata: object = _UNSET,
    evidence: MarketEvidence | None = None,
    current_position_units: Decimal = Decimal("0"),
) -> dict[str, bool]:
    resolved_metadata: InstrumentMetadata | None = (
        _metadata()
        if metadata is _UNSET
        else cast(InstrumentMetadata | None, metadata)
    )
    results = evaluate_instrument_rules(
        symbol=symbol,
        units=units,
        price=price,
        metadata=resolved_metadata,
        evidence=evidence or _evidence(),
        current_position_units=current_position_units,
    )
    return {result.rule: result.passed for result in results}


def _assert_rejects(rules: dict[str, bool], *names: str) -> None:
    for name in names:
        assert rules[name] is False, f"rule {name} must fail"


# ---------------------------------------------------------------------------
# AC-M08-W02-01: catalog allowability and instrument state boundaries
# ---------------------------------------------------------------------------


def test_all_rules_pass_for_valid_input() -> None:
    rules = _evaluate()
    assert all(rules.values()), rules


def test_unknown_instrument_fails_catalog_and_metadata_rules() -> None:
    # No metadata authority: catalog_known and every metadata-gated rule
    # fails closed — the instrument is treated as unknown.
    results = evaluate_instrument_rules(
        symbol="WIDGET_CFD",
        units=Decimal("1000"),
        price=Decimal("1.10500"),
        metadata=None,
        evidence=_evidence(),
    )
    rules = {result.rule: result.passed for result in results}
    _assert_rejects(rules, "catalog_known")
    for rule in (
        "units_precision",
        "price_precision",
        "minimum_size",
        "maximum_order_units",
        "position_cap",
    ):
        assert rules[rule] is False


def test_unknown_instrument_with_metadata_only_fails_catalog_known() -> None:
    # The evidence reports the symbol is not in the catalog; metadata
    # alone cannot rescue it, but the precision rules still evaluate.
    rules = _evaluate(
        symbol="WIDGET_CFD",
        evidence=_evidence(catalog_known=False),
    )
    _assert_rejects(rules, "catalog_known")
    assert rules["units_precision"] is True


def test_inactive_catalog_state_rejects() -> None:
    rules = _evaluate(evidence=_evidence(catalog_active=False))
    _assert_rejects(rules, "catalog_active")


def test_broker_tradeable_false_rejects() -> None:
    rules = _evaluate(evidence=_evidence(tradeable=False))
    _assert_rejects(rules, "broker_tradeable")


def test_units_precision_boundary() -> None:
    # Precision 0: whole units only.
    rules = _evaluate(units=Decimal("1.001"))
    _assert_rejects(rules, "units_precision")
    rules = _evaluate(units=Decimal("1000"))
    assert rules["units_precision"] is True
    # Precision 1 metadata accepts tenths.
    rules = _evaluate(
        units=Decimal("1.5"),
        metadata=_metadata(trade_units_precision=1),
    )
    assert rules["units_precision"] is True
    rules = _evaluate(
        units=Decimal("1.55"),
        metadata=_metadata(trade_units_precision=1),
    )
    _assert_rejects(rules, "units_precision")


def test_price_precision_boundary() -> None:
    rules = _evaluate(price=Decimal("1.105001"))
    _assert_rejects(rules, "price_precision")
    rules = _evaluate(price=Decimal("1.10500"))
    assert rules["price_precision"] is True
    rules = _evaluate(price=None)
    _assert_rejects(rules, "price_precision")


def test_minimum_size_boundary() -> None:
    rules = _evaluate(units=Decimal("1"))
    assert rules["minimum_size"] is True
    rules = _evaluate(
        units=Decimal("1"),
        metadata=_metadata(minimum_trade_size=Decimal("10")),
    )
    _assert_rejects(rules, "minimum_size")


def test_maximum_order_units_boundary() -> None:
    rules = _evaluate(
        units=Decimal("10000"),
        metadata=_metadata(maximum_order_units=Decimal("10000")),
    )
    assert rules["maximum_order_units"] is True
    rules = _evaluate(
        units=Decimal("10001"),
        metadata=_metadata(maximum_order_units=Decimal("10000")),
    )
    _assert_rejects(rules, "maximum_order_units")
    # Zero means unconfigured: never rejects.
    rules = _evaluate(units=Decimal("10001"))
    assert rules["maximum_order_units"] is True


def test_position_cap_boundary() -> None:
    rules = _evaluate(
        units=Decimal("400"),
        metadata=_metadata(maximum_position_size=Decimal("1000")),
        current_position_units=Decimal("600"),
    )
    assert rules["position_cap"] is True
    rules = _evaluate(
        units=Decimal("401"),
        metadata=_metadata(maximum_position_size=Decimal("1000")),
        current_position_units=Decimal("600"),
    )
    _assert_rejects(rules, "position_cap")
    # Zero means unconfigured: never rejects.
    rules = _evaluate(units=Decimal("100000"))
    assert rules["position_cap"] is True


def test_normalized_zero_quantity_rejects() -> None:
    rules = _evaluate(units=Decimal("0"))
    _assert_rejects(rules, "normalized_zero", "minimum_size")


def test_negative_units_are_size_checked_absolutely() -> None:
    rules = _evaluate(units=Decimal("-1000"))
    assert rules["minimum_size"] is True
    assert rules["normalized_zero"] is True


def test_rule_results_are_stable_for_identical_evidence() -> None:
    first = evaluate_instrument_rules(
        symbol="EUR_USD",
        units=Decimal("1000"),
        price=Decimal("1.10500"),
        metadata=_metadata(),
        evidence=_evidence(),
    )
    second = evaluate_instrument_rules(
        symbol="EUR_USD",
        units=Decimal("1000"),
        price=Decimal("1.10500"),
        metadata=_metadata(),
        evidence=_evidence(),
    )
    assert first == second


# ---------------------------------------------------------------------------
# AC-M08-W02-02: market evidence failures reject with stable results
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("evidence", "rule"),
    [
        (_evidence(session_open=False), "session_open"),
        (_evidence(session_holiday=True), "session_open"),
        (_evidence(session_evidence_stale=True), "session_open"),
        (_evidence(quote_present=False), "quote_fresh"),
        (_evidence(quote_fresh=False), "quote_fresh"),
        (_evidence(candle_complete=False), "candle_complete"),
        (_evidence(gap_excessive=True), "gap_bounded"),
        (_evidence(conversion_present=False), "conversion_present"),
        (_evidence(pricing_coverage_complete=False), "pricing_coverage_complete"),
    ],
    ids=[
        "closed-session",
        "holiday",
        "stale-session-evidence",
        "no-quote",
        "stale-quote",
        "incomplete-candle",
        "excessive-gap",
        "missing-conversion",
        "partial-coverage",
    ],
)
def test_market_evidence_failures_reject_new_exposure(
    evidence: MarketEvidence, rule: str
) -> None:
    rules = _evaluate(evidence=evidence)
    _assert_rejects(rules, rule)
    # Every other rule still passes: the failure is stable and targeted.
    assert sum(not passed for passed in rules.values()) == 1


def test_stale_catalog_evidence_rejects() -> None:
    # A stale catalog is expressed through catalog evidence: inactive
    # catalog state or unknown instrument fails closed.
    rules = _evaluate(evidence=_evidence(catalog_active=False))
    _assert_rejects(rules, "catalog_active")


# ---------------------------------------------------------------------------
# AC-M08-W02-03: normalization before evaluation; post-decision changes
# invalidate execution
# ---------------------------------------------------------------------------


def test_normalize_instrument_units_quantizes_to_precision() -> None:
    assert normalize_instrument_units(Decimal("1"), _metadata()) == Decimal("1")
    assert (
        normalize_instrument_units(
            Decimal("1.5"), _metadata(trade_units_precision=1)
        )
        == Decimal("1.5")
    )
    with pytest.raises(InstrumentConstraintError) as excinfo:
        normalize_instrument_units(Decimal("1.001"), _metadata())
    assert excinfo.value.kind == "units_precision"


def test_normalize_instrument_price_requires_representable_price() -> None:
    # Representable prices normalize (trailing zeros are canonical).
    normalized = normalize_instrument_price(
        Decimal("1.105"), _metadata(display_precision=5)
    )
    assert normalized == Decimal("1.10500")
    # A price beyond the display precision is never silently rounded.
    with pytest.raises(InstrumentConstraintError) as excinfo:
        normalize_instrument_price(
            Decimal("1.105001"), _metadata(display_precision=5)
        )
    assert excinfo.value.kind == "price_precision"
    with pytest.raises(InstrumentConstraintError):
        normalize_instrument_price(Decimal("0"), _metadata())


class _BindingInputs(TypedDict):
    """One typed set of executable binding inputs."""

    symbol: str
    units: Decimal
    price: Decimal | None
    instrument_version: str | None
    snapshot_hash: str | None


def test_binding_hash_changes_with_every_input() -> None:
    decision_id = "risk-1"
    base: _BindingInputs = {
        "symbol": "EUR_USD",
        "units": Decimal("1000"),
        "price": Decimal("1.10500"),
        "instrument_version": "catalog-2026-08-13",
        "snapshot_hash": "2026-08-13T12:00:00+00:00",
    }
    bound = bind_execution_inputs(decision_id, **base)
    assert validate_execution_inputs(decision_id, bound, **base) is True
    mutations: list[tuple[str, object]] = [
        ("units", Decimal("1001")),
        ("price", Decimal("1.10600")),
        ("symbol", "GBP_USD"),
        ("instrument_version", "catalog-2026-08-14"),
        ("snapshot_hash", "2026-08-13T13:00:00+00:00"),
    ]
    for field, value in mutations:
        changed = cast(_BindingInputs, {**dict(base), field: value})
        changed_hash = bind_execution_inputs(decision_id, **changed)
        assert changed_hash != bound, field


def _intent() -> OrderIntent:
    return OrderIntent(
        intent_id="ai_test",
        source="model",
        symbol="EUR_USD",
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        rationale="test",
        created_at=NOW,
    )


def _decision(*, execution_input_hash: str | None = None) -> RiskDecision:
    return RiskDecision(
        decision_id="risk_test",
        intent_id="ai_test",
        approved=True,
        reason="approved",
        max_quantity=Decimal("2"),
        risk_tags=["approved"],
        requires_human_review=False,
        source_module="test",
        created_at=NOW,
        execution_input_hash=execution_input_hash,
    )


class _FakeSources:
    """Complete, fresh venue sources with a deterministic clock."""

    def fetch_account(self) -> AccountSourceDatum:
        return AccountSourceDatum(
            account_id=ACCOUNT,
            state="ACTIVE",
            tradeable=True,
            home_currency="USD",
            balance=Decimal("10000"),
            nav=Decimal("10000"),
            margin_used=Decimal("0"),
            margin_available=Decimal("10000"),
            captured_at=NOW,
        )

    def fetch_positions(self) -> list[PositionDatum]:
        return []

    def fetch_pending_orders(self) -> list[PendingOrderDatum]:
        return []

    def fetch_trades(self) -> list[TradeDatum]:
        return []

    def fetch_prices(self) -> list[PriceDatum]:
        return [
            PriceDatum(
                symbol="EUR_USD",
                bid=Decimal("1.10400"),
                ask=Decimal("1.10420"),
                captured_at=NOW,
            )
        ]

    def fetch_conversions(self) -> list[ConversionDatum]:
        return []

    def fetch_catalog_version(self) -> str | None:
        return "catalog-2026-08-13"

    def fetch_reconciliation_state(self) -> ReconciliationState:
        return "clean"

    def fetch_health(self) -> HealthState:
        return "healthy"


def _adapter_with_submit(requests: list[SubmitRequest]) -> BrokerAdapter:
    class _Adapter(BrokerAdapter):
        async def health(self) -> BrokerHealth:
            return BrokerHealth(healthy=True, detail="ok", checked_at=NOW)

        async def submit(
            self, request: SubmitRequest, *, client_order_id: str
        ) -> SubmitResult:
            requests.append(request)
            return SubmitResult(
                broker_order_id=f"broker-{client_order_id}",
                client_order_id=client_order_id,
                status=BrokerOrderStatus.NEW,
                accepted_at=NOW,
            )

        async def cancel(self, broker_order_id: str) -> CancelResult:
            raise NotImplementedError

        async def get_order(self, broker_order_id: str) -> OrderState:
            raise NotImplementedError

        async def list_orders(
            self, status: BrokerOrderStatus | None = None
        ) -> list[OrderState]:
            return []

        async def list_fills(self, since: datetime | None = None) -> list[Fill]:
            return []

        async def get_positions(self) -> list[Position]:
            return []

        async def get_account(self) -> AccountSnapshot:
            raise NotImplementedError

    return _Adapter()


def test_backend_refuses_post_decision_input_change() -> None:
    """A bound decision whose executable inputs changed after approval is
    refused before any submit (AC-M08-W02-03, REQ-RISK-010)."""
    requests: list[SubmitRequest] = []
    adapter = _adapter_with_submit(requests)
    builder = BrokerRiskContextBuilder(_FakeSources(), clock=lambda: NOW)
    # The executable-inputs hash bound at approval uses the same
    # components the backend validates (M08-W07).
    bound_hash = hash_inputs(
        symbol="EUR_USD",
        units=Decimal("1"),
        price=None,
    )
    backend = ExternalPaperExecutionBackend(
        adapter, risk_context_builder=builder
    )

    # Matching inputs: the submit proceeds.
    result = backend.submit(
        _intent(),
        _decision(execution_input_hash=bound_hash),
        reference_price=Decimal("1.10"),
        now=NOW,
        estimated_quantity=Decimal("1"),
    )
    assert result.risk_context_version is not None
    assert len(requests) == 1

    # Changed quantity: the decision's bound inputs no longer match and
    # the submit is refused with no order reaching the adapter.
    with pytest.raises(ExecutionBackendError, match="no longer match"):
        backend.submit(
            _intent(),
            _decision(execution_input_hash=bound_hash),
            reference_price=Decimal("1.10"),
            now=NOW,
            estimated_quantity=Decimal("2"),
        )
    assert len(requests) == 1
