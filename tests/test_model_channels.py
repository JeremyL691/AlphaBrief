"""Tests for the fallback channel and the explicit channel-switch policy."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from alphabrief_models.channels import (
    ModelSettings,
    build_channel_gateway,
    load_model_settings,
)
from alphabrief_models.chatgpt_plan import (
    ChatGptCredentials,
    HttpResponse,
)
from alphabrief_models.gateway import (
    ModelCapability,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)
from alphabrief_models.openai_compatible import (
    FallbackConfig,
    OpenAiCompatibleAdapter,
    load_fallback_config,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


class _ScriptedAdapter:
    """Provider double that succeeds, or raises a scripted error."""

    def __init__(
        self,
        name: str,
        *,
        error: Exception | None = None,
        text: str = "ok",
        capabilities: frozenset[ModelCapability] | None = None,
    ) -> None:
        self.provider_name = name
        self.model_name = f"{name}-model"
        selected: frozenset[ModelCapability] = capabilities or frozenset(
            {"text_generation"}
        )
        self.capabilities = selected
        self._error = error
        self._text = text
        self.calls = 0

    def call(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self.model_name,
            output_text=self._text,
            status="succeeded",
            finish_reason="stop",
        )


class _ChannelFailure(Exception):
    """Provider error carrying a channel error code."""

    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _request() -> ModelRequest:
    return ModelRequest(
        request_id="req-1",
        task_type="test",
        prompt_version="v1",
        input_text="hello",
        required_capabilities=["text_generation"],
    )


class TestFallbackConfiguration:
    def test_missing_configuration_returns_none(self) -> None:
        assert load_fallback_config({}) is None

    def test_complete_configuration_is_loaded(self) -> None:
        config = load_fallback_config(
            {
                "ALPHABRIEF_LLM_BASE_URL": "https://api.example.com/v1",
                "ALPHABRIEF_LLM_API_KEY": "key-value",
                "ALPHABRIEF_LLM_MODEL": "model-1",
            }
        )

        assert config is not None
        assert config.host == "api.example.com"
        assert config.model == "model-1"

    def test_partial_configuration_raises(self) -> None:
        with pytest.raises(ValueError, match="incomplete fallback configuration"):
            load_fallback_config(
                {"ALPHABRIEF_LLM_BASE_URL": "https://api.example.com/v1"}
            )

    @pytest.mark.parametrize(
        "host",
        [
            "https://opencode.ai/zen/go",
            "https://api.opencode.ai/v1",
        ],
    )
    def test_opencode_hosts_are_refused(self, host: str) -> None:
        with pytest.raises(ValueError, match="opencode.ai"):
            load_fallback_config(
                {
                    "ALPHABRIEF_LLM_BASE_URL": host,
                    "ALPHABRIEF_LLM_API_KEY": "key-value",
                    "ALPHABRIEF_LLM_MODEL": "model-1",
                }
            )

    def test_relative_url_is_refused(self) -> None:
        with pytest.raises(ValueError, match="absolute http"):
            load_fallback_config(
                {
                    "ALPHABRIEF_LLM_BASE_URL": "api.example.com/v1",
                    "ALPHABRIEF_LLM_API_KEY": "key-value",
                    "ALPHABRIEF_LLM_MODEL": "model-1",
                }
            )

    def test_config_file_defaults_to_fallback_disabled(self, tmp_path: Any) -> None:
        path = tmp_path / "alphabrief.yaml"
        path.write_text("schema_version: 1\nmodel:\n  fallback_enabled: false\n")

        settings = load_model_settings(path)

        assert settings.fallback_enabled is False

    def test_config_file_typo_raises(self, tmp_path: Any) -> None:
        path = tmp_path / "alphabrief.yaml"
        path.write_text("schema_version: 1\nmodel:\n  fallback_enabled: 'yes'\n")

        with pytest.raises(ValueError, match="must be true or false"):
            load_model_settings(path)


class TestFallbackAdapter:
    def _config(self) -> FallbackConfig:
        return FallbackConfig(
            base_url="https://api.example.com/v1",
            api_key="key-value",
            model="model-1",
        )

    def test_chat_completions_call_returns_text_and_tokens(self) -> None:
        captured: dict[str, Any] = {}

        def http_send(method, url, headers, body, timeout):  # type: ignore[no-untyped-def]
            captured.update(
                {"method": method, "url": url, "headers": headers, "body": body}
            )
            return HttpResponse(
                status=200,
                body=json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"content": "  hello  "},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                    }
                ).encode(),
            )

        adapter = OpenAiCompatibleAdapter(self._config(), http_send=http_send)

        response = adapter.call(_request())

        assert response.output_text == "hello"
        assert response.input_tokens == 5
        assert captured["url"] == "https://api.example.com/v1/chat/completions"
        assert captured["method"] == "POST"
        assert "api_key" not in json.dumps(response.model_dump(mode="json"))

    def test_error_status_is_reported(self) -> None:
        adapter = OpenAiCompatibleAdapter(
            self._config(),
            http_send=lambda *args: HttpResponse(status=401, body=b"{}"),
        )

        with pytest.raises(Exception) as exc:
            adapter.call(_request())

        assert "401" in str(exc.value)

    def test_cost_estimate_uses_configured_prices(self) -> None:
        config = FallbackConfig(
            base_url="https://api.example.com/v1",
            api_key="key-value",
            model="model-1",
            input_cost_per_million=Decimal("1"),
            output_cost_per_million=Decimal("2"),
        )

        cost = config.estimate_cost(input_tokens=1_000_000, output_tokens=1_000_000)

        assert cost == Decimal("3.000000")

    def test_cost_estimate_is_none_without_prices(self) -> None:
        assert (
            self._config().estimate_cost(input_tokens=10, output_tokens=10) is None
        )


class TestChannelSwitchPolicy:
    def test_without_fallback_no_second_provider_is_tried(self) -> None:
        primary = _ScriptedAdapter("chatgpt_plan", error=_ChannelFailure("boom"))
        fallback = _ScriptedAdapter("openai_compatible")
        gateway = ModelGateway(
            [primary, fallback], fallback_enabled=False, clock=lambda: NOW
        )

        result = gateway.invoke(_request())

        assert result.response is None
        assert primary.calls == 1
        assert fallback.calls == 0

    def test_with_fallback_the_second_channel_serves_the_call(self) -> None:
        primary = _ScriptedAdapter("chatgpt_plan", error=_ChannelFailure("boom"))
        fallback = _ScriptedAdapter("openai_compatible")
        gateway = ModelGateway(
            [primary, fallback], fallback_enabled=True, clock=lambda: NOW
        )

        result = gateway.invoke(_request())

        assert result.response is not None
        assert result.record.provider == "openai_compatible"
        assert primary.calls == 1
        assert fallback.calls == 1
        # One record per attempt: the failed channel and the serving one.
        assert [record.provider for record in gateway.call_records] == [
            "chatgpt_plan",
            "openai_compatible",
        ]
        assert gateway.call_records[0].status == "failed"
        assert "boom" in str(gateway.call_records[0].error_type)

    def test_success_on_the_primary_never_touches_the_fallback(self) -> None:
        primary = _ScriptedAdapter("chatgpt_plan")
        fallback = _ScriptedAdapter("openai_compatible")
        gateway = ModelGateway(
            [primary, fallback], fallback_enabled=True, clock=lambda: NOW
        )

        result = gateway.invoke(_request())

        assert result.record.provider == "chatgpt_plan"
        assert fallback.calls == 0


class TestBuildChannelGateway:
    def _credentials(self) -> ChatGptCredentials:
        from datetime import timedelta

        return ChatGptCredentials(
            client_id="client-1",
            agent_host_id="urn:uuid:00000000-0000-4000-8000-000000000000",
            access_token="a",
            refresh_token="r",
            id_token="i",
            scopes=("openid", "chatgpt.tokens.use.direct"),
            expires_at=NOW + timedelta(hours=1),
            account_id="acct",
            default_model="gpt-test-1",
        )

    def test_primary_channel_is_the_subscription(self, tmp_path: Any) -> None:
        channels = build_channel_gateway(
            settings=ModelSettings(fallback_enabled=False),
            credentials=self._credentials(),
            http_send=lambda *args: HttpResponse(status=200, body=b""),
            clock=lambda: NOW,
        )

        assert channels.primary_channel == "chatgpt_plan"
        assert channels.fallback_channel is None

    def test_fallback_enabled_without_configuration_raises(self) -> None:
        with pytest.raises(ValueError, match="no fallback channel is configured"):
            build_channel_gateway(
                settings=ModelSettings(fallback_enabled=True),
                credentials=self._credentials(),
                environ={},
                clock=lambda: NOW,
            )

    def test_fallback_channel_is_added_when_configured(self) -> None:
        channels = build_channel_gateway(
            settings=ModelSettings(fallback_enabled=True),
            credentials=self._credentials(),
            environ={
                "ALPHABRIEF_LLM_BASE_URL": "https://api.example.com/v1",
                "ALPHABRIEF_LLM_API_KEY": "key-value",
                "ALPHABRIEF_LLM_MODEL": "model-1",
            },
            http_send=lambda *args: HttpResponse(status=200, body=b""),
            clock=lambda: NOW,
        )

        assert channels.fallback_channel == "openai_compatible"

    def test_opencode_host_is_refused_when_building(self) -> None:
        with pytest.raises(ValueError, match="opencode.ai"):
            build_channel_gateway(
                settings=ModelSettings(fallback_enabled=True),
                credentials=self._credentials(),
                environ={
                    "ALPHABRIEF_LLM_BASE_URL": "https://opencode.ai/zen/go",
                    "ALPHABRIEF_LLM_API_KEY": "key-value",
                    "ALPHABRIEF_LLM_MODEL": "model-1",
                },
                clock=lambda: NOW,
            )

    def test_switch_report_is_empty_without_switches(self) -> None:
        channels = build_channel_gateway(
            settings=ModelSettings(fallback_enabled=False),
            credentials=self._credentials(),
            clock=lambda: NOW,
        )

        assert channels.switch_report() == []


class TestRefreshPath:
    def test_channel_gateway_refreshes_before_calling(self, monkeypatch: Any) -> None:
        calls: list[str] = []

        def fake_refresh(credentials, **kwargs):  # type: ignore[no-untyped-def]
            calls.append("refresh")
            return credentials

        monkeypatch.setattr(
            "alphabrief_models.channels.refresh_credentials", fake_refresh
        )
        refreshed = build_channel_gateway(
            settings=ModelSettings(fallback_enabled=False),
            credentials=None,
            clock=lambda: NOW,
        )

        assert refreshed.primary_channel == "chatgpt_plan"
        assert calls == []
