"""Production-data workspace views (M14-W03).

Markets, News & Sentiment, and AI Research views are shaped
deterministically from API truth only: browse, search, filter, and
group over the account-discovered catalog; provenance, deduplication,
entity mapping, disagreement, macro events, degradation, and
injection-scan status for news — never reproducing unlicensed full
text; and every committee role turn, citation, dissent, degradation,
proposal or no-trade result, and immutable evidence identifier for AI
research. No view invents runtime values (REQ-UI-004, REQ-UI-005).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Markets workspace
# ---------------------------------------------------------------------------


class MarketInstrumentRow(BaseModel):
    """One catalog row with market truth for the Markets workspace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    display_name: str
    category: str
    tradeable: bool
    unsupported_reason: str | None = None
    price: str | None = None
    spread_bps: str | None = None
    freshness: str | None = None
    quality: str | None = None
    margin_rate: str | None = None


class MarketsView(BaseModel):
    """The complete browseable Markets workspace state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instruments: tuple[MarketInstrumentRow, ...]
    total: int
    groups: dict[str, int]


def build_markets_view(
    catalog_rows: list[dict[str, Any]],
    *,
    prices: dict[str, str] | None = None,
    spreads: dict[str, str] | None = None,
    freshness: dict[str, str] | None = None,
    quality: dict[str, str] | None = None,
    unsupported: dict[str, str] | None = None,
) -> MarketsView:
    """Shape the Markets workspace from catalog and market truth.

    Tradeability comes from the catalog's active state plus any
    documented unsupported reason; prices, spreads, freshness, and
    quality come only from the supplied truth maps — never invented.
    """
    prices = prices or {}
    spreads = spreads or {}
    freshness = freshness or {}
    quality = quality or {}
    unsupported = unsupported or {}

    rows: list[MarketInstrumentRow] = []
    for row in catalog_rows:
        symbol = str(row.get("name", ""))
        active = bool(row.get("active", False))
        reason = unsupported.get(symbol) if not active else None
        rows.append(
            MarketInstrumentRow(
                symbol=symbol,
                display_name=str(row.get("display_name", symbol)),
                category=str(row.get("category", "OTHER_CFD")),
                tradeable=active and reason is None,
                unsupported_reason=reason,
                price=prices.get(symbol),
                spread_bps=spreads.get(symbol),
                freshness=freshness.get(symbol),
                quality=quality.get(symbol),
                margin_rate=(
                    str(row["margin_rate"]) if row.get("margin_rate") else None
                ),
            )
        )

    ordered = tuple(sorted(rows, key=lambda r: r.symbol))
    groups: dict[str, int] = {}
    for instrument in ordered:
        groups[instrument.category] = groups.get(instrument.category, 0) + 1
    return MarketsView(
        instruments=ordered,
        total=len(ordered),
        groups=dict(sorted(groups.items())),
    )


def search_markets(view: MarketsView, query: str) -> tuple[MarketInstrumentRow, ...]:
    """Deterministic case-insensitive search over symbol and name."""
    needle = query.strip().lower()
    if not needle:
        return view.instruments
    return tuple(
        row
        for row in view.instruments
        if needle in row.symbol.lower() or needle in row.display_name.lower()
    )


def filter_markets(
    view: MarketsView, *, category: str | None = None, tradeable: bool | None = None
) -> tuple[MarketInstrumentRow, ...]:
    """Deterministic filtering by category and tradeability."""
    rows = view.instruments
    if category is not None:
        rows = tuple(row for row in rows if row.category == category)
    if tradeable is not None:
        rows = tuple(row for row in rows if row.tradeable is tradeable)
    return rows


def group_markets(view: MarketsView) -> dict[str, tuple[MarketInstrumentRow, ...]]:
    """Deterministic grouping by category."""
    groups: dict[str, list[MarketInstrumentRow]] = {}
    for row in view.instruments:
        groups.setdefault(row.category, []).append(row)
    return {category: tuple(rows) for category, rows in sorted(groups.items())}


# ---------------------------------------------------------------------------
# News & Sentiment workspace
# ---------------------------------------------------------------------------


class NewsItemRow(BaseModel):
    """One news item: provenance and metadata, never full text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    headline_id: str
    source: str
    published_at: str
    age_seconds: int | None = None
    content_hash: str | None = None
    summary: str | None = None
    symbols: tuple[str, ...] = ()
    dedup_verdict: str | None = None
    entity_links: tuple[str, ...] = ()


class SentimentRow(BaseModel):
    """One sentiment aggregate with explainable disagreement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: str
    direction: str
    intensity: str | None = None
    disagreement: str | None = None
    sample_count: int | None = None


class NewsSentimentView(BaseModel):
    """The complete News & Sentiment workspace state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    news: tuple[NewsItemRow, ...]
    sentiment: tuple[SentimentRow, ...]
    macro_events: tuple[dict[str, str], ...]
    degradation: str | None = None
    injection_scan: str | None = None


