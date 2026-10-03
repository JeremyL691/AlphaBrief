"""Database backup, restore, verify, and retention commands (PROJECT_GUIDE S5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from alphabrief_api.db.backup import (
    BackupManifest,
    apply_retention,
    create_backup,
    restore_backup,
    verify_backup,
)
from alphabrief_core import paths as _paths

from alphabrief_cli.api_client import require_local_write

db_app = typer.Typer(
    help="Database backup, restore, verify, and retention inspection.",
    no_args_is_help=True,
)


def _dump(payload: Any, *, pretty: bool) -> None:
    if pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


@db_app.command("backup")
def backup_cmd(
    db_path: Path | None = typer.Option(
        None, "--db-path", help="Path to DuckDB database (default: system db)."
    ),
    backup_dir: Path | None = typer.Option(
        None,
        "--backup-dir",
        help="Directory to store backups (default: system backups dir).",
    ),
    blueprint_version: str = typer.Option(
        "v1.0.0", "--blueprint-version", help="Blueprint version string."
    ),
    max_age_days: int = typer.Option(
        7, "--max-age-days", help="Retention ceiling in days."
    ),
    keep_newest_verified: int = typer.Option(
        1, "--keep-newest-verified", help="Minimum newest verified backups to keep."
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),
) -> None:
    """Create an atomic backup with manifest and apply retention."""
    require_local_write("db backup")
    target_db = db_path or _paths.db_path()
    target_backup_dir = backup_dir or _paths.backups_dir()

    if not target_db.exists():
        typer.secho(
            f"error: source database does not exist: {target_db}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        manifest = create_backup(
            db_path=target_db,
            backup_dir=target_backup_dir,
            blueprint_version=blueprint_version,
            max_age_days=max_age_days,
            keep_newest_verified=keep_newest_verified,
        )
        removed = apply_retention(
            target_backup_dir,
            max_age_days=max_age_days,
            keep_newest_verified=keep_newest_verified,
        )
        res = manifest.model_dump(mode="json")
        res["pruned_backups"] = removed
        _dump(res, pretty=pretty)
    except Exception as exc:
        typer.secho(f"error creating backup: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


@db_app.command("restore")
def restore_cmd(
    backup_id: str = typer.Argument(
        ..., help="The backup ID (e.g. backup-YYYYMMDD-HHMMSS-micros)."
    ),
    target_path: Path | None = typer.Option(
        None,
        "--target-path",
        help="Target path for restored database (default: system db path).",
    ),
    backup_dir: Path | None = typer.Option(
        None, "--backup-dir", help="Directory where backups are stored."
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),
) -> None:
    """Restore a backup into an isolated target or the main database."""
    require_local_write("db restore")
    target_backup_dir = backup_dir or _paths.backups_dir()
    dest = target_path or _paths.db_path()

    try:
        result = restore_backup(
            backup_dir=target_backup_dir,
            backup_id=backup_id,
            target_path=dest,
        )
        _dump(result.model_dump(mode="json"), pretty=pretty)
    except Exception as exc:
        typer.secho(
            f"error restoring backup {backup_id}: {exc}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1) from exc


@db_app.command("verify")
def verify_cmd(
    backup_id: str = typer.Argument(..., help="Backup ID to verify."),
    backup_dir: Path | None = typer.Option(
        None, "--backup-dir", help="Directory where backups are stored."
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),
) -> None:
    """Verify hash integrity of a backup against its manifest."""
    target_backup_dir = backup_dir or _paths.backups_dir()
    manifest_file = target_backup_dir / f"{backup_id}.manifest.json"
    if not manifest_file.exists():
        typer.secho(
            f"error: manifest not found for {backup_id}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1)

    try:
        ok = verify_backup(target_backup_dir, backup_id)
        _dump({"backup_id": backup_id, "verified": ok}, pretty=pretty)
        if not ok:
            raise typer.Exit(code=2)
    except typer.Exit:
        raise
    except Exception as exc:
        typer.secho(f"error verifying backup: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


@db_app.command("list")
def list_cmd(
    backup_dir: Path | None = typer.Option(
        None, "--backup-dir", help="Directory where backups are stored."
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),
) -> None:
    """List all available backup manifests."""
    target_backup_dir = backup_dir or _paths.backups_dir()
    manifests: list[dict[str, Any]] = []

    if target_backup_dir.is_dir():
        for manifest_path in sorted(
            target_backup_dir.glob("*.manifest.json"), reverse=True
        ):
            try:
                manifest = BackupManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
                data = manifest.model_dump(mode="json")
                manifests.append(data)
            except Exception:
                continue

    _dump({"backups": manifests, "count": len(manifests)}, pretty=pretty)


@db_app.command("prune")
def prune_cmd(
    backup_dir: Path | None = typer.Option(
        None, "--backup-dir", help="Directory where backups are stored."
    ),
    max_age_days: int | None = typer.Option(
        None, "--max-age-days", help="Prune backups older than N days."
    ),
    keep_newest: int | None = typer.Option(
        None, "--keep-newest", help="Preserve at least N newest verified backups."
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),
) -> None:
    """Prune expired backups according to retention policy."""
    target_backup_dir = backup_dir or _paths.backups_dir()
    try:
        removed = apply_retention(
            target_backup_dir,
            max_age_days=max_age_days,
            keep_newest_verified=keep_newest,
        )
        _dump({"removed_count": len(removed), "removed": removed}, pretty=pretty)
    except Exception as exc:
        typer.secho(f"error pruning backups: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


__all__ = ["db_app"]
