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

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Any

import duckdb
from alphabrief_core import paths as _paths
from alphabrief_models.gateway import ModelCallRecord
from alphabrief_models.model_budget import (
    MAX_COMMITTEE_NORMAL_CALLS,
    MAX_COMMITTEE_REPAIR_CALLS,
    MAX_ROUND_CALLS,
    NO_TRADE_MODEL_BUDGET,
    NO_TRADE_MODEL_UNAVAILABLE,
    BudgetVerdict,
    ChannelUsage,
    ModelCallKind,
)

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

# PROJECT_GUIDE 5.13: a channel that answered with a rate limit or a quota
# error is disabled for the rest of the UTC day. The state is durable so a
# restart cannot re-enable a channel that already said no.
_CREATE_CHANNEL_STATE_SQL = """
CREATE TABLE IF NOT EXISTS model_channel_day_state (
    channel    TEXT NOT NULL,
    day        TEXT NOT NULL,
    reason     TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (channel, day)
)
"""

_DROP_CHANNEL_STATE_SQL = "DROP TABLE IF EXISTS model_channel_day_state"

_SELECT_COLUMNS = (
    "call_id, request_id, provider, model, task_type, prompt_version, "
    "input_hash, output_hash, latency_ms, cost_estimate, status, "
    "classification, error_type, input_tokens, output_tokens, retry_count, "
    "schema_verdict, snapshot_id, cycle_key, created_at"
)


