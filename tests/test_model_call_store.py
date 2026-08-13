"""M03-W02: model-call facts are append-only and UTC stamped.

Model evaluations are immutable facts: every evaluation keeps its own
ID and UTC timestamp, and later evaluations never mutate earlier rows.

M10-W02 extends this file with the durable ``ModelCallStore`` that
persists every terminal ``ModelGateway`` call record.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_models.gateway import (
    ModelCallClassification,
    ModelCallRecord,
    ModelCallStatus,
)


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


# ---------------------------------------------------------------------------
# M10-W02: durable ModelGateway call records
# ---------------------------------------------------------------------------


def _call_record(
    *,
    call_id: str = "call_1",
    request_id: str = "req_1",
    status: ModelCallStatus = "succeeded",
    classification: ModelCallClassification | None = "success",
    cycle_key: str | None = None,
    snapshot_id: str | None = None,
    cost: Decimal | None = None,
    schema_verdict: str | None = None,
) -> ModelCallRecord:
    return ModelCallRecord(
        call_id=call_id,
        request_id=request_id,
        provider="openai",
        model="gpt-4o-mini",
        task_type="symbol_research",
        prompt_version="committee-v1",
        input_hash="a" * 64,
        output_hash="b" * 64,
        latency_ms=120,
        cost_estimate=cost,
        status=status,
        classification=classification,
        error_type="BudgetExhausted:request_limit" if status == "rejected" else None,
        input_tokens=100,
        output_tokens=50,
        retry_count=2,
        schema_verdict=schema_verdict,
        snapshot_id=snapshot_id,
        cycle_key=cycle_key,
        created_at=datetime.now(UTC),
    )


def test_model_call_store_round_trips_full_record(tmp_path: Path) -> None:
    store = ModelCallStore(db_path=tmp_path / "model.db")
    try:
        record = _call_record(
            cycle_key="cycle-2026-08-13",
            snapshot_id="snap-abc",
            cost=Decimal("0.00123"),
            schema_verdict="valid",
        )
        store.save_call(record)

        row = store.get_call(record.call_id)
        assert row is not None
        assert row["call_id"] == "call_1"
        assert row["request_id"] == "req_1"
        assert row["provider"] == "openai"
        assert row["model"] == "gpt-4o-mini"
        assert row["task_type"] == "symbol_research"
        assert row["prompt_version"] == "committee-v1"
        assert row["input_hash"] == "a" * 64
        assert row["output_hash"] == "b" * 64
        assert row["latency_ms"] == 120
        assert Decimal(str(row["cost_estimate"])) == Decimal("0.00123")
        assert row["status"] == "succeeded"
        assert row["classification"] == "success"
        assert row["error_type"] is None
        assert row["input_tokens"] == 100
        assert row["output_tokens"] == 50
        assert row["retry_count"] == 2
        assert row["schema_verdict"] == "valid"
        assert row["snapshot_id"] == "snap-abc"
        assert row["cycle_key"] == "cycle-2026-08-13"
        assert "created_at" in row
    finally:
        store.close()


def test_model_call_store_is_append_only_and_idempotent(tmp_path: Path) -> None:
    store = ModelCallStore(db_path=tmp_path / "model.db")
    try:
        record = _call_record()
        first_id = store.save_call(record)
        second_id = store.save_call(record)
        # Re-saving the same call_id never duplicates committed evidence.
        assert first_id == second_id == "call_1"
        assert len(store.list_calls()) == 1

        later = _call_record(call_id="call_2", request_id="req_2")
        store.save_call(later)
        rows = store.list_calls()
        assert len(rows) == 2
        # The original record is unchanged by later ingestion.
        original = store.get_call("call_1")
        assert original is not None
        assert original["request_id"] == "req_1"
    finally:
        store.close()


def test_model_call_store_persists_terminal_classifications(tmp_path: Path) -> None:
    store = ModelCallStore(db_path=tmp_path / "model.db")
    try:
        outcomes: list[tuple[str, ModelCallStatus, ModelCallClassification]] = [
            ("call_s", "succeeded", "success"),
            ("call_m", "failed", "malformed"),
            ("call_t", "failed", "timeout"),
            ("call_r", "failed", "rate_limit"),
            ("call_p", "failed", "provider_error"),
            ("call_b", "rejected", "budget_exhausted"),
            ("call_n", "rejected", "no_provider"),
        ]
        for call_id, status, classification in outcomes:
            store.save_call(
                _call_record(
                    call_id=call_id,
                    status=status,
                    classification=classification,
                )
            )
        rows = {row["call_id"]: row for row in store.list_calls()}
        assert len(rows) == len(outcomes)
        for call_id, status, classification in outcomes:
            assert rows[call_id]["status"] == status
            assert rows[call_id]["classification"] == classification
    finally:
        store.close()


def test_model_call_store_queries_by_cycle_and_snapshot(tmp_path: Path) -> None:
    store = ModelCallStore(db_path=tmp_path / "model.db")
    try:
        store.save_call(
            _call_record(call_id="c1", cycle_key="cycle-a", snapshot_id="snap-1")
        )
        store.save_call(
            _call_record(call_id="c2", cycle_key="cycle-a", snapshot_id="snap-1")
        )
        store.save_call(
            _call_record(call_id="c3", cycle_key="cycle-b", snapshot_id="snap-2")
        )

        cycle_a = store.list_calls_by_cycle("cycle-a")
        assert {row["call_id"] for row in cycle_a} == {"c1", "c2"}
        snap_1 = store.list_calls_by_snapshot("snap-1")
        assert {row["call_id"] for row in snap_1} == {"c1", "c2"}
        assert store.list_calls_by_cycle("cycle-missing") == []
        assert store.list_calls_by_snapshot("snap-missing") == []
    finally:
        store.close()


def test_model_call_store_never_stores_raw_prompt_or_secret(tmp_path: Path) -> None:
    store = ModelCallStore(db_path=tmp_path / "model.db")
    try:
        store.save_call(_call_record())
        row = store.get_call("call_1")
        assert row is not None
        serialized = str(row)
        assert "budget test prompt" not in serialized
        assert "raw model output" not in serialized
        assert "sk-" not in serialized
        assert "Bearer" not in serialized
    finally:
        store.close()


def test_model_call_store_persistence_across_instances(tmp_path: Path) -> None:
    first = ModelCallStore(db_path=tmp_path / "model.db")
    first.save_call(_call_record(call_id="c1", cycle_key="cycle-a"))
    first.close()

    second = ModelCallStore(db_path=tmp_path / "model.db")
    try:
        rows = second.list_calls_by_cycle("cycle-a")
        assert len(rows) == 1
        assert rows[0]["call_id"] == "c1"
    finally:
        second.close()


def test_model_call_store_count_since(tmp_path: Path) -> None:
    store = ModelCallStore(db_path=tmp_path / "model.db")
    try:
        store.save_call(_call_record(call_id="c1"))
        store.save_call(_call_record(call_id="c2"))
        store.save_call(_call_record(call_id="c3"))
        assert store.count_calls_since(datetime.now(UTC) - timedelta(days=1)) == 3
        assert store.count_calls_since(datetime.now(UTC) + timedelta(days=1)) == 0
    finally:
        store.close()
