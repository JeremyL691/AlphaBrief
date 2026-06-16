"""CLI subcommands for the research brief module."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from alphabrief_models import (
    FakeProviderAdapter,
    ModelGateway,
    generate_daily_alpha_brief,
    render_brief_prompt_v2,
)
from alphabrief_research import ResearchContextBuilder

brief_app = typer.Typer(help="Generate and inspect AI research briefs.")


def _build_cli_research_context_builder() -> ResearchContextBuilder:
    """Build a ResearchContextBuilder wired to the DB stores."""
    from alphabrief_api.db import MacroStore, NewsStore
    from alphabrief_news import MacroIndicator, NewsHeadline

    news_store = NewsStore()
    macro_store = MacroStore()

    def news_loader(
        symbols: list[str], start: datetime, end: datetime, limit: int,
    ) -> list[NewsHeadline]:
        try:
            rows = news_store.list_headlines(
                symbol=symbols[0] if symbols else None,
                start=start,
                end=end,
                limit=limit,
            )
            return list(rows)
        except Exception:
            return []

    def macro_loader(
        indicators: list[str], start: datetime, end: datetime,
    ) -> list[MacroIndicator]:
        if not indicators:
            return []
        try:
            all_rows: list[MacroIndicator] = []
            for ind_id in indicators:
                rows = macro_store.list_indicators(
                    indicator_id=ind_id,
                    start=start,
                    end=end,
                    limit=20,
                )
                all_rows.extend(rows)
            return all_rows
        except Exception:
            return []

    return ResearchContextBuilder(
        news_loader=news_loader, macro_loader=macro_loader
    )


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
    include_news: bool = typer.Option(
        False,
        "--include-news",
        help="Include news context in the prompt.",
    ),
    include_macro: bool = typer.Option(
        False,
        "--include-macro",
        help="Include macro context in the prompt.",
    ),
    news_symbol: list[str] = typer.Option(
        [],
        "--news-symbol",
        help="Symbols to filter news for (repeatable).",
    ),
    macro_indicator: list[str] = typer.Option(
        [],
        "--macro-indicator",
        help="Macro indicator series to include (repeatable).",
    ),
) -> None:
    """Generate a daily AlphaBrief via ModelGateway + FakeProvider."""
    try:
        provider = FakeProviderAdapter(capabilities=["structured_output"])
        gateway = ModelGateway([provider])

        input_text = "Generate a daily market brief"
        actual_prompt_version = prompt_version

        if prompt_version.endswith("v2") or include_news or include_macro:
            builder = _build_cli_research_context_builder()
            end = datetime.now(UTC)
            start = end - timedelta(days=7)
            news_ctx = (
                builder.build_news_context(list(news_symbol), start, end, limit=20)
                if include_news
                else "(news context disabled)"
            )
            macro_ctx = (
                builder.build_macro_context(list(macro_indicator), start, end)
                if include_macro and macro_indicator
                else "(macro context disabled)"
            )
            rendered = render_brief_prompt_v2(
                "daily_alpha_brief",
                "v2",
                {
                    "trading_day": datetime.now(UTC).date().isoformat(),
                    "market_data_context": input_text,
                    "news_context": news_ctx,
                    "macro_context": macro_ctx,
                    "sentiment_summary": "",
                },
            )
            input_text = rendered.input_text
            actual_prompt_version = rendered.prompt_version

        result = generate_daily_alpha_brief(
            gateway,
            input_text=input_text,
            prompt_version=actual_prompt_version,
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
    print(
        f"News context: {'enabled' if include_news else 'disabled'}"
    )
    print(
        f"Macro context: {'enabled' if include_macro else 'disabled'}"
    )
    if output is not None:
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(brief.model_dump_json(indent=2))
        except OSError as exc:
            print(f"error: could not write brief to {output}: {exc}", file=sys.stderr)
            sys.exit(1)


__all__ = ["brief_app"]
