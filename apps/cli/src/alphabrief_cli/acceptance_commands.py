"""CLI subcommands for project acceptance verification."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import typer

acceptance_app = typer.Typer(help="Run AlphaBrief project acceptance checks.")

_Scope = Literal["full", "paper"]


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

    build_report = _load_build_report(project_root)
    report = build_report(project_root, scope="full")
    _emit_report(report, pretty=pretty)


@acceptance_app.command("preflight")
def preflight_cmd(
    project_root: Path = typer.Option(  # noqa: B008
        Path("."),
        "--project-root",
        help="Repository root to verify.",
    ),
    scope: _Scope = typer.Option(  # noqa: B008
        "paper",
        "--scope",
        help="Pre-flight scope. 'paper' (default) checks paper-broker readiness.",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
        help="Pretty-print JSON output.",
    ),
) -> None:
    """Run a scoped pre-flight check (default: paper-broker readiness)."""

    build_report = _load_build_report(project_root)
    report = build_report(project_root, scope=scope)
    _emit_report(report, pretty=pretty)


def _emit_report(report: Any, *, pretty: bool) -> None:
    indent = 2 if pretty else None
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=indent, sort_keys=True)
    sys.stdout.write("\n")
    if not report.passed:
        sys.exit(1)


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
        raise typer.BadParameter(
            "alphabrief_acceptance package is not installed"
        ) from exc


__all__ = ["acceptance_app"]