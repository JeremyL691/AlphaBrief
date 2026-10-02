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

from alphabrief_models.model_budget import ModelBudgetGuard

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
    "time_series_forecasting",
]
ModelTaskType = Literal[
    "market_summary",
    "symbol_research",
    "risk_review",
    "strategy_review",
    "daily_brief",
    "market_forecast",
    "test",
]
ModelResponseStatus = Literal["succeeded", "failed"]
ModelCallStatus = Literal["succeeded", "failed", "rejected"]
ModelCallClassification = Literal[
    "success",
    "malformed",
    "timeout",
    "rate_limit",
    "provider_error",
    "budget_exhausted",
    "no_provider",
]


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _error_code(exc: Exception) -> str:
    """Return a provider error's stable code, when it has one."""
    code = getattr(exc, "code", None)
    return str(code) if isinstance(code, str) else ""


def _error_type_for(exc: Exception) -> str:
    """Return ``TypeName`` or ``TypeName:channel_code`` for the record.

    The channel code is what makes a failure actionable (usage limit,
    scope missing, re-authorization required), so it is preserved next to
    the exception type instead of replacing it.
    """
    code = _error_code(exc)
    return f"{type(exc).__name__}:{code}" if code else type(exc).__name__


def classify_provider_error(exc: Exception, detail: str) -> ModelCallClassification:
    """Classify a provider exception into a stable terminal category.

    The classification is derived only from the exception type and a
    bounded detail string; it is deterministic for identical inputs and
    never includes raw provider text.
    """
    message = detail.lower()
    if isinstance(exc, TimeoutError):
        return "timeout"
    if "429" in detail or "rate limit" in message:
        return "rate_limit"
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if (
        "not a json object" in message
        or "missing" in message
        or "malformed" in message
        or "invalid" in message
    ):
        return "malformed"
    return "provider_error"


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
    cycle_key: str | None = None
    snapshot_id: str | None = None
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
    def metadata_must_not_use_secret_keys(cls, value: dict[str, str]) -> dict[str, str]:
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
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_estimate: Decimal | None = None

    @field_validator("cost_estimate", mode="before")
    @classmethod
    def _cost(cls, value: Any) -> Any:
        if value is not None and (
            not isinstance(value, Decimal) or not value.is_finite() or value < 0
        ):
            raise ValueError("cost estimate must be a finite nonnegative Decimal")
        return value


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
    classification: ModelCallClassification | None = None
    error_type: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0)
    schema_verdict: str | None = None
    snapshot_id: str | None = None
    cycle_key: str | None = None
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


class ModelCallBudget:
    """Deterministic per-request, per-cycle, and daily model-call budget.

    Every ``authorize`` decision is derived only from the request
    identity, the optional cycle key, and the injected UTC clock, so
    identical states produce identical verdicts. Rejected calls do not
    consume budget; already committed evidence is never altered.
    """

    def __init__(
        self,
        *,
        max_calls_per_request: int = 5,
        max_calls_per_cycle: int = 200,
        max_calls_per_day: int = 2000,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_calls_per_request <= 0:
            raise ValueError("max_calls_per_request must be positive")
        if max_calls_per_cycle <= 0:
            raise ValueError("max_calls_per_cycle must be positive")
        if max_calls_per_day <= 0:
            raise ValueError("max_calls_per_day must be positive")
        self._max_per_request = max_calls_per_request
        self._max_per_cycle = max_calls_per_cycle
        self._max_per_day = max_calls_per_day
        self._clock = clock or (lambda: datetime.now(UTC))
        self._request_counts: dict[str, int] = {}
        self._cycle_counts: dict[str, int] = {}
        self._day_counts: dict[str, int] = {}

    def authorize(self, request: ModelRequest) -> str | None:
        """Return ``None`` when the call is allowed, else the reason.

        Counting happens only on approval, so rejected calls never
        consume budget and repeated identical rejections are stable.
        """
        day_key = self._clock().date().isoformat()
        if self._day_counts.get(day_key, 0) >= self._max_per_day:
            return "daily_limit"
        if request.cycle_key:
            if self._cycle_counts.get(request.cycle_key, 0) >= self._max_per_cycle:
                return "cycle_limit"
        if self._request_counts.get(request.request_id, 0) >= self._max_per_request:
            return "request_limit"
        self._request_counts[request.request_id] = (
            self._request_counts.get(request.request_id, 0) + 1
        )
        if request.cycle_key:
            self._cycle_counts[request.cycle_key] = (
                self._cycle_counts.get(request.cycle_key, 0) + 1
            )
        self._day_counts[day_key] = self._day_counts.get(day_key, 0) + 1
        return None


#: Failure classifications that mean "this channel cannot serve the
#: request", so an explicitly enabled fallback channel may be used.
_FALLBACK_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"provider_error", "timeout", "rate_limit", "no_provider"}
)


