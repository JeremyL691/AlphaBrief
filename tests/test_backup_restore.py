"""M03-W05: atomic backups, verified restore, and retention (AC-01..03).

Covers:
- backup is atomic, has schema/build/file hashes, and never contains
  configured secret patterns (AC-M03-W05-01);
- an isolated restore migrates, rebuilds projections, and passes
  integrity queries (AC-M03-W05-02);
- retention removes only expired explicit backup targets and preserves
  the newest verified restore point (AC-M03-W05-03).
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import duckdb
import pytest
from alphabrief_api.db.backup import (
    BackupManifest,
    apply_retention,
    create_backup,
    restore_backup,
    verify_backup,
)
from alphabrief_api.db.schema import (
    apply_schema,
    current_schema_version,
    latest_schema_version,
)


@pytest.fixture
def seeded_db(
    tmp_path: Path,
) -> Generator[tuple[Path, Path], None, None]:
    """A schema-applied database with data, plus its backup directory."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from alphabrief_api.db.market_data import MarketDataStore
    from alphabrief_core import Bar

    db_path = tmp_path / "source.db"
    store = MarketDataStore(db_path=db_path)
    try:
        store.insert_bars(
            [
                Bar(
                    symbol="EUR_USD",
                    timestamp=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                    open=Decimal("1.09"),
                    high=Decimal("1.11"),
                    low=Decimal("1.08"),
                    close=Decimal("1.10"),
                    volume=Decimal("1000"),
                    source="test",
                    data_version="v1",
                )
            ],
            source="test",
            data_version="v1",
        )
    finally:
        store.close()
    backup_dir = tmp_path / "backups"
    yield db_path, backup_dir


# ---------------------------------------------------------------------------
# AC-M03-W05-01: atomic backup with hashes and scrubbing
# ---------------------------------------------------------------------------


def test_backup_is_atomic_with_hashes(
    seeded_db: tuple[Path, Path],
) -> None:
    db_path, backup_dir = seeded_db
    manifest = create_backup(
        db_path,
        backup_dir,
        blueprint_version="2026-08-13.1",
    )
    assert manifest.schema_version == latest_schema_version()
    assert manifest.blueprint_version == "2026-08-13.1"
    assert manifest.files[0]["sha256"]
    assert verify_backup(backup_dir, manifest.backup_id) is True
    # No temporary files remain after a successful backup.
    assert not list(Path(backup_dir).glob(".tmp-*"))


def test_backup_artifacts_contain_no_secret_patterns(
    seeded_db: tuple[Path, Path],
) -> None:
    db_path, backup_dir = seeded_db
    create_backup(
        db_path,
        backup_dir,
        blueprint_version="2026-08-13.1",
    )
    for path in Path(backup_dir).iterdir():
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "Bearer " not in text
        assert "api_key=" not in text
        assert "101-004-1234567-001" not in text


def test_backup_aborts_on_secret_pattern(tmp_path: Path) -> None:
    """A secret-bearing artifact aborts the backup with no leftovers."""

    db_path = tmp_path / "secret.db"
    conn = duckdb.connect(str(db_path))
    apply_schema(conn)
    conn.execute(
        "INSERT INTO symbols (symbol, source, data_version, bar_count) "
        "VALUES ('EUR_USD', 'test', 'v1', 0)"
    )
    conn.close()

    # Seed a secret-looking value into the database content.
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "INSERT INTO briefs (id, brief_json) VALUES (?, ?::JSON)",
        ["b1", '{"note": "token=abcdef1234567890"}'],
    )
    conn.close()

    with pytest.raises(RuntimeError, match="secret patterns"):
        create_backup(db_path, tmp_path / "backups", blueprint_version="v1")
    backup_dir = tmp_path / "backups"
    assert not list(Path(backup_dir).glob("backup-*.db"))


# ---------------------------------------------------------------------------
# AC-M03-W05-02: isolated restore migrates, rebuilds, and passes integrity
# ---------------------------------------------------------------------------


def test_isolated_restore_migrates_and_passes_integrity(
    seeded_db: tuple[Path, Path],
) -> None:
    db_path, backup_dir = seeded_db
    manifest = create_backup(
        db_path,
        backup_dir,
        blueprint_version="2026-08-13.1",
    )
    target = backup_dir / "restored" / "restored.db"

    result = restore_backup(backup_dir, manifest.backup_id, target)

    assert result.integrity_ok is True
    assert result.restored_schema_version == latest_schema_version()
    assert target.is_file()

    conn = duckdb.connect(str(target))
    try:
        assert current_schema_version(conn) == latest_schema_version()
        rows = conn.execute(
            "SELECT symbol FROM symbols WHERE symbol = 'EUR_USD'"
        ).fetchall()
        assert rows == [("EUR_USD",)]
    finally:
        conn.close()


def test_restore_verifies_backup_hash_before_copy(
    seeded_db: tuple[Path, Path],
) -> None:
    db_path, backup_dir = seeded_db
    manifest = create_backup(
        db_path,
        backup_dir,
        blueprint_version="2026-08-13.1",
    )
    # Corrupt the backup file: the hash check must reject the restore.
    backup_file = Path(backup_dir) / manifest.files[0]["path"]
    with backup_file.open("ab") as handle:
        handle.write(b"corruption")

    with pytest.raises(RuntimeError, match="failed hash verification"):
        restore_backup(backup_dir, manifest.backup_id, backup_dir / "x.db")


# ---------------------------------------------------------------------------
# AC-M03-W05-03: retention preserves the newest verified restore point
# ---------------------------------------------------------------------------


def test_retention_removes_expired_but_preserves_newest_verified(
    seeded_db: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, backup_dir = seeded_db
    manifests: list[BackupManifest] = []
    for _ in range(3):
        manifest = create_backup(
            db_path,
            backup_dir,
            blueprint_version="2026-08-13.1",
        )
        manifests.append(manifest)

    # Age the two oldest backups past the retention window.
    for manifest in manifests[:2]:
        manifest_path = Path(backup_dir) / f"{manifest.backup_id}.manifest.json"
        text = manifest_path.read_text(encoding="utf-8")
        text = text.replace(manifest.created_at, "2020-01-01T00:00:00+00:00")
        manifest_path.write_text(text, encoding="utf-8")

    removed = apply_retention(backup_dir, max_age_days=7, keep_newest_verified=1)

    assert set(removed) == {manifests[0].backup_id, manifests[1].backup_id}
    # The newest verified restore point survives.
    newest = manifests[2]
    assert (Path(backup_dir) / f"{newest.backup_id}.db").is_file()
    assert (Path(backup_dir) / f"{newest.backup_id}.manifest.json").is_file()
    assert verify_backup(backup_dir, newest.backup_id) is True


def test_retention_ignores_foreign_files(
    seeded_db: tuple[Path, Path],
) -> None:
    db_path, backup_dir = seeded_db
    create_backup(db_path, backup_dir, blueprint_version="2026-08-13.1")
    foreign = Path(backup_dir) / "unrelated.txt"
    foreign.write_text("keep me", encoding="utf-8")

    apply_retention(backup_dir, max_age_days=0, keep_newest_verified=0)

    assert foreign.is_file()
