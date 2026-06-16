"""CLI subcommands for the news module."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import typer
from alphabrief_api.db import NewsStore
from alphabrief_news.providers import (
    MockNewsProvider,
    NewsProviderError,
    RssNewsProvider,
    SecEdgarNewsProvider,
    SocialSentimentNewsProvider,
    build_default_mock_news,
)
from alphabrief_news.types import NewsFetchQuery

news_app = typer.Typer(help="Fetch and inspect news headlines.")

NewsSource = Literal["mock", "rss", "sec", "sentiment"]


def _parse_iso_date(value: str) -> datetime:
    """Parse an ISO-8601 date or datetime string into a UTC datetime."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            f"'{value}' is not a valid ISO-8601 datetime"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)

def _build_provider(
    source: NewsSource, symbols: list[str],
) -> (
    MockNewsProvider
    | RssNewsProvider
    | SecEdgarNewsProvider
    | SocialSentimentNewsProvider
):
    if source == "mock":
        return MockNewsProvider(seed_headlines=build_default_mock_news(symbols))
    if source == "rss":
        return RssNewsProvider()
    if source == "sec":
        return SecEdgarNewsProvider()
    if source == "sentiment":
        return SocialSentimentNewsProvider()
    raise typer.BadParameter(f"unknown news source: {source}")


@news_app.command("fetch")
def fetch_cmd(
    source: NewsSource = typer.Option(..., help="News provider source."),
    symbol: list[str] = typer.Option(
        ..., help="Symbol(s) to fetch headlines for."
    ),
    start: str = typer.Option(..., help="Start of the query window (ISO-8601)."),
    end: str = typer.Option(..., help="End of the query window (ISO-8601)."),
    limit: int = typer.Option(100, help="Maximum headlines to fetch."),
    data_version: str = typer.Option(
        "news-v1", help="Data version tag to store with the headlines."
    ),
) -> None:
    """Fetch news headlines from a provider and persist them."""
    for sym in symbol:
        if sym != sym.upper():
            raise typer.BadParameter(
                f"symbol must be uppercase: {sym}"
            )
    if source == "rss":
        from alphabrief_news.providers.rss import _ALLOWED_FEEDS

        invalid = [sym for sym in symbol if sym not in _ALLOWED_FEEDS]
        if invalid:
            allowed = ", ".join(sorted(_ALLOWED_FEEDS))
            raise typer.BadParameter(
                f"rss source requires a known feed name: {invalid}; "
                f"allowed: {allowed}"
            )

    start_dt = _parse_iso_date(start)
    end_dt = _parse_iso_date(end)

    if end_dt <= start_dt:
        raise typer.BadParameter("end must be after start")

    provider = _build_provider(source, symbol)
    query = NewsFetchQuery(
        symbols=list(symbol),
        start=start_dt,
        end=end_dt,
        limit=limit,
        data_version=data_version,
    )

    try:
        headlines = provider.fetch_headlines(query)
    except NewsProviderError as exc:
        typer.echo(f"Provider error [{exc.code}]: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not headlines:
        typer.echo("No headlines returned for the requested window.", err=True)
        raise typer.Exit(code=1)

    store = NewsStore()
    store.insert_headlines(headlines)
    timestamps = sorted(h.published_at for h in headlines)
    typer.echo(
        f"Fetched {len(headlines)} headlines for {','.join(symbol)} "
        f"from {source} ({timestamps[0].isoformat()} to "
        f"{timestamps[-1].isoformat()})"
    )


@news_app.command("list")
def list_cmd(
    symbol: str | None = typer.Option(None, help="Filter by symbol."),
    start: str | None = typer.Option(None, help="Filter start (ISO-8601)."),
    end: str | None = typer.Option(None, help="Filter end (ISO-8601)."),
    limit: int = typer.Option(100, help="Maximum headlines to list."),
) -> None:
    """List persisted news headlines."""
    start_dt = _parse_iso_date(start) if start else None
    end_dt = _parse_iso_date(end) if end else None

    store = NewsStore()
    rows = store.list_headlines(
        symbol=symbol,
        start=start_dt,
        end=end_dt,
        limit=limit,
    )

    if not rows:
        typer.echo("No headlines found.")
        return

    for headline in rows:
        typer.echo(
            f"{headline.published_at.astimezone(UTC).isoformat()} | "
            f"{headline.source} | {','.join(headline.symbols)} | "
            f"{headline.title}"
        )


__all__ = ["news_app"]
