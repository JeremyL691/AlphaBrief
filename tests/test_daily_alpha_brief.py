from datetime import UTC, date, datetime
from typing import Any

import pytest
from alphabrief_models import (
    DailyAlphaBrief,
    DailyBriefGenerationErrorCode,
    FakeProviderAdapter,
    ModelCapability,
    ModelGateway,
    StructuredOutputErrorCode,
    generate_daily_alpha_brief,
)
from pydantic import ValidationError

GENERATED_AT = datetime(2026, 6, 14, 8, 0, tzinfo=UTC)
TRADING_DAY = date(2026, 6, 14)


def _market_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "brief_id": "market_1",
        "generated_at": GENERATED_AT.isoformat(),
        "trading_day": TRADING_DAY.isoformat(),
        "regime": "neutral",
        "summary": "Risk assets are range-bound.",
        "confidence": 0.61,
        "key_factors": ["mixed breadth", "low realized volatility"],
    }
    payload.update(overrides)
    return payload


def _symbol_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "brief_id": "symbol_1",
        "symbol": "NVDA",
        "generated_at": GENERATED_AT.isoformat(),
        "horizon": "1w",
        "verdict": {
            "direction": "bullish",
            "confidence": 0.67,
            "rationale": "Momentum remains constructive.",
        },
        "catalysts": ["AI demand"],
        "risks": ["valuation"],
    }
    payload.update(overrides)
    return payload


def _daily_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "brief_id": "daily_1",
        "generated_at": GENERATED_AT.isoformat(),
        "trading_day": TRADING_DAY.isoformat(),
        "headline": "Risk assets consolidate",
        "executive_summary": "Market conditions remain mixed but orderly.",
        "market_brief": _market_payload(),
        "symbol_briefs": [_symbol_payload()],
        "watchlist": ["NVDA", "BTC-USD"],
        "risk_notes": ["Watch position sizing around earnings."],
    }
    payload.update(overrides)
    return payload


def _gateway_with_payload(
    payload: dict[str, Any],
    *,
    capabilities: list[ModelCapability] | None = None,
) -> ModelGateway:
    provider = FakeProviderAdapter(
        capabilities=capabilities or ["structured_output"],
        structured_output=payload,
    )
    return ModelGateway(
        [provider],
        clock=lambda: GENERATED_AT,
        call_id_factory=lambda: "call_1",
    )


def test_daily_alpha_brief_accepts_valid_data() -> None:
    brief = DailyAlphaBrief.model_validate(_daily_payload())

    assert brief.brief_id == "daily_1"
    assert brief.trading_day == TRADING_DAY
    assert brief.market_brief.regime == "neutral"
    assert brief.symbol_briefs[0].symbol == "NVDA"
    assert brief.watchlist == ["NVDA", "BTC-USD"]


def test_daily_alpha_brief_allows_empty_symbol_briefs_and_lists() -> None:
    brief = DailyAlphaBrief.model_validate(
        _daily_payload(symbol_briefs=[], watchlist=[], risk_notes=[])
    )

    assert brief.symbol_briefs == []
    assert brief.watchlist == []
    assert brief.risk_notes == []


def test_daily_alpha_brief_rejects_naive_generated_at() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        DailyAlphaBrief.model_validate(_daily_payload(generated_at="2026-06-14T08:00:00"))


def test_daily_alpha_brief_rejects_blank_required_strings() -> None:
    for field_name in ("brief_id", "headline", "executive_summary"):
        with pytest.raises(ValidationError, match="blank"):
            DailyAlphaBrief.model_validate(_daily_payload(**{field_name: "  "}))


def test_daily_alpha_brief_requires_matching_market_trading_day() -> None:
    market_payload = _market_payload(trading_day="2026-06-13")

    with pytest.raises(ValidationError, match="trading_day"):
        DailyAlphaBrief.model_validate(_daily_payload(market_brief=market_payload))


def test_daily_alpha_brief_rejects_blank_watchlist_or_risk_notes() -> None:
    with pytest.raises(ValidationError, match="blank"):
        DailyAlphaBrief.model_validate(_daily_payload(watchlist=["NVDA", " "]))

    with pytest.raises(ValidationError, match="blank"):
        DailyAlphaBrief.model_validate(_daily_payload(risk_notes=[" "]))


def test_daily_alpha_brief_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DailyAlphaBrief.model_validate(_daily_payload(unexpected="nope"))


def test_generate_daily_alpha_brief_succeeds_with_fake_provider() -> None:
    gateway = _gateway_with_payload(_daily_payload())

    result = generate_daily_alpha_brief(
        gateway,
        input_text="Generate today's AlphaBrief.",
        prompt_version="daily_alpha_brief_v1",
        request_id="request_1",
    )

    assert result.ok is True
    assert result.brief is not None
    assert result.brief.headline == "Risk assets consolidate"
    assert result.record.status == "succeeded"
    assert result.record.task_type == "daily_brief"
    assert result.record.prompt_version == "daily_alpha_brief_v1"
    assert len(result.record.input_hash) == 64


def test_generate_daily_alpha_brief_returns_error_when_provider_rejected() -> None:
    gateway = _gateway_with_payload(
        _daily_payload(),
        capabilities=["text_generation"],
    )

    result = generate_daily_alpha_brief(
        gateway,
        input_text="Generate today's AlphaBrief.",
        prompt_version="daily_alpha_brief_v1",
        request_id="request_1",
    )

    assert result.ok is False
    assert result.brief is None
    assert result.error_code is DailyBriefGenerationErrorCode.PROVIDER_REJECTED
    assert result.record.status == "rejected"


def test_generate_daily_alpha_brief_returns_error_when_provider_fails() -> None:
    gateway = ModelGateway(
        [FakeProviderAdapter(capabilities=["structured_output"], fail=True)],
        clock=lambda: GENERATED_AT,
        call_id_factory=lambda: "call_1",
    )

    result = generate_daily_alpha_brief(
        gateway,
        input_text="Generate today's AlphaBrief.",
        prompt_version="daily_alpha_brief_v1",
        request_id="request_1",
    )

    assert result.ok is False
    assert result.brief is None
    assert result.error_code is DailyBriefGenerationErrorCode.PROVIDER_FAILED
    assert result.record.status == "failed"


def test_generate_daily_alpha_brief_returns_parse_error() -> None:
    gateway = _gateway_with_payload(_daily_payload(headline=" "))

    result = generate_daily_alpha_brief(
        gateway,
        input_text="Generate today's AlphaBrief.",
        prompt_version="daily_alpha_brief_v1",
        request_id="request_1",
    )

    assert result.ok is False
    assert result.brief is None
    assert result.error_code is DailyBriefGenerationErrorCode.STRUCTURED_OUTPUT_INVALID
    assert (
        result.structured_error_code
        is StructuredOutputErrorCode.SCHEMA_VALIDATION_FAILED
    )
