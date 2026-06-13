"""Structured output parsing for AlphaBrief model responses.

The parser validates a model response against a Pydantic target schema. It does
not call providers, does not read environment variables, does not store secret
values, and does not modify the underlying :class:`ModelResponse`.
"""

import json
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from alphabrief_models.gateway import ModelResponse


class StructuredOutputErrorCode(StrEnum):
    """Stable error codes returned by the structured output parser."""

    EMPTY_OUTPUT = "empty_output"
    INVALID_JSON = "invalid_json"
    NOT_A_MAPPING = "not_a_mapping"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"


class StructuredOutputResult[TargetModel: BaseModel](BaseModel):
    """Result of a structured output parse attempt.

    The parser is failure-safe: it never raises for malformed or missing model
    output. Callers must inspect ``ok`` (or ``error_code``) before using
    ``parsed``.
    """

    model_config = ConfigDict(extra="forbid")

    parsed: TargetModel | None = None
    ok: bool = False
    error_code: StructuredOutputErrorCode | None = None
    error_message: str | None = None


_JsonDecoder = Callable[[str], Any]


def _default_json_decode(value: str) -> Any:
    return json.loads(value)


def _select_payload(
    response: ModelResponse,
    *,
    prefer_structured: bool,
    json_decode: _JsonDecoder,
) -> tuple[Any, StructuredOutputErrorCode | None, str | None]:
    """Pick the payload to validate and return any pre-parse errors."""

    if prefer_structured and response.structured_output is not None:
        return response.structured_output, None, None

    output_text = response.output_text
    if output_text is None or output_text.strip() == "":
        return (
            None,
            StructuredOutputErrorCode.EMPTY_OUTPUT,
            "model output_text is empty",
        )

    try:
        decoded = json_decode(output_text)
    except Exception:
        return (
            None,
            StructuredOutputErrorCode.INVALID_JSON,
            "output_text is not valid JSON",
        )

    if not isinstance(decoded, dict):
        return (
            None,
            StructuredOutputErrorCode.NOT_A_MAPPING,
            "decoded output is not a JSON object",
        )

    return decoded, None, None


def parse_structured_output[TargetModel: BaseModel](
    response: ModelResponse,
    *,
    target: type[TargetModel],
    prefer_structured: bool = True,
    json_decode: _JsonDecoder = _default_json_decode,
) -> StructuredOutputResult[TargetModel]:
    """Parse a :class:`ModelResponse` into a validated Pydantic instance.

    The parser is pure: it does not perform retries, provider calls, or
    side effects. Failures are reported as structured results with stable
    ``error_code`` values so callers can route or audit them.
    """

    payload, error_code, error_message = _select_payload(
        response,
        prefer_structured=prefer_structured,
        json_decode=json_decode,
    )

    if error_code is not None:
        return StructuredOutputResult[TargetModel](
            parsed=None,
            ok=False,
            error_code=error_code,
            error_message=error_message,
        )

    adapter: TypeAdapter[TargetModel] = TypeAdapter(target)
    try:
        parsed = adapter.validate_python(payload)
    except ValidationError as exc:
        return StructuredOutputResult[TargetModel](
            parsed=None,
            ok=False,
            error_code=StructuredOutputErrorCode.SCHEMA_VALIDATION_FAILED,
            error_message=str(exc),
        )

    return StructuredOutputResult[TargetModel](
        parsed=parsed,
        ok=True,
        error_code=None,
        error_message=None,
    )
