"""Macro calendar and revision-aware observation ingestion (M09-W03).

Persists scheduled macro releases and revision-aware observations with
deterministic currency, market, and instrument impact mappings
(REQ-NEWS-004, REQ-NEWS-003). Every release persists release time,
actual, forecast, previous, revision flag, importance, unit, source,
and affected currencies/markets in UTC (AC-M09-W03-01). A revised
observation appends a new version with lineage while the prior value
remains reconstructable (AC-M09-W03-02). States — missing, stale,
partial, and revised — are explicit (AC-M09-W03-03).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field, field_validator

Importance = Literal["low", "medium", "high"]

#: Default staleness window for a released indicator with no actual yet.
DEFAULT_STALE_AFTER_SECONDS = 86400


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("macro release decimal values must not be floats")
    return value


def _utc_time(value: Any) -> datetime:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError("macro times must be datetimes")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class MacroRelease(BaseModel):
    """One immutable macro release version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    release_id: str = Field(min_length=1)
    indicator: str = Field(min_length=1)
    release_time: datetime
    actual: Decimal | None = None
    forecast: Decimal | None = None
    previous: Decimal | None = None
    revision: bool = False
    importance: Importance = "medium"
    unit: str | None = None
    source: str = Field(min_length=1)
    affected_currencies: tuple[str, ...] = ()
    affected_markets: tuple[str, ...] = ()
    version: int = Field(default=1, ge=1)
    lineage: tuple[str, ...] = ()

    @field_validator("actual", "forecast", "previous", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("release_time", mode="before")
    @classmethod
    def time_must_be_utc(cls, value: Any) -> Any:
        return _utc_time(value)

    def with_state(self, state: str) -> dict[str, Any]:
        """One JSON-ready view with the explicit state attached."""
        return {
            **self.model_dump(mode="json"),
            "state": state,
        }


class MacroReleaseState(BaseModel):
    """One explicit release state verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    release_id: str = ""
    state: Literal["fresh", "partial", "stale", "revised", "missing"]
    detail: str = ""


def release_state(
    release: MacroRelease | None,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> MacroReleaseState:
    """One deterministic state for a release.

    - missing: no release record at all;
    - revised: a later version exists (version > 1);
    - partial: released but no actual observation yet;
    - stale: partial and the release time is older than the window;
    - fresh: complete observation at the latest version.
    """
    observed_at = now or datetime.now(UTC)
    if release is None:
        return MacroReleaseState(
            release_id="", state="missing", detail="no release record"
        )
    if release.version > 1:
        return MacroReleaseState(
            release_id=release.release_id,
            state="revised",
            detail=f"version {release.version} with lineage",
        )
    if release.actual is None:
        age = (observed_at - release.release_time).total_seconds()
        if age > stale_after_seconds:
            return MacroReleaseState(
                release_id=release.release_id,
                state="stale",
                detail=f"released {age:.0f}s ago with no actual",
            )
        return MacroReleaseState(
            release_id=release.release_id,
            state="partial",
            detail="released with no actual observation",
        )
    return MacroReleaseState(
        release_id=release.release_id,
        state="fresh",
        detail="complete observation",
    )


class MacroReleaseStore:
    """DuckDB-backed append-only versioned macro release store."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS macro_releases (
                release_id        TEXT NOT NULL,
                version           BIGINT NOT NULL,
                lineage           TEXT NOT NULL,
                indicator         TEXT NOT NULL,
                release_time      TIMESTAMPTZ NOT NULL,
                actual            TEXT,
                forecast          TEXT,
                previous          TEXT,
                revision          BOOLEAN NOT NULL,
                importance        TEXT NOT NULL,
                unit              TEXT,
                source            TEXT NOT NULL,
                affected_currencies TEXT NOT NULL,
                affected_markets  TEXT NOT NULL,
                recorded_at       TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (release_id, version)
            );
            CREATE INDEX IF NOT EXISTS macro_releases_time ON
                macro_releases (release_time, release_id);
            """
        )

    def ingest(self, release: MacroRelease) -> bool:
        """Persist version 1; a duplicate release_id is ignored."""
        return self._insert_version(release, version=1)

    def revise(
        self,
        release_id: str,
        *,
        actual: Decimal | None = None,
        forecast: Decimal | None = None,
        previous: Decimal | None = None,
        importance: Importance | None = None,
        unit: str | None = None,
    ) -> MacroRelease | None:
        """Append the next version with lineage to the prior version.

        The prior value remains reconstructable via ``versions``.
        Returns the new version, or ``None`` when the release is unknown.
        """
        current = self.latest(release_id)
        if current is None:
            return None
        next_version = current.version + 1
        revised = current.model_copy(
            update={
                "actual": current.actual if actual is None else actual,
                "forecast": current.forecast if forecast is None else forecast,
                "previous": current.previous if previous is None else previous,
                "importance": current.importance if importance is None else importance,
                "unit": current.unit if unit is None else unit,
                "revision": True,
                "version": next_version,
                "lineage": (release_id,),
            }
        )
        self._insert_version(revised, version=next_version)
        return revised

    def latest(self, release_id: str) -> MacroRelease | None:
        rows = self._conn.execute(
            """
            SELECT * FROM macro_releases WHERE release_id = ?
            ORDER BY version DESC LIMIT 1
            """,
            [release_id],
        ).fetchall()
        if not rows:
            return None
        return _row_to_release(rows[0])

    def versions(self, release_id: str) -> tuple[MacroRelease, ...]:
        rows = self._conn.execute(
            """SELECT * FROM macro_releases WHERE release_id = ?
               ORDER BY version ASC""",
            [release_id],
        ).fetchall()
        return tuple(_row_to_release(row) for row in rows)

    def releases(
        self, *, indicator: str | None = None
    ) -> tuple[MacroRelease, ...]:
        """Latest version per release, ordered by release time then id."""
        where = "WHERE indicator = ?" if indicator else ""
        params = [indicator] if indicator else []
        rows = self._conn.execute(
            f"""
            SELECT r.* FROM macro_releases r
            JOIN (
                SELECT release_id, MAX(version) AS version
                FROM macro_releases GROUP BY release_id
            ) latest
              ON r.release_id = latest.release_id
             AND r.version = latest.version
            {where}
            ORDER BY r.release_time, r.release_id
            """,
            params,
        ).fetchall()
        return tuple(_row_to_release(row) for row in rows)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass

    def _insert_version(self, release: MacroRelease, *, version: int) -> bool:
        inserted = self._conn.execute(
            """
            INSERT OR IGNORE INTO macro_releases (
                release_id, version, lineage, indicator, release_time,
                actual, forecast, previous, revision, importance, unit,
                source, affected_currencies, affected_markets, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                release.release_id,
                version,
                ",".join(release.lineage),
                release.indicator,
                release.release_time,
                str(release.actual) if release.actual is not None else None,
                str(release.forecast) if release.forecast is not None else None,
                str(release.previous) if release.previous is not None else None,
                release.revision,
                release.importance,
                release.unit,
                release.source,
                ",".join(release.affected_currencies),
                ",".join(release.affected_markets),
                datetime.now(UTC),
            ],
        ).fetchone()
        return bool(inserted and inserted[0] > 0)


def _row_to_release(row: tuple[object, ...]) -> MacroRelease:
    return MacroRelease(
        release_id=str(row[0]),
        version=int(str(row[1])),
        lineage=tuple(str(row[2]).split(",")) if row[2] else (),
        indicator=str(row[3]),
        release_time=_utc_time(row[4]),
        actual=Decimal(str(row[5])) if row[5] is not None else None,
        forecast=Decimal(str(row[6])) if row[6] is not None else None,
        previous=Decimal(str(row[7])) if row[7] is not None else None,
        revision=bool(row[8]),
        importance=str(row[9]),  # type: ignore[arg-type]
        unit=str(row[10]) if row[10] is not None else None,
        source=str(row[11]),
        affected_currencies=tuple(str(row[12]).split(",")) if row[12] else (),
        affected_markets=tuple(str(row[13]).split(",")) if row[13] else (),
    )


def _default_db_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "DEFAULT_STALE_AFTER_SECONDS",
    "Importance",
    "MacroRelease",
    "MacroReleaseState",
    "MacroReleaseStore",
    "release_state",
]
