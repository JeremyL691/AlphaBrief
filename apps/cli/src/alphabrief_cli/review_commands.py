"""CLI subcommands for the review center module."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import typer
from alphabrief_review import ReviewCenterSnapshot, generate_daily_review
from alphabrief_review.io import ReviewSnapshotLoadError, load_review_snapshot
from pydantic import ValidationError

review_app = typer.Typer(help="Browse review snapshots and journals.")


@review_app.command("list")
def list_cmd() -> None:
    """List available review snapshots."""
    print("review list: not yet implemented")


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