def _default_fallback_eligible(record: ModelCallRecord) -> bool:
    """Fallback policy: switch channels only for channel-level failures."""
    return record.classification in _FALLBACK_CLASSIFICATIONS


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
        self.capabilities: frozenset[ModelCapability] = frozenset(selected_capabilities)
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
    """Capability-based gateway for model provider calls.

    Every terminal outcome — success, provider failure, missing
    provider, or budget rejection — produces exactly one
    :class:`ModelCallRecord`. When a ``record_sink`` is configured the
    gateway forwards each terminal record to it (for example a durable
    store); the gateway itself never persists or logs raw prompts,
    responses, or secrets.
    """

    def __init__(
        self,
        providers: Sequence[ProviderAdapter],
        *,
        clock: Callable[[], datetime] | None = None,
        call_id_factory: Callable[[], str] | None = None,
        budget: ModelCallBudget | None = None,
        record_sink: Callable[[ModelCallRecord], None] | None = None,
        fallback_enabled: bool = False,
        fallback_eligible: Callable[[ModelCallRecord], bool] | None = None,
        daily_budget: ModelBudgetGuard | None = None,
    ) -> None:
        self._providers = list(providers)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._call_id_factory = call_id_factory or (lambda: f"model_call_{uuid4().hex}")
        self._budget = budget
        self._daily_budget = daily_budget
        self._record_sink = record_sink
        # Channel fallback is opt-in: it is only used when the caller
        # explicitly allows switching billing channels, and only for
        # failures that mean "this channel cannot serve the request".
        self._fallback_enabled = fallback_enabled
        self._fallback_eligible = fallback_eligible or _default_fallback_eligible
        self.call_records: list[ModelCallRecord] = []
        self._invoke_counts: dict[str, int] = {}

    def set_budget(self, budget: ModelCallBudget | None) -> None:
        """Attach or replace the call budget after construction."""
        self._budget = budget

    @property
    def fallback_channels(self) -> tuple[str, ...]:
        return (
            tuple(p.provider_name for p in self._providers[1:])
            if self._fallback_enabled
            else ()
        )

    def invoke(self, request: ModelRequest) -> ModelGatewayResult:
        retry_count = self._invoke_counts.get(request.request_id, 0)
        self._invoke_counts[request.request_id] = retry_count + 1

        if self._budget is not None:
            budget_reason = self._budget.authorize(request)
            if budget_reason is not None:
                record = self._build_record(
                    request=request,
                    provider="unselected",
                    model="unselected",
                    output_text="",
                    latency_ms=0,
                    status="rejected",
                    error_type=f"BudgetExhausted:{budget_reason}",
                    classification="budget_exhausted",
                    retry_count=retry_count,
                )
                self._emit(record)
                return ModelGatewayResult(response=None, record=record)

        candidates = self._eligible_providers(request.required_capabilities)
        if not candidates:
            record = self._build_record(
                request=request,
                provider="unselected",
                model="unselected",
                output_text="",
                latency_ms=0,
                status="rejected",
                error_type="NoProviderForCapabilities",
                classification="no_provider",
                retry_count=retry_count,
            )
            self._emit(record)
            return ModelGatewayResult(response=None, record=record)

        last_result: ModelGatewayResult | None = None
        for index, provider in enumerate(candidates):
            call_id = self._call_id_factory()
            if self._daily_budget is not None:
                estimate = getattr(provider, "budget_cost", None)
                try:
                    cost = estimate(request) if estimate is not None else None
                except Exception:
                    cost = None
                verdict = self._daily_budget.reserve(
                    provider.provider_name, call_id, estimated_cost=cost
                )
                if not verdict.allowed:
                    record = self._build_record(
                        request=request,
                        provider=provider.provider_name,
                        model=provider.model_name,
                        output_text="",
                        latency_ms=0,
                        status="rejected",
                        classification="budget_exhausted",
                        error_type=f"BudgetExhausted:{verdict.reason}",
                        retry_count=retry_count,
                        call_id=call_id,
                    )
                    self._emit(record)
                    last_result = ModelGatewayResult(response=None, record=record)
                    if index + 1 < len(candidates):
                        continue
                    return last_result
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
                    error_type=_error_type_for(exc),
                    classification=classify_provider_error(exc, str(exc)),
                    retry_count=retry_count,
                    call_id=call_id,
                )
                self._emit(record)
                channel_code = (record.error_type or "").split(":")[-1]
                if self._daily_budget is not None and (
                    self._daily_budget.cost_limited(provider.provider_name)
                    or record.classification == "rate_limit"
                    or channel_code
                    in {"usage_limit_exceeded", "quota_exceeded", "rate_limit_exceeded"}
                ):
                    self._daily_budget.record_channel_unavailable(
                        provider.provider_name, detail=channel_code
                    )
                last_result = ModelGatewayResult(response=None, record=record)
                if index + 1 < len(candidates) and self._fallback_eligible(record):
                    continue
                return last_result
            latency_ms = int((perf_counter() - started_at) * 1000)
            record = self._build_record(
                request=request,
                provider=response.provider,
                model=response.model,
                output_text=response.output_text,
                latency_ms=latency_ms,
                status="succeeded",
                error_type=None,
                classification="success",
                retry_count=retry_count,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_estimate=response.cost_estimate,
                call_id=call_id,
            )
            self._emit(record)
            if (
                self._daily_budget is not None
                and self._daily_budget.cost_limited(provider.provider_name)
                and response.cost_estimate is None
            ):
                self._daily_budget.record_channel_unavailable(
                    provider.provider_name, detail="paid_usage_unknown"
                )
            return ModelGatewayResult(response=response, record=record)

        assert last_result is not None  # every candidate was attempted
        return last_result

    def _emit(self, record: ModelCallRecord) -> None:
        self.call_records.append(record)
        if self._record_sink is not None:
            self._record_sink(record)

    def _eligible_providers(
        self, required_capabilities: Sequence[ModelCapability]
    ) -> list[ProviderAdapter]:
        required = frozenset(required_capabilities)
        eligible = [
            provider
            for provider in self._providers
            if required.issubset(provider.capabilities)
        ]
        if self._fallback_enabled:
            return eligible
        # Without explicit opt-in only the first eligible provider may
        # serve the request: the billing channel never switches silently.
        return eligible[:1]

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
        classification: ModelCallClassification | None = None,
        retry_count: int = 0,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_estimate: Decimal | None = None,
        call_id: str | None = None,
    ) -> ModelCallRecord:
        return ModelCallRecord(
            call_id=call_id or self._call_id_factory(),
            request_id=request.request_id,
            provider=provider,
            model=model,
            task_type=request.task_type,
            prompt_version=request.prompt_version,
            input_hash=_hash_text(request.input_text),
            output_hash=_hash_text(output_text) if output_text else "",
            latency_ms=latency_ms,
            cost_estimate=cost_estimate,
            status=status,
            classification=classification,
            error_type=error_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            retry_count=retry_count,
            snapshot_id=request.snapshot_id,
            cycle_key=request.cycle_key,
            created_at=self._clock(),
        )
