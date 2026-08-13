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


@observation_app.command("start")
def start_cmd(
    runbook: str = typer.Option(
        "docs/oanda_30_day_runbook.md",
        "--runbook",
        help="Path to the observation runbook.",
    ),
    compact: bool = typer.Option(True, "--compact/--pretty"),
) -> None:
    """Attempt to freeze Day 0 and commission the real observation.

    The Day 0 manifest is created only after engineering readiness,
    full OANDA practice preflight, controlled formal-path E2E, clean
    reconciliation, and isolated restore all succeed. Missing checks
    record BLOCKED_EXTERNAL blockers and never manufacture a manifest.
    """
    import hashlib
    import subprocess
    import sys
    from datetime import UTC, date, datetime
    from pathlib import Path

    from alphabrief_core.observation_controller import (
        build_day_zero_attempt,
    )
    from alphabrief_core.preflight import run_preflight
    from alphabrief_core.runbook_rehearsal import run_rehearsal

    def _git(args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                check=True,
                cwd=str(Path(__file__).resolve().parents[2]),
            )
            return result.stdout.strip()
        except Exception:
            return ""

    tree_hash = _git(["rev-parse", "HEAD^{tree}"])
    commit_hash = _git(["rev-parse", "HEAD"])
    dependency_hash = hashlib.sha256(
        subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
        ).stdout.encode("utf-8")
    ).hexdigest()[:12]

    preflight = run_preflight("oanda_observation", {})
    rehearsal = run_rehearsal({})
    attempt = build_day_zero_attempt(
        today=date.today(),
        rehearsal_dates=(
            date(2026, 8, 13),
            date(2026, 8, 14),
        ),
        gates={
            "engineering_readiness": False,
            "observation_preflight": preflight.passed,
            "practice_e2e": False,
            "clean_reconciliation": False,
            "isolated_restore": False,
        },
        manifest_fields={
            "observation_id": f"obs_{commit_hash[:8] or 'pending'}",
            "commit_hash": commit_hash or "pending",
            "tree_hash": tree_hash or "pending",
            "schema_version": "read-v1",
            "config_version": "2026-08-13.1",
            "dependency_hash": dependency_hash or "pending",
            "provider_profile": "oanda-practice",
            "account_hash": "pending",
            "catalog_version": "pending",
            "timezone": "UTC",
            "start_timestamp": datetime.now(UTC).isoformat(),
        },
    )
    emit_json(
        {
            "runbook": runbook,
            "ready": attempt.ready,
            "manifest": (
                attempt.manifest.model_dump(mode="json")
                if attempt.manifest is not None
                else None
            ),
            "blockers": list(attempt.blockers),
            "rehearsal_counts_as_observation": (
                rehearsal.counts_as_observation
            ),
        },
        pretty=not compact,
    )


@observation_app.command("verify-day")
def verify_day_cmd(
    day: int = typer.Option(0, "--day", min=0, max=30),
    compact: bool = typer.Option(True, "--compact/--pretty"),
) -> None:
    """Verify one observation day's evidence state.

    Without a frozen Day 0 manifest the day cannot be qualified;
    missing external evidence is recorded as BLOCKED_EXTERNAL.
    """
    from datetime import date

    from alphabrief_core.observation_controller import (
        qualified_start_date,
    )

    start = qualified_start_date(
        date.today(), rehearsal_dates=(date(2026, 8, 13), date(2026, 8, 14))
    )
    emit_json(
        {
            "day": day,
            "qualified": start is not None and 0 <= day <= 30,
            "status": (
                "BLOCKED_EXTERNAL"
                if start is None
                else "READY"
            ),
        },
        pretty=not compact,
    )


__all__ = ["observation_app"]
