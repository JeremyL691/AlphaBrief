"""CLI subcommands for the research brief module."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from alphabrief_models import (
    FakeProviderAdapter,
    ModelGateway,
    generate_daily_alpha_brief,
)

brief_app = typer.Typer(help="Generate and inspect AI research briefs.")


@brief_app.command("daily")
def daily_cmd(
    prompt_version: str = typer.Option(
        ...,
        "--prompt-version",
        help="Prompt template version, e.g. 'daily_alpha_brief:v1'.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Optional path to write the DailyAlphaBrief JSON.",
    ),
) -> None:
    """Generate a daily AlphaBrief via ModelGateway + FakeProvider."""
    try:
        provider = FakeProviderAdapter(capabilities=["structured_output"])
        gateway = ModelGateway([provider])
        result = generate_daily_alpha_brief(
            gateway,
            input_text="Generate a daily market brief",
            prompt_version=prompt_version,
        )
    except Exception as exc:
        print(f"error: brief daily failed: {exc}", file=sys.stderr)
        sys.exit(1)
    if not result.ok or result.brief is None:
        code = result.error_code.value if result.error_code is not None else "unknown"
        print(f"brief daily failed: {code}", file=sys.stderr)
        sys.exit(1)

    brief = result.brief
    print(f"brief_id: {brief.brief_id}")
    print(f"trading_day: {brief.trading_day.isoformat()}")
    print(f"generated_at: {brief.generated_at.isoformat()}")
    print(f"regime: {brief.market_brief.regime}")
    print(f"confidence: {brief.market_brief.confidence}")
    print(f"Watchlist: {len(brief.watchlist)} symbols")
    if output is not None:
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(brief.model_dump_json(indent=2))
        except OSError as exc:
            print(f"error: could not write brief to {output}: {exc}", file=sys.stderr)
            sys.exit(1)


__all__ = ["brief_app"]
