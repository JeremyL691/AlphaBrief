"""Rule 6: the macro/news event window (PROJECT_GUIDE 5.7).

No new exposure is opened within 30 minutes of a high-impact release for
the instrument's currencies.

This module owns the **rule**, not the classification: callers (the news
layer classifies headlines, a macro calendar provides release times) hand
in the events as ``symbol -> reason`` and the rule rejects entries while an
event is inside the window. Keeping it this way means the risk package
needs no dependency on the news or macro data planes, matching the
existing ``NewsMacroSource`` protocol convention.

Closes are exempt: the gate only applies this rule to entry intents.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

#: High-impact keywords from PROJECT_GUIDE 5.7 rule 6. The news layer
#: matches these; they are kept here as the canonical policy list.
HIGH_IMPACT_KEYWORDS: tuple[str, ...] = (
    "cpi",
    "consumer price",
    "inflation report",
    "nfp",
    "nonfarm",
    "non-farm",
    "payrolls",
    "fomc",
    "rate decision",
    "interest rate decision",
    "ecb",
    "boe",
    "boj",
    "rba",
    "boc",
    "snb",
)

#: Keywords that name a specific currency's central bank, so a headline
#: without instrument tags can still be pinned to a currency.
KEYWORD_CURRENCIES: Mapping[str, str] = {
    "fomc": "USD",
    "ecb": "EUR",
    "boe": "GBP",
    "boj": "JPY",
    "rba": "AUD",
    "boc": "CAD",
    "snb": "CHF",
}

#: Default window in minutes (PROJECT_GUIDE 5.7 rule 6).
DEFAULT_EVENT_WINDOW_MINUTES = 30


class HighImpactEventLike(Protocol):
    """Anything the rule can read: a symbol and a human-readable reason."""

    @property
    def symbol(self) -> str: ...

    def reason(self) -> str: ...


@dataclass(frozen=True)
class EventWindowVerdict:
    """One deterministic event-window verdict."""

    blocked: bool
    symbol: str
    reason: str

    def to_dict(self) -> dict[str, str | bool]:
        return {"blocked": self.blocked, "symbol": self.symbol, "reason": self.reason}


def match_high_impact_keyword(text: str) -> str | None:
    """The first high-impact keyword in the text, if any."""
    lowered = text.lower()
    for keyword in HIGH_IMPACT_KEYWORDS:
        if keyword in lowered:
            return keyword
    return None


def keyword_currency(keyword: str) -> str | None:
    """The currency a central-bank keyword is about, if it names one."""
    return KEYWORD_CURRENCIES.get(keyword.lower())


def event_window_reason(
    symbol: str, events: Mapping[str, str] | Sequence[HighImpactEventLike]
) -> str | None:
    """The reason an event blocks new exposure in ``symbol``, if any.

    ``events`` is either the already-resolved ``symbol -> reason`` mapping
    the risk context carries, or objects exposing ``symbol``/``reason()``.
    """
    if isinstance(events, Mapping):
        return events.get(symbol)
    for event in events:
        if event.symbol == symbol:
            return event.reason()
    return None


def events_within_window(
    events: Sequence[HighImpactEventLike],
    *,
    now: datetime,
    window_minutes: int = DEFAULT_EVENT_WINDOW_MINUTES,
) -> tuple[HighImpactEventLike, ...]:
    """The events whose timestamp is inside the window ending at ``now``.

    Callers pass objects with ``published_at``; anything older than the
    window (or timestamped in the future) is dropped rather than treated
    as current.
    """
    if window_minutes <= 0:
        raise ValueError("window_minutes must be positive")
    cutoff = now.astimezone(UTC) - timedelta(minutes=window_minutes)
    kept: list[HighImpactEventLike] = []
    for event in events:
        published = getattr(event, "published_at", None)
        if published is None:
            kept.append(event)
            continue
        observed = published.astimezone(UTC)
        if cutoff <= observed <= now.astimezone(UTC):
            kept.append(event)
    return tuple(kept)


def window_reason_map(
    events: Sequence[HighImpactEventLike],
    *,
    now: datetime,
    window_minutes: int = DEFAULT_EVENT_WINDOW_MINUTES,
) -> dict[str, str]:
    """Resolve events into the ``symbol -> reason`` map the gate reads."""
    resolved: dict[str, str] = {}
    for event in events_within_window(
        events, now=now, window_minutes=window_minutes
    ):
        resolved.setdefault(event.symbol, event.reason())
    return resolved


__all__ = [
    "DEFAULT_EVENT_WINDOW_MINUTES",
    "HIGH_IMPACT_KEYWORDS",
    "KEYWORD_CURRENCIES",
    "EventWindowVerdict",
    "HighImpactEventLike",
    "event_window_reason",
    "events_within_window",
    "keyword_currency",
    "match_high_impact_keyword",
    "window_reason_map",
]
