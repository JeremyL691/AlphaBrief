"""Tests for the real data-quality evaluation (S4-1).

PROJECT_GUIDE 5.7 rule 5 requires the risk gate to receive the *real*
result of the input-quality check. These tests pin the fail-closed
contract: stale, malformed, or future-dated inputs are rejected, and the
trading cycle passes that verdict through instead of hardcoding it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import (
    DailyTradingCycle,
    DisciplineConfig,
    MarketSnapshot,
    TradingCommittee,
)
from alphabrief_trader.data_quality import (
    DEFAULT_MAX_AGE_SECONDS,
    DataQualityVerdict,
    evaluate_snapshot_quality,
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


def _snapshot(*, captured_at: datetime = NOW, price: str = "1.1000") -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EUR_USD",
        reference_price=Decimal(price),
        data_version="test",
        captured_at=captured_at,
    )


class TestVerdicts:
    def test_fresh_snapshot_passes(self) -> None:
        verdict = evaluate_snapshot_quality(_snapshot(), now=NOW)

        assert verdict.passed is True
        assert verdict.reasons == ()

    def test_stale_snapshot_fails_with_the_age(self) -> None:
        stale = _snapshot(captured_at=NOW - timedelta(seconds=7201))

        verdict = evaluate_snapshot_quality(stale, now=NOW)

        assert verdict.passed is False
        assert verdict.reasons == ("snapshot_stale_7201s",)

    def test_snapshot_at_the_limit_still_passes(self) -> None:
        at_limit = _snapshot(
            captured_at=NOW - timedelta(seconds=DEFAULT_MAX_AGE_SECONDS)
        )

        assert evaluate_snapshot_quality(at_limit, now=NOW).passed is True

    def test_future_capture_time_fails(self) -> None:
        future = _snapshot(captured_at=NOW + timedelta(minutes=5))

        verdict = evaluate_snapshot_quality(future, now=NOW)

        assert verdict.passed is False
        assert "captured_at_in_the_future" in verdict.reasons

    def test_verdict_is_json_safe(self) -> None:
        verdict = evaluate_snapshot_quality(
            _snapshot(captured_at=NOW - timedelta(hours=5)), now=NOW
        )

        assert isinstance(verdict, DataQualityVerdict)
        payload = verdict.to_dict()
        assert payload["passed"] is False
        assert isinstance(payload["reasons"], list)


class _RecordingBackend:
    def __init__(self) -> None:
        self.submissions = 0

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

        self.submissions += 1
        return ExecutionBackendResult(
            execution_backend="external_paper",
            order_id="fake-1",
            broker_order_id="fake-1",
            filled=True,
            fill_price=reference_price,
            fill_quantity=Decimal("1"),
            fill_json=None,
        )


def _cycle(
    store: AiTradingStore,
    backend: object,
    *,
    snapshot: MarketSnapshot,
    clock: datetime = NOW,
) -> DailyTradingCycle:
    provider = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=_BULLISH,
    )
    return DailyTradingCycle(
        committee=TradingCommittee(
            gateway=ModelGateway(providers=[provider]),
            discipline=DisciplineConfig(),
        ),
        risk_gate=RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True, symbol_allowlist=frozenset({"EUR_USD"})
            )
        ),
        execution_backend=backend,  # type: ignore[arg-type]
        store=store,
        snapshot_loader=lambda symbol: snapshot,
        enabled=True,
        clock=lambda: clock,
        trading_mode="on",
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AiTradingStore]:
    trading_store = AiTradingStore(db_path=tmp_path / "trader.duckdb")
    try:
        yield trading_store
    finally:
        trading_store.close()


class TestCycleUsesTheRealVerdict:
    def test_stale_inputs_are_rejected_by_the_gate(
        self, store: AiTradingStore
    ) -> None:
        backend = _RecordingBackend()
        cycle = _cycle(
            store,
            backend,
            snapshot=_snapshot(captured_at=NOW - timedelta(hours=5)),
        )

        record = cycle.run(["EUR_USD"])

        assert record.outcome == "blocked_risk_gate"
        assert backend.submissions == 0
        # The rejection names the real reason, not a hardcoded pass.
        assert "data quality" in str(record.attempts[0].reason)

    def test_fresh_inputs_execute(self, store: AiTradingStore) -> None:
        backend = _RecordingBackend()

        record = _cycle(store, backend, snapshot=_snapshot()).run(["EUR_USD"])

        assert record.outcome == "executed"
        assert backend.submissions == 1
