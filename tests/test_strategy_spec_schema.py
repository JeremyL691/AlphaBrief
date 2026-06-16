from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from alphabrief_strategy import (
    EvaluationPeriod,
    ExternalEvidenceConfig,
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
    assert spec.external_evidence is None


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


def test_external_evidence_config_defaults_are_safe() -> None:
    cfg = ExternalEvidenceConfig()

    assert cfg.enabled is False
    assert cfg.source is None
    assert cfg.data_version is None
    assert cfg.require_human_review_on_negative is True
    assert cfg.negative_sentiment_threshold is None
    assert cfg.macro_indicators == []


def test_external_evidence_config_can_be_attached_to_spec() -> None:
    data = _valid_spec_data()
    data["external_evidence"] = {
        "enabled": True,
        "source": "news_alpha",
        "data_version": "v1",
        "require_human_review_on_negative": True,
        "negative_sentiment_threshold": -0.3,
        "macro_indicators": ["fred:CPIAUCSL", "fred:UNRATE"],
    }

    spec = StrategySpec(**data)

    assert spec.external_evidence is not None
    assert spec.external_evidence.enabled is True
    assert spec.external_evidence.source == "news_alpha"
    assert spec.external_evidence.data_version == "v1"
    assert spec.external_evidence.negative_sentiment_threshold == -0.3
    assert spec.external_evidence.macro_indicators == [
        "fred:CPIAUCSL",
        "fred:UNRATE",
    ]


def test_external_evidence_config_rejects_blank_strings() -> None:
    with pytest.raises(ValidationError, match="blank"):
        ExternalEvidenceConfig(source=" ")
    with pytest.raises(ValidationError, match="blank"):
        ExternalEvidenceConfig(data_version=" ")


def test_external_evidence_config_rejects_out_of_range_threshold() -> None:
    with pytest.raises(ValidationError):
        ExternalEvidenceConfig(negative_sentiment_threshold=-2.0)
    with pytest.raises(ValidationError):
        ExternalEvidenceConfig(negative_sentiment_threshold=2.0)


def test_external_evidence_config_rejects_blank_macro_indicators() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        ExternalEvidenceConfig(macro_indicators=[" ", "valid"])


def test_signal_evidence_defaults_are_safe() -> None:
    from alphabrief_core import SignalEvidence

    evidence = SignalEvidence()

    assert evidence.news_headline_ids == []
    assert evidence.macro_indicator_ids == []
    assert evidence.sentiment_score is None
    assert evidence.source is None
    assert evidence.data_version is None
    assert evidence.external_context_version is None
    assert evidence.generated_at is None


def test_signal_evidence_validates_sentiment_range() -> None:
    from alphabrief_core import SignalEvidence

    with pytest.raises(ValidationError):
        SignalEvidence(sentiment_score=-1.5)
    with pytest.raises(ValidationError):
        SignalEvidence(sentiment_score=2.0)

    valid = SignalEvidence(sentiment_score=0.42)
    assert valid.sentiment_score == 0.42


def test_signal_evidence_validates_generated_at_timezone() -> None:
    from alphabrief_core import SignalEvidence

    with pytest.raises(ValidationError, match="timezone"):
        SignalEvidence(generated_at=datetime(2024, 1, 1, 12, 0, 0))

    aware = SignalEvidence(generated_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC))
    assert aware.generated_at is not None


def test_signal_evidence_rejects_blank_ids() -> None:
    from alphabrief_core import SignalEvidence

    with pytest.raises(ValidationError, match="non-empty"):
        SignalEvidence(news_headline_ids=["valid", " "])
    with pytest.raises(ValidationError, match="non-empty"):
        SignalEvidence(macro_indicator_ids=[""])


def test_signal_accepts_optional_evidence_field() -> None:
    from alphabrief_core import Signal, SignalEvidence

    signal = Signal(
        signal_id="sig1",
        strategy_id="strategy_1",
        symbol="BTC-USD",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        direction="long",
        confidence=0.8,
        horizon="1m",
        rationale="test",
        evidence=SignalEvidence(
            news_headline_ids=["h1"],
            sentiment_score=-0.2,
            source="news_alpha",
        ),
    )

    assert signal.evidence is not None
    assert signal.evidence.news_headline_ids == ["h1"]


def test_signal_without_evidence_is_unchanged() -> None:
    from alphabrief_core import Signal

    signal = Signal(
        signal_id="sig1",
        strategy_id="strategy_1",
        symbol="BTC-USD",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        direction="long",
        confidence=0.8,
        horizon="1m",
        rationale="test",
    )

    assert signal.evidence is None
