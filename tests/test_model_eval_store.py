"""Tests for the DuckDB-backed ModelEvalStore (Phase 14 Round 1)."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.db.model_eval import ModelEvalStore


@pytest.fixture()
def store(tmp_path: Path) -> Generator[ModelEvalStore, None, None]:
    db_path = tmp_path / "test.db"
    s = ModelEvalStore(db_path=db_path)
    yield s
    s.close()

def test_save_and_get_evaluation(store: ModelEvalStore) -> None:
    eid = store.save_evaluation(
        model_id="openai:gpt-4o",
        provider="openai",
        task_type="daily_brief",
        eval_dataset="daily_brief_v1",
        json_valid_rate=0.95,
        schema_pass_rate=0.90,
        avg_latency_ms=1200,
        sample_count=10,
    )
    assert eid.startswith("eval_")
    records = store.get_evaluations(model_id="openai:gpt-4o")
    assert len(records) == 1
    rec = records[0]
    assert rec["model_id"] == "openai:gpt-4o"
    assert rec["provider"] == "openai"
    assert rec["task_type"] == "daily_brief"
    assert rec["json_valid_rate"] == 0.95
    assert rec["schema_pass_rate"] == 0.90
    assert rec["hallucination_rate"] is None
    assert rec["avg_latency_ms"] == 1200
    assert rec["avg_cost_estimate"] is None
    assert rec["sample_count"] == 10
    assert rec["eval_config"] == {}


def test_save_evaluation_with_all_fields(store: ModelEvalStore) -> None:
    eid = store.save_evaluation(
        model_id="anthropic:claude-3",
        provider="anthropic",
        task_type="market_summary",
        eval_dataset="market_summary_v1",
        json_valid_rate=0.85,
        schema_pass_rate=0.80,
        hallucination_rate=0.05,
        avg_latency_ms=850,
        avg_cost_estimate=0.003,
        sample_count=20,
        eval_config={"temperature": 0.0, "max_tokens": 2048},
    )
    rec = store.get_evaluations(model_id="anthropic:claude-3")[0]
    assert rec["id"] == eid
    assert rec["hallucination_rate"] == 0.05
    assert rec["avg_cost_estimate"] == pytest.approx(0.003)
    assert rec["eval_config"] == {"temperature": 0.0, "max_tokens": 2048}


def test_get_evaluations_filter_by_task_type(store: ModelEvalStore) -> None:
    store.save_evaluation(
        model_id="m1", provider="p1", task_type="market_summary",
        eval_dataset="d1", sample_count=5,
    )
    store.save_evaluation(
        model_id="m1", provider="p1", task_type="daily_brief",
        eval_dataset="d2", sample_count=5,
    )
    recs = store.get_evaluations(task_type="daily_brief")
    assert len(recs) == 1
    assert recs[0]["task_type"] == "daily_brief"


def test_get_latest_evaluation(store: ModelEvalStore) -> None:
    store.save_evaluation(
        model_id="m1", provider="p1", task_type="daily_brief",
        eval_dataset="d1", sample_count=5, schema_pass_rate=0.5,
    )
    store.save_evaluation(
        model_id="m1", provider="p1", task_type="daily_brief",
        eval_dataset="d1", sample_count=5, schema_pass_rate=0.9,
    )
    latest = store.get_latest_evaluation("m1", "daily_brief")
    assert latest is not None
    assert latest["schema_pass_rate"] == 0.9

    none = store.get_latest_evaluation("m1", "missing_task")
    assert none is None


def test_list_evaluations_pagination(store: ModelEvalStore) -> None:
    for i in range(5):
        store.save_evaluation(
            model_id=f"m{i}", provider="p", task_type="t",
            eval_dataset="d", sample_count=1,
        )
    recs = store.list_evaluations(limit=3, offset=0)
    assert len(recs) == 3
    recs2 = store.list_evaluations(limit=3, offset=3)
    assert len(recs2) == 2
    assert recs[0]["id"] != recs2[0]["id"]


def test_get_latest_per_task_for_model(store: ModelEvalStore) -> None:
    store.save_evaluation(
        model_id="m1", provider="p", task_type="task_a",
        eval_dataset="d", sample_count=1, schema_pass_rate=0.5,
    )
    store.save_evaluation(
        model_id="m1", provider="p", task_type="task_a",
        eval_dataset="d", sample_count=1, schema_pass_rate=0.9,
    )
    store.save_evaluation(
        model_id="m1", provider="p", task_type="task_b",
        eval_dataset="d", sample_count=1, schema_pass_rate=0.7,
    )
    per_task = store.get_latest_per_task_for_model("m1")
    assert "task_a" in per_task
    assert "task_b" in per_task
    assert per_task["task_a"]["schema_pass_rate"] == 0.9
    assert per_task["task_b"]["schema_pass_rate"] == 0.7


def test_save_evaluation_rejects_invalid_rates(store: ModelEvalStore) -> None:
    with pytest.raises(ValueError, match="json_valid_rate"):
        store.save_evaluation(
            model_id="m", provider="p", task_type="t",
            eval_dataset="d", sample_count=1, json_valid_rate=1.5,
        )
    with pytest.raises(ValueError, match="schema_pass_rate"):
        store.save_evaluation(
            model_id="m", provider="p", task_type="t",
            eval_dataset="d", sample_count=1, schema_pass_rate=-0.1,
        )
    with pytest.raises(ValueError, match="hallucination_rate"):
        store.save_evaluation(
            model_id="m", provider="p", task_type="t",
            eval_dataset="d", sample_count=1, hallucination_rate=2.0,
        )


def test_save_evaluation_rejects_invalid_sample_count(store: ModelEvalStore) -> None:
    with pytest.raises(ValueError, match="sample_count"):
        store.save_evaluation(
            model_id="m", provider="p", task_type="t",
            eval_dataset="d", sample_count=0,
        )
    with pytest.raises(ValueError, match="sample_count"):
        store.save_evaluation(
            model_id="m", provider="p", task_type="t",
            eval_dataset="d", sample_count=-1,
        )


def test_save_evaluation_rejects_blank_strings(store: ModelEvalStore) -> None:
    with pytest.raises(ValueError, match="model_id"):
        store.save_evaluation(
            model_id="", provider="p", task_type="t",
            eval_dataset="d", sample_count=1,
        )
    with pytest.raises(ValueError, match="provider"):
        store.save_evaluation(
            model_id="m", provider="", task_type="t",
            eval_dataset="d", sample_count=1,
        )
    with pytest.raises(ValueError, match="task_type"):
        store.save_evaluation(
            model_id="m", provider="p", task_type="",
            eval_dataset="d", sample_count=1,
        )
    with pytest.raises(ValueError, match="eval_dataset"):
        store.save_evaluation(
            model_id="m", provider="p", task_type="t",
            eval_dataset="", sample_count=1,
        )


def test_save_evaluation_rejects_negative_latency_or_cost(
    store: ModelEvalStore,
) -> None:
    with pytest.raises(ValueError, match="avg_latency_ms"):
        store.save_evaluation(
            model_id="m", provider="p", task_type="t",
            eval_dataset="d", sample_count=1, avg_latency_ms=-1,
        )
    with pytest.raises(ValueError, match="avg_cost_estimate"):
        store.save_evaluation(
            model_id="m", provider="p", task_type="t",
            eval_dataset="d", sample_count=1, avg_cost_estimate=-0.1,
        )


def test_clear_removes_all_records(store: ModelEvalStore) -> None:
    store.save_evaluation(
        model_id="m1", provider="p", task_type="t",
        eval_dataset="d", sample_count=1,
    )
    assert len(store.get_evaluations()) == 1
    store.clear()
    assert len(store.get_evaluations()) == 0


def test_persistence_across_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "persist.db"
    s1 = ModelEvalStore(db_path=db_path)
    s1.save_evaluation(
        model_id="m1", provider="p", task_type="t",
        eval_dataset="d", sample_count=1, schema_pass_rate=0.8,
    )
    s1.close()

    s2 = ModelEvalStore(db_path=db_path)
    recs = s2.get_evaluations()
    assert len(recs) == 1
    assert recs[0]["schema_pass_rate"] == 0.8
    s2.close()


def test_get_evaluations_empty_returns_empty_list(store: ModelEvalStore) -> None:
    assert store.get_evaluations() == []
    assert store.get_evaluations(model_id="nonexistent") == []


def test_eval_config_serialized_as_json(store: ModelEvalStore) -> None:
    cfg = {"strategy": "balanced", "attempts": 3}
    store.save_evaluation(
        model_id="m", provider="p", task_type="t",
        eval_dataset="d", sample_count=1, eval_config=cfg,
    )
    raw = store._conn.execute(  # noqa: SLF001 - test inspect
        "SELECT eval_config_json FROM model_evaluations"
    ).fetchone()
    assert raw is not None
    parsed = json.loads(raw[0])
    assert parsed == cfg
