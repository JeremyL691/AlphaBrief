"""Observation runtime commands: runbook rehearsal.

Script-safe commands over the runbook rehearsal contract, emitting
stable compact JSON via the machine-readable CLI contract.
"""

from __future__ import annotations

import typer
from alphabrief_core.runbook_rehearsal import run_rehearsal

from alphabrief_cli.contracts import emit_json

observation_app = typer.Typer(
    name="observation",
    help="Observation runbook drills.",
)


@observation_app.command("rehearse")
def rehearse_cmd(
    all_drills: bool = typer.Option(
        True, "--all-drills", help="Run every rehearsal drill."
    ),
    compact: bool = typer.Option(True, "--compact/--pretty"),
) -> None:
    """Run the non-production runbook rehearsal.

    The rehearsal completes every flow step against the declared
    contract; a step without runtime truth fails closed. Rehearsal
    time never counts as real observation.
    """
    report = run_rehearsal(truth={})
    emit_json(
        {
            "all_drills": all_drills,
            "passed": report.passed,
            "counts_as_observation": report.counts_as_observation,
            "steps": [
                {
                    "step": step.step,
                    "completed": step.completed,
                    "detail": step.detail,
                }
                for step in report.steps
            ],
        },
        pretty=not compact,
    )


__all__ = ["observation_app"]
