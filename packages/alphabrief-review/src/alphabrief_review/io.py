"""Local JSON persistence for Review Center snapshots."""

import json
from pathlib import Path

from pydantic import ValidationError

from alphabrief_review.schemas import ReviewCenterSnapshot


class ReviewSnapshotLoadError(ValueError):
    """Raised when a review snapshot cannot be loaded."""


def write_review_snapshot(snapshot: ReviewCenterSnapshot, path: str | Path) -> None:
    """Write a review snapshot as local JSON."""

    Path(path).write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")


def load_review_snapshot(path: str | Path) -> ReviewCenterSnapshot:
    """Load and validate a review snapshot from local JSON."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReviewSnapshotLoadError(f"failed to read review snapshot: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewSnapshotLoadError(f"invalid review snapshot JSON: {exc}") from exc

    try:
        return ReviewCenterSnapshot.model_validate(payload)
    except ValidationError as exc:
        raise ReviewSnapshotLoadError(
            f"invalid review snapshot schema: {exc}"
        ) from exc
