"""Model evaluation and routing routes for the AlphaBrief API.

All routes in this module are **read-only advisory**. They never
place orders, never modify RiskGate state, and never call provider
SDKs directly. All model invocations go through the existing
:mod:`alphabrief_models` gateway.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal

from alphabrief_core import Bar
from alphabrief_models import (
    BUNDLED_DATASET_SPECS,
    DeterministicKronosRuntime,
    FakeProviderAdapter,
    KronosForecastAdapter,
    KronosForecastEvidence,
    KronosForecastReport,
    KronosForecastRequest,
    KronosRuntime,
    ModelEvaluator,
    ModelGateway,
    ModelProfile,
    ModelRegistry,
    ModelRouter,
    ProviderConfig,
    build_kronos_evidence,
    build_kronos_model_request,
    get_dataset_by_id,
)
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_api.db import ModelEvalStore


def _get_store() -> ModelEvalStore:
    global _store  # noqa: PLW0603
    if _store is None:
        _store = ModelEvalStore()
    return _store


def _clear_store() -> None:
    global _store  # noqa: PLW0603
    if _store is None:
        _store = ModelEvalStore()
    _store.clear()


_store: ModelEvalStore | None = None
_kronos_runtime: KronosRuntime | None = None


def _default_registry() -> ModelRegistry:
    return ModelRegistry(
        providers=[
            ProviderConfig(provider_name="fake", enabled=True),
            ProviderConfig(provider_name="openai", enabled=True),
            ProviderConfig(provider_name="anthropic", enabled=True),
            ProviderConfig(provider_name="kronos", enabled=True),
        ],
        profiles=[
            ModelProfile(
                profile_id="fake_default",
                provider_name="fake",
                model_name="fake-model",
                capabilities=[
                    "text_generation",
                    "structured_output",
                    "json_mode",
                ],
                priority=100,
            ),
            ModelProfile(
                profile_id="openai_default",
                provider_name="openai",
                model_name="gpt-4o-mini",
                capabilities=[
                    "text_generation",
                    "structured_output",
                    "json_mode",
                    "low_cost",
                    "low_latency",
                ],
                priority=10,
            ),
            ModelProfile(
                profile_id="anthropic_strong",
                provider_name="anthropic",
                model_name="claude-3",
                capabilities=[
                    "text_generation",
                    "structured_output",
                    "json_mode",
                    "strong_reasoning",
                ],
                priority=5,
            ),
            ModelProfile(
                profile_id="kronos_mini_forecast",
                provider_name="kronos",
                model_name="NeoQuasar/Kronos-mini",
                capabilities=[
                    "structured_output",
                    "time_series_forecasting",
                ],
                priority=20,
            ),
        ],
    )


def _build_evaluator(use_real: bool) -> ModelEvaluator:
    """Build an evaluator.

    When ``use_real`` is False (default), the FakeProviderAdapter is
    used so tests are deterministic. When True, the evaluator uses the
    same real provider wiring as the AI Trading Committee (env-backed
    OpenAI/Ollama provider through ``ModelGateway``).
    """
    if use_real:
        from alphabrief_trader import build_ai_trading_provider

        return ModelEvaluator(
            ModelGateway([build_ai_trading_provider()])
        )
    adapter = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-model",
        output_text=json.dumps({"brief_id": "b1", "summary": "ok", "confidence": 0.8}),
        structured_output={
            "brief_id": "b1",
            "summary": "ok",
            "confidence": 0.8,
        },
    )
    return ModelEvaluator(ModelGateway([adapter]))


def _build_router() -> ModelRouter:
    store = _get_store()
    registry = _default_registry()

    def provider(model_id: str, task_type: str) -> dict[str, object] | None:
        rec = store.get_latest_evaluation(model_id, task_type)
        if rec is None:
            return None
        return rec

    return ModelRouter(registry, performance_provider=provider)


def _is_structured_task(task_type: str) -> bool:
    return task_type in {
        "daily_brief",
        "strategy_review",
        "symbol_research",
        "risk_review",
        "market_summary",
        "market_forecast",
    }


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

TaskTypeLiteral = Literal[
    "market_summary",
    "symbol_research",
    "risk_review",
    "strategy_review",
    "daily_brief",
    "market_forecast",
    "test",
]


class ModelEvaluationRequest(BaseModel):
    """Request body for POST /api/v1/models/evaluate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=3, description="e.g. 'openai:gpt-4o'")
    task_type: TaskTypeLiteral
    dataset_id: str = Field(min_length=1)
    sample_count: int = Field(default=10, ge=1, le=50)
    use_real_provider: bool = False

    @field_validator("model_id")
    @classmethod
    def _model_id_format(cls, value: str) -> str:
        if ":" not in value:
            raise ValueError("model_id must be in 'provider:model' format")
        provider, _, model = value.partition(":")
        if not provider or not model:
            raise ValueError("model_id must be in 'provider:model' format")
        return value


