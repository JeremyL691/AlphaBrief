"""Read-only acceptance verification route for AlphaBrief."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/v1/acceptance", tags=["acceptance"])

_Scope = Literal["full", "paper"]


@router.get("/verify")
def verify_acceptance(
    project_root: str = Query(default="."),
) -> Any:
    """Return the project-level acceptance verification report."""

    root = Path(project_root)
    build_report = _load_build_report(root)
    return build_report(root, scope="full")


@router.get("/preflight")
def preflight_acceptance(
    project_root: str = Query(default="."),
    scope: _Scope = Query(default="paper"),  # noqa: B008
) -> Any:
    """Return a scoped pre-flight report (default: paper-broker readiness)."""

    root = Path(project_root)
    build_report = _load_build_report(root)
    return build_report(root, scope=scope)


def _load_build_report(
    project_root: Path,
) -> Callable[..., Any]:
    try:
        from alphabrief_acceptance import build_preflight_report

        return build_preflight_report
    except ModuleNotFoundError as exc:
        fallback = project_root.resolve() / "packages/alphabrief-acceptance/src"
        if fallback.is_dir():
            sys.path.insert(0, str(fallback))
            try:
                from alphabrief_acceptance import build_preflight_report

                return build_preflight_report
            except ModuleNotFoundError:
                pass
        raise HTTPException(
            status_code=503,
            detail="alphabrief_acceptance package is not installed",
        ) from exc


__all__ = ["router"]