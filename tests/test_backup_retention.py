"""M03-W05: backup retention policy (AC-M03-W05-03).

Retention removes only expired explicit backup targets and always
preserves the newest verified restore point.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_api.db.backup import apply_retention, create_backup, verify_backup


@pytest.fixture
def backups(tmp_path: Path) -> tuple[Path, Path, list[str]]:
    """Three backups of one seeded database."""
    from alphabrief_api.db.schema import apply_schema

    db_path = tmp_path / "source.db"
    import duckdb

    conn = duckdb.connect(str(db_path))
    apply_schema(conn)
    conn.execute(
        "INSERT INTO symbols (symbol, source, data_version, bar_count) "
        "VALUES ('EUR_USD', 'test', 'v1', 0)"
    )
    conn.close()

    backup_dir = tmp_path / "backups"
    ids: list[str] = []
    for _ in range(3):
        manifest = create_backup(db_path, backup_dir, blueprint_version="v1")
        ids.append(manifest.backup_id)
    return db_path, backup_dir, ids


def test_retention_keeps_newest_verified_only(
    backups: tuple[Path, Path, list[str]],
) -> None:
    db_path, backup_dir, ids = backups
    removed = apply_retention(backup_dir, max_age_days=7, keep_newest_verified=1)
    # keep_newest_verified=1 keeps only the newest verified restore point.
    assert set(removed) == set(ids[:2])
    assert (Path(backup_dir) / f"{ids[2]}.db").is_file()


def test_retention_keeps_newest_verified_even_when_expired(
    backups: tuple[Path, Path, list[str]],
) -> None:
    db_path, backup_dir, ids = backups
    # Age every manifest so all are expired.
    from alphabrief_api.db.backup import BackupManifest

    for backup_id in ids:
        manifest_path = Path(backup_dir) / f"{backup_id}.manifest.json"
        manifest = BackupManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        aged = manifest.model_copy(
            update={"created_at": "2020-01-01T00:00:00+00:00"}
        )
        manifest_path.write_text(aged.model_dump_json(indent=2), encoding="utf-8")

    removed = apply_retention(backup_dir, max_age_days=7, keep_newest_verified=1)

    assert len(removed) == 2
    newest = ids[-1]
    assert newest not in removed
    assert (Path(backup_dir) / f"{newest}.db").is_file()
    assert verify_backup(backup_dir, newest) is True


def test_retention_removes_corrupt_backups_except_newest_verified(
    backups: tuple[Path, Path, list[str]],
) -> None:
    db_path, backup_dir, ids = backups
    # Corrupt the two oldest backups; only the newest verified must stay.
    for backup_id in ids[:2]:
        with (Path(backup_dir) / f"{backup_id}.db").open("ab") as handle:
            handle.write(b"x")

    removed = apply_retention(backup_dir, max_age_days=0, keep_newest_verified=1)

    newest = ids[-1]
    assert newest not in removed
    assert (Path(backup_dir) / f"{newest}.db").is_file()
    assert verify_backup(backup_dir, newest) is True
