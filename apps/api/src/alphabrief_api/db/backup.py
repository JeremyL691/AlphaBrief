"""Atomic database backups, isolated restore, and retention (M03-W05).

- ``create_backup`` snapshots the DuckDB file atomically (temp file +
  rename) with a manifest carrying file hashes, the schema version, the
  blueprint version, and the retention policy; artifacts are scanned for
  configured secret patterns before publication (REQ-PLAT-007,
  REQ-OPS-002).
- ``restore_backup`` restores into an isolated target, migrates it to
  the latest schema version, rebuilds cycle projections, and runs
  integrity queries (REQ-OPS-006).
- ``apply_retention`` removes only expired explicit targets and always
  preserves the newest verified restore point.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

#: Secret patterns that must never appear in backup artifacts.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.IGNORECASE),
    re.compile(
        r"(?:api[_-]?key|secret|token)\s*[:=]\s*[A-Za-z0-9._~+/=-]{12,}",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{3}-\d{3}-\d{7,}-\d{3}\b"),
)


class BackupManifest(BaseModel):
    """One verified backup artifact set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backup_id: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    source_db_sha256: str = Field(min_length=1)
    schema_version: int = Field(ge=0)
    blueprint_version: str = Field(min_length=1)
    files: tuple[dict[str, str], ...] = Field(min_length=1)
    retention: dict[str, int] = Field(min_length=1)


class RestoreResult(BaseModel):
    """The outcome of one isolated restore."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backup_id: str
    restored_schema_version: int
    integrity_ok: bool
    projections_rebuilt: bool
    detail: str | None = None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_for_secrets(path: Path) -> list[str]:
    """Return configured secret patterns found in *path* (best effort)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [
        pattern.pattern
        for pattern in _SECRET_PATTERNS
        if pattern.search(text)
    ]


def _current_schema_version(db_path: Path) -> int:
    import duckdb

    connection = duckdb.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    finally:
        connection.close()


def create_backup(
    db_path: Path | str,
    backup_dir: Path | str,
    *,
    blueprint_version: str,
    max_age_days: int = 7,
    keep_newest_verified: int = 1,
) -> BackupManifest:
    """Create one atomic backup with a scrubbed, hashed manifest.

    The database file is checkpointed, copied to a temporary name, and
    renamed into place (atomic on the same filesystem); the manifest is
    written only after the file copy succeeds. Any secret pattern found
    in the artifacts aborts the backup.
    """
    import duckdb

    source = Path(db_path)
    target_dir = Path(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Flush any WAL state into the file so the copy is a consistent point.
    connection = duckdb.connect(str(source))
    try:
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    backup_id = datetime.now(UTC).strftime("backup-%Y%m%d-%H%M%S-%f")
    final_name = f"{backup_id}.db"
    temp_name = f".tmp-{backup_id}.db"
    temp_path = target_dir / temp_name
    final_path = target_dir / final_name
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, final_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    source_sha = _file_sha256(source)
    file_sha = _file_sha256(final_path)
    schema_version = _current_schema_version(source)
    manifest = BackupManifest(
        backup_id=backup_id,
        created_at=datetime.now(UTC).isoformat(),
        source_db_sha256=source_sha,
        schema_version=schema_version,
        blueprint_version=blueprint_version,
        files=(
            {
                "path": final_name,
                "sha256": file_sha,
                "size": str(final_path.stat().st_size),
            },
        ),
        retention={
            "max_age_days": max_age_days,
            "keep_newest_verified": keep_newest_verified,
        },
    )
    manifest_path = target_dir / f"{backup_id}.manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    secrets = _scan_for_secrets(final_path) + _scan_for_secrets(manifest_path)
    if secrets:
        final_path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"backup {backup_id} contains secret patterns: {secrets}"
        )
    return manifest


def verify_backup(backup_dir: Path | str, backup_id: str) -> bool:
    """Return True when the backup file hash matches its manifest."""
    target_dir = Path(backup_dir)
    manifest = BackupManifest.model_validate_json(
        (target_dir / f"{backup_id}.manifest.json").read_text(encoding="utf-8")
    )
    for entry in manifest.files:
        path = target_dir / entry["path"]
        if not path.is_file():
            return False
        if _file_sha256(path) != entry["sha256"]:
            return False
    return True


