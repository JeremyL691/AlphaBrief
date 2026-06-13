import json
from typing import Any

from alphabrief_models import (
    ModelResponse,
    StructuredOutputErrorCode,
    parse_structured_output,
)
from pydantic import BaseModel, Field


class SymbolVerdict(BaseModel):
    symbol: str = Field(min_length=1)
    view: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


def _response(
    *,
    output_text: str = "",
    structured_output: dict[str, Any] | None = None,
) -> ModelResponse:
    return ModelResponse(
        request_id="req_1",
        provider="fake",
        model="fake-model",
        output_text=output_text,
        structured_output=structured_output,
        status="succeeded",
        finish_reason="stop",
    )


# --- Success cases ---


def test_parser_succeeds_with_structured_output_payload() -> None:
    payload: dict[str, Any] = {"symbol": "NVDA", "view": "watchlist", "confidence": 0.7}
    result = parse_structured_output(
        _response(structured_output=payload), target=SymbolVerdict
    )

    assert result.ok is True
    assert result.parsed is not None
    assert result.parsed.symbol == "NVDA"
    assert result.parsed.confidence == 0.7
    assert result.error_code is None


def test_parser_succeeds_when_parsing_output_text_json() -> None:
    payload = {"symbol": "BTC-USD", "view": "long", "confidence": 0.4}
    result = parse_structured_output(
        _response(output_text=json.dumps(payload)),
        target=SymbolVerdict,
        prefer_structured=False,
    )

    assert result.ok is True
    assert result.parsed is not None
    assert result.parsed.symbol == "BTC-USD"


# --- Failure cases ---


def test_parser_fails_when_output_text_is_empty_and_no_structured_payload() -> None:
    result = parse_structured_output(_response(), target=SymbolVerdict)

    assert result.ok is False
    assert result.parsed is None
    assert result.error_code is StructuredOutputErrorCode.EMPTY_OUTPUT


def test_parser_fails_when_output_text_is_not_valid_json() -> None:
    result = parse_structured_output(
        _response(output_text="not-a-json"),
        target=SymbolVerdict,
        prefer_structured=False,
    )

    assert result.ok is False
    assert result.parsed is None
    assert result.error_code is StructuredOutputErrorCode.INVALID_JSON


def test_parser_fails_when_decoded_value_is_not_a_mapping() -> None:
    result = parse_structured_output(
        _response(output_text="[1, 2, 3]"),
        target=SymbolVerdict,
        prefer_structured=False,
    )

    assert result.ok is False
    assert result.parsed is None
    assert result.error_code is StructuredOutputErrorCode.NOT_A_MAPPING


def test_parser_fails_when_schema_validation_rejects_payload() -> None:
    result = parse_structured_output(
        _response(
            structured_output={"symbol": "NVDA", "view": "watch", "confidence": 1.5}
        ),
        target=SymbolVerdict,
    )

    assert result.ok is False
    assert result.parsed is None
    assert result.error_code is StructuredOutputErrorCode.SCHEMA_VALIDATION_FAILED


# --- Behaviour ---


def test_parser_prefers_structured_output_when_available() -> None:
    response = _response(
        output_text=json.dumps({"symbol": "WRONG", "view": "wrong", "confidence": 0.0}),
        structured_output={"symbol": "NVDA", "view": "watchlist", "confidence": 0.6},
    )

    result = parse_structured_output(response, target=SymbolVerdict)

    assert result.ok is True
    assert result.parsed is not None
    assert result.parsed.symbol == "NVDA"


def test_parser_falls_back_to_output_text_when_structured_output_is_none() -> None:
    response = _response(
        output_text=json.dumps({"symbol": "ETH-USD", "view": "flat", "confidence": 0.1})
    )

    result = parse_structured_output(
        response, target=SymbolVerdict, prefer_structured=False
    )

    assert result.ok is True
    assert result.parsed is not None
    assert result.parsed.symbol == "ETH-USD"


def test_parser_treats_decoder_exceptions_as_invalid_json() -> None:
    def raising_decoder(_value: str) -> Any:
        raise RuntimeError("decoder exploded")

    result = parse_structured_output(
        _response(output_text="ignored"),
        target=SymbolVerdict,
        prefer_structured=False,
        json_decode=raising_decoder,
    )

    assert result.ok is False
    assert result.parsed is None
    assert result.error_code is StructuredOutputErrorCode.INVALID_JSON


def test_parser_uses_injected_decoder() -> None:
    calls: list[str] = []

    def tracking_decoder(value: str) -> Any:
        calls.append(value)
        return json.loads(value)

    payload = {"symbol": "SPY", "view": "long", "confidence": 0.8}
    result = parse_structured_output(
        _response(output_text=json.dumps(payload)),
        target=SymbolVerdict,
        prefer_structured=False,
        json_decode=tracking_decoder,
    )

    assert result.ok is True
    assert len(calls) == 1
    assert calls[0] == json.dumps(payload)
