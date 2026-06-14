"""Real provider adapters for AlphaBrief ModelGateway."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from alphabrief_models.gateway import (
    ModelCapability,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
)

_HttpPost = Callable[[Request, float], bytes]
_DEFAULT_OLLAMA_CAPABILITIES: frozenset[ModelCapability] = frozenset(
    ("text_generation",)
)


def _default_http_post(request: Request, timeout_seconds: float) -> bytes:
    with urlopen(request, timeout=timeout_seconds) as response:
        return cast(bytes, response.read())


@dataclass
class OllamaProviderAdapter:
    """Provider adapter for a local Ollama server.

    This adapter performs a real HTTP request to Ollama's local API, but it
    does not use provider SDKs and does not store API keys or secrets.
    """

    provider_name: str = field(init=False, default="ollama")
    model_name: str
    base_url: str = "http://localhost:11434"
    capabilities: frozenset[ModelCapability] = _DEFAULT_OLLAMA_CAPABILITIES
    timeout_seconds: float = 30.0
    http_post: _HttpPost = _default_http_post

    def __post_init__(self) -> None:
        if self.model_name.strip() == "":
            raise ValueError("model_name must not be blank")
        if self.base_url.strip() == "":
            raise ValueError("base_url must not be blank")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def call(self, request: ModelRequest) -> ModelResponse:
        payload = {
            "model": self.model_name,
            "prompt": request.input_text,
            "stream": False,
        }
        if "structured_output" in request.required_capabilities:
            payload["format"] = "json"

        http_request = Request(
            _join_url(self.base_url, "/api/generate"),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            raw_response = self.http_post(http_request, self.timeout_seconds)
            decoded = json.loads(raw_response.decode("utf-8"))
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
            raise ModelProviderError("ollama provider call failed") from exc

        if not isinstance(decoded, dict):
            raise ModelProviderError("ollama response is not a JSON object")

        output_text = decoded.get("response")
        if not isinstance(output_text, str):
            raise ModelProviderError("ollama response is missing text output")

        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self.model_name,
            output_text=output_text,
            structured_output=_maybe_structured_output(output_text),
            status="succeeded",
            finish_reason=_finish_reason(decoded),
        )


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _finish_reason(payload: dict[str, Any]) -> str:
    done = payload.get("done")
    if done is False:
        return "incomplete"
    return "stop"


def _maybe_structured_output(output_text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None
