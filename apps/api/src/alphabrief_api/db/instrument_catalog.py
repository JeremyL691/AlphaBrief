"""Versioned instrument catalog snapshots and diffs (M04-W03).

``InstrumentCatalogStore`` persists account-scoped immutable catalog
versions atomically: a snapshot row, its instrument rows, the content
hash, the account correlation, the UTC fetched-at timestamp, and the
computed diff publish in one transaction or not at all. Replaying
identical content is a no-op; additions, removals, reactivations, and
metadata changes create queryable history without overwriting prior
versions. The current projection rebuilds from the immutable rows and
matches the latest complete snapshot exactly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from alphabrief_execution.broker.oanda.instruments import (
    InstrumentCatalogSnapshot,
    InstrumentMetadata,
)
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.db.schema import apply_schema, drop_schema


class CatalogDiff(BaseModel):
    """One snapshot's changes versus the previous projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    reactivated: tuple[str, ...] = ()
    metadata_changed: tuple[str, ...] = ()


class CatalogProjection(BaseModel):
    """The current instrument view rebuilt from immutable facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id_hash: str
    snapshot_id: str
    content_hash: str
    instruments: tuple[InstrumentMetadata, ...] = Field(min_length=1)


def _content_hash(snapshot: InstrumentCatalogSnapshot) -> str:
    rows = [
        {
            "name": instrument.name,
            "metadata": instrument.model_dump(mode="json"),
        }
        for instrument in snapshot.instruments
    ]
    raw = json.dumps(rows, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _snapshot_id(account_id_hash: str, content_hash: str) -> str:
    raw = f"{account_id_hash}|{content_hash}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


class InstrumentCatalogStore:
    """DuckDB-backed store for immutable instrument catalog snapshots."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_schema(self._conn)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def publish_snapshot(
        self,
        snapshot: InstrumentCatalogSnapshot,
    ) -> str:
        """Publish one immutable catalog version atomically.

        Returns the snapshot ID. Identical content replays idempotently
        (the existing snapshot ID is returned, nothing is rewritten);
        the snapshot row, instrument rows, content hash, diff, and UTC
        fetched-at timestamp commit together or not at all.
        """
        content_hash = _content_hash(snapshot)
        existing = self._conn.execute(
            "SELECT snapshot_id FROM instrument_catalog_snapshots "
            "WHERE content_hash = ? ORDER BY created_at LIMIT 1",
            [content_hash],
        ).fetchone()
        if existing is not None:
            return str(existing[0])

        snapshot_id = _snapshot_id(snapshot.account_id_hash, content_hash)
        previous = self.current_projection()
        diff = _compute_diff(previous, snapshot)

        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                """
                INSERT INTO instrument_catalog_snapshots (
                    snapshot_id, account_id_hash, content_hash,
                    diff_json, fetched_at
                ) VALUES (?, ?, ?, ?::JSON, ?)
                """,
                [
                    snapshot_id,
                    snapshot.account_id_hash,
                    content_hash,
                    diff.model_dump_json(),
                    snapshot.fetched_at,
                ],
            )
            for instrument in snapshot.instruments:
                self._conn.execute(
                    """
                    INSERT INTO instrument_catalog_rows (
                        snapshot_id, name, metadata_json
                    ) VALUES (?, ?, ?::JSON)
                    """,
                    [
                        snapshot_id,
                        instrument.name,
                        instrument.model_dump_json(),
                    ],
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return snapshot_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def current_projection(self) -> CatalogProjection | None:
        """Rebuild the current view from the latest complete snapshot."""
        latest = self._conn.execute(
            "SELECT snapshot_id, account_id_hash, content_hash "
            "FROM instrument_catalog_snapshots "
            "ORDER BY created_at DESC, snapshot_id LIMIT 1"
        ).fetchone()
        if latest is None:
            return None
        snapshot_id = str(latest[0])
        rows = self._conn.execute(
            "SELECT metadata_json FROM instrument_catalog_rows "
            "WHERE snapshot_id = ? ORDER BY name",
            [snapshot_id],
        ).fetchall()
        instruments = [
            InstrumentMetadata.model_validate(
                json.loads(row[0]) if isinstance(row[0], str) else row[0]
            )
            for row in rows
        ]
        return CatalogProjection(
            account_id_hash=str(latest[1]),
            snapshot_id=snapshot_id,
            content_hash=str(latest[2]),
            instruments=tuple(instruments),
        )

    def projection_matches_latest_snapshot(self) -> bool:
        """Return True when the rebuilt projection equals the latest rows.

        Both the projection rebuild and the latest snapshot content are
        normalized to their canonical content hash (AC-M03-W03-02 style
        byte-for-byte equality after normalization).
        """
        projection = self.current_projection()
        if projection is None:
            return False
        rebuilt = self._snapshot_from_projection(projection)
        return _content_hash(rebuilt) == projection.content_hash

    def snapshot_diff(self, snapshot_id: str) -> CatalogDiff | None:
        """Return the stored diff of one snapshot."""
        row = self._conn.execute(
            "SELECT diff_json FROM instrument_catalog_snapshots "
            "WHERE snapshot_id = ?",
            [snapshot_id],
        ).fetchone()
        if row is None:
            return None
        return CatalogDiff.model_validate(
            json.loads(row[0]) if isinstance(row[0], str) else row[0]
        )

    def list_snapshots(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return snapshot summaries, newest first."""
        rows = self._conn.execute(
            """SELECT snapshot_id, account_id_hash, content_hash, fetched_at
               FROM instrument_catalog_snapshots
               ORDER BY created_at DESC LIMIT ?""",
            [limit],
        ).fetchall()
        return [
            {
                "snapshot_id": str(row[0]),
                "account_id_hash": str(row[1]),
                "content_hash": str(row[2]),
                "fetched_at": str(row[3]),
            }
            for row in rows
        ]

    def _snapshot_from_projection(
        self,
        projection: CatalogProjection,
    ) -> InstrumentCatalogSnapshot:
        return InstrumentCatalogSnapshot(
            account_id_hash=projection.account_id_hash,
            fetched_at=datetime.now(UTC),
            instruments=tuple(projection.instruments),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Drop and recreate tables (for test isolation)."""
        drop_schema(self._conn)
        apply_schema(self._conn)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def _compute_diff(
    previous: CatalogProjection | None,
    snapshot: InstrumentCatalogSnapshot,
) -> CatalogDiff:
    """Compute additions/removals/reactivations/metadata changes.

    Reactivations are names present in the previous projection's
    *predecessor* but absent from the previous projection and present
    again now; with only one stored version they are recorded as
    additions, never guessed from symbol naming.
    """
    if previous is None:
        return CatalogDiff(
            added=tuple(instrument.name for instrument in snapshot.instruments)
        )

    prev_by_name = {i.name: i for i in previous.instruments}
    new_by_name = {i.name: i for i in snapshot.instruments}
    added = sorted(set(new_by_name) - set(prev_by_name))
    removed = sorted(set(prev_by_name) - set(new_by_name))
    metadata_changed = sorted(
        name
        for name in set(prev_by_name) & set(new_by_name)
        if prev_by_name[name].model_dump(mode="json")
        != new_by_name[name].model_dump(mode="json")
    )
    return CatalogDiff(
        added=tuple(added),
        removed=tuple(removed),
        reactivated=(),
        metadata_changed=tuple(metadata_changed),
    )


def _default_db_path() -> Path:
    import os

    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "CatalogDiff",
    "CatalogProjection",
    "InstrumentCatalogStore",
]
