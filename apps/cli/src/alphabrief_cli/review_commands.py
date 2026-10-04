"""CLI subcommands for the review center module."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import typer
from alphabrief_api.db import ReviewStore
from alphabrief_core import paths as _paths
from alphabrief_review import ReviewCenterSnapshot, generate_daily_review
from alphabrief_review.io import ReviewSnapshotLoadError, load_review_snapshot
from pydantic import ValidationError

from alphabrief_cli.api_client import is_api_running

review_app = typer.Typer(help="Browse review snapshots and journals.")


def _open_review_store() -> ReviewStore:
    """Return the review store on the shared database path."""
    return ReviewStore(db_path=_paths.db_path())


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
    snapshot: Path | None = typer.Option(  # noqa: B008
        None,
        "--snapshot",
        "-s",
        help=(
            "Path to a ReviewCenterSnapshot JSON file "
            "(optional if daily reports exist)."
        ),
        exists=False,
        readable=True,
    ),
    trading_day: str | None = typer.Option(
        None,
        "--trading-day",
        "-d",
        help=(
            "ISO trading day (YYYY-MM-DD). Defaults to most recent "
            "brief, report, or today."
        ),
    ),
) -> None:
    """Display the daily review or report from a snapshot or persistent report store."""
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

    if snapshot is not None:
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
        return

    # If --snapshot is omitted, look in _paths.daily_reports_dir() first
    daily_dir = _paths.daily_reports_dir()
    if daily_dir.is_dir():
        target_md: Path | None
        target_json: Path | None
        if resolved_day is not None:
            day_str = resolved_day.isoformat()
            target_md = daily_dir / f"{day_str}.md"
            target_json = daily_dir / f"{day_str}.json"
        else:
            md_files = sorted(daily_dir.glob("*.md"), reverse=True)
            json_files = sorted(daily_dir.glob("*.json"), reverse=True)
            target_md = md_files[0] if md_files else None
            target_json = json_files[0] if json_files else None

        if target_md and target_md.exists():
            print(target_md.read_text(encoding="utf-8"))
            return
        if target_json and target_json.exists():
            data = json.loads(target_json.read_text(encoding="utf-8"))
            print(f"=== Daily Report: {target_json.stem} ===")
            print(data.get("summary", "No summary provided."))
            if "cycles" in data:
                print(f"Executed cycles: {len(data['cycles'])}")
            if "nav" in data:
                print(f"Account NAV: {data['nav']}")
            return

    # Fallback to latest snapshot in ReviewStore
    store = _open_review_store()
    try:
        latest = store.get_latest_snapshot()
    finally:
        store.close()

    if latest is not None and "snapshot" in latest:
        try:
            loaded = ReviewCenterSnapshot.model_validate(latest["snapshot"])
            if resolved_day is None:
                if loaded.daily_briefs:
                    resolved_day = max(
                        brief.trading_day for brief in loaded.daily_briefs
                    )
                else:
                    resolved_day = date.today()
            entry = generate_daily_review(loaded, trading_day=resolved_day)
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
            return
        except Exception:
            pass

    print("No daily reports or review snapshots found in storage.")


__all__ = ["review_app"]
