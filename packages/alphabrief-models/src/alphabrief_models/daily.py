"""Daily AlphaBrief generation through the ModelGateway."""

from collections.abc import Sequence
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from alphabrief_models.briefs import DailyAlphaBrief
from alphabrief_models.gateway import (
    ModelCallRecord,
    ModelCapability,
    ModelGateway,
    ModelRequest,
)
from alphabrief_models.structured_output import (
    StructuredOutputErrorCode,
    parse_structured_output,
)


class DailyBriefGenerationErrorCode(StrEnum):
    """Stable error codes for daily brief generation failures."""

    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_FAILED = "provider_failed"
    STRUCTURED_OUTPUT_INVALID = "structured_output_invalid"


class DailyBriefGenerationResult(BaseModel):
    """Result of a DailyAlphaBrief generation attempt."""

    model_config = ConfigDict(extra="forbid")

    brief: DailyAlphaBrief | None = None
    ok: bool = False
    record: ModelCallRecord
    error_code: DailyBriefGenerationErrorCode | None = None
    structured_error_code: StructuredOutputErrorCode | None = None
    error_message: str | None = None


def generate_daily_alpha_brief(
    gateway: ModelGateway,
    *,
    input_text: str,
    prompt_version: str,
    request_id: str | None = None,
    required_capabilities: Sequence[ModelCapability] = ("structured_output",),
    metadata: dict[str, str] | None = None,
) -> DailyBriefGenerationResult:
    """Generate and validate a DailyAlphaBrief through ModelGateway."""

    request = ModelRequest(
        request_id=request_id or f"daily_brief_{uuid4().hex}",
        task_type="daily_brief",
        prompt_version=prompt_version,
        input_text=input_text,
        required_capabilities=list(required_capabilities),
        metadata=metadata or {},
    )
    gateway_result = gateway.invoke(request)

    if gateway_result.response is None:
        return DailyBriefGenerationResult(
            brief=None,
            ok=False,
            record=gateway_result.record,
            error_code=_generation_error_code(gateway_result.record),
            structured_error_code=None,
            error_message=gateway_result.record.error_type,
        )

    parsed = parse_structured_output(
        gateway_result.response,
        target=DailyAlphaBrief,
    )
    if not parsed.ok:
        return DailyBriefGenerationResult(
            brief=None,
            ok=False,
            record=gateway_result.record,
            error_code=DailyBriefGenerationErrorCode.STRUCTURED_OUTPUT_INVALID,
            structured_error_code=parsed.error_code,
            error_message=parsed.error_message,
        )

    return DailyBriefGenerationResult(
        brief=parsed.parsed,
        ok=True,
        record=gateway_result.record,
        error_code=None,
        structured_error_code=None,
        error_message=None,
    )


def _generation_error_code(
    record: ModelCallRecord,
) -> DailyBriefGenerationErrorCode:
    if record.status == "rejected":
        return DailyBriefGenerationErrorCode.PROVIDER_REJECTED
    return DailyBriefGenerationErrorCode.PROVIDER_FAILED