class ModelEvaluationResponse(BaseModel):
    """Response body for a successful evaluation."""

    model_config = ConfigDict(frozen=True)

    eval_id: str
    model_id: str
    provider: str
    task_type: str
    dataset_id: str
    sample_count: int
    json_valid_rate: float | None
    schema_pass_rate: float | None
    hallucination_rate: float | None
    avg_latency_ms: int | None
    avg_cost_estimate: float | None
    failed_calls: int
    notes: str


class ModelEvaluationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    model_id: str
    provider: str
    task_type: str
    eval_dataset: str
    json_valid_rate: float | None
    schema_pass_rate: float | None
    hallucination_rate: float | None
    avg_latency_ms: int | None
    avg_cost_estimate: float | None
    sample_count: int
    evaluated_at: str


class ModelEvaluationListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: list[ModelEvaluationSummary]
    total: int


class ModelPerformanceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    evaluations_by_task: dict[str, ModelEvaluationSummary]
    latest_evaluated_at: str | None


class ModelRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_type: TaskTypeLiteral
    required_capabilities: list[str] = Field(min_length=1)
    prefer_low_cost: bool = False
    prefer_low_latency: bool = False

    @field_validator("required_capabilities")
    @classmethod
    def _capabilities_non_empty(cls, value: list[str]) -> list[str]:
        if not value or any(not v or not v.strip() for v in value):
            raise ValueError("required_capabilities must be non-empty strings")
        return value


class ModelRouteResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str | None
    provider_name: str
    model_name: str
    routing_reason: str
    candidates: list[str]
    used_performance_data: bool


class ModelCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_ids: list[str] = Field(min_length=2, max_length=10)
    task_type: TaskTypeLiteral


class ModelCompareRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    schema_pass_rate: float | None
    json_valid_rate: float | None
    avg_latency_ms: int | None
    avg_cost_estimate: float | None
    sample_count: int | None
    evaluated_at: str | None
    has_data: bool


class ModelCompareResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_type: str
    rows: list[ModelCompareRow]


RuntimeModeLiteral = Literal["configured", "deterministic"]


