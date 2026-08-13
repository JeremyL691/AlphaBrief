"""Immutable daily regime and sentiment snapshots (M09-W06).

Combines news, macro, sentiment, entity-link, quality, freshness, and
source-version IDs into one immutable daily evidence snapshot shared by
research and deterministic risk (REQ-PLAT-009, REQ-NEWS-005,
REQ-NEWS-007, REQ-NEWS-009, REQ-RISK-005). A snapshot records every
input ID under one immutable version ID and hash (AC-M09-W06-01).
Partial-source failure and stale critical coverage produce
deterministic degraded or blocked verdicts with missing-source reasons —
never synthesized replacement facts (AC-M09-W06-02). Research context
and news-risk context loaded by the same snapshot ID resolve identical
evidence and quality verdicts (AC-M09-W06-03).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field

DegradationState = Literal["healthy", "degraded", "blocked"]

#: The deterministic snapshot algorithm version.
SNAPSHOT_ALGORITHM_VERSION = "2026-08-13.1"


class SourceStatus(BaseModel):
    """One source's fetch status within a snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1)
    ok: bool
    version: str | None = None
    detail: str = ""


class QualityVerdict(BaseModel):
    """One deterministic quality verdict for a snapshot input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: str = Field(min_length=1)
    passed: bool
    detail: str = ""


class FreshnessVerdict(BaseModel):
    """One deterministic freshness verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_kind: str = Field(min_length=1)
    age_seconds: int = Field(ge=0)
    max_age_seconds: int = Field(gt=0)
    fresh: bool


class RegimeSnapshotInput(BaseModel):
    """One deterministic snapshot input bundle (IDs only, no content)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    news_ids: tuple[str, ...] = ()
    macro_ids: tuple[str, ...] = ()
    sentiment_ids: tuple[str, ...] = ()
    entity_link_ids: tuple[str, ...] = ()
    quality_verdicts: tuple[QualityVerdict, ...] = ()
    freshness_verdicts: tuple[FreshnessVerdict, ...] = ()
    source_statuses: tuple[SourceStatus, ...] = ()


class DegradationPolicy(BaseModel):
    """One deterministic degradation policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    critical_sources: tuple[str, ...] = ()
    critical_input_kinds: tuple[str, ...] = ()


class RegimeSnapshot(BaseModel):
    """One immutable daily regime and sentiment snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    algorithm_version: str = SNAPSHOT_ALGORITHM_VERSION
    degradation: DegradationState
    missing_source_reasons: tuple[str, ...] = ()
    news_ids: tuple[str, ...] = ()
    macro_ids: tuple[str, ...] = ()
    sentiment_ids: tuple[str, ...] = ()
    entity_link_ids: tuple[str, ...] = ()
    quality_verdicts: tuple[QualityVerdict, ...] = ()
    freshness_verdicts: tuple[FreshnessVerdict, ...] = ()
    source_versions: tuple[tuple[str, str], ...] = ()
    created_at: datetime


def _normalized_payload(inputs: RegimeSnapshotInput) -> str:
    return json.dumps(
        inputs.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )


def build_regime_snapshot(
    inputs: RegimeSnapshotInput,
    *,
    policy: DegradationPolicy | None = None,
    now: datetime | None = None,
) -> RegimeSnapshot:
    """Build one immutable snapshot deterministically.

    Degradation (AC-M09-W06-02):

    - ``blocked`` when any critical source failed or is missing;
    - ``degraded`` when any non-critical source failed or is missing;
    - ``healthy`` otherwise.

    Missing sources are recorded as reasons only — replacement facts
    are never synthesized.
    """
    resolved_policy = policy or DegradationPolicy()
    missing: list[str] = []
    source_versions: list[tuple[str, str]] = []
    for status in inputs.source_statuses:
        if not status.ok:
            missing.append(status.source)
        elif status.version is not None:
            source_versions.append((status.source, status.version))
    for verdict in inputs.freshness_verdicts:
        if not verdict.fresh:
            missing.append(f"{verdict.input_kind} (stale)")

    missing_reasons = tuple(
        f"{source}: fetch failed, missing, or stale"
        for source in sorted(missing)
    )
    critical_missing = [
        source
        for source in missing
        if source in resolved_policy.critical_sources
        or source.removesuffix(" (stale)") in resolved_policy.critical_input_kinds
    ]
    if critical_missing:
        degradation: DegradationState = "blocked"
    elif missing:
        degradation = "degraded"
    else:
        degradation = "healthy"

    content_hash = hashlib.sha256(
        _normalized_payload(inputs).encode("utf-8")
    ).hexdigest()
    version_id = f"regime-v1-{content_hash[:16]}"
    snapshot_id = version_id
    return RegimeSnapshot(
        snapshot_id=snapshot_id,
        version_id=version_id,
        content_hash=content_hash,
        algorithm_version=SNAPSHOT_ALGORITHM_VERSION,
        degradation=degradation,
        missing_source_reasons=missing_reasons,
        news_ids=inputs.news_ids,
        macro_ids=inputs.macro_ids,
        sentiment_ids=inputs.sentiment_ids,
        entity_link_ids=inputs.entity_link_ids,
        quality_verdicts=inputs.quality_verdicts,
        freshness_verdicts=inputs.freshness_verdicts,
        source_versions=tuple(sorted(source_versions)),
        created_at=now or datetime.now(UTC),
    )


class RegimeSnapshotStore:
    """DuckDB-backed append-only immutable snapshot store."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS regime_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                snapshot_json TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )

    def persist(self, snapshot: RegimeSnapshot) -> bool:
        """Persist one immutable snapshot; a duplicate ID is ignored."""
        inserted = self._conn.execute(
            """
            INSERT OR IGNORE INTO regime_snapshots (
                snapshot_id, snapshot_json, created_at
            ) VALUES (?, ?, ?)
            """,
            [snapshot.snapshot_id, snapshot.model_dump_json(), snapshot.created_at],
        ).fetchone()
        return bool(inserted and inserted[0] > 0)

    def get(self, snapshot_id: str) -> RegimeSnapshot | None:
        """The shared authority: the same ID resolves the same snapshot
        for research and risk consumers (AC-M09-W06-03)."""
        row = self._conn.execute(
            "SELECT snapshot_json FROM regime_snapshots WHERE snapshot_id = ?",
            [snapshot_id],
        ).fetchone()
        if row is None:
            return None
        return RegimeSnapshot.model_validate_json(str(row[0]))

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass


def _default_db_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "SNAPSHOT_ALGORITHM_VERSION",
    "DegradationPolicy",
    "FreshnessVerdict",
    "QualityVerdict",
    "RegimeSnapshot",
    "RegimeSnapshotInput",
    "RegimeSnapshotStore",
    "SourceStatus",
    "build_regime_snapshot",
]
