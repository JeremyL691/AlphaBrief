"""Advisory-model boundary invariants.

Gym policies and advisory predictions can create evidence records but
cannot directly create an OrderIntent, a RiskDecision, or a broker
request.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from alphabrief_core import Bar

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
