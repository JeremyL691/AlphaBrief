from datetime import UTC, datetime

import pytest
from alphabrief_models import (
    FakeProviderAdapter,
    ModelCapability,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)
from pydantic import ValidationError

NOW = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)


def make_request(
    *, required_capabilities: list[ModelCapability] | None = None
) -> ModelRequest:
    return ModelRequest(
        request_id="request_1",
        task_type="test",
        prompt_version="test_v1",
        input_text="Summarize this market note.",
        required_capabilities=required_capabilities or ["text_generation"],
    )


def test_model_request_rejects_duplicate_capabilities() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        make_request(required_capabilities=["text_generation", "text_generation"])


def test_model_request_rejects_secret_like_metadata_keys() -> None:
    with pytest.raises(ValidationError, match="secret-like"):
        ModelRequest(
            request_id="request_1",
            task_type="test",
            prompt_version="test_v1",
            input_text="hello",
            required_capabilities=["text_generation"],
            metadata={"api_key": "not allowed"},
        )


def test_gateway_invokes_fake_provider_and_records_hashes() -> None:
    provider = FakeProviderAdapter(output_text="structured fake answer")
    gateway = ModelGateway(
        [provider], clock=lambda: NOW, call_id_factory=lambda: "call_1"
    )

    result = gateway.invoke(make_request())

    assert result.response is not None
    assert result.response.output_text == "structured fake answer"
    assert result.record.call_id == "call_1"
    assert result.record.provider == "fake"
    assert result.record.model == "fake-model"
    assert result.record.status == "succeeded"
    assert len(result.record.input_hash) == 64
    assert len(result.record.output_hash) == 64
    assert gateway.call_records == [result.record]


def test_gateway_selects_provider_by_required_capability() -> None:
    low_cost_provider = FakeProviderAdapter(
        provider_name="cheap",
        model_name="cheap-model",
        capabilities=["text_generation", "low_cost"],
    )
    reasoning_provider = FakeProviderAdapter(
        provider_name="reasoning",
        model_name="reasoning-model",
        capabilities=["text_generation", "strong_reasoning"],
    )
    gateway = ModelGateway(
        [low_cost_provider, reasoning_provider],
        clock=lambda: NOW,
        call_id_factory=lambda: "call_1",
    )

    result = gateway.invoke(make_request(required_capabilities=["strong_reasoning"]))

    assert result.response is not None
    assert result.response.provider == "reasoning"
    assert result.record.provider == "reasoning"


def test_gateway_accepts_time_series_forecasting_capability() -> None:
    provider = FakeProviderAdapter(
        provider_name="forecast",
        model_name="forecast-model",
        capabilities=["structured_output", "time_series_forecasting"],
        structured_output={"ok": True},
    )
    gateway = ModelGateway(
        [provider], clock=lambda: NOW, call_id_factory=lambda: "call_1"
    )
    request = ModelRequest(
        request_id="request_1",
        task_type="market_forecast",
        prompt_version="forecast_v1",
        input_text="{}",
        required_capabilities=["time_series_forecasting"],
    )

    result = gateway.invoke(request)

    assert result.response is not None
    assert result.record.provider == "forecast"


def test_gateway_rejects_when_no_provider_matches_capabilities() -> None:
    provider = FakeProviderAdapter(capabilities=["text_generation"])
    gateway = ModelGateway(
        [provider], clock=lambda: NOW, call_id_factory=lambda: "call_1"
    )

    result = gateway.invoke(make_request(required_capabilities=["json_mode"]))

    assert result.response is None
    assert result.record.status == "rejected"
    assert result.record.provider == "unselected"
    assert result.record.error_type == "NoProviderForCapabilities"
    assert gateway.call_records == [result.record]


