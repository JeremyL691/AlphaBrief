"""CLI subcommands for the macro module."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import typer
from alphabrief_api.db import MacroStore
from alphabrief_news.macro_release import (
    MacroReleaseStore,
    release_state,
)
from alphabrief_news.providers import (
    FredMacroProvider,
    MockMacroProvider,
    NewsProviderError,
    build_default_mock_macro,
)
from alphabrief_news.types import MacroFetchQuery

macro_app = typer.Typer(help="Fetch and inspect macro-economic indicators.")

MacroSource = Literal["mock", "fred"]


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
    source: MacroSource, indicators: list[str]
) -> MockMacroProvider | FredMacroProvider:
    if source == "mock":
        return MockMacroProvider(
            seed_indicators=build_default_mock_macro(indicators)
        )
    if source == "fred":
        return FredMacroProvider()
    raise typer.BadParameter(f"unknown macro source: {source}")


@macro_app.command("fetch")
def fetch_cmd(
    source: MacroSource = typer.Option(..., help="Macro provider source."),
    indicator: list[str] = typer.Option(
        ..., help="Indicator series to fetch (e.g. CPIAUCSL)."
    ),
    start: str = typer.Option(..., help="Start of the query window (ISO-8601)."),
    end: str = typer.Option(..., help="End of the query window (ISO-8601)."),
    data_version: str = typer.Option(
        "macro-v1", help="Data version tag to store with the indicators."
    ),
) -> None:
    """Fetch macro indicators from a provider and persist them."""
    start_dt = _parse_iso_date(start)
    end_dt = _parse_iso_date(end)

    if end_dt <= start_dt:
        raise typer.BadParameter("end must be after start")

    provider = _build_provider(source, list(indicator))
    query = MacroFetchQuery(
        indicators=list(indicator),
        start=start_dt,
        end=end_dt,
        data_version=data_version,
    )

    try:
        indicators = provider.fetch_indicators(query)
    except NewsProviderError as exc:
        typer.echo(f"Provider error [{exc.code}]: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not indicators:
        typer.echo("No indicators returned for the requested window.", err=True)
        raise typer.Exit(code=1)

    store = MacroStore()
    store.insert_indicators(indicators)
    timestamps = sorted(i.released_at for i in indicators)
    typer.echo(
        f"Fetched {len(indicators)} indicator(s) for {','.join(indicator)} "
        f"from {source} ({timestamps[0].isoformat()} to "
        f"{timestamps[-1].isoformat()})"
    )


@macro_app.command("list")
def list_cmd(
    indicator: str | None = typer.Option(
        None, help="Filter by indicator series id."
    ),
    start: str | None = typer.Option(None, help="Filter start (ISO-8601)."),
    end: str | None = typer.Option(None, help="Filter end (ISO-8601)."),
    limit: int = typer.Option(100, help="Maximum indicators to list."),
) -> None:
    """List persisted macro indicators."""
    start_dt = _parse_iso_date(start) if start else None
    end_dt = _parse_iso_date(end) if end else None

    store = MacroStore()
    rows = store.list_indicators(
        indicator_id=indicator,
        start=start_dt,
        end=end_dt,
        limit=limit,
    )

    if not rows:
        typer.echo("No indicators found.")
        return

    for ind in rows:
        typer.echo(
            f"{ind.released_at.astimezone(UTC).isoformat()} | "
            f"{ind.indicator_id} | {ind.name} | "
            f"{ind.value}"
        )


@macro_app.command("releases")
def releases_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """List ordered macro releases with explicit states (same as the API)."""
    import json
    import sys

    store = MacroReleaseStore()
    try:
        releases = store.releases()
        now = datetime.now(UTC)
        events = [
            release.with_state(release_state(release, now=now).state)
            for release in releases
        ]
    finally:
        store.close()
    json.dump(
        {"releases": events, "total": len(events)},
        sys.stdout,
        indent=2 if pretty else None,
        sort_keys=True,
        default=str,
    )
    sys.stdout.write("\n")


__all__ = ["macro_app"]
