"""Soak commands (PROJECT_GUIDE 5.7, 7.3 S10).

Provides CLI commands to inspect soak test status and manage run lifecycles.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import typer
from alphabrief_trader.soak_evaluator import evaluate_soak_status
from alphabrief_trader.soak_store import SoakStartTimeError, SoakStore

soak_app = typer.Typer(help="Inspect and manage soak testing runs.")


def _dump(payload: object, *, pretty: bool) -> None:
    json.dump(payload, sys.stdout, indent=2 if pretty else None, default=str)
    sys.stdout.write("\n")


@soak_app.command("status")
def status_cmd(
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Show current soak testing qualification progress and status."""
    status = evaluate_soak_status()
    _dump(status.to_dict(), pretty=pretty)


@soak_app.command("start")
def start_cmd(
    started_at: str | None = typer.Option(  # noqa: B008
        None,
        "--started-at",
        help="UTC timestamp for starting the soak run (defaults to current time).",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Start or record Day 0 of the 14-day soak run."""
    from alphabrief_cli.api_client import require_local_write

    require_local_write("soak start")

    dt = None
    if started_at:
        try:
            dt = datetime.fromisoformat(started_at)
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=UTC)
        except ValueError as exc:
            raise typer.BadParameter(
                f"--started-at must be ISO timestamp: {started_at!r}"
            ) from exc

    store = SoakStore()
    try:
        run = store.start_soak(started_at=dt)
    except SoakStartTimeError as exc:
        # A backdated Day 0 would fake elapsed days; refuse it loudly.
        _dump({"action": "refused", "error": str(exc)}, pretty=pretty)
        raise typer.Exit(code=1) from exc
    finally:
        store.close()

    status = evaluate_soak_status()
    _dump(
        {
            "action": "started",
            "run": run.to_dict(),
            "status": status.to_dict(),
        },
        pretty=pretty,
    )


@soak_app.command("reset")
def reset_cmd(
    reason: str = typer.Option(  # noqa: B008
        ...,
        "--reason",
        help=(
            "Why the run is being reset. Required: the reset history is the "
            "audit trail."
        ),
    ),
    started_at: str | None = typer.Option(  # noqa: B008
        None,
        "--started-at",
        help="UTC start of the new run (defaults to now; no backdating).",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Supersede the active soak run and start a new Day 0.

    A failed run must stay in the history rather than be edited away, so
    this writes a ``reset`` row with the reason and opens a new active run
    at the next index. Days still come only from real elapsed time.
    """
    from alphabrief_cli.api_client import require_local_write

    require_local_write("soak reset")

    if not reason.strip():
        _dump(
            {"action": "refused", "error": "a reset requires a non-empty reason"},
            pretty=pretty,
        )
        raise typer.Exit(code=1)

    dt = None
    if started_at:
        try:
            dt = datetime.fromisoformat(started_at)
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=UTC)
        except ValueError as exc:
            raise typer.BadParameter(
                f"--started-at must be ISO timestamp: {started_at!r}"
            ) from exc

    store = SoakStore()
    try:
        active = store.get_active_run()
        if active is None:
            # Creating a run here would silently turn "nothing to reset"
            # into "Day 0 started", which is a different decision.
            _dump(
                {
                    "action": "refused",
                    "error": "there is no active soak run to reset",
                },
                pretty=pretty,
            )
            raise typer.Exit(code=1)
        try:
            run = store.record_reset(reason.strip(), new_started_at=dt)
        except SoakStartTimeError as exc:
            _dump({"action": "refused", "error": str(exc)}, pretty=pretty)
            raise typer.Exit(code=1) from exc
    finally:
        store.close()

    status = evaluate_soak_status()
    _dump(
        {
            "action": "reset",
            "reason": reason.strip(),
            "previous_run": active.to_dict(),
            "run": run.to_dict(),
            "status": status.to_dict(),
        },
        pretty=pretty,
    )


__all__ = ["reset_cmd", "soak_app", "start_cmd", "status_cmd"]
