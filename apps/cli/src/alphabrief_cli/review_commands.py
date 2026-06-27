"""CLI subcommands for the review center module."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import typer
from alphabrief_api.db import ReviewStore
from alphabrief_review import ReviewCenterSnapshot, generate_daily_review
from alphabrief_review.io import ReviewSnapshotLoadError, load_review_snapshot
from pydantic import ValidationError

from alphabrief_cli.api_client import is_api_running

review_app = typer.Typer(help="Browse review snapshots and journals.")


def _open_review_store() -> ReviewStore:
    """Return a store rooted at ``$ALPHABRIEF_DATA_DIR`` (if set)."""
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return ReviewStore(db_path=db_dir / "alphabrief.db")
    return ReviewStore()


@review_app.command("list")
def list_cmd() -> None:
    """List available review snapshots."""
    # ponytail: read directly from ReviewStore when no API is running.
    # The list is purely metadata (id + trading_day + generated_at) so the
    # full snapshot JSON is not materialized here.
    if is_api_running():
        # Avoid DuckDB file-lock conflicts with the API process.
        print(
            "review list via API: not yet wired; "
            "use GET /api/v1/review/snapshot instead",
            file=sys.stderr,
        )
        sys.exit(1)

    store = _open_review_store()
    try:
        rows = store.list_snapshots()
    finally:
        store.close()

    if not rows:
        print("No review snapshots recorded.")
        return
    for row in rows:
        sid = row.get("id", row.get("snapshot_id", ""))
        td = row.get("trading_day", "")
        gen = row.get("generated_at", "")
        print(f"{sid} | trading_day={td} | generated_at={gen}")


@review_app.command("daily")
def daily_cmd(
    snapshot: Path = typer.Option(  # noqa: B008  (typer.Option is the documented pattern)
        ...,
        "--snapshot",
        "-s",
        help="Path to a ReviewCenterSnapshot JSON file.",
        exists=False,
        readable=True,
    ),
    trading_day: str | None = typer.Option(
        None,
        "--trading-day",
        "-d",
        help="ISO trading day (YYYY-MM-DD). Defaults to most recent brief or today.",
    ),
) -> None:
    """Generate a daily review journal from a ReviewCenterSnapshot JSON file."""
    resolved_day: date | None = None
    if trading_day is not None:
        try:
            resolved_day = date.fromisoformat(trading_day)
        except ValueError as exc:
            print(
                f"error: --trading-day must be ISO YYYY-MM-DD, got {trading_day!r}",
                file=sys.stderr,
            )
            print(f"detail: {exc}", file=sys.stderr)
            sys.exit(1)
    try:
        text = snapshot.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        print(f"error: snapshot file not found: {snapshot}", file=sys.stderr)
        print(f"detail: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"error: failed to read snapshot file: {snapshot}", file=sys.stderr)
        print(f"detail: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        loaded = ReviewCenterSnapshot.model_validate_json(text)
    except (ValidationError, ValueError):
        try:
            loaded = load_review_snapshot(snapshot)
        except (FileNotFoundError, ReviewSnapshotLoadError, OSError) as exc:
            print(f"error: invalid review snapshot: {snapshot}", file=sys.stderr)
            print(f"detail: {exc}", file=sys.stderr)
            sys.exit(1)

    if resolved_day is None:
        if loaded.daily_briefs:
            resolved_day = max(brief.trading_day for brief in loaded.daily_briefs)
        else:
            resolved_day = date.today()

    try:
        entry = generate_daily_review(loaded, trading_day=resolved_day)
    except (ValidationError, ValueError) as exc:
        print(f"error: failed to generate daily review: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"=== {entry.title} ===")
    print(entry.summary)
    print()
    print("Highlights:")
    for highlight in entry.highlights:
        print(f"  - {highlight}")
    print()
    print("Action items:")
    for item in entry.action_items:
        print(f"  - {item}")


__all__ = ["review_app"]
