"""Tests for AI trading model channel selection.

All model traffic goes through the ModelGateway channels: the ChatGPT
subscription channel is the default, an OpenAI-compatible endpoint is an
explicit opt-in fallback, and the deterministic fake exists only behind
an explicit ``ALPHABRIEF_AI_MODEL_PROVIDER=fake`` selection. The
operator's ``OPENAI_API_KEY`` is never read by the product.
"""

from __future__ import annotations

import pytest
from alphabrief_models import FakeProviderAdapter
from alphabrief_trader import (
    build_ai_trading_committee,
    build_ai_trading_provider,
    build_conservative_fake_provider,
)

_AI_ENV_VARS = (
    "ALPHABRIEF_AI_MODEL_PROVIDER",
    "ALPHABRIEF_AI_MODEL_NAME",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
)


@pytest.fixture(autouse=True)
def _clean_ai_model_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    for name in _AI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # Keep any accidental credential writes inside the test directory.
    monkeypatch.setenv(
        "ALPHABRIEF_HOME", str(tmp_path_factory.mktemp("ai-model-home"))
    )


class TestAiTradingModelFactory:
    def test_default_selection_is_the_chatgpt_channel(self) -> None:
        provider = build_ai_trading_provider()

        assert provider.provider_name == "chatgpt_plan"
        assert "structured_output" in provider.capabilities

    def test_operator_openai_key_is_not_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The product must never use the operator's coding-tool key."""
        monkeypatch.setenv("OPENAI_API_KEY", "operator-coding-tool-key")

        provider = build_ai_trading_provider()

        assert provider.provider_name == "chatgpt_plan"

    def test_explicit_fake_is_available_for_tests(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_MODEL_PROVIDER", "fake")

        provider = build_ai_trading_provider()

        assert isinstance(provider, FakeProviderAdapter)
        assert provider.model_name == "fake-ai-committee"
        assert "structured_output" in provider.capabilities

    def test_unknown_provider_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_MODEL_PROVIDER", "surprise")

        with pytest.raises(ValueError, match="auto, chatgpt, fake"):
            build_ai_trading_provider()

    def test_conservative_fake_requires_explicit_selection(self) -> None:
        provider = build_conservative_fake_provider()

        assert isinstance(provider, FakeProviderAdapter)
        # The fake is never reachable through the default composition path.
        assert build_ai_trading_provider().provider_name == "chatgpt_plan"

    def test_committee_is_built_on_the_channels(self) -> None:
        committee = build_ai_trading_committee()

        assert committee.roles

    def test_committee_with_explicit_fake_is_usable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_MODEL_PROVIDER", "fake")

        committee = build_ai_trading_committee()

        assert committee.roles  # explicit test composition builds a committee
