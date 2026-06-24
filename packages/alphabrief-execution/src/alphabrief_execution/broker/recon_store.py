"""Broker reconciliation store.

Persists three things:

1. ``broker_order_id_map``: client_order_id -> broker_order_id mapping.
   Read at startup to seed the in-memory map so restarts do not double-submit.

2. ``broker_recon_snapshots``: per-reconciliation diffs.

3. ``broker_freeze_events``: append-only freeze / unfreeze log.
   Any row with ``cleared_at IS NULL`` represents an open freeze.

The store is duckdb-backed and safe to use from a single writer; it
opens one DuckDB connection per process. Concurrent processes must
coordinate via the database file lock.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb

# ---------------------------------------------------------------------------
# Schema bootstrap (kept in this file to keep the package self-contained;
# mirrors what apps/api/src/alphabrief_api/db/schema.py defines.)
# ---------------------------------------------------------------------------

_FREEZE_COLS = (
    "event_id, raised_at, cleared_at, scope, reason, source, related_snapshot_id"
)


def _freeze_select(where: str = "") -> str:
    """Return a SELECT over broker_freeze_events with the canonical column order."""
    return f"SELECT {_FREEZE_COLS} FROM broker_freeze_events {where}".strip()


CREATE_ORDER_ID_MAP = """
CREATE TABLE IF NOT EXISTS broker_order_id_map (
    client_order_id    TEXT PRIMARY KEY,
    broker_order_id    TEXT NOT NULL,
    status             TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_RECON_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS broker_recon_snapshots (
    snapshot_id        TEXT PRIMARY KEY,
    captured_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    scope              TEXT NOT NULL,
    orders_match       BOOLEAN NOT NULL,
    fills_match        BOOLEAN NOT NULL,
    cash_match         BOOLEAN NOT NULL,
    positions_match    BOOLEAN NOT NULL,
    diff_json          JSON NOT NULL DEFAULT '{}'
)
"""

CREATE_FREEZE_EVENTS = """
CREATE TABLE IF NOT EXISTS broker_freeze_events (
    event_id           TEXT PRIMARY KEY,
    raised_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cleared_at         TIMESTAMPTZ,
    scope              TEXT NOT NULL,
    reason             TEXT NOT NULL,
    source             TEXT NOT NULL,
    related_snapshot_id TEXT
)
"""

# ---------------------------------------------------------------------------
# Path / time helpers
# ---------------------------------------------------------------------------

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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Pydantic-free value types
# ---------------------------------------------------------------------------


class ReconSnapshot:
    """Read-only view of one ``broker_recon_snapshots`` row."""

    __slots__ = (
        "snapshot_id",
        "captured_at",
        "scope",
        "orders_match",
        "fills_match",
        "cash_match",
        "positions_match",
        "diff",
    )

    def __init__(
        self,
        *,
        snapshot_id: str,
        captured_at: str,
        scope: str,
        orders_match: bool,
        fills_match: bool,
        cash_match: bool,
        positions_match: bool,
        diff: dict[str, Any],
    ) -> None:
        self.snapshot_id = snapshot_id
        self.captured_at = captured_at
        self.scope = scope
        self.orders_match = orders_match
        self.fills_match = fills_match
        self.cash_match = cash_match
        self.positions_match = positions_match
        self.diff = diff

    @property
    def all_match(self) -> bool:
        return (
            self.orders_match
            and self.fills_match
            and self.cash_match
            and self.positions_match
        )


class FreezeEvent:
    """Read-only view of one ``broker_freeze_events`` row."""

    __slots__ = (
        "event_id",
        "raised_at",
        "cleared_at",
        "scope",
        "reason",
        "source",
        "related_snapshot_id",
    )

    def __init__(
        self,
        *,
        event_id: str,
        raised_at: str,
        cleared_at: str | None,
        scope: str,
        reason: str,
        source: str,
        related_snapshot_id: str | None,
    ) -> None:
        self.event_id = event_id
        self.raised_at = raised_at
        self.cleared_at = cleared_at
        self.scope = scope
        self.reason = reason
        self.source = source
        self.related_snapshot_id = related_snapshot_id

    @property
    def is_open(self) -> bool:
        return self.cleared_at is None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class BrokerReconStore:
    """DuckDB-backed store for broker reconciliation and freeze state."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        self._apply()

    # ------------------------------------------------------------------
    # Schema lifecycle
    # ------------------------------------------------------------------

    def _apply(self) -> None:
        self._conn.execute(CREATE_ORDER_ID_MAP)
        self._conn.execute(CREATE_RECON_SNAPSHOTS)
        self._conn.execute(CREATE_FREEZE_EVENTS)

    def clear(self) -> None:
        """Drop and recreate the broker tables. Test isolation only."""
        self._conn.execute("DROP TABLE IF EXISTS broker_freeze_events")
        self._conn.execute("DROP TABLE IF EXISTS broker_recon_snapshots")
        self._conn.execute("DROP TABLE IF EXISTS broker_order_id_map")
        self._apply()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Order id map
    # ------------------------------------------------------------------

    def upsert_order_id_map(
        self,
        *,
        client_order_id: str,
        broker_order_id: str,
        status: str,
    ) -> None:
        if not client_order_id or not broker_order_id:
            raise ValueError("client_order_id and broker_order_id must be non-empty")
        self._conn.execute(
            """
            INSERT INTO broker_order_id_map (
                client_order_id, broker_order_id, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (client_order_id) DO UPDATE
            SET broker_order_id = EXCLUDED.broker_order_id,
                status          = EXCLUDED.status,
                updated_at      = EXCLUDED.updated_at
            """,
            [client_order_id, broker_order_id, status, _now_iso(), _now_iso()],
        )

    def list_order_id_map(self) -> list[dict[str, str]]:
        rows = self._conn.execute(
            "SELECT client_order_id, broker_order_id, status FROM broker_order_id_map"
        ).fetchall()
        return [
            {
                "client_order_id": str(row[0]),
                "broker_order_id": str(row[1]),
                "status": str(row[2]),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Recon snapshots
    # ------------------------------------------------------------------

    def record_snapshot(
        self,
        *,
        scope: str,
        orders_match: bool,
        fills_match: bool,
        cash_match: bool,
        positions_match: bool,
        diff: dict[str, Any] | None = None,
        snapshot_id: str | None = None,
    ) -> ReconSnapshot:
        sid = snapshot_id or f"recon_{uuid4().hex}"
        payload = diff or {}
        self._conn.execute(
            """
            INSERT INTO broker_recon_snapshots (
                snapshot_id, captured_at, scope, orders_match, fills_match,
                cash_match, positions_match, diff_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                sid,
                _now_iso(),
                scope,
                orders_match,
                fills_match,
                cash_match,
                positions_match,
                json.dumps(payload, sort_keys=True),
            ],
        )
        return ReconSnapshot(
            snapshot_id=sid,
            captured_at=_now_iso(),
            scope=scope,
            orders_match=orders_match,
            fills_match=fills_match,
            cash_match=cash_match,
            positions_match=positions_match,
            diff=payload,
        )

    def list_snapshots(self, *, limit: int = 50) -> list[ReconSnapshot]:
        rows = self._conn.execute(
            "SELECT snapshot_id, captured_at, scope, orders_match, fills_match, "
            "cash_match, positions_match, diff_json "
            "FROM broker_recon_snapshots ORDER BY captured_at DESC LIMIT ?",
            [limit],
        ).fetchall()
        return [_row_to_snapshot(row) for row in rows]

    def latest_snapshot(self, *, scope: str | None = None) -> ReconSnapshot | None:
        if scope is None:
            rows = self._conn.execute(
                "SELECT snapshot_id, captured_at, scope, orders_match, fills_match, "
                "cash_match, positions_match, diff_json "
                "FROM broker_recon_snapshots ORDER BY captured_at DESC LIMIT 1"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT snapshot_id, captured_at, scope, orders_match, fills_match, "
                "cash_match, positions_match, diff_json "
                "FROM broker_recon_snapshots WHERE scope = ? "
                "ORDER BY captured_at DESC LIMIT 1",
                [scope],
            ).fetchall()
        if not rows:
            return None
        return _row_to_snapshot(rows[0])

    # ------------------------------------------------------------------
    # Freeze events
    # ------------------------------------------------------------------

    def raise_freeze(
        self,
        *,
        reason: str,
        source: str,
        related_snapshot_id: str | None = None,
        scope: str = "broker",
    ) -> FreezeEvent:
        if not reason.strip():
            raise ValueError("freeze reason must be non-empty")
        if not source.strip():
            raise ValueError("freeze source must be non-empty")
        event_id = f"freeze_{uuid4().hex}"
        self._conn.execute(
            """
            INSERT INTO broker_freeze_events (
                event_id, raised_at, cleared_at, scope, reason,
                source, related_snapshot_id
            )
            VALUES (?, ?, NULL, ?, ?, ?, ?)
            """,
            [
                event_id,
                _now_iso(),
                scope,
                reason,
                source,
                related_snapshot_id,
            ],
        )
        return FreezeEvent(
            event_id=event_id,
            raised_at=_now_iso(),
            cleared_at=None,
            scope=scope,
            reason=reason,
            source=source,
            related_snapshot_id=related_snapshot_id,
        )

    def clear_freeze(self, *, event_id: str, reason: str | None = None) -> FreezeEvent:
        # Log the reason in a fresh freeze record? No — Phase 17 design:
        # clearing is a separate action. We update cleared_at and the
        # reason is recorded in a separate companion row.
        self._conn.execute(
            (
                "UPDATE broker_freeze_events SET cleared_at = ? "
                "WHERE event_id = ? AND cleared_at IS NULL"
            ),
            [_now_iso(), event_id],
        )
        if reason:
            self._conn.execute(
                """
                INSERT INTO broker_freeze_events (
                    event_id, raised_at, cleared_at, scope, reason,
                    source, related_snapshot_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    f"unfreeze_{uuid4().hex}",
                    _now_iso(),
                    _now_iso(),
                    "unfreeze",
                    reason,
                    "manual",
                    event_id,
                ],
            )
        row = self._conn.execute(
            _freeze_select("WHERE event_id = ?"),
            [event_id],
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown freeze event_id: {event_id}")
        return _row_to_freeze(row)

    def list_freezes(self, *, only_open: bool = True) -> list[FreezeEvent]:
        if only_open:
            where = "WHERE cleared_at IS NULL ORDER BY raised_at DESC"
        else:
            where = "ORDER BY raised_at DESC"
        rows = self._conn.execute(_freeze_select(where)).fetchall()
        return [_row_to_freeze(row) for row in rows]

    def has_open_freeze(self) -> bool:
        rows = self._conn.execute(
            "SELECT 1 FROM broker_freeze_events WHERE cleared_at IS NULL LIMIT 1"
        ).fetchall()
        return bool(rows)


# ---------------------------------------------------------------------------
# Row mapping helpers
# ---------------------------------------------------------------------------


def _row_to_snapshot(row: tuple[Any, ...]) -> ReconSnapshot:
    sid, captured_at, scope, om, fm, cm, pm, diff_json = row
    if isinstance(diff_json, str):
        try:
            parsed = json.loads(diff_json)
        except json.JSONDecodeError:
            diff = {"_raw": diff_json}
        else:
            diff = parsed if isinstance(parsed, dict) else {"_raw": diff_json}
    elif isinstance(diff_json, dict):
        diff = diff_json
    else:
        diff = {}
    return ReconSnapshot(
        snapshot_id=str(sid),
        captured_at=str(captured_at),
        scope=str(scope),
        orders_match=bool(om),
        fills_match=bool(fm),
        cash_match=bool(cm),
        positions_match=bool(pm),
        diff=diff if isinstance(diff, dict) else {"_value": diff},
    )


def _row_to_freeze(row: tuple[Any, ...]) -> FreezeEvent:
    event_id, raised_at, cleared_at, scope, reason, source, related = row
    return FreezeEvent(
        event_id=str(event_id),
        raised_at=str(raised_at),
        cleared_at=str(cleared_at) if cleared_at is not None else None,
        scope=str(scope),
        reason=str(reason),
        source=str(source),
        related_snapshot_id=str(related) if related is not None else None,
    )


__all__ = [
    "BrokerReconStore",
    "FreezeEvent",
    "ReconSnapshot",
]
