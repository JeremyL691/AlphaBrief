"""Model gateway contracts for AlphaBrief.

This module defines the only runtime boundary for model calls. It does not
implement real provider SDK integrations, prompt templates, agents, research
briefs, trading decisions, or risk controls.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from time import perf_counter
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

ModelCapability = Literal[
    "text_generation",
    "structured_output",
    "tool_calling",
    "json_mode",
    "long_context",
    "low_latency",
    "low_cost",
    "strong_reasoning",
    "multilingual",
    "code_generation",
    "vision",
    "embeddings",
    "reranking",
]
ModelTaskType = Literal[
    "market_summary",
    "symbol_research",
    "risk_review",
    "strategy_review",
    "daily_brief",
    "test",
]
ModelResponseStatus = Literal["succeeded", "failed"]
ModelCallStatus = Literal["succeeded", "failed", "rejected"]


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _validate_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime fields must be timezone-aware")
    return value


class AlphaBriefModelSchema(BaseModel):
    """Shared strict schema configuration for model boundary objects."""

    model_config = ConfigDict(extra="forbid")


class ModelRequest(AlphaBriefModelSchema):
    request_id: str = Field(min_length=1)
    task_type: ModelTaskType
    prompt_version: str = Field(min_length=1)
    input_text: str = Field(min_length=1)
    required_capabilities: list[ModelCapability] = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("required_capabilities")
    @classmethod
    def capabilities_must_be_unique(
        cls, value: list[ModelCapability]
    ) -> list[ModelCapability]:
        deduplicated = list(dict.fromkeys(value))
        if len(deduplicated) != len(value):
            raise ValueError("required_capabilities must not contain duplicates")
        return value

    @field_validator("metadata")
    @classmethod
    def metadata_must_not_use_secret_keys(
        cls, value: dict[str, str]
    ) -> dict[str, str]:
        secret_markers = ("api_key", "secret", "token", "password")
        for key in value:
            normalized = key.lower()
            if any(marker in normalized for marker in secret_markers):
                raise ValueError("metadata must not include secret-like keys")
        return value


class ModelResponse(AlphaBriefModelSchema):
    request_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    output_text: str
    structured_output: dict[str, Any] | None = None
    status: ModelResponseStatus = "succeeded"
    finish_reason: str = Field(min_length=1)


class ModelCallRecord(AlphaBriefModelSchema):
    call_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    task_type: ModelTaskType
    prompt_version: str = Field(min_length=1)
    input_hash: str = Field(min_length=64, max_length=64)
    output_hash: str = Field(min_length=0, max_length=64)
    latency_ms: int = Field(ge=0)
    cost_estimate: Decimal | None = None
    status: ModelCallStatus
    error_type: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("cost_estimate", mode="before")
    @classmethod
    def cost_estimate_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("cost_estimate must not be provided as a float")
        return value


class ModelGatewayResult(AlphaBriefModelSchema):
    response: ModelResponse | None
    record: ModelCallRecord


class ModelProviderError(Exception):
    """Raised when a provider adapter cannot complete a model call."""


class ProviderAdapter(Protocol):
    """Provider adapter contract used by ModelGateway."""

    provider_name: str
    model_name: str
    capabilities: frozenset[ModelCapability]

    def call(self, request: ModelRequest) -> ModelResponse:
        """Call the provider for a validated request."""


class FakeProviderAdapter:
    """Deterministic provider adapter for tests and local development."""

    def __init__(
        self,
        *,
        provider_name: str = "fake",
        model_name: str = "fake-model",
        capabilities: Sequence[ModelCapability] | None = None,
        output_text: str = "fake response",
        structured_output: dict[str, Any] | None = None,
        fail: bool = False,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        default_capabilities: Sequence[ModelCapability] = ("text_generation",)
        selected_capabilities = capabilities or default_capabilities
        self.capabilities: frozenset[ModelCapability] = frozenset(
            selected_capabilities
        )
        self.output_text = output_text
        self.structured_output = structured_output
        self.fail = fail

    def call(self, request: ModelRequest) -> ModelResponse:
        if self.fail:
            raise ModelProviderError("fake provider failure")

        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self.model_name,
            output_text=self.output_text,
            structured_output=self.structured_output,
            status="succeeded",
            finish_reason="stop",
        )


class ModelGateway:
    """Capability-based gateway for model provider calls."""

    def __init__(
        self,
        providers: Sequence[ProviderAdapter],
        *,
        clock: Callable[[], datetime] | None = None,
        call_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._providers = list(providers)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._call_id_factory = call_id_factory or (lambda: f"model_call_{uuid4().hex}")
        self.call_records: list[ModelCallRecord] = []

    def invoke(self, request: ModelRequest) -> ModelGatewayResult:
        provider = self._select_provider(request.required_capabilities)
        if provider is None:
            record = self._build_record(
                request=request,
                provider="unselected",
                model="unselected",
                output_text="",
                latency_ms=0,
                status="rejected",
                error_type="NoProviderForCapabilities",
            )
            self.call_records.append(record)
            return ModelGatewayResult(response=None, record=record)

        started_at = perf_counter()
        try:
            response = provider.call(request)
        except Exception as exc:
            latency_ms = int((perf_counter() - started_at) * 1000)
            record = self._build_record(
                request=request,
                provider=provider.provider_name,
                model=provider.model_name,
                output_text="",
                latency_ms=latency_ms,
                status="failed",
                error_type=type(exc).__name__,
            )
            self.call_records.append(record)
            return ModelGatewayResult(response=None, record=record)

        latency_ms = int((perf_counter() - started_at) * 1000)
        record = self._build_record(
            request=request,
            provider=response.provider,
            model=response.model,
            output_text=response.output_text,
            latency_ms=latency_ms,
            status="succeeded",
            error_type=None,
        )
        self.call_records.append(record)
        return ModelGatewayResult(response=response, record=record)

    def _select_provider(
        self, required_capabilities: Sequence[ModelCapability]
    ) -> ProviderAdapter | None:
        required = frozenset(required_capabilities)
        for provider in self._providers:
            if required.issubset(provider.capabilities):
                return provider
        return None

    def _build_record(
        self,
        *,
        request: ModelRequest,
        provider: str,
        model: str,
        output_text: str,
        latency_ms: int,
        status: ModelCallStatus,
        error_type: str | None,
    ) -> ModelCallRecord:
        return ModelCallRecord(
            call_id=self._call_id_factory(),
            request_id=request.request_id,
            provider=provider,
            model=model,
            task_type=request.task_type,
            prompt_version=request.prompt_version,
            input_hash=_hash_text(request.input_text),
            output_hash=_hash_text(output_text) if output_text else "",
            latency_ms=latency_ms,
            cost_estimate=None,
            status=status,
            error_type=error_type,
            created_at=self._clock(),
        )
