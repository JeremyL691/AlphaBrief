"""Tests for alphabrief db commands (PROJECT_GUIDE S5)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from alphabrief_api.db.schema import apply_schema
from alphabrief_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def test_db_and_backups(tmp_path: Path) -> tuple[Path, Path]:
    db_file = tmp_path / "test.duckdb"
    conn = duckdb.connect(str(db_file))
    apply_schema(conn)
    conn.execute(
        "INSERT INTO symbols (symbol, source, data_version, bar_count) "
        "VALUES ('EUR_USD', 'test', 'v1', 10)"
    )
    conn.close()

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return db_file, backup_dir


def test_db_backup_and_list(test_db_and_backups: tuple[Path, Path]) -> None:
    db_file, backup_dir = test_db_and_backups
    res = runner.invoke(
        app,
        [
            "db",
            "backup",
            "--db-path",
            str(db_file),
            "--backup-dir",
            str(backup_dir),
            "--compact",
        ],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert "backup_id" in data
    backup_id = data["backup_id"]

    # List backups
    res_list = runner.invoke(
        app,
        ["db", "list", "--backup-dir", str(backup_dir), "--compact"],
    )
    assert res_list.exit_code == 0
    list_data = json.loads(res_list.output)
    assert list_data["count"] == 1
    assert list_data["backups"][0]["backup_id"] == backup_id


def test_db_verify_and_restore(
    test_db_and_backups: tuple[Path, Path], tmp_path: Path
) -> None:
    db_file, backup_dir = test_db_and_backups
    res_backup = runner.invoke(
        app,
        [
            "db",
            "backup",
            "--db-path",
            str(db_file),
            "--backup-dir",
            str(backup_dir),
            "--compact",
        ],
    )
    assert res_backup.exit_code == 0
    backup_id = json.loads(res_backup.output)["backup_id"]

    # Verify backup
    res_verify = runner.invoke(
        app,
        ["db", "verify", backup_id, "--backup-dir", str(backup_dir), "--compact"],
    )
    assert res_verify.exit_code == 0
    assert json.loads(res_verify.output)["verified"] is True

    # Restore to a new location
    restore_target = tmp_path / "restored.duckdb"
    res_restore = runner.invoke(
        app,
        [
            "db",
            "restore",
            backup_id,
            "--target-path",
            str(restore_target),
            "--backup-dir",
            str(backup_dir),
            "--compact",
        ],
    )
    assert res_restore.exit_code == 0, res_restore.output
    restore_data = json.loads(res_restore.output)
    assert restore_data["integrity_ok"] is True
    assert restore_target.is_file()

    # Verify data in restored db
    conn = duckdb.connect(str(restore_target))
    row = conn.execute("SELECT symbol FROM symbols WHERE symbol = 'EUR_USD'").fetchone()
    conn.close()
    assert row is not None and row[0] == "EUR_USD"


def test_db_verify_corrupted_fails(test_db_and_backups: tuple[Path, Path]) -> None:
    db_file, backup_dir = test_db_and_backups
    res_backup = runner.invoke(
        app,
        [
            "db",
            "backup",
            "--db-path",
            str(db_file),
            "--backup-dir",
            str(backup_dir),
            "--compact",
        ],
    )
    assert res_backup.exit_code == 0
    backup_id = json.loads(res_backup.output)["backup_id"]

    # Corrupt the db file
    db_path = backup_dir / f"{backup_id}.db"
    db_path.write_bytes(b"corrupted data")

    res_verify = runner.invoke(
        app,
        ["db", "verify", backup_id, "--backup-dir", str(backup_dir), "--compact"],
    )
    assert res_verify.exit_code == 2
    assert json.loads(res_verify.output)["verified"] is False


def test_db_prune(test_db_and_backups: tuple[Path, Path]) -> None:
    db_file, backup_dir = test_db_and_backups
    runner.invoke(
        app,
        [
            "db",
            "backup",
            "--db-path",
            str(db_file),
            "--backup-dir",
            str(backup_dir),
            "--compact",
        ],
    )
    res_prune = runner.invoke(
        app,
        ["db", "prune", "--backup-dir", str(backup_dir), "--compact"],
    )
    assert res_prune.exit_code == 0
    data = json.loads(res_prune.output)
    assert "removed_count" in data
