from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from alphabrief_strategy import (
    EvaluationPeriod,
    StrategyCosts,
    StrategyEvaluation,
    StrategyRisk,
    StrategyRule,
    StrategySpec,
    StrategyUniverse,
)
from pydantic import ValidationError


def _valid_spec_data() -> dict[str, Any]:
    return {
        "strategy_id": "ema_trend_v1",
        "name": "EMA Trend Following",
        "version": "1.0.0",
        "universe": {"symbols": ["BTC-USD"]},
        "timeframe": "4h",
        "entry": {"condition": "close > ema_50"},
        "exit": {"condition": "close < ema_50"},
        "risk": {
            "max_position_pct": Decimal("0.2"),
            "stop_loss": "atr_2x",
        },
        "costs": {
            "fee_bps": Decimal("5"),
            "slippage_bps": Decimal("10"),
        },
        "evaluation": {
            "train_period": {
                "start": date(2020, 1, 1),
                "end": date(2023, 12, 31),
            },
            "test_period": {
                "start": date(2024, 1, 1),
                "end": date(2025, 12, 31),
            },
        },
    }


def test_valid_strategy_spec_can_be_created() -> None:
    spec = StrategySpec(**_valid_spec_data())

    assert spec.strategy_id == "ema_trend_v1"
    assert spec.universe.symbols == ["BTC-USD"]
    assert spec.risk.max_position_pct == Decimal("0.2")
    assert spec.costs.fee_bps == Decimal("5")


@pytest.mark.parametrize("field", ["strategy_id", "name", "version", "timeframe"])
def test_strategy_spec_key_strings_must_not_be_blank(field: str) -> None:
    data = _valid_spec_data()
    data[field] = " "

    with pytest.raises(ValidationError):
        StrategySpec(**data)


def test_universe_symbols_must_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        StrategyUniverse(symbols=[])

    with pytest.raises(ValidationError, match="empty"):
        StrategyUniverse(symbols=["BTC-USD", " "])


def test_universe_symbols_are_stably_deduplicated() -> None:
    universe = StrategyUniverse(symbols=["BTC-USD", "ETH-USD", "BTC-USD"])

    assert universe.symbols == ["BTC-USD", "ETH-USD"]


def test_entry_and_exit_conditions_must_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        StrategyRule(condition="")

    with pytest.raises(ValidationError, match="blank"):
        StrategyRule(condition="   ")


def test_max_position_pct_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        StrategyRisk(max_position_pct=Decimal("-0.01"))

    with pytest.raises(ValidationError):
        StrategyRisk(max_position_pct=Decimal("1.01"))


def test_stop_loss_must_not_be_blank_when_provided() -> None:
    with pytest.raises(ValidationError, match="stop_loss"):
        StrategyRisk(max_position_pct=Decimal("0.2"), stop_loss=" ")


def test_costs_reject_negative_values_and_float_inputs() -> None:
    with pytest.raises(ValidationError):
        StrategyCosts(fee_bps=Decimal("-1"), slippage_bps=Decimal("0"))

    with pytest.raises(ValidationError, match="float"):
        StrategyCosts.model_validate(
            {"fee_bps": 1.0, "slippage_bps": Decimal("0")}
        )

    with pytest.raises(ValidationError, match="float"):
        StrategyCosts.model_validate(
            {"fee_bps": Decimal("1"), "slippage_bps": 0.5}
        )


def test_evaluation_period_rejects_reversed_dates() -> None:
    with pytest.raises(ValidationError, match="start"):
        EvaluationPeriod(start=date(2024, 1, 2), end=date(2024, 1, 1))


def test_test_period_must_start_after_train_period() -> None:
    with pytest.raises(ValidationError, match="test period"):
        StrategyEvaluation(
            train_period=EvaluationPeriod(
                start=date(2020, 1, 1),
                end=date(2024, 1, 1),
            ),
            test_period=EvaluationPeriod(
                start=date(2024, 1, 1),
                end=date(2025, 1, 1),
            ),
        )

    with pytest.raises(ValidationError, match="test period"):
        StrategyEvaluation(
            train_period=EvaluationPeriod(
                start=date(2020, 1, 1),
                end=date(2024, 1, 2),
            ),
            test_period=EvaluationPeriod(
                start=date(2024, 1, 1),
                end=date(2025, 1, 1),
            ),
        )


def test_extra_fields_are_forbidden() -> None:
    data = _valid_spec_data()
    data["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StrategySpec(**data)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StrategyRule.model_validate(
            {"condition": "close > ema_50", "unexpected": True}
        )
