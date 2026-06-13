from datetime import UTC, date, datetime
from typing import Any

import pytest
from alphabrief_models import (
    MarketBrief,
    ModelResponse,
    SymbolBrief,
    SymbolVerdict,
    parse_structured_output,
)
from pydantic import ValidationError

GENERATED_AT = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
TRADING_DAY = date(2026, 6, 12)


def _market_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "brief_id": "mb_1",
        "generated_at": GENERATED_AT.isoformat(),
        "trading_day": TRADING_DAY.isoformat(),
        "regime": "neutral",
        "summary": "Range-bound session with low volume.",
        "confidence": 0.6,
        "key_factors": ["range", "low volume"],
    }
    payload.update(overrides)
    return payload


def _symbol_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "brief_id": "sb_1",
        "symbol": "NVDA",
        "generated_at": GENERATED_AT.isoformat(),
        "horizon": "1w",
        "verdict": {
            "direction": "bullish",
            "confidence": 0.7,
            "rationale": "Earnings momentum and AI demand.",
        },
        "catalysts": ["upcoming earnings"],
        "risks": ["regulatory"],
    }
    payload.update(overrides)
    return payload


# --- MarketBrief happy path ---


def test_market_brief_accepts_valid_data() -> None:
    brief = MarketBrief.model_validate(_market_payload())

    assert brief.brief_id == "mb_1"
    assert brief.regime == "neutral"
    assert brief.trading_day == TRADING_DAY
    assert brief.confidence == pytest.approx(0.6)
    assert brief.key_factors == ["range", "low volume"]


def test_market_brief_rejects_naive_datetime() -> None:
    payload = _market_payload()
    payload["generated_at"] = "2026-06-12T12:00:00"

    with pytest.raises(ValidationError, match="timezone-aware"):
        MarketBrief.model_validate(payload)


def test_market_brief_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        MarketBrief.model_validate(_market_payload(confidence=1.5))

    with pytest.raises(ValidationError):
        MarketBrief.model_validate(_market_payload(confidence=-0.1))


def test_market_brief_rejects_unknown_regime() -> None:
    with pytest.raises(ValidationError):
        MarketBrief.model_validate(_market_payload(regime="sideways"))


def test_market_brief_rejects_blank_fields() -> None:
    with pytest.raises(ValidationError, match="blank"):
        MarketBrief.model_validate(_market_payload(brief_id=" "))

    with pytest.raises(ValidationError, match="blank"):
        MarketBrief.model_validate(_market_payload(summary=" "))


def test_market_brief_rejects_blank_key_factors() -> None:
    with pytest.raises(ValidationError, match="blank"):
        MarketBrief.model_validate(_market_payload(key_factors=["range", "  "]))


def test_market_brief_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MarketBrief.model_validate(_market_payload(unexpected="nope"))


# --- SymbolBrief happy path ---


def test_symbol_brief_accepts_valid_data() -> None:
    brief = SymbolBrief.model_validate(_symbol_payload())

    assert brief.symbol == "NVDA"
    assert brief.horizon == "1w"
    assert brief.verdict.direction == "bullish"
    assert brief.verdict.confidence == pytest.approx(0.7)
    assert brief.catalysts == ["upcoming earnings"]
    assert brief.risks == ["regulatory"]


def test_symbol_brief_rejects_unknown_horizon() -> None:
    with pytest.raises(ValidationError):
        SymbolBrief.model_validate(_symbol_payload(horizon="1y"))


def test_symbol_brief_rejects_unknown_verdict_direction() -> None:
    payload = _symbol_payload()
    payload["verdict"] = {
        "direction": "sideways",
        "confidence": 0.5,
        "rationale": "r",
    }

    with pytest.raises(ValidationError):
        SymbolBrief.model_validate(payload)


def test_symbol_brief_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        SymbolBrief.model_validate(_symbol_payload(verdict={
            "direction": "bullish",
            "confidence": 1.1,
            "rationale": "r",
        }))


def test_symbol_verdict_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SymbolVerdict.model_validate(
            {
                "direction": "bullish",
                "confidence": 0.5,
                "rationale": "r",
                "unexpected": True,
            }
        )


def test_symbol_brief_rejects_blank_catalysts() -> None:
    with pytest.raises(ValidationError, match="blank"):
        SymbolBrief.model_validate(_symbol_payload(catalysts=["  "]))


def test_symbol_brief_rejects_blank_symbol() -> None:
    with pytest.raises(ValidationError, match="blank"):
        SymbolBrief.model_validate(_symbol_payload(symbol=" "))


def test_symbol_brief_serializes_to_json() -> None:
    brief = SymbolBrief.model_validate(_symbol_payload())

    payload = brief.model_dump(mode="json")

    assert payload["symbol"] == "NVDA"
    assert payload["verdict"]["direction"] == "bullish"


# --- Integration with parse_structured_output ---


def test_market_brief_validates_via_parse_structured_output() -> None:
    response = ModelResponse(
        request_id="req_1",
        provider="fake",
        model="fake-model",
        output_text="",
        structured_output=_market_payload(),
        status="succeeded",
        finish_reason="stop",
    )

    result = parse_structured_output(response, target=MarketBrief)

    assert result.ok is True
    assert result.parsed is not None
    assert result.parsed.regime == "neutral"


def test_symbol_brief_validates_via_parse_structured_output() -> None:
    response = ModelResponse(
        request_id="req_2",
        provider="fake",
        model="fake-model",
        output_text="",
        structured_output=_symbol_payload(),
        status="succeeded",
        finish_reason="stop",
    )

    result = parse_structured_output(response, target=SymbolBrief)

    assert result.ok is True
    assert result.parsed is not None
    assert result.parsed.symbol == "NVDA"
