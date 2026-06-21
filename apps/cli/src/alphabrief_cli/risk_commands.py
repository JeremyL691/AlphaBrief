"""CLI subcommands for the risk module."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import typer
from alphabrief_core import OrderIntent
from alphabrief_research import build_structured_summary
from alphabrief_risk import (
    RiskContextDecision,
    RiskGate,
    RiskLimitConfig,
    evaluate_news_macro_risk,
)

risk_app = typer.Typer(help="Inspect risk decisions and KillSwitch state.")


@risk_app.command("status")
def status_cmd() -> None:
    """Show the current RiskGate and KillSwitch status."""
    print("risk status: not yet implemented")


def _parse_risk_context(
    raw: str | None, source_label: str
) -> RiskContextDecision | None:
    """Parse a RiskContextDecision from inline JSON or return None."""
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            f"error: invalid JSON in {source_label}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(data, dict):
        print(
            f"error: {source_label} must be a JSON object",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        return RiskContextDecision.model_validate(data)
    except ValueError as exc:
        print(
            f"error: invalid RiskContextDecision in {source_label}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


@risk_app.command("check")
def check_cmd(
    intent: Path = typer.Option(  # noqa: B008 - typer pattern
        ..., "--intent", help="Path to OrderIntent JSON file."
    ),
    risk_context: str | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--risk-context",
        help=(
            "Optional RiskContextDecision as inline JSON. When provided, "
            "the gate is tightened by merging risk_tags, OR-ing "
            "requires_human_review, and reducing max_quantity by "
            "suggested_max_position_multiplier. The context can never "
            "relax existing limits."
        ),
    ),
    risk_context_file: Path | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--risk-context-file",
        help="Optional path to a JSON file with a RiskContextDecision.",
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

    if risk_context is not None and risk_context_file is not None:
        print(
            "error: --risk-context and --risk-context-file are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(1)

    parsed_context: RiskContextDecision | None = None
    if risk_context is not None:
        parsed_context = _parse_risk_context(risk_context, "--risk-context")
    elif risk_context_file is not None:
        try:
            file_text = risk_context_file.read_text()
        except OSError as exc:
            print(
                f"error: could not read risk context file {risk_context_file}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        parsed_context = _parse_risk_context(
            file_text, f"--risk-context-file {risk_context_file}"
        )

    gate = RiskGate(limits=RiskLimitConfig())
    try:
        decision = gate.evaluate(order_intent, risk_context=parsed_context)
    except Exception as exc:
        print(f"error: risk gate evaluation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"decision_id: {decision.decision_id}")
    print(f"approved: {decision.approved}")
    print(f"reason: {decision.reason}")
    print(f"risk_tags: {','.join(decision.risk_tags)}")
    print(f"requires_human_review: {decision.requires_human_review}")
    if parsed_context is not None:
        print(f"applied_risk_context: {parsed_context.decision_id}")


@risk_app.command("context")
def context_cmd(
    headlines: Path | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--headlines",
        help=(
            "Optional path to a JSON file with a list of NewsHeadline "
            "dicts. If omitted, an empty news list is used."
        ),
    ),
    indicators: Path | None = typer.Option(  # noqa: B008 - typer pattern
        None,
        "--indicators",
        help=(
            "Optional path to a JSON file with a list of "
            "MacroIndicator dicts. If omitted, an empty list is used."
        ),
    ),
    decision_id: str = typer.Option(
        "rctx_cli",
        "--decision-id",
        help="Identifier echoed in the RiskContextDecision.",
    ),
    pretty: bool = typer.Option(
        True,
        "--pretty/--compact",
        help="Pretty-print the JSON output (default: pretty).",
    ),
) -> None:
    """Show the read-only news/macro risk context decision.

    The command is read-only: it never modifies risk limits, never
    places orders, and never writes to any store. Use ``--headlines``
    and ``--indicators`` to feed a one-off summary; otherwise the
    decision is computed from empty inputs and is guaranteed to be
    the no-op (no tightening) variant.
    """
    from alphabrief_news import MacroIndicator, NewsHeadline

    headline_objs: list[NewsHeadline] = []
    if headlines is not None:
        try:
            raw_headlines = json.loads(headlines.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"error: could not load headlines from {headlines}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not isinstance(raw_headlines, list):
            print(
                "error: --headlines file must contain a JSON array of "
                "NewsHeadline objects",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            headline_objs = [
                NewsHeadline.model_validate(item) for item in raw_headlines
            ]
        except ValueError as exc:
            print(
                f"error: invalid NewsHeadline in {headlines}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    indicator_objs: list[MacroIndicator] = []
    if indicators is not None:
        try:
            raw_indicators = json.loads(indicators.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"error: could not load indicators from {indicators}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not isinstance(raw_indicators, list):
            print(
                "error: --indicators file must contain a JSON array of "
                "MacroIndicator objects",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            indicator_objs = [
                MacroIndicator.model_validate(item) for item in raw_indicators
            ]
        except ValueError as exc:
            print(
                f"error: invalid MacroIndicator in {indicators}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    summary = build_structured_summary(headline_objs, indicator_objs)
    decision: RiskContextDecision = evaluate_news_macro_risk(
        summary,
        decision_id=decision_id,
    )

    payload = {
        "summary": summary.to_dict(),
        "decision": {
            "requires_human_review": decision.requires_human_review,
            "risk_tags": list(decision.risk_tags),
            "suggested_max_position_multiplier": (
                decision.suggested_max_position_multiplier
            ),
            "notes": list(decision.notes),
            "source_summary_untrusted": decision.source_summary_untrusted,
            "decision_id": decision.decision_id,
            "context_id": decision.context_id,
        },
        "query": {
            "headlines_path": str(headlines) if headlines else None,
            "indicators_path": str(indicators) if indicators else None,
            "decision_id": decision_id,
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    }
    indent = 2 if pretty else None
    json.dump(payload, sys.stdout, indent=indent, sort_keys=True)
    sys.stdout.write("\n")


__all__ = ["risk_app"]