def build_news_sentiment_view(
    *,
    headlines: list[dict[str, Any]],
    sentiment_aggregates: list[dict[str, Any]] | None = None,
    macro_events: list[dict[str, Any]] | None = None,
    degradation: str | None = None,
    injection_scan: str | None = None,
    now: datetime | None = None,
) -> NewsSentimentView:
    """Shape the News & Sentiment workspace from news truth.

    Items expose provenance, age, dedup verdict, entity links, and a
    bounded summary — never the unlicensed full text. Age is computed
    from the published timestamp and the supplied clock.
    """
    clock = now or datetime.now(UTC)
    rows: list[NewsItemRow] = []
    for headline in headlines:
        published = headline.get("published_at")
        age: int | None = None
        if published is not None:
            try:
                published_dt = datetime.fromisoformat(str(published))
                age = max(0, int((clock - published_dt).total_seconds()))
            except ValueError:
                age = None
        rows.append(
            NewsItemRow(
                headline_id=str(headline.get("headline_id", "")),
                source=str(headline.get("source", "")),
                published_at=str(published or ""),
                age_seconds=age,
                content_hash=(
                    str(headline["content_hash"])
                    if headline.get("content_hash")
                    else None
                ),
                summary=(
                    str(headline["summary"]) if headline.get("summary") else None
                ),
                symbols=tuple(str(s) for s in headline.get("symbols", [])),
                dedup_verdict=(
                    str(headline["dedup_verdict"])
                    if headline.get("dedup_verdict")
                    else None
                ),
                entity_links=tuple(
                    str(link) for link in headline.get("entity_links", [])
                ),
            )
        )

    sentiments = tuple(
        SentimentRow(
            scope=str(item.get("scope", "")),
            direction=str(item.get("direction", "")),
            intensity=(
                str(item["intensity"]) if item.get("intensity") else None
            ),
            disagreement=(
                str(item["disagreement"])
                if item.get("disagreement")
                else None
            ),
            sample_count=(
                int(item["sample_count"])
                if item.get("sample_count") is not None
                else None
            ),
        )
        for item in (sentiment_aggregates or [])
    )

    macro = tuple(
        {
            key: str(value)
            for key, value in sorted(event.items())
            if key in ("release_time", "indicator", "importance", "actual", "forecast")
        }
        for event in (macro_events or [])
    )

    return NewsSentimentView(
        news=tuple(sorted(rows, key=lambda r: r.published_at, reverse=True)),
        sentiment=sentiments,
        macro_events=macro,
        degradation=degradation,
        injection_scan=injection_scan,
    )


# ---------------------------------------------------------------------------
# AI Research workspace
# ---------------------------------------------------------------------------


class RoleTurnRow(BaseModel):
    """One committee role turn with citations and dissent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    model_name: str
    view: str
    confidence: float
    citations: tuple[str, ...] = ()
    dissent: str | None = None


class ProposalRow(BaseModel):
    """One final proposal or no-trade result with evidence ids."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str | None = None
    symbol: str | None = None
    side: str | None = None
    confidence: float | None = None
    needs_human_review: bool | None = None
    evidence_ids: tuple[str, ...] = ()


class AiResearchView(BaseModel):
    """The complete AI Research workspace state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cycle_id: str
    role_turns: tuple[RoleTurnRow, ...]
    proposals: tuple[ProposalRow, ...]
    outcome: str | None = None
    degradation: str | None = None


def build_ai_research_view(
    *,
    cycle_id: str,
    votes: list[dict[str, Any]],
    plans: list[dict[str, Any]] | None = None,
    outcome: str | None = None,
    degradation: str | None = None,
) -> AiResearchView:
    """Shape the AI Research workspace from committee truth.

    Every role turn, citation, and dissent is shown; the final result
    is the proposal list or the explicit no-trade outcome. Evidence
    identifiers are carried verbatim.
    """
    turns = tuple(
        RoleTurnRow(
            role=str(vote.get("role", "")),
            model_name=str(vote.get("model_name", "")),
            view=str(vote.get("view", "")),
            confidence=float(vote.get("confidence", 0.0)),
            citations=tuple(
                str(citation) for citation in vote.get("citations", [])
            ),
            dissent=(
                str(vote["dissent"]) if vote.get("dissent") else None
            ),
        )
        for vote in votes
    )

    proposals = tuple(
        ProposalRow(
            proposal_id=(
                str(plan["proposal_id"]) if plan.get("proposal_id") else None
            ),
            symbol=str(plan.get("symbol", "")),
            side=str(plan.get("side", "")),
            confidence=(
                float(plan["confidence"]) if plan.get("confidence") else None
            ),
            needs_human_review=(
                bool(plan["needs_human_review"])
                if plan.get("needs_human_review") is not None
                else None
            ),
            evidence_ids=tuple(
                str(evidence) for evidence in plan.get("key_evidence", [])
            ),
        )
        for plan in (plans or [])
    )

    return AiResearchView(
        cycle_id=cycle_id,
        role_turns=turns,
        proposals=proposals,
        outcome=outcome,
        degradation=degradation,
    )


__all__ = [
    "AiResearchView",
    "MarketInstrumentRow",
    "MarketsView",
    "NewsItemRow",
    "NewsSentimentView",
    "ProposalRow",
    "RoleTurnRow",
    "SentimentRow",
    "build_ai_research_view",
    "build_markets_view",
    "build_news_sentiment_view",
    "filter_markets",
    "group_markets",
    "search_markets",
]
