"""CLI subcommands for the risk module."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from alphabrief_core import OrderIntent
from alphabrief_risk import RiskGate, RiskLimitConfig

risk_app = typer.Typer(help="Inspect risk decisions and KillSwitch state.")


@risk_app.command("status")
def status_cmd() -> None:
    """Show the current RiskGate and KillSwitch status."""
    print("risk status: not yet implemented")


@risk_app.command("check")
def check_cmd(
    intent: Path = typer.Option(  # noqa: B008 - typer pattern
        ..., "--intent", help="Path to OrderIntent JSON file."
    ),
) -> None:
    """Evaluate an OrderIntent JSON file through RiskGate."""
    try:
        payload = intent.read_text()
    except OSError as exc:
        print(f"error: could not read intent file {intent}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        order_intent = OrderIntent.model_validate_json(payload)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {intent}: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"error: invalid OrderIntent in {intent}: {exc}", file=sys.stderr)
        sys.exit(1)

    gate = RiskGate(limits=RiskLimitConfig())
    try:
        decision = gate.evaluate(order_intent)
    except Exception as exc:
        print(f"error: risk gate evaluation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"decision_id: {decision.decision_id}")
    print(f"approved: {decision.approved}")
    print(f"reason: {decision.reason}")
    print(f"risk_tags: {','.join(decision.risk_tags)}")
    print(f"requires_human_review: {decision.requires_human_review}")


__all__ = ["risk_app"]
