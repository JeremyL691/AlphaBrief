"""CLI subcommands for the audit log module."""

from __future__ import annotations

import sys

import typer
from alphabrief_execution import ExecutionAuditLog

audit_app = typer.Typer(help="Inspect the execution audit log.")


@audit_app.command("list")
def list_cmd() -> None:
    """List entries from the execution audit log."""
    try:
        audit_log = ExecutionAuditLog()
        if not audit_log.entries:
            print("No audit events recorded")
            return
        for entry in audit_log.entries:
            print(entry)
    except Exception as exc:
        print(f"error: audit list failed: {exc}", file=sys.stderr)
        sys.exit(1)


__all__ = ["audit_app"]
