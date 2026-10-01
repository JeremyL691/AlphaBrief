"""High-impact news classification for the event window (PROJECT_GUIDE 5.7 rule 6).

Turns stored headlines into the per-instrument events the risk gate's
event-window rule reads. The classification is deterministic:

* a headline is high-impact when its title or summary carries one of the
  canonical keywords from :mod:`alphabrief_risk.event_window`;
* a keyword that names a central bank (FOMC, ECB, BoE, BoJ, RBA, BoC,
  SNB) pins the event to that currency, even when the headline itself is
  untagged;
* a generic keyword (CPI, NFP, rate decision) uses the headline's own
  currency-relevance tags; an untagged generic headline fails closed for
  every traded instrument rather than being assumed irrelevant.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from alphabrief_risk.event_window import (
    DEFAULT_EVENT_WINDOW_MINUTES,
    keyword_currency,
    match_high_impact_keyword,
)

from alphabrief_news.currency_tags import (
    GENERAL_TAG,
    TRADED_INSTRUMENTS,
    instruments_for_currencies,
)


@dataclass(frozen=True)
class HighImpactNewsEvent:
    """One high-impact headline pinned to an instrument."""

    symbol: str
    currency: str
    keyword: str
    headline_id: str
    source: str
    published_at: datetime
    detail: str

    def reason(self) -> str:
        return (
            f"{self.keyword} ({self.currency}) from {self.source} at "
            f"{self.published_at.astimezone(UTC).isoformat()}"
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "currency": self.currency,
            "keyword": self.keyword,
            "headline_id": self.headline_id,
            "source": self.source,
            "published_at": self.published_at.astimezone(UTC).isoformat(),
            "reason": self.reason(),
        }


@dataclass(frozen=True)
class HeadlineLike:
    """The headline fields the classifier reads (no store dependency)."""

    headline_id: str
    title: str
    summary: str
    source: str
    published_at: datetime
    symbols: tuple[str, ...]


def high_impact_events(
    headlines: Iterable[HeadlineLike],
    *,
    now: datetime | None = None,
    window_minutes: int = DEFAULT_EVENT_WINDOW_MINUTES,
    universe: Sequence[str] = TRADED_INSTRUMENTS,
) -> tuple[HighImpactNewsEvent, ...]:
    """The high-impact events inside the window, one per instrument."""
    if window_minutes <= 0:
        raise ValueError("window_minutes must be positive")
    observed_at = now or datetime.now(UTC)
    cutoff = observed_at.astimezone(UTC) - timedelta(minutes=window_minutes)
    events: list[HighImpactNewsEvent] = []
    for headline in headlines:
        published = headline.published_at.astimezone(UTC)
        if published < cutoff or published > observed_at.astimezone(UTC):
            continue
        keyword = match_high_impact_keyword(
            f"{headline.title} {headline.summary}"
        )
        if keyword is None:
            continue
        currency = keyword_currency(keyword)
        if currency is not None:
            targets = instruments_for_currencies((currency,))
            currency_label = currency
        else:
            targets = [
                symbol
                for symbol in headline.symbols
                if symbol in universe and symbol != GENERAL_TAG
            ]
            if not targets:
                # A generic keyword on an untagged headline cannot be
                # pinned to a currency: fail closed for the whole universe.
                targets = list(universe)
            currency_label = "MULTI"
        for symbol in targets:
            events.append(
                HighImpactNewsEvent(
                    symbol=symbol,
                    currency=currency_label,
                    keyword=keyword,
                    headline_id=headline.headline_id,
                    source=headline.source,
                    published_at=published,
                    detail=headline.title[:120],
                )
            )
    return tuple(events)


__all__ = [
    "HeadlineLike",
    "HighImpactNewsEvent",
    "high_impact_events",
]
