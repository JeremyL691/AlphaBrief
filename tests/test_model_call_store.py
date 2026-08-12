"""M03-W02: model-call facts are append-only and UTC stamped.

Model evaluations are immutable facts: every evaluation keeps its own
ID and UTC timestamp, and later evaluations never mutate earlier rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _evaluation() -> dict[str, Any]:
    return {
        "model_id": "kronos",
        "provider": "test",
        "task_type": "forecast",
        "eval_dataset": "fx-eur",
        "sample_count": 10,
        "json_valid_rate": 1.0,
        "schema_pass_rate": 1.0,
        "hallucination_rate": 0.0,
        "avg_latency_ms": 12,
        "avg_cost_estimate": 0.001,
        "eval_config": {"seed": 7},
    }


def test_model_evaluations_are_append_only(tmp_path: Path) -> None:
    """Each evaluation is a distinct immutable fact."""
    from alphabrief_api.db.model_eval import ModelEvalStore

    store = ModelEvalStore(db_path=tmp_path / "model.db")
    try:
        first_id = store.save_evaluation(**_evaluation())
        second_id = store.save_evaluation(**_evaluation())

        assert first_id != second_id
        first = store.get_latest_evaluation(model_id="kronos", task_type="forecast")
        assert first is not None
        assert first["id"] == second_id

        rows = store.get_evaluations(model_id="kronos")
        assert len(rows) == 2
        assert {row["id"] for row in rows} == {first_id, second_id}
        for row in rows:
            assert "evaluated_at" in row
    finally:
        store.close()


def test_evaluation_rows_keep_utc_timestamps(tmp_path: Path) -> None:
    from alphabrief_api.db.model_eval import ModelEvalStore

    store = ModelEvalStore(db_path=tmp_path / "model.db")
    try:
        store.save_evaluation(**_evaluation())
        row = store.get_evaluations(model_id="kronos")[0]
        assert "evaluated_at" in row
    finally:
        store.close()