class KronosForecastApiRequest(BaseModel):
    """Request body for POST /api/v1/models/kronos/forecast."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(default="api_kronos_forecast", min_length=1)
    symbol: str = Field(min_length=1)
    bars: list[Bar] = Field(min_length=2)
    prediction_length: int = Field(default=3, ge=1, le=512)
    model_name: str = Field(default="NeoQuasar/Kronos-mini", min_length=1)
    tokenizer_name: str = Field(default="NeoQuasar/Kronos-Tokenizer-base", min_length=1)
    runtime_mode: RuntimeModeLiteral = "configured"


class KronosForecastApiResponse(BaseModel):
    """Response body for a successful Kronos forecast."""

    model_config = ConfigDict(frozen=True)

    report: KronosForecastReport
    evidence: KronosForecastEvidence
    model_call_status: str
    model_call_provider: str
    model_call_model: str


class DatasetSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: str
    task_type: str
    sample_count: int
    description: str


class DatasetListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    datasets: list[DatasetSummary]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/models", tags=["models"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/datasets", response_model=DatasetListResponse)
def list_datasets() -> DatasetListResponse:
    """Return the bundled evaluation dataset metadata."""
    entries: list[DatasetSummary] = []
    for spec in BUNDLED_DATASET_SPECS:
        entries.append(
            DatasetSummary(
                dataset_id=spec.dataset_id,
                task_type=spec.task_type,
                sample_count=len(spec.samples),
                description=spec.description,
            )
        )
    return DatasetListResponse(datasets=entries)


@router.post("/evaluate", response_model=ModelEvaluationResponse)
def run_evaluation(body: ModelEvaluationRequest) -> ModelEvaluationResponse:
    """Run an evaluation and persist the result.

    By default, the FakeProvider is used regardless of the model_id
    in the request. Pass ``use_real_provider=true`` to wire a real
    provider (out of scope for this round).
    """
    try:
        dataset = get_dataset_by_id(body.dataset_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"unknown dataset_id: {body.dataset_id!r}",
        ) from exc

    if body.task_type != dataset.task_type:
        raise HTTPException(
            status_code=422,
            detail=(
                f"task_type {body.task_type!r} does not match dataset "
                f"{body.dataset_id!r} (expected {dataset.task_type!r})"
            ),
        )

    evaluator = _build_evaluator(use_real=body.use_real_provider)
    result = evaluator.run_dataset(
        model_id=body.model_id,
        dataset=dataset,
        sample_count=body.sample_count,
    )

    store = _get_store()
    eval_id = store.save_evaluation(
        model_id=result.model_id,
        provider=result.provider,
        task_type=result.task_type,
        eval_dataset=result.dataset_id,
        sample_count=result.sample_count,
        json_valid_rate=result.json_valid_rate,
        schema_pass_rate=result.schema_pass_rate,
        hallucination_rate=result.hallucination_rate,
        avg_latency_ms=result.avg_latency_ms,
        avg_cost_estimate=result.avg_cost_estimate,
    )

    return ModelEvaluationResponse(
        eval_id=eval_id,
        model_id=result.model_id,
        provider=result.provider,
        task_type=result.task_type,
        dataset_id=result.dataset_id,
        sample_count=result.sample_count,
        json_valid_rate=result.json_valid_rate,
        schema_pass_rate=result.schema_pass_rate,
        hallucination_rate=result.hallucination_rate,
        avg_latency_ms=result.avg_latency_ms,
        avg_cost_estimate=result.avg_cost_estimate,
        failed_calls=result.failed_calls,
        notes=result.notes,
    )


@router.get("/evaluations", response_model=ModelEvaluationListResponse)
def list_evaluations(
    model_id: str | None = Query(default=None),
    task_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> ModelEvaluationListResponse:
    """Return recent evaluation records, optionally filtered."""
    from alphabrief_api.db.merged import merge_dedupe, open_snapshot_store

    store = _get_store()
    if model_id is not None or task_type is not None:
        records = store.get_evaluations(model_id=model_id, task_type=task_type)
    else:
        records = store.list_evaluations(limit=limit, offset=0)
    snapshot_store = open_snapshot_store(ModelEvalStore)
    if snapshot_store is not None:
        try:
            if model_id is not None or task_type is not None:
                snapshot_records = snapshot_store.get_evaluations(
                    model_id=model_id, task_type=task_type
                )
            else:
                snapshot_records = snapshot_store.list_evaluations(
                    limit=limit, offset=0
                )
            records = merge_dedupe(
                list(records),
                list(snapshot_records),
                key=lambda r: r["id"],
                sort_key=lambda r: r["evaluated_at"],
            )
        finally:
            snapshot_store.close()
    summaries = [
        ModelEvaluationSummary(
            id=str(r["id"]),
            model_id=str(r["model_id"]),
            provider=str(r["provider"]),
            task_type=str(r["task_type"]),
            eval_dataset=str(r["eval_dataset"]),
            json_valid_rate=_maybe_float(r.get("json_valid_rate")),
            schema_pass_rate=_maybe_float(r.get("schema_pass_rate")),
            hallucination_rate=_maybe_float(r.get("hallucination_rate")),
            avg_latency_ms=_maybe_int(r.get("avg_latency_ms")),
            avg_cost_estimate=_maybe_float(r.get("avg_cost_estimate")),
            sample_count=int(r["sample_count"]),
            evaluated_at=str(r["evaluated_at"]),
        )
        for r in records
    ]
    return ModelEvaluationListResponse(entries=summaries, total=len(summaries))


@router.get("/evaluations/{eval_id}", response_model=ModelEvaluationSummary)
def get_evaluation(eval_id: str) -> ModelEvaluationSummary:
    """Return a single evaluation record by id."""
    store = _get_store()
    for record in store.get_evaluations():
        if record["id"] == eval_id:
            return ModelEvaluationSummary(
                id=str(record["id"]),
                model_id=str(record["model_id"]),
                provider=str(record["provider"]),
                task_type=str(record["task_type"]),
                eval_dataset=str(record["eval_dataset"]),
                json_valid_rate=_maybe_float(record.get("json_valid_rate")),
                schema_pass_rate=_maybe_float(record.get("schema_pass_rate")),
                hallucination_rate=_maybe_float(record.get("hallucination_rate")),
                avg_latency_ms=_maybe_int(record.get("avg_latency_ms")),
                avg_cost_estimate=_maybe_float(record.get("avg_cost_estimate")),
                sample_count=int(record["sample_count"]),
                evaluated_at=str(record["evaluated_at"]),
            )
    raise HTTPException(status_code=404, detail=f"evaluation {eval_id!r} not found")


@router.get("/performance/{model_id}", response_model=ModelPerformanceSummary)
def get_performance(model_id: str) -> ModelPerformanceSummary:
    """Return the latest evaluation per task_type for a model."""
    if not model_id or ":" not in model_id:
        raise HTTPException(
            status_code=422,
            detail="model_id must be in 'provider:model' format",
        )
    store = _get_store()
    per_task = store.get_latest_per_task_for_model(model_id)
    if not per_task:
        raise HTTPException(
            status_code=404,
            detail=f"no evaluations found for model {model_id!r}",
        )
    by_task: dict[str, ModelEvaluationSummary] = {}
    latest_at: str | None = None
    for task, record in per_task.items():
        summary = ModelEvaluationSummary(
            id=str(record["id"]),
            model_id=str(record["model_id"]),
            provider=str(record["provider"]),
            task_type=str(record["task_type"]),
            eval_dataset=str(record["eval_dataset"]),
            json_valid_rate=_maybe_float(record.get("json_valid_rate")),
            schema_pass_rate=_maybe_float(record.get("schema_pass_rate")),
            hallucination_rate=_maybe_float(record.get("hallucination_rate")),
            avg_latency_ms=_maybe_int(record.get("avg_latency_ms")),
            avg_cost_estimate=_maybe_float(record.get("avg_cost_estimate")),
            sample_count=int(record["sample_count"]),
            evaluated_at=str(record["evaluated_at"]),
        )
        by_task[task] = summary
        if latest_at is None or str(record["evaluated_at"]) > latest_at:
            latest_at = str(record["evaluated_at"])
    return ModelPerformanceSummary(
        model_id=model_id,
        evaluations_by_task=by_task,
        latest_evaluated_at=latest_at,
    )


@router.post("/route", response_model=ModelRouteResponse)
def query_route(body: ModelRouteRequest) -> ModelRouteResponse:
    """Return the router's recommendation for a task type."""
    router_obj = _build_router()
    caps: list[Any] = list(body.required_capabilities)
    decision = router_obj.route(
        task_type=body.task_type,
        required_capabilities=caps,
        prefer_low_cost=body.prefer_low_cost,
        prefer_low_latency=body.prefer_low_latency,
    )
    return ModelRouteResponse(
        profile_id=decision.profile_id,
        provider_name=decision.provider_name,
        model_name=decision.model_name,
        routing_reason=decision.routing_reason,
        candidates=list(decision.candidates),
        used_performance_data=decision.used_performance_data,
    )