def test_gateway_records_provider_failures_without_raw_output() -> None:
    provider = FakeProviderAdapter(fail=True)
    gateway = ModelGateway(
        [provider], clock=lambda: NOW, call_id_factory=lambda: "call_1"
    )

    result = gateway.invoke(make_request())

    assert result.response is None
    assert result.record.status == "failed"
    assert result.record.error_type == "ModelProviderError"
    assert result.record.output_hash == ""
    assert gateway.call_records == [result.record]


def test_model_call_record_does_not_store_raw_prompt_or_api_key() -> None:
    provider = FakeProviderAdapter(output_text="raw model output")
    gateway = ModelGateway(
        [provider], clock=lambda: NOW, call_id_factory=lambda: "call_1"
    )

    result = gateway.invoke(make_request())

    record_payload = result.record.model_dump()

    assert "input_text" not in record_payload
    assert "output_text" not in record_payload
    assert "api_key" not in record_payload
    assert "Summarize this market note." not in str(record_payload)
    assert "raw model output" not in str(record_payload)


# ---------------------------------------------------------------------------
# M10-W02: terminal classification and durable record sink
# ---------------------------------------------------------------------------


class _TimedOutProvider(FakeProviderAdapter):
    def call(self, request: ModelRequest) -> ModelResponse:
        raise TimeoutError("provider timed out")


class _RateLimitedProvider(FakeProviderAdapter):
    def call(self, request: ModelRequest) -> ModelResponse:
        from alphabrief_models import ModelProviderError

        raise ModelProviderError("openai provider call failed: HTTP Error 429: ...")


class _MalformedProvider(FakeProviderAdapter):
    def call(self, request: ModelRequest) -> ModelResponse:
        from alphabrief_models import ModelProviderError

        raise ModelProviderError("ollama response is missing text output")


def test_gateway_classifies_timeout_errors() -> None:
    gateway = ModelGateway([_TimedOutProvider()])
    result = gateway.invoke(make_request())
    assert result.response is None
    assert result.record.classification == "timeout"
    assert result.record.status == "failed"


def test_gateway_classifies_rate_limit_errors() -> None:
    gateway = ModelGateway([_RateLimitedProvider()])
    result = gateway.invoke(make_request())
    assert result.response is None
    assert result.record.classification == "rate_limit"


def test_gateway_classifies_malformed_response_errors() -> None:
    gateway = ModelGateway([_MalformedProvider()])
    result = gateway.invoke(make_request())
    assert result.response is None
    assert result.record.classification == "malformed"


def test_gateway_classifies_generic_provider_errors() -> None:
    gateway = ModelGateway([FakeProviderAdapter(fail=True)])
    result = gateway.invoke(make_request())
    assert result.response is None
    assert result.record.classification == "provider_error"


def test_gateway_classifies_missing_provider_as_no_provider() -> None:
    gateway = ModelGateway(
        [FakeProviderAdapter(capabilities=["text_generation"])]
    )
    result = gateway.invoke(
        make_request(required_capabilities=["vision"])
    )
    assert result.response is None
    assert result.record.classification == "no_provider"
    assert result.record.status == "rejected"


def test_gateway_sink_receives_every_terminal_record() -> None:
    from alphabrief_models import ModelCallBudget, ModelCallRecord

    sunk: list[tuple[str, str]] = []

    def sink(record: ModelCallRecord) -> None:
        sunk.append((record.request_id, record.classification or ""))

    gateway = ModelGateway(
        [FakeProviderAdapter(capabilities=["text_generation"])],
        budget=ModelCallBudget(max_calls_per_request=1),
        record_sink=sink,
    )
    gateway.invoke(make_request())
    gateway.invoke(make_request())

    assert sunk == [("request_1", "success"), ("request_1", "budget_exhausted")]


def test_gateway_sink_receives_failure_records() -> None:
    sunk: list[str] = []
    gateway = ModelGateway(
        [FakeProviderAdapter(fail=True)],
        record_sink=lambda record: sunk.append(record.classification or ""),
    )
    gateway.invoke(make_request())
    assert sunk == ["provider_error"]
