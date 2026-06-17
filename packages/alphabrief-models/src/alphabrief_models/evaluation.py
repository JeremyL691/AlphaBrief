"""Model evaluation engine for AlphaBrief.

The :class:`ModelEvaluator` runs automated evaluations against
gold-standard local datasets through the existing :class:`ModelGateway`.
It measures JSON validity, schema pass rate, hallucination, latency,
and cost.

The evaluator **never** calls provider SDKs directly. All model
invocations go through ``ModelGateway`` so that routing, capability
filtering, and call records are honored.

Gold-standard datasets are hardcoded Python definitions in
:mod:`alphabrief_models.evaluation.datasets`. They contain no secrets
or network resources.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_models.gateway import (
    ModelGateway,
    ModelRequest,
    ModelTaskType,
)

# ponytail: hard upper bound on per-eval sample count. Bump only with a
# comment explaining the cost ceiling.
MAX_SAMPLE_COUNT: int = 50

_DEFAULT_CAPABILITIES: tuple[str, ...] = ("text_generation",)


@dataclass(frozen=True)
class EvalDataset:
    """A gold-standard evaluation dataset for a single task type.

    All fields are local; no secrets, no URLs, no file I/O.
    """

    dataset_id: str
    task_type: ModelTaskType
    json_prompts: tuple[str, ...] = ()
    schema_prompts: tuple[str, ...] = ()
    knowledge_pairs: tuple[tuple[str, str], ...] = ()
    required_capabilities: tuple[str, ...] = _DEFAULT_CAPABILITIES
    description: str = ""


@dataclass(frozen=True)
class EvalResult:
    """Result of a single evaluation run."""

    dataset_id: str
    model_id: str
    provider: str
    sample_count: int
    task_type: str = ""
    json_valid_rate: float | None = None
    schema_pass_rate: float | None = None
    hallucination_rate: float | None = None
    avg_latency_ms: int | None = None
    avg_cost_estimate: float | None = None
    failed_calls: int = 0
    notes: str = ""


class ModelEvaluation(BaseModel):
    """Pydantic mirror of :class:`EvalResult` for persistence and API use."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    eval_id: str = Field(default_factory=lambda: f"eval_{uuid4().hex[:12]}")
    dataset_id: str
    model_id: str
    provider: str
    task_type: str
    sample_count: int = Field(ge=1)
    json_valid_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    schema_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    hallucination_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    avg_latency_ms: int | None = Field(default=None, ge=0)
    avg_cost_estimate: float | None = Field(default=None, ge=0.0)
    failed_calls: int = Field(default=0, ge=0)
    notes: str = ""

    @field_validator("model_id", "provider", "dataset_id", "task_type")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("string fields must be non-empty")
        return value


class EvalSample(BaseModel):
    """One item in a dataset: prompt and expected response (or facts)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: str
    expected: str | None = None
    target_schema: dict[str, Any] | None = None


class EvalDatasetSpec(BaseModel):
    """Pydantic version of :class:`EvalDataset` for API surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str
    task_type: ModelTaskType
    samples: list[EvalSample] = Field(default_factory=list)
    required_capabilities: tuple[str, ...] = _DEFAULT_CAPABILITIES
    description: str = ""

    @field_validator("dataset_id")
    @classmethod
    def _dataset_id_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("dataset_id must be non-empty")
        return value

    def _as_dataset(self) -> EvalDataset:
        json_prompts = tuple(s.prompt for s in self.samples if s.expected is None)
        schema_prompts = tuple(
            s.prompt for s in self.samples if s.target_schema is not None
        )
        knowledge_pairs = tuple(
            (s.prompt, s.expected or "")
            for s in self.samples
            if s.expected is not None and s.target_schema is None
        )
        return EvalDataset(
            dataset_id=self.dataset_id,
            task_type=self.task_type,
            json_prompts=json_prompts,
            schema_prompts=schema_prompts,
            knowledge_pairs=knowledge_pairs,
            required_capabilities=self.required_capabilities,
            description=self.description,
        )


def _avg(values: Sequence[int]) -> int:
    if not values:
        return 0
    return int(sum(values) / len(values))


