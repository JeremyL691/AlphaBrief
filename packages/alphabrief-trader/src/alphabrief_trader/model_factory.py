"""Model provider factory for the AI Trading Committee.

The scheduler/API/CLI all need the same model wiring. This module keeps
that selection in one place and fails closed when no real provider has
been configured: production composition never falls back to a fake
provider. A fake provider is available only through an explicit
``ALPHABRIEF_AI_MODEL_PROVIDER=fake`` selection used by tests.
"""

from __future__ import annotations

import os

from alphabrief_models import (
    FakeProviderAdapter,
    ModelCapability,
    ModelGateway,
    OllamaProviderAdapter,
    OpenAIProviderAdapter,
    ProviderAdapter,
)

from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.rules import DisciplineConfig

AI_MODEL_PROVIDER_ENV = "ALPHABRIEF_AI_MODEL_PROVIDER"
AI_MODEL_NAME_ENV = "ALPHABRIEF_AI_MODEL_NAME"
AI_MODEL_BASE_URL_ENV = "ALPHABRIEF_AI_MODEL_BASE_URL"
AI_MODEL_TIMEOUT_ENV = "ALPHABRIEF_AI_MODEL_TIMEOUT_SECONDS"

_STRUCTURED_CAPABILITIES: frozenset[ModelCapability] = frozenset(
    {"text_generation", "structured_output", "json_mode"}
)


class ModelProviderUnavailableError(RuntimeError):
    """Raised when no real model provider is configured.

    Production composition must fail closed: a missing provider must
    never be silently replaced by a deterministic fake that could
    fabricate research or orders.
    """


def build_ai_trading_committee() -> TradingCommittee:
    """Build the AI Trading Committee from environment-backed providers.

    Raises :class:`ModelProviderUnavailableError` when no real provider
    is configured so the caller can fail closed (for example persist a
    durable blocked or no-trade cycle) before any proposal or intent
    exists.
    """

    provider = build_ai_trading_provider()
    gateway = ModelGateway(providers=[provider])
    return TradingCommittee(gateway=gateway, discipline=DisciplineConfig())


def build_ai_trading_provider() -> ProviderAdapter:
    """Return the configured AI trading model provider.

    Selection rules:

    1. ``ALPHABRIEF_AI_MODEL_PROVIDER=fake`` forces the conservative
       fake. This is an explicit test/dev selection, never a fallback.
    2. ``...=openai`` requires ``OPENAI_API_KEY`` and uses
       ``ALPHABRIEF_AI_MODEL_NAME`` or ``gpt-4o-mini``.
    3. ``...=ollama`` uses local Ollama and requires an explicit model
       name or falls back to ``llama3.1``.
    4. ``...=auto`` (default) selects OpenAI only when
       ``OPENAI_API_KEY`` exists, otherwise raises
       :class:`ModelProviderUnavailableError` — production never
       silently falls back to a fake provider.
    """

    requested = os.environ.get(AI_MODEL_PROVIDER_ENV, "auto").strip().lower()
    if requested in {"", "auto"}:
        if os.environ.get("OPENAI_API_KEY"):
            return _build_openai_provider()
        raise ModelProviderUnavailableError(
            "no model provider configured: set ALPHABRIEF_AI_MODEL_PROVIDER "
            "to 'openai' with OPENAI_API_KEY, or 'ollama' with a local "
            "server, or select 'fake' explicitly for test composition"
        )
    if requested == "fake":
        return build_conservative_fake_provider()
    if requested == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError(
                "ALPHABRIEF_AI_MODEL_PROVIDER=openai requires OPENAI_API_KEY"
            )
        return _build_openai_provider()
    if requested == "ollama":
        return _build_ollama_provider()
    raise ValueError(
        "ALPHABRIEF_AI_MODEL_PROVIDER must be one of auto, fake, openai, ollama"
    )


def build_conservative_fake_provider() -> FakeProviderAdapter:
    """Return the deterministic fake provider for explicit test selection.

    Only reachable through an explicit ``ALPHABRIEF_AI_MODEL_PROVIDER=fake``
    environment selection or a direct test import. It is never used as a
    production fallback.
    """

    return FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-ai-committee",
        capabilities=sorted(_STRUCTURED_CAPABILITIES),
        structured_output={
            "analysis": (
                "Trend remains constructive on improving breadth; downside risks "
                "centered on macro headlines and crowded positioning."
            ),
            "view": "bullish",
            "confidence": 0.62,
            "evidence": [
                "EMA20 above EMA50 with rising volume",
                "News tone modestly positive",
            ],
            "risks": ["Macro headline tail-risk", "Crowded long positioning"],
            "suggested_action": "watch",
            "target_position_pct": "0.10",
            "veto": False,
            "needs_human_review": True,
        },
    )


def _build_openai_provider() -> OpenAIProviderAdapter:
    return OpenAIProviderAdapter(
        model_name=os.environ.get(AI_MODEL_NAME_ENV, "gpt-4o-mini"),
        capabilities=_STRUCTURED_CAPABILITIES,
        timeout_seconds=_timeout_seconds(),
    )


def _build_ollama_provider() -> OllamaProviderAdapter:
    return OllamaProviderAdapter(
        model_name=os.environ.get(AI_MODEL_NAME_ENV, "llama3.1"),
        base_url=os.environ.get(AI_MODEL_BASE_URL_ENV, "http://localhost:11434"),
        capabilities=_STRUCTURED_CAPABILITIES,
        timeout_seconds=_timeout_seconds(),
    )


def _timeout_seconds() -> float:
    raw = os.environ.get(AI_MODEL_TIMEOUT_ENV)
    if raw is None or raw.strip() == "":
        return 30.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{AI_MODEL_TIMEOUT_ENV} must be a positive number") from exc
    if value <= 0:
        raise ValueError(f"{AI_MODEL_TIMEOUT_ENV} must be positive")
    return value


__all__ = [
    "AI_MODEL_BASE_URL_ENV",
    "AI_MODEL_NAME_ENV",
    "AI_MODEL_PROVIDER_ENV",
    "AI_MODEL_TIMEOUT_ENV",
    "ModelProviderUnavailableError",
    "build_ai_trading_committee",
    "build_ai_trading_provider",
    "build_conservative_fake_provider",
]
