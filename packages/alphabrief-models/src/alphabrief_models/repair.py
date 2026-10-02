"""Bounded structured-output repair for ModelGateway calls (M10-W05).

When a model returns invalid JSON, a schema violation, or a grounding
violation (e.g. a nonexistent citation), the caller may re-ask the model
through the gateway a bounded number of times. Every attempt records a
typed verdict (attempt number, outcome, error code, model-call ID, UTC
timestamp); exhausted repair is a terminal failure that must resolve to
a blocked or no-trade result — never to an OrderIntent.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_models.gateway import ModelGateway, ModelRequest, ModelResponse
from alphabrief_models.structured_output import (
    StructuredOutputResult,
    parse_structured_output,
)

_MAX_REPAIR_PROMPT_CHARS = 4000


class RepairVerdict(BaseModel):
    """One bounded repair attempt and its terminal verdict."""

    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    ok: bool
    error_code: str | None = None
    model_call_id: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class StructuredRepairResult(BaseModel):
    """Outcome of a bounded repair sequence."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    parsed: BaseModel | None = None
    attempts: list[RepairVerdict] = Field(default_factory=list)
    exhausted: bool = False
    response: ModelResponse | None = None


def default_repair_prompt_builder(
    request: ModelRequest,
    raw_output: str,
    failure_reason: str,
) -> str:
    """Build the deterministic repair prompt from the failed output."""
    bounded_output = raw_output[:_MAX_REPAIR_PROMPT_CHARS]
    return (
        "Your previous response failed validation. Return ONLY valid JSON "
        "matching the requested schema — no markdown code blocks, no extra "
        "text. Keep every factual claim grounded in the evidence IDs already "
        "available; do not invent citations.\n\n"
        f"Failure reason: {failure_reason}\n\n"
        f"Previous output:\n{bounded_output}\n\n"
        f"Original task:\n{request.input_text[:_MAX_REPAIR_PROMPT_CHARS]}"
    )


def repair_structured_output[TargetModel: BaseModel](
    *,
    gateway: ModelGateway,
    request: ModelRequest,
    target: type[TargetModel],
    raw_output: str,
    failure_reason: str,
    max_attempts: int = 2,
    repair_prompt_builder: Callable[[ModelRequest, str, str], str] | None = None,
    grounding_check: Callable[[TargetModel], Sequence[str]] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> StructuredRepairResult:
    """Re-ask the model up to ``max_attempts`` times until output validates.

    Each attempt invokes the gateway (every call record persists through
    the gateway's ``record_sink``) and records a :class:`RepairVerdict`.
    The repair prompt carries the schema hint, the previous raw output
    (bounded), and the failure reason; grounding violations are checked
    after every successful parse when ``grounding_check`` is provided.
    Exhausted attempts return ``ok=False, exhausted=True`` — the caller
    must resolve this to blocked or no-trade.
    """
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    builder = repair_prompt_builder or default_repair_prompt_builder
    now = clock or (lambda: datetime.now(UTC))
    attempts: list[RepairVerdict] = []
    current_raw = raw_output
    current_reason = failure_reason

    for attempt in range(1, max_attempts + 1):
        repair_request = request.model_copy(
            update={
                "request_id": f"{request.request_id}_repair_{attempt}",
                "call_kind": "repair",
                "input_text": builder(request, current_raw, current_reason),
            }
        )
        result = gateway.invoke(repair_request)
        if result.response is None or result.record.status != "succeeded":
            error_code = "provider_call_failed"
            if result.record.classification == "budget_exhausted":
                error_code = "model_budget:" + (
                    result.record.error_type or "budget_exhausted"
                )
                if (result.record.error_type or "").endswith(
                    ":NO_TRADE_MODEL_UNAVAILABLE"
                ):
                    error_code = "provider_unavailable:NO_TRADE_MODEL_UNAVAILABLE"
            attempts.append(
                RepairVerdict(
                    attempt=attempt,
                    ok=False,
                    error_code=error_code,
                    model_call_id=result.record.call_id,
                    created_at=now(),
                )
            )
            if result.record.classification == "budget_exhausted":
                break
            current_reason = "provider_call_failed"
            continue

        parsed: StructuredOutputResult[TargetModel] = parse_structured_output(
            result.response, target=target
        )
        violations = (
            []
            if parsed.parsed is None or grounding_check is None
            else list(grounding_check(parsed.parsed))
        )
        gateway.record_validation(
            result.record.call_id,
            target=target,
            parsed=parsed.parsed,
            error_code=None if parsed.ok else str(parsed.error_code),
            violations=violations,
        )
        if not parsed.ok or parsed.parsed is None:
            code = parsed.error_code or "schema_validation_failed"
            attempts.append(
                RepairVerdict(
                    attempt=attempt,
                    ok=False,
                    error_code=f"schema_validation_failed:{code}",
                    model_call_id=result.record.call_id,
                    created_at=now(),
                )
            )
            current_raw = result.response.output_text
            current_reason = f"schema_validation_failed:{code}"
            continue

        if grounding_check is not None:
            if violations:
                attempts.append(
                    RepairVerdict(
                        attempt=attempt,
                        ok=False,
                        error_code="grounding_failed:" + ",".join(violations),
                        model_call_id=result.record.call_id,
                        created_at=now(),
                    )
                )
                current_raw = result.response.output_text
                current_reason = "grounding_failed:" + ",".join(violations)
                continue

        attempts.append(
            RepairVerdict(
                attempt=attempt,
                ok=True,
                model_call_id=result.record.call_id,
                created_at=now(),
            )
        )
        return StructuredRepairResult(
            ok=True,
            parsed=parsed.parsed,
            attempts=attempts,
            exhausted=False,
            response=result.response,
        )

    return StructuredRepairResult(
        ok=False,
        parsed=None,
        attempts=attempts,
        exhausted=True,
    )


__all__ = [
    "RepairVerdict",
    "StructuredRepairResult",
    "default_repair_prompt_builder",
    "repair_structured_output",
]
