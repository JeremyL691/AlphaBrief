"""Tests for the trading-cycle options behind ``alphabrief cycle`` (S3-4/S3-5).

Covers the safety measures the vertical slice depends on:

* ``trading_mode="off"`` runs the whole cycle and stops before submitting;
* ``quantity_override`` pins the first orders to a fixed size;
* ``direction_override`` requires a recorded reason and only changes the
  direction, leaving the committee output intact;
* the CLI refuses an instrument outside the reviewed universe and refuses
  ``--force-direction`` without ``--reason``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_cli.cycle_commands import _parse_units, _require_instrument
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import (
    DailyTradingCycle,
    DisciplineConfig,
    MarketSnapshot,
    TradingCommittee,
)
from alphabrief_trader.db_store import AiTradingStore

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)

_BULLISH = {
    "analysis": "Bullish continuation.",
    "view": "bullish",
    "confidence": 0.8,
    "evidence": ["trend"],
    "risks": [],
    "suggested_action": "buy",
    "target_position_pct": "0.10",
    "veto": False,
    "needs_human_review": False,
}


class _RecordingBackend:
    """Execution backend double that records submissions."""

    def __init__(self) -> None:
        self.submissions: list[dict[str, object]] = []

    def estimate_quantity(
        self, intent: object, *, reference_price: Decimal
    ) -> Decimal | None:
        quantity = getattr(intent, "quantity", None)
        return quantity if isinstance(quantity, Decimal) else None

    def submit(
        self,
        intent: object,
        decision: object,
        *,
        reference_price: Decimal,
        now: datetime,
        estimated_quantity: Decimal | None,
    ) -> object:
        from alphabrief_trader.execution_backend import ExecutionBackendResult

        self.submissions.append(
            {
                "intent_id": getattr(intent, "intent_id", ""),
                "side": getattr(intent, "side", ""),
                "quantity": getattr(intent, "quantity", None),
                "rationale": getattr(intent, "rationale", ""),
            }
        )
        return ExecutionBackendResult(
            execution_backend="external_paper",
            order_id="fake-1",
            broker_order_id="fake-1",
            filled=True,
            fill_price=reference_price,
            fill_quantity=Decimal("1"),
            fill_json=None,
        )


def _committee() -> TradingCommittee:
    provider = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=_BULLISH,
    )
    return TradingCommittee(
        gateway=ModelGateway(providers=[provider]),
        discipline=DisciplineConfig(),
    )


def _cycle(
    store: AiTradingStore,
    backend: object,
    *,
    trading_mode: str = "on",
    quantity_override: Decimal | None = None,
    direction_override: str | None = None,
    override_reason: str | None = None,
) -> DailyTradingCycle:
    return DailyTradingCycle(
        committee=_committee(),
        risk_gate=RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True, symbol_allowlist=frozenset({"EUR_USD"})
            )
        ),
        execution_backend=backend,  # type: ignore[arg-type]
        store=store,
        snapshot_loader=lambda symbol: MarketSnapshot(
            symbol=symbol,
            reference_price=Decimal("1.1000"),
            data_version="test",
            captured_at=NOW,
        ),
        enabled=True,
        clock=lambda: NOW,
        trading_mode=trading_mode,
        quantity_override=quantity_override,
        direction_override=direction_override,
        override_reason=override_reason,
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AiTradingStore]:
    trading_store = AiTradingStore(db_path=tmp_path / "trader.duckdb")
    try:
        yield trading_store
    finally:
        trading_store.close()


class TestTradingMode:
    def test_trading_off_stops_before_submitting(self, store: AiTradingStore) -> None:
        backend = _RecordingBackend()

        record = _cycle(store, backend, trading_mode="off").run(["EUR_USD"])

        assert record.outcome == "blocked_trading_off"
        assert backend.submissions == []
        assert record.attempts[0].outcome == "blocked_trading_off"
        # The reason is persisted on the attempt so an operator can see why
        # nothing was submitted.
        assert record.attempts[0].reason == "NO_TRADE_TRADING_OFF"

    def test_trading_on_submits(self, store: AiTradingStore) -> None:
        backend = _RecordingBackend()

        record = _cycle(store, backend, trading_mode="on").run(["EUR_USD"])

        assert record.outcome == "executed"
        assert len(backend.submissions) == 1

    def test_unknown_trading_mode_is_rejected(self, store: AiTradingStore) -> None:
        with pytest.raises(ValueError, match="trading_mode must be"):
            _cycle(store, _RecordingBackend(), trading_mode="maybe")


class TestQuantityOverride:
    def test_fixed_units_replace_position_sizing(self, store: AiTradingStore) -> None:
        backend = _RecordingBackend()

        record = _cycle(
            store, backend, quantity_override=Decimal("1000")
        ).run(["EUR_USD"])

        assert record.outcome == "executed"
        assert backend.submissions[0]["quantity"] == Decimal("1000")

    def test_without_override_the_committee_size_is_used(
        self, store: AiTradingStore
    ) -> None:
        backend = _RecordingBackend()

        _cycle(store, backend).run(["EUR_USD"])

        # No explicit quantity: the intent carries the committee's target.
        assert backend.submissions[0]["quantity"] is None


class TestDirectionOverride:
    def test_override_requires_a_reason(self, store: AiTradingStore) -> None:
        with pytest.raises(ValueError, match="requires a non-empty reason"):
            _cycle(store, _RecordingBackend(), direction_override="short")

    def test_override_rejects_an_unknown_direction(
        self, store: AiTradingStore
    ) -> None:
        with pytest.raises(ValueError, match="must be 'long' or 'short'"):
            _cycle(
                store,
                _RecordingBackend(),
                direction_override="sideways",
                override_reason="test",
            )

    def test_override_changes_direction_and_records_the_reason(
        self, store: AiTradingStore
    ) -> None:
        backend = _RecordingBackend()

        record = _cycle(
            store,
            backend,
            direction_override="short",
            override_reason="S3 vertical slice",
            quantity_override=Decimal("1000"),
        ).run(["EUR_USD"])

        assert backend.submissions[0]["side"] == "sell"
        assert "S3 vertical slice" in str(backend.submissions[0]["rationale"])
        # The committee's own output is still recorded unchanged.
        assert record.votes
        assert record.plans[0].side == "buy"


class TestCliArgumentChecks:
    def test_instrument_outside_the_universe_is_refused(self) -> None:
        with pytest.raises(SystemExit):
            _require_instrument("XAU_USD")

    def test_instrument_is_normalised(self) -> None:
        assert _require_instrument("eur_usd") == "EUR_USD"

    @pytest.mark.parametrize("raw", ["0", "-5", "abc", ""])
    def test_invalid_units_are_refused(self, raw: str) -> None:
        with pytest.raises(Exception, match="units"):
            _parse_units(raw)

    def test_units_are_parsed_as_decimal(self) -> None:
        assert _parse_units("1000") == Decimal("1000")
        assert _parse_units(None) is None


class TestExposureCapRegime:
    """PROJECT_GUIDE 5.6: NAV fractions when sizing is risk-based."""

    def test_nav_selects_the_percentage_caps(self) -> None:
        from alphabrief_cli.cycle_commands import (
            MAX_ORDER_NOTIONAL_PCT,
            MAX_TOTAL_EXPOSURE_PCT,
            _risk_gate,
        )

        nav = Decimal("100000")
        gate = _risk_gate(("EUR_USD",), nav=nav)

        assert gate.limits.max_order_value == nav * MAX_ORDER_NOTIONAL_PCT
        assert gate.limits.max_total_exposure == nav * MAX_TOTAL_EXPOSURE_PCT

    def test_without_nav_the_reviewed_absolute_caps_apply(self) -> None:
        from alphabrief_cli.cycle_commands import _risk_gate
        from alphabrief_core import load_paper_execution_policy, load_settings

        policy = load_paper_execution_policy(
            load_settings().execution_policy_file
        )
        gate = _risk_gate(("EUR_USD",))

        assert gate.limits.max_order_value == policy.max_order_notional
        assert gate.limits.max_total_exposure == policy.max_total_exposure
