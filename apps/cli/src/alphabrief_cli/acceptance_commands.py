"""CLI subcommands for project acceptance verification."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

acceptance_app = typer.Typer(help="Run AlphaBrief project acceptance checks.")


@acceptance_app.command("verify")
def verify_cmd(
    project_root: Path = typer.Option(  # noqa: B008
        Path("."),
        "--project-root",
        help="Repository root to verify.",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
        help="Pretty-print JSON output.",
    ),
) -> None:
    """Run the project acceptance verifier."""

    build_acceptance_report = _load_build_acceptance_report(project_root)
    report = build_acceptance_report(project_root)
    indent = 2 if pretty else None
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=indent, sort_keys=True)
    sys.stdout.write("\n")
    if not report.passed:
        sys.exit(1)


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
        raise typer.BadParameter(
            "alphabrief_acceptance package is not installed"
        ) from exc


__all__ = ["acceptance_app"]