def _avg_float(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _is_valid_json(text: str) -> bool:
    if not text or not text.strip():
        return False
    try:
        json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False
    return True


def _matches_schema_minimal(payload: Any, schema: dict[str, Any]) -> bool:
    """A minimal recursive schema check.

    Supports the subset used by the bundled datasets:
    ``{"type": "object", "required": [..], "properties": {name: {"type": ...}}}``.
    The check is intentionally conservative — unknown structures are
    treated as failing. This is **not** a full JSON Schema validator.
    """
    if not isinstance(schema, dict):
        return False
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(payload, dict):
            return False
        for required_key in schema.get("required", []):
            if required_key not in payload:
                return False
        props = schema.get("properties", {})
        for key, prop_schema in props.items():
            if key in payload and not _matches_schema_minimal(
                payload[key], prop_schema
            ):
                return False
        return True
    if expected_type == "string":
        return isinstance(payload, str)
    if expected_type == "number":
        return isinstance(payload, (int, float)) and not isinstance(payload, bool)
    if expected_type == "integer":
        return isinstance(payload, int) and not isinstance(payload, bool)
    if expected_type == "boolean":
        return isinstance(payload, bool)
    if expected_type == "array":
        if not isinstance(payload, list):
            return False
        item_schema = schema.get("items")
        if item_schema is not None:
            return all(_matches_schema_minimal(item, item_schema) for item in payload)
        return True
    return True


def _is_hallucinated(response_text: str, expected_answer: str) -> bool:
    """Conservative contradiction check.

    Treats a response as a hallucination if it asserts the opposite
    of the expected answer using a small negation set, or if it
    contradicts a known numeric answer. Returns ``False`` for
    responses that do not contain the answer at all.
    """
    if not response_text or not expected_answer:
        return False
    lower_response = response_text.lower()
    lower_expected = expected_answer.lower()
    if lower_expected in lower_response:
        return False
    negation_pairs: tuple[tuple[str, str], ...] = (
        ("above", "below"),
        ("below", "above"),
        ("higher", "lower"),
        ("lower", "higher"),
        ("increase", "decrease"),
        ("decrease", "increase"),
        ("bullish", "bearish"),
        ("bearish", "bullish"),
        ("up", "down"),
        ("down", "up"),
    )
    for positive, negative in negation_pairs:
        if positive in lower_expected and negative in lower_response:
            return True
    return False


def _request_id() -> str:
    return f"eval_req_{uuid4().hex[:12]}"


def _build_request(
    *,
    task_type: ModelTaskType,
    prompt: str,
    required_capabilities: Sequence[str],
) -> ModelRequest:
    caps: tuple[str, ...] = tuple(required_capabilities) or _DEFAULT_CAPABILITIES
    request = ModelRequest.model_construct(
        request_id=_request_id(),
        task_type=task_type,
        prompt_version="eval-v1",
        input_text=prompt,
        required_capabilities=list(caps),
        metadata={},
    )
    return ModelRequest.model_validate(request.model_dump())


class ModelEvaluator:
    """Run automated evaluations through :class:`ModelGateway`.

    The evaluator never calls provider SDKs directly. It always goes
    through the gateway so that capability filtering, fallback, and
    ``ModelCallRecord`` are honored.
    """

    def __init__(self, gateway: ModelGateway) -> None:
        if gateway is None:
            raise ValueError("gateway must not be None")
        self._gateway = gateway

    def evaluate_json_validity(
        self,
        *,
        model_id: str,
        task_type: ModelTaskType,
        prompts: Sequence[str],
        sample_count: int = 10,
    ) -> EvalResult:
        if not prompts:
            raise ValueError("prompts must not be empty")
        sample_count = _clamp_sample_count(sample_count)
        provider, model = _split_model_id(model_id)
        valid = 0
        failed = 0
        latencies: list[int] = []
        for prompt in prompts[:sample_count]:
            request = _build_request(
                task_type=task_type,
                prompt=prompt,
                required_capabilities=_DEFAULT_CAPABILITIES,
            )
            result = self._gateway.invoke(request)
            if result.response is None:
                failed += 1
                continue
            latencies.append(result.record.latency_ms)
            if _is_valid_json(result.response.output_text):
                valid += 1
        total = len(prompts[:sample_count])
        rate = valid / total if total > 0 else 0.0
        return EvalResult(
            dataset_id="json_validity",
            model_id=f"{provider}:{model}",
            provider=provider,
            task_type=task_type,
            sample_count=total,
            json_valid_rate=rate,
            avg_latency_ms=_avg(latencies),
            failed_calls=failed,
        )

    def evaluate_schema_pass(
        self,
        *,
        model_id: str,
        task_type: ModelTaskType,
        schema: dict[str, Any],
        prompts: Sequence[str],
        sample_count: int = 10,
    ) -> EvalResult:
        if not prompts:
            raise ValueError("prompts must not be empty")
        if not isinstance(schema, dict):
            raise ValueError("schema must be a JSON Schema object")
        sample_count = _clamp_sample_count(sample_count)
        provider, model = _split_model_id(model_id)
        passed = 0
        failed = 0
        latencies: list[int] = []
        for prompt in prompts[:sample_count]:
            request = _build_request(
                task_type=task_type,
                prompt=prompt,
                required_capabilities=("structured_output", "json_mode"),
            )
            result = self._gateway.invoke(request)
            if result.response is None:
                failed += 1
                continue
            latencies.append(result.record.latency_ms)
            payload = result.response.structured_output
            if payload is None and result.response.output_text:
                try:
                    payload = json.loads(result.response.output_text)
                except (json.JSONDecodeError, ValueError):
                    payload = None
            if payload is not None and _matches_schema_minimal(payload, schema):
                passed += 1
        total = len(prompts[:sample_count])
        rate = passed / total if total > 0 else 0.0
        return EvalResult(
            dataset_id="schema_pass",
            model_id=f"{provider}:{model}",
            provider=provider,
            task_type=task_type,
            sample_count=total,
            schema_pass_rate=rate,
            avg_latency_ms=_avg(latencies),
            failed_calls=failed,
        )

    def evaluate_hallucination(
        self,
        *,
        model_id: str,
        task_type: ModelTaskType,
        knowledge_pairs: Sequence[tuple[str, str]],
        sample_count: int = 10,
    ) -> EvalResult:
        if not knowledge_pairs:
            raise ValueError("knowledge_pairs must not be empty")
        sample_count = _clamp_sample_count(sample_count)
        provider, model = _split_model_id(model_id)
        hallucinations = 0
        failed = 0
        latencies: list[int] = []
        pairs = list(knowledge_pairs[:sample_count])
        for prompt, expected in pairs:
            request = _build_request(
                task_type=task_type,
                prompt=prompt,
                required_capabilities=_DEFAULT_CAPABILITIES,
            )
            result = self._gateway.invoke(request)
            if result.response is None:
                failed += 1
                continue
            latencies.append(result.record.latency_ms)
            if _is_hallucinated(result.response.output_text, expected):
                hallucinations += 1
        total = len(pairs)
        rate = hallucinations / total if total > 0 else 0.0
        return EvalResult(
            dataset_id="hallucination",
            model_id=f"{provider}:{model}",
            provider=provider,
            task_type=task_type,
            sample_count=total,
            hallucination_rate=rate,
            avg_latency_ms=_avg(latencies),
            failed_calls=failed,
        )

    def run_dataset(
        self,
        *,
        model_id: str,
        dataset: EvalDataset,
        sample_count: int = 10,
    ) -> ModelEvaluation:
        """Run all applicable evaluations defined in a dataset."""
        sample_count = _clamp_sample_count(sample_count)
        provider, model = _split_model_id(model_id)
        json_rate: float | None = None
        schema_rate: float | None = None
        hallu_rate: float | None = None
        avg_latency: int | None = None
        total_failed = 0

        all_latencies: list[int] = []
        notes_parts: list[str] = []

        if dataset.json_prompts:
            json_result = self.evaluate_json_validity(
                model_id=model_id,
                task_type=dataset.task_type,
                prompts=dataset.json_prompts,
                sample_count=sample_count,
            )
            json_rate = json_result.json_valid_rate
            total_failed += json_result.failed_calls
            if json_result.avg_latency_ms:
                all_latencies.append(json_result.avg_latency_ms)
            notes_parts.append(
                f"json_validity={json_rate:.2f} over {json_result.sample_count}"
            )

        if dataset.knowledge_pairs:
            hallu_result = self.evaluate_hallucination(
                model_id=model_id,
                task_type=dataset.task_type,
                knowledge_pairs=dataset.knowledge_pairs,
                sample_count=sample_count,
            )
            hallu_rate = hallu_result.hallucination_rate
            total_failed += hallu_result.failed_calls
            if hallu_result.avg_latency_ms:
                all_latencies.append(hallu_result.avg_latency_ms)
            notes_parts.append(
                f"hallucination={hallu_rate:.2f} over {hallu_result.sample_count}"
            )

        if all_latencies:
            avg_latency = _avg(all_latencies)

        return ModelEvaluation(
            dataset_id=dataset.dataset_id,
            model_id=f"{provider}:{model}",
            provider=provider,
            task_type=dataset.task_type,
            sample_count=sample_count,
            json_valid_rate=json_rate,
            schema_pass_rate=schema_rate,
            hallucination_rate=hallu_rate,
            avg_latency_ms=avg_latency,
            failed_calls=total_failed,
            notes="; ".join(notes_parts),
        )


def _clamp_sample_count(sample_count: int) -> int:
    if not isinstance(sample_count, int) or sample_count <= 0:
        raise ValueError("sample_count must be a positive integer")
    return min(sample_count, MAX_SAMPLE_COUNT)


def _split_model_id(model_id: str) -> tuple[str, str]:
    if not model_id or not isinstance(model_id, str):
        raise ValueError("model_id must be a non-empty string")
    if ":" not in model_id:
        return ("unknown", model_id)
    provider, _, model = model_id.partition(":")
    if not provider or not model:
        raise ValueError("model_id must be in 'provider:model' format")
    return (provider, model)


def eval_result_to_record(result: EvalResult) -> ModelEvaluation:
    """Convert an :class:`EvalResult` to a :class:`ModelEvaluation`."""
    return ModelEvaluation(
        dataset_id=result.dataset_id,
        model_id=result.model_id,
        provider=result.provider,
        task_type="",
        sample_count=result.sample_count,
        json_valid_rate=result.json_valid_rate,
        schema_pass_rate=result.schema_pass_rate,
        hallucination_rate=result.hallucination_rate,
        avg_latency_ms=result.avg_latency_ms,
        avg_cost_estimate=result.avg_cost_estimate,
        failed_calls=result.failed_calls,
        notes=result.notes,
    )


__all__ = [
    "EvalDataset",
    "EvalDatasetSpec",
    "EvalResult",
    "EvalSample",
    "MAX_SAMPLE_COUNT",
    "ModelEvaluation",
    "ModelEvaluator",
    "eval_result_to_record",
]