class ModelCallStore:
    """DuckDB-backed append-only store for ModelGateway call records.

    Usage::

        store = ModelCallStore()
        call_id = store.save_call(record)
        records = store.list_calls_by_cycle("cycle-2026-08-13")
        store.close()
    """

    def __init__(
        self, db_path: Path | str | None = None, *, read_only: bool = False
    ) -> None:
        if db_path is None:
            db_path = _paths.db_path()
        self._db_path = Path(db_path)
        self._lock = RLock()
        self._conn = duckdb.connect(str(self._db_path), read_only=read_only)
        if not read_only:
            self._conn.execute(_CREATE_TABLE_SQL)
            self._conn.execute(_CREATE_CHANNEL_STATE_SQL)
            self._conn.execute("""CREATE TABLE IF NOT EXISTS model_call_reservations (
                call_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL, reserved_cost DECIMAL(38,18))""")
            for column in ("round_key", "symbol", "call_kind"):
                self._conn.execute(
                    "ALTER TABLE model_call_reservations ADD COLUMN IF NOT EXISTS "
                    f"{column} TEXT"
                )
            self._conn.execute("""CREATE TABLE IF NOT EXISTS model_budget_day_mutex (
                channel TEXT NOT NULL, day TEXT NOT NULL, revision BIGINT NOT NULL,
                PRIMARY KEY(channel, day))""")
            self._conn.execute("""CREATE TABLE IF NOT EXISTS model_budget_round_mutex (
                round_key TEXT PRIMARY KEY, revision BIGINT NOT NULL)""")

    def save_call(self, record: ModelCallRecord) -> str:
        with self._lock:
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

    # ------------------------------------------------------------------
    # Daily budget support (PROJECT_GUIDE 5.13)
    # ------------------------------------------------------------------

    def daily_usage(self, since: Any) -> dict[str, ChannelUsage]:
        """Recorded calls and estimated cost per channel since an instant."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT COALESCE(a.provider, r.provider),
                       COUNT(*),
                       COALESCE(SUM(COALESCE(r.cost_estimate, a.reserved_cost)), 0),
                       BOOL_AND(COALESCE(r.cost_estimate, a.reserved_cost) IS NOT NULL)
                FROM model_call_records r FULL OUTER JOIN model_call_reservations a
                  ON r.call_id = a.call_id
                WHERE COALESCE(a.created_at, r.created_at) >= ?
                  AND (a.call_id IS NOT NULL OR r.status != 'rejected')
                GROUP BY COALESCE(a.provider, r.provider)
                """,
                [since],
            ).fetchall()
            return {
                str(provider): ChannelUsage(
                    calls=int(calls),
                    cost=Decimal(str(cost or 0)),
                    cost_known=bool(known),
                )
                for provider, calls, cost, known in rows
            }

    def reserve_call(
        self,
        *,
        channel: str,
        call_id: str,
        observed_at: datetime,
        call_limit: int | None,
        cost_limit: Decimal | None,
        estimated_cost: Decimal | None,
        round_key: str | None = None,
        symbol: str | None = None,
        call_kind: ModelCallKind = "normal",
    ) -> BudgetVerdict:
        """Atomically serialize the day's admissions across store connections."""
        with self._lock:
            if observed_at.tzinfo is None or not channel or not call_id:
                raise ValueError("admission requires channel, identity and UTC time")
            if call_kind not in {"normal", "repair"}:
                raise ValueError("unknown model call kind")
            if round_key is not None and (
                not round_key.strip()
                or round_key != round_key.strip()
                or symbol is None
                or not symbol.strip()
                or symbol != symbol.strip().upper()
            ):
                raise ValueError("round admission requires round identity and symbol")
            if round_key is None and symbol is not None:
                raise ValueError("symbol admission requires round identity")
            if call_kind == "repair" and round_key is None:
                raise ValueError("repair admission requires round identity")
            day = observed_at.astimezone(UTC).date().isoformat()
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    """INSERT INTO model_budget_day_mutex VALUES (?, ?, 1)
                    ON CONFLICT(channel, day) DO UPDATE SET
                    revision = model_budget_day_mutex.revision + 1""",
                    [channel, day],
                )
                if round_key is not None:
                    self._conn.execute(
                        """INSERT INTO model_budget_round_mutex VALUES (?, 1)
                        ON CONFLICT(round_key) DO UPDATE SET
                        revision = model_budget_round_mutex.revision + 1""",
                        [round_key],
                    )
                disabled = self.disabled_channel_reason(channel, day)
                since = observed_at.astimezone(UTC).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                usage = self.daily_usage(since).get(channel, ChannelUsage())
                reason = NO_TRADE_MODEL_BUDGET
                detail = ""
                if disabled is not None:
                    reason = NO_TRADE_MODEL_UNAVAILABLE
                    detail = "channel disabled for this UTC day"
                elif (
                    self._conn.execute(
                        """SELECT 1 FROM model_call_reservations WHERE call_id = ?
                       UNION ALL SELECT 1 FROM model_call_records WHERE call_id = ?""",
                        [call_id, call_id],
                    ).fetchone()
                    is not None
                ):
                    detail = "admission identity already used"
                elif call_limit is not None and usage.calls >= call_limit:
                    detail = "daily call limit"
                elif cost_limit is not None and (
                    not usage.cost_known
                    or estimated_cost is None
                    or not estimated_cost.is_finite()
                    or estimated_cost < 0
                    or usage.cost + estimated_cost > cost_limit
                    or usage.cost >= cost_limit
                ):
                    detail = "paid cost unknown or daily cost limit"
                if not detail and round_key is not None:
                    legacy = self._conn.execute(
                        """SELECT 1 FROM model_call_records r
                        LEFT JOIN model_call_reservations a ON r.call_id = a.call_id
                        WHERE r.cycle_key = ? AND r.status != 'rejected'
                          AND a.round_key IS NULL LIMIT 1""",
                        [round_key],
                    ).fetchone()
                    round_usage = self.round_usage(round_key)
                    symbol_usage = self.round_usage(round_key, symbol=symbol)
                    if legacy is not None:
                        detail = "round call scope unknown"
                    elif round_usage["total"] >= MAX_ROUND_CALLS:
                        detail = "round total call limit"
                    elif (
                        call_kind == "normal"
                        and symbol_usage["normal"] >= MAX_COMMITTEE_NORMAL_CALLS
                    ):
                        detail = "symbol normal call limit"
                    elif (
                        call_kind == "repair"
                        and symbol_usage["repair"] >= MAX_COMMITTEE_REPAIR_CALLS
                    ):
                        detail = "symbol repair call limit"
                if detail:
                    self._conn.execute("ROLLBACK")
                    return BudgetVerdict(
                        False, channel, reason, detail, usage.calls, usage.cost
                    )
                self._conn.execute(
                    """INSERT INTO model_call_reservations
                    (call_id, provider, created_at, reserved_cost,
                     round_key, symbol, call_kind)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        call_id,
                        channel,
                        observed_at,
                        None if estimated_cost is None else str(estimated_cost),
                        round_key,
                        symbol,
                        call_kind,
                    ],
                )
                self._conn.execute("COMMIT")
                return BudgetVerdict(
                    True,
                    channel,
                    "",
                    "durable admission",
                    usage.calls + 1,
                    usage.cost + (estimated_cost or 0),
                )
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def round_usage(
        self, round_key: str, *, symbol: str | None = None
    ) -> dict[str, int]:
        """Count durable outbound admissions across all channels and UTC days."""
        with self._lock:
            row = self._conn.execute(
                """SELECT COUNT(*), COUNT(*) FILTER (WHERE call_kind = 'normal'),
                COUNT(*) FILTER (WHERE call_kind = 'repair')
                FROM model_call_reservations
                WHERE round_key = ? AND (? IS NULL OR symbol = ?)""",
                [round_key, symbol, symbol],
            ).fetchone()
            assert row is not None
            return {"total": int(row[0]), "normal": int(row[1]), "repair": int(row[2])}

    def disabled_channel_reason(self, channel: str, day: str) -> str | None:
        """The reason a channel is disabled for one UTC day, if any."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT reason FROM model_channel_day_state
                WHERE channel = ? AND day = ?
                """,
                [channel, day],
            ).fetchone()
            return str(row[0]) if row is not None else None

    def disable_channel(self, channel: str, day: str, reason: str) -> None:
        """Disable one channel for one UTC day (idempotent)."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO model_channel_day_state (channel, day, reason, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (channel, day) DO NOTHING
                """,
                [channel, day, reason, datetime.now(UTC)],
            )

    def clear(self) -> None:
        """Drop only the model-call tables (for test isolation)."""
        self._conn.execute(_DROP_TABLE_SQL)
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.execute(_DROP_CHANNEL_STATE_SQL)
        self._conn.execute(_CREATE_CHANNEL_STATE_SQL)
        self._conn.execute("DELETE FROM model_call_reservations")
        self._conn.execute("DELETE FROM model_budget_day_mutex")
        self._conn.execute("DELETE FROM model_budget_round_mutex")

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
