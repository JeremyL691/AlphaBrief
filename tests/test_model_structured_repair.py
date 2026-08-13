"""M10-W05: bounded structured-output repair.

Covers AC-M10-W05-01/02 at the repair layer: invalid JSON, schema
violations, and nonexistent citations trigger no more than the
configured repair attempts; every attempt records a typed verdict with
its model-call ID; exhausted repair is a terminal failure that must
resolve to blocked or no-trade.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from alphabrief_models import (
    FakeProviderAdapter,
    ModelGateway,
    ModelRequest,
    ModelResponse,
    repair_structured_output,
)
from alphabrief_models.repair import RepairVerdict
from pydantic import BaseModel, ConfigDict, Field

_NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


class _Vote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: str = Field(min_length=1)
    view: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


def _request() -> ModelRequest:
    return ModelRequest(
        request_id="repair_req_1",
        task_type="symbol_research",
        prompt_version="test-v1",
        input_text="original task",
        required_capabilities=["structured_output"],
    )


class _SequencedProvider(FakeProviderAdapter):
    """Returns one canned output per call, in order."""

    def __init__(self, outputs: list[dict[str, object] | None]) -> None:
        super().__init__(
            provider_name="fake",
            model_name="fake-1",
            capabilities=["structured_output"],
        )
        self._outputs = list(outputs)
        self.calls = 0

    def call(self, request: ModelRequest) -> ModelResponse:
        output = self._outputs[min(self.calls, len(self._outputs) - 1)]
        self.calls += 1
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self.model_name,
            output_text="{}",
            structured_output=output,
            status="succeeded",
            finish_reason="stop",
        )


def _gateway(provider: _SequencedProvider) -> ModelGateway:
    return ModelGateway(providers=[provider])


class TestRepairAttempts:
    def test_invalid_json_repairs_to_valid_output(self) -> None:
        provider = _SequencedProvider(
            [
                None,  # first repair call returns unparseable output
                {
                    "analysis": "fixed",
                    "view": "bullish",
                    "confidence": 0.6,
                    "evidence": [],
                },
            ]
        )
        result = repair_structured_output(
            gateway=_gateway(provider),
            request=_request(),
            target=_Vote,
            raw_output="{not json",
            failure_reason="schema_validation_failed:invalid_json",
            max_attempts=2,
            clock=lambda: _NOW,
        )
        assert result.ok is True
        assert result.exhausted is False
        assert result.parsed is not None
        assert cast(_Vote, result.parsed).analysis == "fixed"
        assert len(result.attempts) == 2
        assert result.attempts[0].ok is False
        assert result.attempts[0].error_code is not None
        assert result.attempts[1].ok is True
        assert all(attempt.model_call_id for attempt in result.attempts)
        assert all(attempt.created_at == _NOW for attempt in result.attempts)

    def test_schema_violation_repairs(self) -> None:
        provider = _SequencedProvider(
            [
                {"analysis": "", "view": "bullish", "confidence": 0.5},
                {
                    "analysis": "valid now",
                    "view": "bullish",
                    "confidence": 0.5,
                    "evidence": [],
                },
            ]
        )
        result = repair_structured_output(
            gateway=_gateway(provider),
            request=_request(),
            target=_Vote,
            raw_output="{}",
            failure_reason="schema_validation_failed:schema_validation_failed",
            max_attempts=2,
            clock=lambda: _NOW,
        )
        assert result.ok is True
        assert result.attempts[0].ok is False
        assert "schema_validation_failed" in (result.attempts[0].error_code or "")

    def test_grounding_violation_repairs(self) -> None:
        provider = _SequencedProvider(
            [
                {
                    "analysis": "ok",
                    "view": "bullish",
                    "confidence": 0.5,
                    "evidence": ["ev-fake-99: invented"],
                },
                {
                    "analysis": "ok",
                    "view": "bullish",
                    "confidence": 0.5,
                    "evidence": ["ev-real-1: actual"],
                },
            ]
        )

        def grounding_check(parsed: _Vote) -> list[str]:
            violations = []
            for entry in parsed.evidence:
                token = entry.split(":")[0].strip()
                if token not in {"ev-real-1"}:
                    violations.append(f"nonexistent_citation:{token}")
            return violations

        result = repair_structured_output(
            gateway=_gateway(provider),
            request=_request(),
            target=_Vote,
            raw_output="{}",
            failure_reason="grounding_failed:nonexistent_citation:ev-fake-99",
            max_attempts=2,
            grounding_check=grounding_check,
            clock=lambda: _NOW,
        )
        assert result.ok is True
        assert result.attempts[0].ok is False
        assert "grounding_failed" in (result.attempts[0].error_code or "")
        assert result.attempts[1].ok is True

    def test_repair_is_bounded_to_max_attempts(self) -> None:
        provider = _SequencedProvider([{"bogus": "field"}])
        result = repair_structured_output(
            gateway=_gateway(provider),
            request=_request(),
            target=_Vote,
            raw_output="{}",
            failure_reason="schema_validation_failed:invalid_json",
            max_attempts=3,
            clock=lambda: _NOW,
        )
        assert result.ok is False
        assert result.exhausted is True
        assert len(result.attempts) == 3
        assert provider.calls == 3
        assert all(not attempt.ok for attempt in result.attempts)

    def test_provider_failure_attempts_recorded(self) -> None:
        provider = FakeProviderAdapter(
            provider_name="fake",
            model_name="fake-1",
            capabilities=["structured_output"],
            fail=True,
        )
        result = repair_structured_output(
            gateway=ModelGateway(providers=[provider]),
            request=_request(),
            target=_Vote,
            raw_output="{}",
            failure_reason="schema_validation_failed:invalid_json",
            max_attempts=2,
            clock=lambda: _NOW,
        )
        assert result.ok is False
        assert result.exhausted is True
        assert [a.error_code for a in result.attempts] == [
            "provider_call_failed",
            "provider_call_failed",
        ]

    def test_max_attempts_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            repair_structured_output(
                gateway=_gateway(_SequencedProvider([None])),
                request=_request(),
                target=_Vote,
                raw_output="{}",
                failure_reason="x",
                max_attempts=0,
            )

    def test_repair_verdicts_are_typed_and_strict(self) -> None:
        verdict = RepairVerdict(
            attempt=1, ok=True, model_call_id="call_1", created_at=_NOW
        )
        assert verdict.attempt == 1
        assert verdict.ok is True
        with pytest.raises(ValueError):
            RepairVerdict(attempt=0, ok=True, created_at=_NOW)
        with pytest.raises(ValueError):
            cast(Any, RepairVerdict)(
                attempt=1, ok=True, created_at=_NOW, extra="x"
            )

    def test_repair_prompt_includes_previous_output_and_reason(self) -> None:
        from alphabrief_models.repair import default_repair_prompt_builder

        prompt = default_repair_prompt_builder(
            _request(), "bad raw output", "schema_validation_failed:invalid_json"
        )
        assert "bad raw output" in prompt
        assert "schema_validation_failed:invalid_json" in prompt
        assert "original task" in prompt
