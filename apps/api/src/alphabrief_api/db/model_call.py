"""DuckDB-backed durable model-call record store (M10-W02).

``ModelCallStore`` persists every terminal ``ModelCallRecord`` produced
by ``ModelGateway``: request and response hashes, template version,
provider/model parameters, latency, token counts, cost, retry count,
schema verdict, terminal classification, and correlation IDs
(``request_id``, ``cycle_key``, ``snapshot_id``). Rows are append-only,
UTC stamped, and idempotent by ``call_id`` — re-saving the same call
never duplicates or mutates committed evidence, and the store never
persists raw prompts, responses, tokens, or secrets.

Schema note: ``apps/api/src/alphabrief_api/db/schema.py`` (the versioned
migration ledger) is outside the ``models_research`` scope, so this
store owns an idempotent local DDL (``CREATE TABLE IF NOT EXISTS``).
The table is intentionally compatible with a future storage-scope
migration entry, which can adopt the same name with ``IF NOT EXISTS``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import duckdb
from alphabrief_models.gateway import ModelCallRecord

_DEFAULT_DB_DIR = Path.home() / ".alphabrief" / "data"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS model_call_records (
    call_id         TEXT PRIMARY KEY,
    request_id      TEXT NOT NULL,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    task_type       TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    input_hash      TEXT NOT NULL,
    output_hash     TEXT NOT NULL,
    latency_ms      BIGINT NOT NULL,
    cost_estimate   DECIMAL(38, 18),
    status          TEXT NOT NULL,
    classification  TEXT,
    error_type      TEXT,
    input_tokens    BIGINT,
    output_tokens   BIGINT,
    retry_count     BIGINT NOT NULL DEFAULT 0,
    schema_verdict  TEXT,
    snapshot_id     TEXT,
    cycle_key       TEXT,
    created_at      TIMESTAMPTZ NOT NULL
)
"""

_DROP_TABLE_SQL = "DROP TABLE IF EXISTS model_call_records"

_SELECT_COLUMNS = (
    "call_id, request_id, provider, model, task_type, prompt_version, "
    "input_hash, output_hash, latency_ms, cost_estimate, status, "
    "classification, error_type, input_tokens, output_tokens, retry_count, "
    "schema_verdict, snapshot_id, cycle_key, created_at"
)


def _db_dir() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return _DEFAULT_DB_DIR


def _db_path() -> Path:
    db_dir = _db_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "alphabrief.db"


class ModelCallStore:
    """DuckDB-backed append-only store for ModelGateway call records.

    Usage::

        store = ModelCallStore()
        call_id = store.save_call(record)
        records = store.list_calls_by_cycle("cycle-2026-08-13")
        store.close()
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_CREATE_TABLE_SQL)

    def save_call(self, record: ModelCallRecord) -> str:
        """Persist one terminal call record idempotently and return its ID.

        Saving a record whose ``call_id`` already exists is a no-op that
        returns the existing ID — committed evidence is never duplicated
        or overwritten.
        """
        existing = self._conn.execute(
            "SELECT call_id FROM model_call_records WHERE call_id = ?",
            [record.call_id],
        ).fetchone()
        if existing is not None:
            return str(existing[0])

        cost: str | None = (
            str(record.cost_estimate) if record.cost_estimate is not None else None
        )
        self._conn.execute(
            """
            INSERT INTO model_call_records (
                call_id, request_id, provider, model, task_type,
                prompt_version, input_hash, output_hash, latency_ms,
                cost_estimate, status, classification, error_type,
                input_tokens, output_tokens, retry_count, schema_verdict,
                snapshot_id, cycle_key, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record.call_id,
                record.request_id,
                record.provider,
                record.model,
                record.task_type,
                record.prompt_version,
                record.input_hash,
                record.output_hash,
                record.latency_ms,
                cost,
                record.status,
                record.classification,
                record.error_type,
                record.input_tokens,
                record.output_tokens,
                record.retry_count,
                record.schema_verdict,
                record.snapshot_id,
                record.cycle_key,
                record.created_at,
            ],
        )
        return record.call_id

    def get_call(self, call_id: str) -> dict[str, Any] | None:
        """Return one call record by ID, or ``None``."""
        row = self._conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM model_call_records WHERE call_id = ?",
            [call_id],
        ).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)

    def list_calls(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return all call records paginated (newest first)."""
        rows = self._conn.execute(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM model_call_records
            ORDER BY created_at DESC, call_id DESC
            LIMIT ? OFFSET ?
            """,
            [limit, offset],
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_calls_by_cycle(self, cycle_key: str) -> list[dict[str, Any]]:
        """Return every call record bound to one cycle key (newest first)."""
        rows = self._conn.execute(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM model_call_records
            WHERE cycle_key = ?
            ORDER BY created_at DESC, call_id DESC
            """,
            [cycle_key],
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_calls_by_snapshot(self, snapshot_id: str) -> list[dict[str, Any]]:
        """Return every call record bound to one snapshot ID (newest first)."""
        rows = self._conn.execute(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM model_call_records
            WHERE snapshot_id = ?
            ORDER BY created_at DESC, call_id DESC
            """,
            [snapshot_id],
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def count_calls_since(self, created_at: Any) -> int:
        """Return the number of call records at or after a UTC instant."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM model_call_records WHERE created_at >= ?",
            [created_at],
        ).fetchone()
        return int(row[0]) if row else 0

    def clear(self) -> None:
        """Drop only the model-call table (for test isolation)."""
        self._conn.execute(_DROP_TABLE_SQL)
        self._conn.execute(_CREATE_TABLE_SQL)

    def close(self) -> None:
        """Close the DuckDB connection."""
        try:
            self._conn.close()
        except Exception:
            pass


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "call_id": str(row[0]),
        "request_id": str(row[1]),
        "provider": str(row[2]),
        "model": str(row[3]),
        "task_type": str(row[4]),
        "prompt_version": str(row[5]),
        "input_hash": str(row[6]),
        "output_hash": str(row[7]),
        "latency_ms": int(row[8]),
        "cost_estimate": row[9],
        "status": str(row[10]),
        "classification": row[11],
        "error_type": row[12],
        "input_tokens": row[13],
        "output_tokens": row[14],
        "retry_count": int(row[15]),
        "schema_verdict": row[16],
        "snapshot_id": row[17],
        "cycle_key": row[18],
        "created_at": str(row[19]),
    }


__all__ = ["ModelCallStore"]
