"""CLI subcommands for project acceptance verification."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import typer

acceptance_app = typer.Typer(help="Run AlphaBrief project acceptance checks.")

_Scope = Literal[
    "full",
    "paper",
    "oanda_observation",
    "oanda-observation",
    "final-release",
]


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

    if scope in ("oanda_observation", "oanda-observation"):
        from alphabrief_core.preflight import run_preflight

        _emit_report(
            run_preflight("oanda_observation", {}),
            pretty=pretty,
        )
        return
    if scope == "final-release":
        from alphabrief_core.preflight import run_preflight

        _emit_report(
            run_preflight("final_release", {}),
            pretty=pretty,
        )
        return
    build_report = _load_build_report(project_root)
    report = build_report(project_root, scope=scope)
    _emit_report(report, pretty=pretty)


@acceptance_app.command("practice-e2e")
def practice_e2e_cmd(
    scenario: str = typer.Option(
        "commissioning",
        "--scenario",
        help="E2E scenario (commissioning).",
    ),
    pretty: bool = typer.Option(
        False,
        "--pretty/--compact",
        help="Pretty-print JSON output.",
    ),
) -> None:
    """Run the controlled practice E2E commissioning drill.

    The formal proposal -> OrderIntent -> persisted RiskDecision ->
    submit -> transaction -> cleanup -> reconciliation path is the only
    permitted sequence. Missing practice credentials are recorded as
    BLOCKED_EXTERNAL without fabricating evidence or asking a question.
    """
    import os

    from alphabrief_core.preflight import run_preflight
    from alphabrief_core.recovery import run_recovery_drill
    from alphabrief_core.runbook_rehearsal import run_rehearsal

    has_credentials = bool(
        os.environ.get("ALPHABRIEF_OANDA_TOKEN")
        and os.environ.get("ALPHABRIEF_OANDA_ACCOUNT_ID")
    )
    preflight = run_preflight("oanda_observation", {})
    rehearsal = run_rehearsal({})
    recovery = run_recovery_drill(scenario=scenario, boundary_truth={})
    from alphabrief_cli.contracts import emit_json

    emit_json(
        {
            "scenario": scenario,
            "formal_path_required": True,
            "credentials_present": has_credentials,
            "status": "BLOCKED_EXTERNAL" if not has_credentials else "READY",
            "preflight_passed": preflight.passed,
            "rehearsal_passed": rehearsal.passed,
            "recovery_drill_passed": recovery.passed,
        },
        pretty=pretty,
    )


def _emit_report(report: Any, *, pretty: bool) -> None:
    indent = 2 if pretty else None
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=indent, sort_keys=True)
    sys.stdout.write("\n")
    if not report.passed:
        sys.exit(1)


@acceptance_app.command("loop")
def loop_cmd(
    work_item_id: str = typer.Argument(
        ...,
        help="Work item ID to run through the deterministic controller.",
    ),
    round_id: str = typer.Argument(
        ...,
        help="Stable round ID for this run (R-YYYYMMDD-NNN).",
    ),
    commit_message: str = typer.Argument(
        ...,
        help="Commit message for the round.",
    ),
    project_root: Path = typer.Option(  # noqa: B008
        Path("."),
        "--project-root",
        help="Repository root to control.",
    ),
    artifacts_dir: Path = typer.Option(  # noqa: B008
        Path(".agent-artifacts"),
        "--artifacts-dir",
        help="Directory for scrubbed command evidence.",
    ),
    dry_run: bool = typer.Option(  # noqa: B008
        False,
        "--dry-run",
        help="Run every gate but skip the Git commit.",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
        help="Pretty-print JSON output.",
    ),
) -> None:
    """Run one work item through the deterministic loop controller.

    The controller runs the item's declared commands (PASS/FAIL from
    exit codes only), evaluates the scope/safety/test-delta gates,
    re-verifies the frozen acceptance, appends the ledger, updates
    progress, and commits with the protocol trailers.
    """
    from alphabrief_acceptance.loop_controller import controller_run

    outcome = controller_run(
        repo_root=project_root,
        work_item_id=work_item_id,
        round_id=round_id,
        commit_message=commit_message,
        artifacts_dir=artifacts_dir,
        dry_run=dry_run,
    )
    _emit_outcome(outcome, pretty=pretty)


def _emit_outcome(outcome: Any, *, pretty: bool) -> None:
    indent = 2 if pretty else None
    json.dump(
        outcome.model_dump(mode="json"),
        sys.stdout,
        indent=indent,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    if outcome.status != "DONE":
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