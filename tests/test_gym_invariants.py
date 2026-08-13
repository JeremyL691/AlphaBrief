"""M12-W06: advisory-model boundary invariants.

Covers AC-M12-W06-03: Kronos, Gym, and advisory predictions can create
evidence records but cannot directly create an OrderIntent, a
RiskDecision, or a broker request.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import Bar, OrderIntent
from alphabrief_models import (
    DeterministicKronosRuntime,
    KronosForecastEvidence,
    KronosForecastRequest,
    build_kronos_evidence,
)
from alphabrief_risk.decision_store import RiskDecisionRecord
from pydantic import ValidationError

GYM_PACKAGE = (
    Path(__file__).resolve().parents[1]
    / "packages/alphabrief-gym/src/alphabrief_gym"
)

#: Symbols that must never appear in the Gym package (evidence only).
_FORBIDDEN_TOKENS = (
    "OrderIntent",
    "RiskDecision",
    "broker",
    "submit",
    "oanda",
)


def _bars(symbol: str = "SPY") -> list[Bar]:
    start = datetime(2026, 6, 1, 13, 30, tzinfo=UTC)
    return [
        Bar(
            symbol=symbol,
            timestamp=start + timedelta(days=index),
            open=Decimal(str(100 + index)),
            high=Decimal(str(101 + index)),
            low=Decimal(str(99 + index)),
            close=Decimal(str(100 + index)),
            volume=Decimal("1000"),
            source="unit",
            data_version="v1",
        )
        for index in range(3)
    ]


def _evidence() -> KronosForecastEvidence:
    request = KronosForecastRequest(
        request_id="req_1",
        symbol="SPY",
        bars=_bars(),
        prediction_length=2,
    )
    report = DeterministicKronosRuntime(
        clock=lambda: datetime(2026, 6, 2, 12, tzinfo=UTC),
        forecast_id_factory=lambda: "forecast_1",
    ).forecast(request)
    return build_kronos_evidence(report)


class TestGymBoundary:
    def test_gym_sources_never_reference_orders_or_brokers(self) -> None:
        for source in GYM_PACKAGE.glob("*.py"):
            text = source.read_text(encoding="utf-8")
            for token in _FORBIDDEN_TOKENS:
                assert token not in text, (
                    f"{source.name} contains forbidden token {token!r}"
                )

    def test_gym_public_exports_are_evidence_only(self) -> None:
        import alphabrief_gym

        for name in alphabrief_gym.__all__:
            lowered = name.lower()
            assert "order" not in lowered
            assert "broker" not in lowered
            assert "submit" not in lowered

    def test_gym_policy_output_is_a_typed_evaluation_not_an_order(self) -> None:
        from alphabrief_gym import EpisodeMetrics, PolicyEvaluation

        evaluation = PolicyEvaluation(
            policy_name="buy_and_hold",
            metrics=EpisodeMetrics(
                initial_value=Decimal("10000"),
                final_value=Decimal("11000"),
                total_return=Decimal("0.10"),
                max_drawdown=Decimal("0.05"),
                steps=10,
                trades=1,
            ),
        )
        assert isinstance(evaluation, PolicyEvaluation)
        assert "OrderIntent" not in type(evaluation).model_fields
        assert "OrderIntent" not in type(evaluation.metrics).model_fields

    def test_no_gym_function_returns_an_order_intent(self) -> None:
        import alphabrief_gym

        for name in alphabrief_gym.__all__:
            member = getattr(alphabrief_gym, name)
            if inspect.isfunction(member):
                annotation = str(inspect.signature(member).return_annotation)
                assert "OrderIntent" not in annotation, name


class TestKronosEvidenceBoundary:
    def test_evidence_records_are_advisory_only_and_locked(self) -> None:
        evidence = _evidence()
        assert evidence.advisory_only is True
        with pytest.raises(ValueError, match="advisory_only"):
            KronosForecastEvidence.model_validate(
                {
                    **evidence.model_dump(),
                    "advisory_only": False,
                }
            )

    def test_evidence_cannot_become_an_order_intent(self) -> None:
        evidence = _evidence()
        order_like = {
            "intent_id": evidence.forecast_id,
            "symbol": evidence.symbol,
            "rationale": evidence.model,
        }
        with pytest.raises(ValidationError):
            OrderIntent.model_validate(order_like)

    def test_evidence_cannot_become_a_risk_decision(self) -> None:
        evidence = _evidence()
        # A persisted RiskDecision requires authority fields the
        # evidence record cannot supply; building one from evidence
        # data alone must fail validation.
        with pytest.raises(ValidationError):
            RiskDecisionRecord.model_validate(evidence.model_dump())
        required = {"decision_id", "account_id", "policy_hash", "inputs_hash"}
        missing = required - set(evidence.model_dump())
        assert missing == required

    def test_order_intent_requires_fields_evidence_does_not_have(self) -> None:
        evidence = _evidence()
        # An evidence record has no side, order type, or created_at;
        # constructing an order from it must fail validation.
        with pytest.raises(ValidationError):
            OrderIntent.model_validate(evidence.model_dump())


class TestAdvisoryEvidenceRecords:
    def test_kronos_evidence_is_a_durable_record(self) -> None:
        evidence = _evidence()
        assert evidence.forecast_id == "forecast_1"
        assert evidence.symbol == "SPY"
        assert evidence.direction_bias in ("bullish", "bearish", "neutral")
        assert 0 <= evidence.confidence <= 1
        assert evidence.expected_return is not None

    def test_evidence_fields_are_typed_and_bounded(self) -> None:
        evidence = _evidence()
        payload = evidence.model_dump()
        assert set(payload) == {
            "forecast_id",
            "symbol",
            "model",
            "horizon_steps",
            "direction_bias",
            "confidence",
            "expected_return",
            "generated_at",
            "advisory_only",
        }
        assert evidence.horizon_steps >= 1
