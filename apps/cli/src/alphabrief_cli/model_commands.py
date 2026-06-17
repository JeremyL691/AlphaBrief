"""CLI subcommands for the model gateway module."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import get_args

import typer
from alphabrief_models import (
    BUNDLED_DATASET_SPECS,
    FakeProviderAdapter,
    ModelEvaluator,
    ModelGateway,
    ModelProfile,
    ModelRegistry,
    ModelRequest,
    ModelRouter,
    ModelTaskType,
    OllamaProviderAdapter,
    ProviderAdapter,
    ProviderConfig,
    get_dataset_by_id,
)

model_app = typer.Typer(help="Manage model profiles, providers, and call records.")


@model_app.command("list")
def list_cmd() -> None:
    """List configured model profiles and providers."""
    print("model list: not yet implemented")


@model_app.command("test")
def test_cmd(
    provider: str = typer.Option(
        ...,
        "--provider",
        help="Provider to test: 'fake' or 'ollama'.",
    ),
    task: str = typer.Option(
        "market_summary",
        "--task",
        help="Task type used for the test request.",
    ),
) -> None:
    """Test provider connectivity via ModelGateway."""
    if provider == "fake":
        adapter: ProviderAdapter = FakeProviderAdapter()
    elif provider == "ollama":
        adapter = OllamaProviderAdapter(model_name="llama3")
    else:
        print(f"Unknown provider: {provider}. Use 'fake' or 'ollama'.", file=sys.stderr)
        sys.exit(1)

    valid_tasks = set(get_args(ModelTaskType))
    if task not in valid_tasks:
        print(
            f"error: invalid task type {task!r}. Valid: {sorted(valid_tasks)}",
            file=sys.stderr,
        )
        sys.exit(1)

    request = ModelRequest(
        request_id=f"cli_model_test_{provider}",
        task_type=task,  # type: ignore[arg-type]
        prompt_version="cli-model-test-v1",
        input_text="alphabrief model test ping",
        required_capabilities=["text_generation"],
    )

    gateway = ModelGateway(providers=[adapter])
    try:
        result = gateway.invoke(request)
    except Exception as exc:
        print(f"error: model gateway invoke failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if result.response is not None and result.record.status == "succeeded":
        print(f"Provider {provider}: OK")
        return

    error_detail = result.record.error_type or "unknown error"
    print(f"Provider {provider}: FAILED - {error_detail}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Phase 14: evaluation, performance, routing
# ---------------------------------------------------------------------------


def _default_registry() -> ModelRegistry:
    return ModelRegistry(
        providers=[
            ProviderConfig(provider_name="fake", enabled=True),
            ProviderConfig(provider_name="openai", enabled=True),
            ProviderConfig(provider_name="anthropic", enabled=True),
        ],
        profiles=[
            ModelProfile(
                profile_id="fake_default",
                provider_name="fake",
                model_name="fake-model",
                capabilities=["text_generation", "structured_output", "json_mode"],
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
        ],
    )


def _build_evaluator() -> ModelEvaluator:
    adapter = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-model",
        output_text=json.dumps(
            {"brief_id": "b1", "summary": "ok", "confidence": 0.8}
        ),
        structured_output={"brief_id": "b1", "summary": "ok", "confidence": 0.8},
    )
    return ModelEvaluator(ModelGateway([adapter]))


@model_app.command("evaluate")
def evaluate_cmd(
    model_id: str = typer.Option(  # noqa: B008
        ...,
        "--model-id",
        help="Provider-prefixed model id, e.g. 'openai:gpt-4o'.",
    ),
    task_type: str = typer.Option(  # noqa: B008
        ...,
        "--task",
        help="Task type to evaluate (e.g. 'daily_brief').",
    ),
    dataset_id: str = typer.Option(  # noqa: B008
        "daily_brief_v1",
        "--dataset",
        help="Bundled dataset id (default: 'daily_brief_v1').",
    ),
    sample_count: int = typer.Option(  # noqa: B008
        5,
        "--sample-count",
        help="Number of samples (1-50).",
    ),
    real_provider: bool = typer.Option(  # noqa: B008
        False,
        "--real-provider",
        help="Use a real provider instead of FakeProvider (not wired in MVP).",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
        help="Pretty-print the JSON output.",
    ),
) -> None:
    """Run an evaluation and print the result as JSON."""
    if ":" not in model_id:
        print(
            f"error: model_id must be in 'provider:model' format, got {model_id!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        dataset = get_dataset_by_id(dataset_id)
    except KeyError:
        ids = ", ".join(s.dataset_id for s in BUNDLED_DATASET_SPECS)
        print(
            f"error: unknown dataset_id {dataset_id!r}. Available: {ids}",
            file=sys.stderr,
        )
        sys.exit(1)
    if task_type != dataset.task_type:
        print(
            f"error: task {task_type!r} does not match dataset {dataset_id!r} "
            f"(expected {dataset.task_type!r})",
            file=sys.stderr,
        )
        sys.exit(1)

    evaluator = _build_evaluator()
    if real_provider:
        print(
            "warning: --real-provider is not wired in the MVP, using FakeProvider",
            file=sys.stderr,
        )

    result = evaluator.run_dataset(
        model_id=model_id, dataset=dataset, sample_count=sample_count
    )

    from alphabrief_api.db import ModelEvalStore

    db_path = os.environ.get("ALPHABRIEF_DATA_DIR")
    db_dir = Path(db_path) if db_path else Path.home() / ".alphabrief" / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    store = ModelEvalStore(db_path=db_dir / "alphabrief.db")
    try:
        store.save_evaluation(
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
    finally:
        store.close()

    indent = 2 if pretty else None
    json.dump(result.model_dump(), sys.stdout, indent=indent, sort_keys=True)
    sys.stdout.write("\n")


@model_app.command("performance")
def performance_cmd(
    model_id: str = typer.Option(  # noqa: B008
        ...,
        "--model-id",
        help="Provider-prefixed model id, e.g. 'openai:gpt-4o'.",
    ),
    task_type: str | None = typer.Option(  # noqa: B008
        None,
        "--task",
        help="Optional task type filter.",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Show stored evaluation results for a model."""
    if ":" not in model_id:
        print(
            f"error: model_id must be in 'provider:model' format, got {model_id!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    from alphabrief_api.db import ModelEvalStore

    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        store = ModelEvalStore(db_path=db_dir / "alphabrief.db")
    else:
        store = ModelEvalStore()

    try:
        if task_type is not None:
            records = store.get_evaluations(
                model_id=model_id, task_type=task_type
            )
        else:
            per_task = store.get_latest_per_task_for_model(model_id)
            records = list(per_task.values())
    finally:
        store.close()

    if not records:
        print(f"no evaluations found for model {model_id!r}", file=sys.stderr)
        sys.exit(1)

    indent = 2 if pretty else None
    json.dump(records, sys.stdout, indent=indent, sort_keys=True, default=str)
    sys.stdout.write("\n")


@model_app.command("route")
def route_cmd(
    task_type: str = typer.Option(  # noqa: B008
        ...,
        "--task",
        help="Task type to route.",
    ),
    capabilities: str = typer.Option(  # noqa: B008
        ...,
        "--capabilities",
        help="Comma-separated required capabilities.",
    ),
    prefer_low_cost: bool = typer.Option(  # noqa: B008
        False,
        "--prefer-low-cost",
    ),
    prefer_low_latency: bool = typer.Option(  # noqa: B008
        False,
        "--prefer-low-latency",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Query the router's recommendation for a task."""
    caps = [c.strip() for c in capabilities.split(",") if c.strip()]
    if not caps:
        print("error: --capabilities must contain at least one value", file=sys.stderr)
        sys.exit(1)

    from alphabrief_api.db import ModelEvalStore

    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        store = ModelEvalStore(db_path=db_dir / "alphabrief.db")
    else:
        store = ModelEvalStore()

    def provider(model_id: str, task: str) -> dict[str, object] | None:
        rec = store.get_latest_evaluation(model_id, task)
        if rec is None:
            return None
        return {
            "schema_pass_rate": rec.get("schema_pass_rate"),
            "json_valid_rate": rec.get("json_valid_rate"),
            "avg_latency_ms": rec.get("avg_latency_ms"),
            "avg_cost_estimate": rec.get("avg_cost_estimate"),
        }

    try:
        router_obj = ModelRouter(
            _default_registry(),
            performance_provider=provider,
        )
        decision = router_obj.route(
            task_type=task_type,
            required_capabilities=caps,  # type: ignore[arg-type]
            prefer_low_cost=prefer_low_cost,
            prefer_low_latency=prefer_low_latency,
        )
    finally:
        store.close()

    payload = {
        "profile_id": decision.profile_id,
        "provider_name": decision.provider_name,
        "model_name": decision.model_name,
        "routing_reason": decision.routing_reason,
        "candidates": list(decision.candidates),
        "used_performance_data": decision.used_performance_data,
    }
    indent = 2 if pretty else None
    json.dump(payload, sys.stdout, indent=indent, sort_keys=True)
    sys.stdout.write("\n")


@model_app.command("compare")
def compare_cmd(
    model_ids: str = typer.Option(  # noqa: B008
        ...,
        "--model-ids",
        help="Comma-separated list of model_ids to compare.",
    ),
    task_type: str = typer.Option(  # noqa: B008
        ...,
        "--task",
        help="Task type to compare on.",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Compare multiple models for a given task type."""
    ids = [m.strip() for m in model_ids.split(",") if m.strip()]
    if len(ids) < 2:
        print("error: --model-ids must contain at least 2 models", file=sys.stderr)
        sys.exit(1)
    for mid in ids:
        if ":" not in mid:
            print(
                f"error: model_id {mid!r} must be in 'provider:model' format",
                file=sys.stderr,
            )
            sys.exit(1)

    from alphabrief_api.db import ModelEvalStore

    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        store = ModelEvalStore(db_path=db_dir / "alphabrief.db")
    else:
        store = ModelEvalStore()

    rows: list[dict[str, object]] = []
    try:
        for mid in ids:
            rec = store.get_latest_evaluation(mid, task_type)
            if rec is None:
                rows.append(
                    {"model_id": mid, "has_data": False}
                )
            else:
                rows.append(
                    {
                        "model_id": mid,
                        "has_data": True,
                        "schema_pass_rate": rec.get("schema_pass_rate"),
                        "json_valid_rate": rec.get("json_valid_rate"),
                        "avg_latency_ms": rec.get("avg_latency_ms"),
                        "avg_cost_estimate": rec.get("avg_cost_estimate"),
                        "sample_count": rec.get("sample_count"),
                        "evaluated_at": str(rec.get("evaluated_at")),
                    }
                )
    finally:
        store.close()

    payload = {"task_type": task_type, "rows": rows}
    indent = 2 if pretty else None
    json.dump(payload, sys.stdout, indent=indent, sort_keys=True)
    sys.stdout.write("\n")


__all__ = ["model_app"]
