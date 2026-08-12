"""OpenAI provider adapter for AlphaBrief ModelGateway."""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from alphabrief_models.adapters import _maybe_structured_output
from alphabrief_models.gateway import (
    ModelCapability,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
)

_HttpPost = Callable[[Request, float], bytes]
_DEFAULT_OPENAI_CAPABILITIES: frozenset[ModelCapability] = frozenset(
    ("text_generation",)
)


def _default_http_post(request: Request, timeout_seconds: float) -> bytes:
    with urlopen(request, timeout=timeout_seconds) as response:
        return cast(bytes, response.read())


@dataclass
class OpenAIProviderAdapter:
    """Provider adapter for OpenAI API.

    This adapter performs HTTP requests to OpenAI's chat completions endpoint
    using urllib only. It does not use the openai SDK.
    """

    provider_name: str = field(init=False, default="openai")
    model_name: str = "gpt-3.5-turbo"
    api_key: str | None = None
    base_url: str | None = None
    capabilities: frozenset[ModelCapability] = _DEFAULT_OPENAI_CAPABILITIES
    timeout_seconds: float = 30.0
    http_post: _HttpPost = _default_http_post

    def __post_init__(self) -> None:
        explicit_api_key = self.api_key is not None
        if self.model_name.strip() == "":
            raise ValueError("model_name must not be blank")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.api_key is None:
            self.api_key = os.environ.get("OPENAI_API_KEY")
        if self.base_url is None:
            self.base_url = (
                "https://api.openai.com"
                if explicit_api_key
                else os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")
            )
        self.base_url = self.base_url.rstrip("/")

    def _chat_url(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    def call(self, request: ModelRequest) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": request.input_text}],
        }
        if "structured_output" in request.required_capabilities:
            payload["response_format"] = {"type": "json_object"}
            # Some OpenAI-compatible upstreams (e.g. opencode's Console Go)
            # reject json_object mode unless the prompt mentions JSON.
            # A system instruction satisfies that requirement without
            # touching the caller's prompt.
            payload["messages"].insert(
                0,
                {"role": "system", "content": "Respond in JSON format."},
            )

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "openai-python/1.30.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        http_request = Request(
            self._chat_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            raw_response = self.http_post(http_request, self.timeout_seconds)
            decoded = json.loads(raw_response.decode("utf-8"))
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
            raise ModelProviderError(f"openai provider call failed: {exc}") from exc

        if not isinstance(decoded, dict):
            raise ModelProviderError("openai response is not a JSON object")

        choices = decoded.get("choices")
        if not isinstance(choices, list) or len(choices) == 0:
            raise ModelProviderError("openai response is missing choices")

        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ModelProviderError("openai response is missing message")

        output_text = message.get("content")
        if not isinstance(output_text, str):
            raise ModelProviderError("openai response is missing text output")

        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self.model_name,
            output_text=output_text,
            structured_output=_maybe_structured_output(output_text),
            status="succeeded",
            finish_reason="stop",
        )
