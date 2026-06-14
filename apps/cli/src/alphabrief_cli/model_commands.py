"""CLI subcommands for the model gateway module."""

from __future__ import annotations

import sys
from typing import get_args

import typer
from alphabrief_models import (
    FakeProviderAdapter,
    ModelGateway,
    ModelRequest,
    ModelTaskType,
    OllamaProviderAdapter,
    ProviderAdapter,
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


__all__ = ["model_app"]