@router.post("/compare", response_model=ModelCompareResponse)
def compare_models(body: ModelCompareRequest) -> ModelCompareResponse:
    """Compare multiple models side-by-side for a task type."""
    for mid in body.model_ids:
        if ":" not in mid:
            raise HTTPException(
                status_code=422,
                detail=f"model_id {mid!r} must be in 'provider:model' format",
            )
    store = _get_store()
    rows: list[ModelCompareRow] = []
    for mid in body.model_ids:
        record = store.get_latest_evaluation(mid, body.task_type)
        if record is None:
            rows.append(
                ModelCompareRow(
                    model_id=mid,
                    schema_pass_rate=None,
                    json_valid_rate=None,
                    avg_latency_ms=None,
                    avg_cost_estimate=None,
                    sample_count=None,
                    evaluated_at=None,
                    has_data=False,
                )
            )
        else:
            rows.append(
                ModelCompareRow(
                    model_id=mid,
                    schema_pass_rate=_maybe_float(record.get("schema_pass_rate")),
                    json_valid_rate=_maybe_float(record.get("json_valid_rate")),
                    avg_latency_ms=_maybe_int(record.get("avg_latency_ms")),
                    avg_cost_estimate=_maybe_float(record.get("avg_cost_estimate")),
                    sample_count=int(record["sample_count"]),
                    evaluated_at=str(record["evaluated_at"]),
                    has_data=True,
                )
            )
    return ModelCompareResponse(task_type=body.task_type, rows=rows)