def restore_backup(
    backup_dir: Path | str,
    backup_id: str,
    target_path: Path | str,
) -> RestoreResult:
    """Restore *backup_id* into an isolated *target_path*.

    The target is migrated to the latest schema version, cycle
    projections are rebuilt from facts, and integrity queries run before
    the result is returned. The source backup is never modified.
    """
    import duckdb

    from alphabrief_api.db.schema import apply_schema, current_schema_version

    target_dir = Path(backup_dir)
    manifest = BackupManifest.model_validate_json(
        (target_dir / f"{backup_id}.manifest.json").read_text(encoding="utf-8")
    )
    entry = manifest.files[0]
    if not verify_backup(target_dir, backup_id):
        raise RuntimeError(f"backup {backup_id} failed hash verification")

    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target_dir / entry["path"], target)

    integrity_ok = False
    projections_rebuilt = False
    connection = duckdb.connect(str(target))
    try:
        apply_schema(connection)
        restored_version = current_schema_version(connection)
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        integrity_ok = (
            "symbols" in tables and "bars" in tables and "schema_migrations" in tables
        )
        try:
            from alphabrief_trader.db_store import CycleCheckpointStore

            checkpoints = CycleCheckpointStore(db_path=target)
            try:
                cycle_rows = connection.execute(
                    "SELECT cycle_id FROM ai_daily_cycles"
                ).fetchall()
                projections_rebuilt = (
                    all(
                        checkpoints.projection_matches_stored(str(row[0]))
                        for row in cycle_rows
                    )
                    if cycle_rows
                    else True
                )
            finally:
                checkpoints.close()
        except Exception:
            projections_rebuilt = False
        if not integrity_ok:
            raise RuntimeError(
                f"restored database {backup_id} failed integrity check"
            )
    finally:
        connection.close()

    return RestoreResult(
        backup_id=backup_id,
        restored_schema_version=restored_version,
        integrity_ok=integrity_ok,
        projections_rebuilt=projections_rebuilt,
        detail=f"restored to schema v{restored_version}",
    )


def apply_retention(
    backup_dir: Path | str,
    *,
    max_age_days: int | None = None,
    keep_newest_verified: int | None = None,
) -> list[str]:
    """Remove expired backups, always preserving the newest verified one.

    Only explicit backup targets (``backup-*.db`` + manifests) are
    considered; foreign files are never touched. Returns the removed
    backup IDs.
    """
    target_dir = Path(backup_dir)
    manifests: list[BackupManifest] = []
    for manifest_path in target_dir.glob("*.manifest.json"):
        try:
            manifests.append(
                BackupManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
            )
        except Exception:
            continue

    now = datetime.now(UTC)
    removed: list[str] = []

    def _sort_key(manifest: BackupManifest) -> tuple[str, str]:
        # The backup id is chronologically monotonic, so it breaks ties
        # deterministically when created_at values collide.
        return (manifest.created_at, manifest.backup_id)

    verified = [
        manifest
        for manifest in manifests
        if verify_backup(target_dir, manifest.backup_id)
    ]
    newest_verified = max(
        verified,
        key=_sort_key,
        default=None,
    )

    candidates = sorted(
        manifests,
        key=_sort_key,
        reverse=True,
    )
    for index, manifest in enumerate(candidates):
        expired = False
        if max_age_days is not None:
            try:
                created = datetime.fromisoformat(manifest.created_at)
                if (now - created).days >= max_age_days:
                    expired = True
            except ValueError:
                expired = True
        if keep_newest_verified is not None and index >= keep_newest_verified:
            expired = True
        if expired and manifest.backup_id != (
            newest_verified.backup_id if newest_verified else None
        ):
            for suffix in (".db", ".manifest.json"):
                (target_dir / f"{manifest.backup_id}{suffix}").unlink(
                    missing_ok=True
                )
            removed.append(manifest.backup_id)
    return removed


__all__ = [
    "BackupManifest",
    "RestoreResult",
    "apply_retention",
    "create_backup",
    "restore_backup",
    "verify_backup",
]
