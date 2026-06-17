"""DuckDB-backed model evaluation store for AlphaBrief.

``ModelEvalStore`` persists ``ModelEvaluation`` records produced by
``ModelEvaluator``. Records include JSON-validity, schema-pass,
hallucination, latency, and cost metrics. Used by ``ModelRouter`` to
select the best model for a given task.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb

from alphabrief_api.db.schema import apply_schema, drop_schema

_DEFAULT_DB_DIR = Path.home() / ".alphabrief" / "data"


def _db_dir() -> Path:
    import os

    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return _DEFAULT_DB_DIR


def _db_path() -> Path:
    db_dir = _db_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "alphabrief.db"


class ModelEvalStore:
    """DuckDB-backed persistent store for model evaluation records.

    Usage::

        store = ModelEvalStore()
        eid = store.save_evaluation(
            model_id="openai:gpt-4o", provider="openai",
            task_type="daily_brief", eval_dataset="daily_brief_v1",
            json_valid_rate=0.95, schema_pass_rate=0.90,
            avg_latency_ms=1200, sample_count=10,
        )
        records = store.get_evaluations(model_id="openai:gpt-4o")
        latest = store.get_latest_evaluation("openai:gpt-4o", "daily_brief")
        store.clear()
        store.close()
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_schema(self._conn)

    def save_evaluation(
        self,
        *,
        model_id: str,
        provider: str,
        task_type: str,
        eval_dataset: str,
        sample_count: int,
        json_valid_rate: float | None = None,
        schema_pass_rate: float | None = None,
        hallucination_rate: float | None = None,
        avg_latency_ms: int | None = None,
        avg_cost_estimate: float | None = None,
        eval_config: dict[str, Any] | None = None,
    ) -> str:
        """Persist a ModelEvaluation record and return its ID."""
        if not model_id or not isinstance(model_id, str):
            raise ValueError("model_id must be a non-empty string")
        if not provider or not isinstance(provider, str):
            raise ValueError("provider must be a non-empty string")
        if not task_type or not isinstance(task_type, str):
            raise ValueError("task_type must be a non-empty string")
        if not eval_dataset or not isinstance(eval_dataset, str):
            raise ValueError("eval_dataset must be a non-empty string")
        if not isinstance(sample_count, int) or sample_count <= 0:
            raise ValueError("sample_count must be a positive integer")
        for name, value in (
            ("json_valid_rate", json_valid_rate),
            ("schema_pass_rate", schema_pass_rate),
            ("hallucination_rate", hallucination_rate),
        ):
            if value is not None and not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be in [0.0, 1.0]")
        if avg_latency_ms is not None and avg_latency_ms < 0:
            raise ValueError("avg_latency_ms must be non-negative")
        if avg_cost_estimate is not None and avg_cost_estimate < 0:
            raise ValueError("avg_cost_estimate must be non-negative")

        eval_id = f"eval_{uuid4().hex[:12]}"
        self._conn.execute(
            """
            INSERT INTO model_evaluations (
                id, model_id, provider, task_type, eval_dataset,
                json_valid_rate, schema_pass_rate, hallucination_rate,
                avg_latency_ms, avg_cost_estimate, sample_count,
                eval_config_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                eval_id,
                model_id,
                provider,
                task_type,
                eval_dataset,
                json_valid_rate,
                schema_pass_rate,
                hallucination_rate,
                avg_latency_ms,
                avg_cost_estimate,
                sample_count,
                json.dumps(eval_config or {}),
            ],
        )
        return eval_id

    def get_evaluations(
        self,
        *,
        model_id: str | None = None,
        task_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return evaluation records ordered by evaluated_at (newest first)."""
        query = (
            "SELECT id, model_id, provider, task_type, eval_dataset, "
            "json_valid_rate, schema_pass_rate, hallucination_rate, "
            "avg_latency_ms, avg_cost_estimate, sample_count, "
            "eval_config_json, evaluated_at FROM model_evaluations"
        )
        params: list[Any] = []
        clauses: list[str] = []
        if model_id is not None:
            clauses.append("model_id = ?")
            params.append(model_id)
        if task_type is not None:
            clauses.append("task_type = ?")
            params.append(task_type)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY evaluated_at DESC"

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_latest_evaluation(
        self,
        model_id: str,
        task_type: str,
    ) -> dict[str, Any] | None:
        """Return the most recent evaluation for a (model, task) pair."""
        row = self._conn.execute(
            """
            SELECT id, model_id, provider, task_type, eval_dataset,
                   json_valid_rate, schema_pass_rate, hallucination_rate,
                   avg_latency_ms, avg_cost_estimate, sample_count,
                   eval_config_json, evaluated_at
            FROM model_evaluations
            WHERE model_id = ? AND task_type = ?
            ORDER BY evaluated_at DESC
            LIMIT 1
            """,
            [model_id, task_type],
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_evaluations(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return all evaluations paginated (newest first)."""
        rows = self._conn.execute(
            """
            SELECT id, model_id, provider, task_type, eval_dataset,
                   json_valid_rate, schema_pass_rate, hallucination_rate,
                   avg_latency_ms, avg_cost_estimate, sample_count,
                   eval_config_json, evaluated_at
            FROM model_evaluations
            ORDER BY evaluated_at DESC
            LIMIT ? OFFSET ?
            """,
            [limit, offset],
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_latest_per_task_for_model(
        self,
        model_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Return the latest evaluation per task_type for a given model."""
        rows = self._conn.execute(
            """
            SELECT id, model_id, provider, task_type, eval_dataset,
                   json_valid_rate, schema_pass_rate, hallucination_rate,
                   avg_latency_ms, avg_cost_estimate, sample_count,
                   eval_config_json, evaluated_at
            FROM model_evaluations
            WHERE model_id = ?
            ORDER BY evaluated_at DESC
            """,
            [model_id],
        ).fetchall()
        latest_per_task: dict[str, dict[str, Any]] = {}
        for row in rows:
            record = self._row_to_dict(row)
            task = record["task_type"]
            if task not in latest_per_task:
                latest_per_task[task] = record
        return latest_per_task

    def _row_to_dict(self, row: tuple[Any, ...]) -> dict[str, Any]:
        config_raw = row[11]
        config: dict[str, Any] = (
            config_raw if isinstance(config_raw, dict) else json.loads(str(config_raw))
        )
        return {
            "id": row[0],
            "model_id": row[1],
            "provider": row[2],
            "task_type": row[3],
            "eval_dataset": row[4],
            "json_valid_rate": row[5],
            "schema_pass_rate": row[6],
            "hallucination_rate": row[7],
            "avg_latency_ms": row[8],
            "avg_cost_estimate": row[9],
            "sample_count": row[10],
            "eval_config": config,
            "evaluated_at": str(row[12]),
        }

    def clear(self) -> None:
        """Drop and recreate all tables (for test isolation)."""
        drop_schema(self._conn)
        apply_schema(self._conn)

    def close(self) -> None:
        """Close the DuckDB connection."""
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["ModelEvalStore"]
