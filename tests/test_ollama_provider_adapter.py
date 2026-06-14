import json
from datetime import UTC, datetime
from urllib.error import URLError
from urllib.request import Request

import pytest
from alphabrief_models import (
    ModelCapability,
    ModelGateway,
    ModelRequest,
    OllamaProviderAdapter,
)

NOW = datetime(2026, 6, 14, 9, 0, tzinfo=UTC)


def _request(
    *,
    required_capabilities: list[ModelCapability] | None = None,
) -> ModelRequest:
    return ModelRequest(
        request_id="request_1",
        task_type="daily_brief",
        prompt_version="daily_alpha_brief:v1",
        input_text="Generate a daily brief.",
        required_capabilities=required_capabilities or ["text_generation"],
    )


def test_ollama_provider_adapter_calls_generate_endpoint() -> None:
    captured: dict[str, object] = {}

    def http_post(request: Request, timeout_seconds: float) -> bytes:
        captured["url"] = request.full_url
        captured["timeout"] = timeout_seconds
        payload_bytes = request.data
        assert isinstance(payload_bytes, bytes)
        captured["payload"] = json.loads(payload_bytes)
        return json.dumps(
            {
                "model": "llama3.1",
                "response": "local model response",
                "done": True,
            }
        ).encode("utf-8")

    adapter = OllamaProviderAdapter(
        model_name="llama3.1",
        base_url="http://localhost:11434/",
        http_post=http_post,
        timeout_seconds=3.0,
    )

    response = adapter.call(_request())

    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["timeout"] == 3.0
    assert captured["payload"] == {
        "model": "llama3.1",
        "prompt": "Generate a daily brief.",
        "stream": False,
    }
    assert response.provider == "ollama"
    assert response.model == "llama3.1"
    assert response.output_text == "local model response"
    assert response.finish_reason == "stop"


def test_ollama_provider_adapter_requests_json_format_for_structured_output() -> None:
    captured: dict[str, object] = {}
    structured_payload = {"brief_id": "daily_1"}

    def http_post(request: Request, _timeout_seconds: float) -> bytes:
        payload_bytes = request.data
        assert isinstance(payload_bytes, bytes)
        captured["payload"] = json.loads(payload_bytes)
        return json.dumps(
            {
                "model": "llama3.1",
                "response": json.dumps(structured_payload),
                "done": True,
            }
        ).encode("utf-8")

    adapter = OllamaProviderAdapter(
        model_name="llama3.1",
        capabilities=frozenset({"text_generation", "structured_output"}),
        http_post=http_post,
    )

    response = adapter.call(_request(required_capabilities=["structured_output"]))

    assert captured["payload"] == {
        "model": "llama3.1",
        "prompt": "Generate a daily brief.",
        "stream": False,
        "format": "json",
    }
    assert response.structured_output == structured_payload


def test_ollama_provider_adapter_integrates_with_model_gateway() -> None:
    def http_post(_request: Request, _timeout_seconds: float) -> bytes:
        return json.dumps(
            {
                "model": "llama3.1",
                "response": "local response",
                "done": True,
            }
        ).encode("utf-8")

    adapter = OllamaProviderAdapter(model_name="llama3.1", http_post=http_post)
    gateway = ModelGateway(
        [adapter],
        clock=lambda: NOW,
        call_id_factory=lambda: "call_1",
    )

    result = gateway.invoke(_request())

    assert result.response is not None
    assert result.response.provider == "ollama"
    assert result.record.status == "succeeded"
    assert result.record.provider == "ollama"
    assert result.record.model == "llama3.1"
    assert len(result.record.input_hash) == 64
    assert len(result.record.output_hash) == 64


def test_ollama_provider_adapter_failure_is_recorded_by_gateway() -> None:
    def http_post(_request: Request, _timeout_seconds: float) -> bytes:
        raise URLError("connection refused")

    adapter = OllamaProviderAdapter(model_name="llama3.1", http_post=http_post)
    gateway = ModelGateway(
        [adapter],
        clock=lambda: NOW,
        call_id_factory=lambda: "call_1",
    )

    result = gateway.invoke(_request())

    assert result.response is None
    assert result.record.status == "failed"
    assert result.record.error_type == "ModelProviderError"


def test_ollama_provider_adapter_rejects_invalid_config() -> None:
    with pytest.raises(ValueError, match="model_name"):
        OllamaProviderAdapter(model_name=" ")

    with pytest.raises(ValueError, match="timeout_seconds"):
        OllamaProviderAdapter(model_name="llama3.1", timeout_seconds=0)
