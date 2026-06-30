"""Tests for AI trading model provider selection."""

from __future__ import annotations

import pytest
from alphabrief_models import FakeProviderAdapter, OllamaProviderAdapter
from alphabrief_models.openai_adapter import OpenAIProviderAdapter
from alphabrief_trader import build_ai_trading_provider

_AI_ENV_VARS = (
    "ALPHABRIEF_AI_MODEL_PROVIDER",
    "ALPHABRIEF_AI_MODEL_NAME",
    "ALPHABRIEF_AI_MODEL_BASE_URL",
    "ALPHABRIEF_AI_MODEL_TIMEOUT_SECONDS",
    "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _clean_ai_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _AI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class TestAiTradingModelFactory:
    def test_auto_without_openai_key_uses_conservative_fake(self) -> None:
        provider = build_ai_trading_provider()

        assert isinstance(provider, FakeProviderAdapter)
        assert provider.model_name == "fake-ai-committee"
        assert "structured_output" in provider.capabilities

    def test_auto_with_openai_key_uses_openai(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        provider = build_ai_trading_provider()

        assert isinstance(provider, OpenAIProviderAdapter)
        assert provider.model_name == "gpt-4o-mini"
        assert "structured_output" in provider.capabilities

    def test_explicit_openai_requires_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_MODEL_PROVIDER", "openai")

        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            build_ai_trading_provider()

    def test_explicit_ollama_uses_local_adapter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_MODEL_PROVIDER", "ollama")
        monkeypatch.setenv("ALPHABRIEF_AI_MODEL_NAME", "llama3.1")
        monkeypatch.setenv("ALPHABRIEF_AI_MODEL_BASE_URL", "http://127.0.0.1:11434")

        provider = build_ai_trading_provider()

        assert isinstance(provider, OllamaProviderAdapter)
        assert provider.model_name == "llama3.1"
        assert provider.base_url == "http://127.0.0.1:11434"
        assert "structured_output" in provider.capabilities

    def test_unknown_provider_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_MODEL_PROVIDER", "surprise")

        with pytest.raises(ValueError, match="auto, fake, openai, ollama"):
            build_ai_trading_provider()
