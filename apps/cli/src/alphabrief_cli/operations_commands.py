"""Operations runtime commands: recovery drill and bounded soak.

Script-safe commands over the recovery and soak contracts, emitting
stable compact JSON via the machine-readable CLI contract.
"""

from __future__ import annotations

import typer
from alphabrief_core.recovery import (
    run_recovery_drill,
    run_soak,
    shutdown_plan,
)

from alphabrief_cli.contracts import emit_json

operations_app = typer.Typer(
    name="operations",
    help="Recovery and soak runtime drills.",
)


@operations_app.command("recovery-drill")
def recovery_drill_cmd(
    scenario: str = typer.Option(
        "all", "--scenario", help="Recovery scenario (all | per-boundary)."
    ),
    compact: bool = typer.Option(True, "--compact/--pretty"),
) -> None:
    """Run the deterministic recovery drill over every boundary."""
    plan = shutdown_plan()
    # The drill reports the shutdown plan and the per-boundary verdicts
    # from the declared recovery contract; a boundary without runtime
    # truth stays frozen (fail-closed).
    drill = run_recovery_drill(
        scenario=scenario,
        boundary_truth={},
    )
    emit_json(
        {
            "scenario": scenario,
            "shutdown_sequence": list(plan.sequence),
            "shutdown_budget_s": str(plan.budget_s),
            "passed": drill.passed,
            "boundaries": [
                {
                    "boundary": boundary.boundary,
                    "verdict": boundary.verdict,
                    "detail": boundary.detail,
                }
                for boundary in drill.boundaries
            ],
        },
        pretty=not compact,
    )


@operations_app.command("restore-drill")
def restore_drill_cmd(
    latest: bool = typer.Option(
        True, "--latest", help="Restore the latest backup."
    ),
    isolated: bool = typer.Option(
        True, "--isolated", help="Restore into an isolated directory."
    ),
    compact: bool = typer.Option(True, "--compact/--pretty"),
) -> None:
    """Run the isolated restore drill.

    The drill validates the backup-integrity invariant over the
    declared soak contract; a backup without runtime truth stays not
    preserved (fail-closed).
    """
    from alphabrief_core.recovery import run_soak

    soak = run_soak(cycles=1, invariant_truth={})
    emit_json(
        {
            "latest": latest,
            "isolated": isolated,
            "passed": soak.passed,
            "backup_integrity": next(
                (
                    invariant.preserved
                    for invariant in soak.invariants
                    if invariant.name == "backup_integrity"
                ),
                False,
            ),
        },
        pretty=not compact,
    )


@operations_app.command("soak")
def soak_cmd(
    cycles: int = typer.Option(
        1000, "--cycles", min=1, max=100000,
        help="Bounded soak cycle count.",
    ),
    compact: bool = typer.Option(True, "--compact/--pretty"),
) -> None:
    """Run the bounded soak drill over every invariant."""
    soak = run_soak(cycles=cycles, invariant_truth={})
    emit_json(
        {
            "cycles": cycles,
            "passed": soak.passed,
            "invariants": [
                {
                    "name": invariant.name,
                    "preserved": invariant.preserved,
                    "detail": invariant.detail,
                }
                for invariant in soak.invariants
            ],
        },
        pretty=not compact,
    )


__all__ = ["operations_app"]
