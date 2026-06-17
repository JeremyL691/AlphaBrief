"""Tests for ModelEvaluator (Phase 14 Round 2)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from alphabrief_models import (
    BUNDLED_DATASET_SPECS,
    BUNDLED_DATASETS,
    EvalDataset,
    ModelEvaluation,
    ModelEvaluator,
    ModelGateway,
    ModelRequest,
    ModelResponse,
    get_dataset_by_id,
)
from alphabrief_models.gateway import (
    ModelCapability,
    ModelProviderError,
)


class _RotatingProvider:
    """Test provider that returns a different output per call."""

    def __init__(
        self,
        *,
        outputs: Sequence[str] | None = None,
        structured_outputs: Sequence[dict[str, object]] | None = None,
        fail: bool = False,
        provider_name: str = "fake",
        model_name: str = "fake-model",
        capabilities: Sequence[ModelCapability] = (
            "text_generation",
            "structured_output",
            "json_mode",
        ),
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.capabilities: frozenset[ModelCapability] = frozenset(capabilities)
        self._outputs = list(outputs or [])
        self._structured = list(structured_outputs or [])
        self._index = 0
        self._fail = fail

    def call(self, request: ModelRequest) -> ModelResponse:
        if self._fail:
            raise ModelProviderError("rotating provider failure")
        idx = min(self._index, len(self._outputs) - 1) if self._outputs else 0
        sidx = min(self._index, len(self._structured) - 1) if self._structured else 0
        self._index += 1
        text = self._outputs[idx] if self._outputs else "{}"
        struct = self._structured[sidx] if self._structured else None
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self.model_name,
            output_text=text,
            structured_output=struct,
            status="succeeded",
            finish_reason="stop",
        )


def _gateway_with(
    *,
    outputs: list[str] | None = None,
    structured_outputs: list[dict[str, object]] | None = None,
    fail: bool = False,
) -> ModelGateway:
    return ModelGateway(
        [
            _RotatingProvider(
                outputs=outputs,
                structured_outputs=structured_outputs,
                fail=fail,
            )
        ]
    )


# ---------------------------------------------------------------------------
# JSON validity
# ---------------------------------------------------------------------------


def test_evaluate_json_validity_all_valid() -> None:
    gateway = _gateway_with(
        outputs=['{"a": 1}', '{"b": 2}', '{"c": 3}'],
    )
    ev = ModelEvaluator(gateway)
    result = ev.evaluate_json_validity(
        model_id="fake:fake-model",
        task_type="test",
        prompts=["p1", "p2", "p3"],
        sample_count=3,
    )
    assert result.json_valid_rate == 1.0
    assert result.sample_count == 3
    assert result.failed_calls == 0


def test_evaluate_json_validity_mixed() -> None:
    gateway = _gateway_with(outputs=['{"a": 1}', "not json", '{"c": 3}'])
    ev = ModelEvaluator(gateway)
    result = ev.evaluate_json_validity(
        model_id="fake:fake-model",
        task_type="test",
        prompts=["p1", "p2", "p3"],
        sample_count=3,
    )
    assert result.json_valid_rate == pytest.approx(2 / 3)


def test_evaluate_json_validity_handles_provider_failure() -> None:
    gateway = _gateway_with(fail=True)
    ev = ModelEvaluator(gateway)
    result = ev.evaluate_json_validity(
        model_id="fake:fake-model",
        task_type="test",
        prompts=["p1", "p2"],
        sample_count=2,
    )
    assert result.json_valid_rate == 0.0
    assert result.failed_calls == 2


def test_evaluate_json_validity_rejects_empty_prompts() -> None:
    ev = ModelEvaluator(_gateway_with())
    with pytest.raises(ValueError, match="prompts"):
        ev.evaluate_json_validity(
            model_id="fake:fake-model",
            task_type="test",
            prompts=[],
        )


# ---------------------------------------------------------------------------
# Schema pass
# ---------------------------------------------------------------------------


def test_evaluate_schema_pass_all_match() -> None:
    schema = {
        "type": "object",
        "required": ["brief_id", "summary"],
        "properties": {
            "brief_id": {"type": "string"},
            "summary": {"type": "string"},
        },
    }
    gateway = _gateway_with(
        outputs=[],
        structured_outputs=[
            {"brief_id": "b1", "summary": "ok"},
            {"brief_id": "b2", "summary": "fine"},
        ],
    )
    ev = ModelEvaluator(gateway)
    result = ev.evaluate_schema_pass(
        model_id="fake:fake-model",
        task_type="test",
        schema=schema,
        prompts=["p1", "p2"],
        sample_count=2,
    )
    assert result.schema_pass_rate == 1.0


def test_evaluate_schema_pass_rejects_missing_fields() -> None:
    schema = {
        "type": "object",
        "required": ["brief_id", "summary"],
        "properties": {
            "brief_id": {"type": "string"},
            "summary": {"type": "string"},
        },
    }
    gateway = _gateway_with(
        outputs=[],
        structured_outputs=[
            {"brief_id": "b1"},
        ],
    )
    ev = ModelEvaluator(gateway)
    result = ev.evaluate_schema_pass(
        model_id="fake:fake-model",
        task_type="test",
        schema=schema,
        prompts=["p1"],
        sample_count=1,
    )
    assert result.schema_pass_rate == 0.0


def test_evaluate_schema_pass_rejects_invalid_schema() -> None:
    ev = ModelEvaluator(_gateway_with())
    with pytest.raises(ValueError, match="schema"):
        ev.evaluate_schema_pass(
            model_id="fake:fake-model",
            task_type="test",
            schema="not a dict",  # type: ignore[arg-type]
            prompts=["p1"],
        )


# ---------------------------------------------------------------------------
# Hallucination
# ---------------------------------------------------------------------------


def test_evaluate_hallucination_zero_when_response_contains_answer() -> None:
    gateway = _gateway_with(
        outputs=["Bitcoin ticker is BTC", "Ethereum ticker is ETH"],
    )
    ev = ModelEvaluator(gateway)
    result = ev.evaluate_hallucination(
        model_id="fake:fake-model",
        task_type="symbol_research",
        knowledge_pairs=[
            ("What is the BTC ticker?", "BTC"),
            ("What is the ETH ticker?", "ETH"),
        ],
        sample_count=2,
    )
    assert result.hallucination_rate == 0.0


def test_evaluate_hallucination_detects_negation_contradiction() -> None:
    gateway = _gateway_with(
        outputs=["The price is below the 200-day MA."],
    )
    ev = ModelEvaluator(gateway)
    result = ev.evaluate_hallucination(
        model_id="fake:fake-model",
        task_type="symbol_research",
        knowledge_pairs=[
            ("Is the market above or below the 200-day MA?", "above"),
        ],
        sample_count=1,
    )
    assert result.hallucination_rate == 1.0


def test_evaluate_hallucination_rejects_empty_pairs() -> None:
    ev = ModelEvaluator(_gateway_with())
    with pytest.raises(ValueError, match="knowledge_pairs"):
        ev.evaluate_hallucination(
            model_id="fake:fake-model",
            task_type="symbol_research",
            knowledge_pairs=[],
        )


# ---------------------------------------------------------------------------
# Sample count clamping
# ---------------------------------------------------------------------------


def test_sample_count_clamped_to_max() -> None:
    gateway = _gateway_with(outputs=['{"a": 1}'] * 100)
    ev = ModelEvaluator(gateway)
    result = ev.evaluate_json_validity(
        model_id="fake:fake-model",
        task_type="test",
        prompts=["p"] * 100,
        sample_count=999,
    )
    from alphabrief_models.evaluation import MAX_SAMPLE_COUNT

    assert result.sample_count == MAX_SAMPLE_COUNT


def test_sample_count_must_be_positive() -> None:
    ev = ModelEvaluator(_gateway_with())
    with pytest.raises(ValueError, match="sample_count"):
        ev.evaluate_json_validity(
            model_id="fake:fake-model",
            task_type="test",
            prompts=["p"],
            sample_count=0,
        )


# ---------------------------------------------------------------------------
# model_id parsing
# ---------------------------------------------------------------------------


def test_evaluator_rejects_blank_model_id() -> None:
    ev = ModelEvaluator(_gateway_with())
    with pytest.raises(ValueError, match="model_id"):
        ev.evaluate_json_validity(
            model_id="",
            task_type="test",
            prompts=["p"],
        )


def test_evaluator_accepts_single_segment_model_id() -> None:
    """A model_id without ':' uses 'unknown' as the provider."""
    gateway = _gateway_with(outputs=['{"a": 1}'])
    ev = ModelEvaluator(gateway)
    result = ev.evaluate_json_validity(
        model_id="custom-model",
        task_type="test",
        prompts=["p"],
        sample_count=1,
    )
    assert result.provider == "unknown"
    assert result.model_id == "unknown:custom-model"


# ---------------------------------------------------------------------------
# Bundled datasets
# ---------------------------------------------------------------------------


def test_bundled_datasets_are_non_empty() -> None:
    assert len(BUNDLED_DATASETS) >= 3
    assert len(BUNDLED_DATASET_SPECS) >= 3
    for ds in BUNDLED_DATASETS:
        assert ds.dataset_id
        assert ds.task_type


def test_get_dataset_by_id_returns_known_dataset() -> None:
    ds = get_dataset_by_id("daily_brief_v1")
    assert isinstance(ds, EvalDataset)
    assert ds.dataset_id == "daily_brief_v1"


def test_get_dataset_by_id_raises_for_unknown() -> None:
    with pytest.raises(KeyError):
        get_dataset_by_id("nonexistent_v999")


# ---------------------------------------------------------------------------
# Full dataset run
# ---------------------------------------------------------------------------


def test_run_dataset_combines_results() -> None:
    gateway = _gateway_with(
        outputs=[
            '{"brief_id": "b1", "summary": "ok"}',
            "Bitcoin is BTC",
            '{"brief_id": "b2", "summary": "fine"}',
        ],
        structured_outputs=[
            {"brief_id": "b1", "summary": "ok"},
        ],
    )
    ev = ModelEvaluator(gateway)
    dataset = get_dataset_by_id("daily_brief_v1")
    result = ev.run_dataset(
        model_id="fake:fake-model", dataset=dataset, sample_count=3
    )
    assert isinstance(result, ModelEvaluation)
    assert result.sample_count == 3
    assert result.json_valid_rate is not None
    assert "json_validity" in result.notes


# ---------------------------------------------------------------------------
# ModelCallRecord creation
# ---------------------------------------------------------------------------


def test_each_call_creates_a_call_record() -> None:
    gateway = _gateway_with(outputs=['{"a": 1}', '{"b": 2}'])
    ev = ModelEvaluator(gateway)
    ev.evaluate_json_validity(
        model_id="fake:fake-model",
        task_type="test",
        prompts=["p1", "p2"],
        sample_count=2,
    )
    assert len(gateway.call_records) == 2
    assert all(r.task_type == "test" for r in gateway.call_records)


def test_failed_call_creates_failed_record() -> None:
    gateway = _gateway_with(fail=True)
    ev = ModelEvaluator(gateway)
    ev.evaluate_json_validity(
        model_id="fake:fake-model",
        task_type="test",
        prompts=["p1"],
        sample_count=1,
    )
    assert len(gateway.call_records) == 1
    assert gateway.call_records[0].status == "failed"
    assert gateway.call_records[0].error_type == "ModelProviderError"