@router.post("/kronos/forecast", response_model=KronosForecastApiResponse)
def run_kronos_forecast(
    body: KronosForecastApiRequest,
) -> KronosForecastApiResponse:
    """Run an advisory Kronos OHLCV forecast through ModelGateway."""

    try:
        forecast_request = KronosForecastRequest(
            request_id=body.request_id,
            symbol=body.symbol,
            bars=body.bars,
            prediction_length=body.prediction_length,
            model_name=body.model_name,
            tokenizer_name=body.tokenizer_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    runtime = _select_kronos_runtime(body.runtime_mode)
    gateway = ModelGateway(
        [
            KronosForecastAdapter(
                runtime=runtime,
                model_name=body.model_name,
                tokenizer_name=body.tokenizer_name,
            )
        ]
    )
    result = gateway.invoke(build_kronos_model_request(forecast_request))
    if result.response is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "kronos_forecast_unavailable",
                "kind": result.record.error_type or "unknown",
            },
        )
    try:
        report = KronosForecastReport.model_validate(result.response.structured_output)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "kronos_forecast_invalid",
                "kind": type(exc).__name__,
            },
        ) from exc
    evidence = build_kronos_evidence(report)
    return KronosForecastApiResponse(
        report=report,
        evidence=evidence,
        model_call_status=result.record.status,
        model_call_provider=result.record.provider,
        model_call_model=result.record.model,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _maybe_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _select_kronos_runtime(mode: RuntimeModeLiteral) -> KronosRuntime | None:
    if mode == "deterministic":
        return DeterministicKronosRuntime()
    return _kronos_runtime


def _set_kronos_runtime(runtime: KronosRuntime | None) -> None:
    global _kronos_runtime  # noqa: PLW0603
    _kronos_runtime = runtime


def _build_evaluator_with_callback(  # pragma: no cover - test seam
    callback: Callable[[dict[str, Any]], ModelEvaluator],
) -> Callable[[bool], ModelEvaluator]:
    return callback  # type: ignore[return-value]


__all__ = [
    "DatasetListResponse",
    "DatasetSummary",
    "ModelCompareRequest",
    "ModelCompareResponse",
    "ModelCompareRow",
    "KronosForecastApiRequest",
    "KronosForecastApiResponse",
    "ModelEvaluationListResponse",
    "ModelEvaluationRequest",
    "ModelEvaluationResponse",
    "ModelEvaluationSummary",
    "ModelPerformanceSummary",
    "ModelRouteRequest",
    "ModelRouteResponse",
    "_build_evaluator",
    "_build_router",
    "_clear_store",
    "_get_store",
    "_set_kronos_runtime",
    "router",
]
