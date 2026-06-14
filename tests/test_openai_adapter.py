import json
from datetime import UTC, datetime
from email.message import Message
from typing import cast
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from alphabrief_models import (
    ModelCapability,
    ModelGateway,
    ModelProviderError,
    ModelRequest,
    OpenAIProviderAdapter,
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


def test_openai_provider_adapter_returns_success_on_valid_response() -> None:
    captured: dict[str, object] = {}

    def http_post(request: Request, timeout_seconds: float) -> bytes:
        captured["url"] = request.full_url
        captured["timeout"] = timeout_seconds
        payload_bytes = request.data
        assert isinstance(payload_bytes, bytes)
        captured["payload"] = json.loads(payload_bytes)
        captured["headers"] = dict(request.header_items())
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "OpenAI model response",
                        }
                    }
                ]
            }
        ).encode("utf-8")

    adapter = OpenAIProviderAdapter(
        model_name="gpt-3.5-turbo",
        api_key="sk-test",
        http_post=http_post,
        timeout_seconds=3.0,
    )

    response = adapter.call(_request())

    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["timeout"] == 3.0
    assert captured["payload"] == {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Generate a daily brief."}],
    }
    headers = cast(dict[str, str], captured["headers"])
    assert headers["Authorization"] == "Bearer sk-test"
    assert response.provider == "openai"
    assert response.model == "gpt-3.5-turbo"
    assert response.output_text == "OpenAI model response"
    assert response.finish_reason == "stop"


def test_openai_provider_adapter_raises_on_http_401() -> None:
    def http_post(_request: Request, _timeout_seconds: float) -> bytes:
        raise HTTPError(
            "https://api.openai.com/v1/chat/completions",
            401,
            "Unauthorized",
            Message(),
            None,
        )

    adapter = OpenAIProviderAdapter(
        model_name="gpt-3.5-turbo",
        api_key="sk-test",
        http_post=http_post,
    )

    with pytest.raises(ModelProviderError) as exc_info:
        adapter.call(_request())

    assert "401" in str(exc_info.value)


def test_openai_provider_adapter_integrates_with_model_gateway() -> None:
    def http_post(_request: Request, _timeout_seconds: float) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "gateway response",
                        }
                    }
                ]
            }
        ).encode("utf-8")

    adapter = OpenAIProviderAdapter(
        model_name="gpt-3.5-turbo",
        api_key="sk-test",
        http_post=http_post,
    )
    gateway = ModelGateway(
        [adapter],
        clock=lambda: NOW,
        call_id_factory=lambda: "call_1",
    )

    result = gateway.invoke(_request())

    assert result.response is not None
    assert result.response.provider == "openai"
    assert result.record.status == "succeeded"
    assert result.record.provider == "openai"
    assert result.record.model == "gpt-3.5-turbo"
    assert len(result.record.input_hash) == 64
    assert len(result.record.output_hash) == 64
