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
from committee_provider import GroundedProvider

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


def test_production_factory_uses_five_calls_and_manager_sees_analysts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal
    from types import SimpleNamespace
    from typing import Any

    import alphabrief_trader.model_factory as factory
    from alphabrief_models import (
        ModelGateway,
        ModelRequest,
        ModelResponse,
    )
    from alphabrief_trader import CommitteeInput, MarketSnapshot

    requests: list[ModelRequest] = []

    class RecordingProvider(GroundedProvider):
        def call(self, request: ModelRequest) -> ModelResponse:
            requests.append(request)
            return super().call(request)

    provider = RecordingProvider(
        capabilities=["structured_output"], structured_output={
            "analysis": "Observed trend from this snapshot", "view": "bullish",
            "confidence": 0.8, "evidence_ids": [], "risks": [],
            "suggested_action": "buy", "target_position_pct": "0.1",
            "veto": False, "needs_human_review": False,
        },
    )

    def channels(**kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(gateway=ModelGateway([provider]))

    monkeypatch.setattr(factory, "build_ai_trading_channels", channels)
    committee = factory.build_ai_trading_committee()
    result = committee.run(CommitteeInput(snapshot=MarketSnapshot(
        symbol="EUR_USD", reference_price=Decimal("1.1"),
        captured_at=datetime.now(UTC),
    )))
    assert result.ok
    assert len(requests) == 5
    roles = [request.metadata["committee_role"] for request in requests]
    assert roles == committee.roles
    manager_input = requests[-1].input_text
    assert "Earlier analyst votes" in manager_input
    for role in committee.roles[:-1]:
        assert f'"role": "{role}"' in manager_input
    assert manager_input.count("Observed trend from this snapshot") == 4
