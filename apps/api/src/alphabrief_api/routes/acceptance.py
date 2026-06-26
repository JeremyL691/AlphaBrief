"""Read-only acceptance verification route for AlphaBrief."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/v1/acceptance", tags=["acceptance"])


@router.get("/verify")
def verify_acceptance(
    project_root: str = Query(default="."),
) -> Any:
    """Return the project-level acceptance verification report."""

    root = Path(project_root)
    build_acceptance_report = _load_build_acceptance_report(root)
    return build_acceptance_report(root)


def _load_build_acceptance_report(
    project_root: Path,
) -> Callable[[Path | str | None], Any]:
    try:
        from alphabrief_acceptance import build_acceptance_report

        return build_acceptance_report
    except ModuleNotFoundError as exc:
        fallback = project_root.resolve() / "packages/alphabrief-acceptance/src"
        if fallback.is_dir():
            sys.path.insert(0, str(fallback))
            try:
                from alphabrief_acceptance import build_acceptance_report

                return build_acceptance_report
            except ModuleNotFoundError:
                pass
        raise HTTPException(
            status_code=503,
            detail="alphabrief_acceptance package is not installed",
        ) from exc


__all__ = ["router"]
