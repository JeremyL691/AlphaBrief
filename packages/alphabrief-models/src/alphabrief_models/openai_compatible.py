"""OpenAI-compatible fallback channel (``openai_compatible``).

This channel is **optional and never implicit**: it is only constructed
when the configuration enables ``model.fallback_enabled``, and every
switch away from the subscription channel is recorded so the billing
channel can never change silently.

Hosts containing ``opencode.ai`` are rejected at construction time
because that service's terms of use do not cover product traffic.

Configuration:

* ``ALPHABRIEF_LLM_BASE_URL`` — e.g. ``https://api.deepseek.com/v1``
* ``ALPHABRIEF_LLM_API_KEY``
* ``ALPHABRIEF_LLM_MODEL``
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlparse

from alphabrief_models.chatgpt_plan import (
    USER_AGENT,
    ChatGptPlanError,
    HttpSend,
    default_http_send,
)
from alphabrief_models.gateway import (
    ModelCapability,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
)

ENV_BASE_URL = "ALPHABRIEF_LLM_BASE_URL"
ENV_API_KEY = "ALPHABRIEF_LLM_API_KEY"
ENV_MODEL = "ALPHABRIEF_LLM_MODEL"

#: Hosts that must never be used as the product's model backend.
FORBIDDEN_HOST_FRAGMENTS = ("opencode.ai",)


@dataclass(frozen=True)
class FallbackConfig:
    """Resolved fallback-channel configuration."""

    base_url: str
    api_key: str
    model: str
    input_cost_per_million: Decimal | None = None
    output_cost_per_million: Decimal | None = None

    @property
    def host(self) -> str:
        return urlparse(self.base_url).hostname or ""

    def estimate_cost(
        self, *, input_tokens: int | None, output_tokens: int | None
    ) -> Decimal | None:
        if self.input_cost_per_million is None and self.output_cost_per_million is None:
            return None
        million = Decimal(1_000_000)
        cost = Decimal(0)
        if input_tokens is not None and self.input_cost_per_million is not None:
            cost += self.input_cost_per_million * Decimal(input_tokens) / million
        if output_tokens is not None and self.output_cost_per_million is not None:
            cost += self.output_cost_per_million * Decimal(output_tokens) / million
        return cost.quantize(Decimal("0.000001"))


def _reject_forbidden_host(base_url: str) -> None:
    host = (urlparse(base_url).hostname or "").lower()
    for fragment in FORBIDDEN_HOST_FRAGMENTS:
        if fragment in host:
            raise ValueError(
                f"{ENV_BASE_URL} must not point at {fragment}: that service's "
                "terms do not allow product traffic"
            )


def load_fallback_config(
    environ: dict[str, str] | None = None,
) -> FallbackConfig | None:
    """Return the configured fallback channel, or ``None`` when unset.

    A partially configured channel (URL but no key, or an unusable URL)
    raises instead of silently degrading, so a misconfiguration cannot
    look like "no fallback configured".
    """
    source = os.environ if environ is None else environ
    base_url = (source.get(ENV_BASE_URL) or "").strip()
    api_key = (source.get(ENV_API_KEY) or "").strip()
    model = (source.get(ENV_MODEL) or "").strip()
    if not base_url and not api_key and not model:
        return None
    if not base_url or not api_key or not model:
        raise ValueError(
            f"incomplete fallback configuration: set {ENV_BASE_URL}, "
            f"{ENV_API_KEY} and {ENV_MODEL} together"
        )
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{ENV_BASE_URL} must be an absolute http(s) URL")
    _reject_forbidden_host(base_url)
    return FallbackConfig(base_url=base_url.rstrip("/"), api_key=api_key, model=model)


class OpenAiCompatibleAdapter:
    """Provider adapter for a user-configured OpenAI-compatible endpoint."""

    provider_name = "openai_compatible"

    def __init__(
        self,
        config: FallbackConfig,
        *,
        http_send: HttpSend | None = None,
        timeout_seconds: float = 60.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        _reject_forbidden_host(config.base_url)
        self._config = config
        self._http_send = http_send or default_http_send
        self._timeout = timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        capabilities: frozenset[ModelCapability] = frozenset(
            {"text_generation", "structured_output", "json_mode"}
        )
        self.capabilities = capabilities
        self.model_name = config.model

    @property
    def config(self) -> FallbackConfig:
        return self._config

    def call(self, request: ModelRequest) -> ModelResponse:
        payload = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": request.input_text}],
            "stream": False,
        }
        response = self._http_send(
            "POST",
            f"{self._config.base_url}/chat/completions",
            {
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            json.dumps(payload).encode("utf-8"),
            self._timeout,
        )
        if response.status != 200:
            detail = ""
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("code") or "")
                elif body.get("detail"):
                    detail = str(body["detail"])
            raise ChatGptPlanError(
                "stream_failed",
                f"HTTP {response.status}{f': {detail[:200]}' if detail else ''}",
            )
        body = response.json()
        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ModelProviderError("compatible endpoint returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        text = ""
        if isinstance(message, dict):
            text = str(message.get("content") or "")
        usage = body.get("usage") if isinstance(body, dict) else None
        input_tokens = output_tokens = None
        if isinstance(usage, dict):
            raw_in = usage.get("prompt_tokens")
            raw_out = usage.get("completion_tokens")
            input_tokens = int(raw_in) if isinstance(raw_in, int) else None
            output_tokens = int(raw_out) if isinstance(raw_out, int) else None
        finish = ""
        if isinstance(choices[0], dict):
            finish = str(choices[0].get("finish_reason") or "")
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self._config.model,
            output_text=text.strip(),
            structured_output=None,
            status="succeeded",
            finish_reason=finish or "stop",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


__all__ = [
    "ENV_API_KEY",
    "ENV_BASE_URL",
    "ENV_MODEL",
    "FORBIDDEN_HOST_FRAGMENTS",
    "FallbackConfig",
    "OpenAiCompatibleAdapter",
    "load_fallback_config",
]
