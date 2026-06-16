"""Rule-based sentiment analysis for AlphaBrief news headlines.

The :class:`RuleBasedSentimentAnalyzer` is a deterministic, keyword-driven
heuristic that produces a :class:`SentimentLabel` for a single headline
or a batch of headlines. The analyzer is intentionally simple and
transparent — it does not call any model and does not hide its rules.
Every keyword list is a small, fixed mapping; new words should only be
added with explicit review because the analyzer is part of the
research-context surface.

All outputs are **background context** for research prompts and must
not be used as a trading signal on their own. The RiskGate remains
the single authority on what orders may be submitted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from alphabrief_news import NewsHeadline, SentimentLabel

_POSITIVE_KEYWORDS: frozenset[str] = frozenset(
    {
        "beat", "beats", "surge", "surges", "rally", "rallies", "gain",
        "gains", "growth", "strong", "upgrade", "upgraded", "outperform",
        "record high", "expansion", "profit", "profits", "bullish", "win",
        "wins", "approve", "approved", "milestone", "breakthrough",
    }
)
_NEGATIVE_KEYWORDS: frozenset[str] = frozenset(
    {
        "miss", "misses", "missed", "decline", "declines", "fall", "falls",
        "drop", "drops", "weak", "downgrade", "downgraded", "underperform",
        "loss", "losses", "bearish", "concern", "concerns", "warn", "warns",
        "warning", "lawsuit", "fraud", "probe", "investigation", "halt",
        "halted", "ban", "banned", "crash", "crisis", "layoff", "layoffs",
        "default", "defaulted",
    }
)


def _tokenize(text: str) -> list[str]:
    lowered = text.lower()
    out: list[str] = []
    current: list[str] = []
    for char in lowered:
        if char.isalnum():
            current.append(char)
        else:
            if current:
                out.append("".join(current))
                current = []
    if current:
        out.append("".join(current))
    return out


def _score_text(text: str) -> int:
    tokens = _tokenize(text)
    score = 0
    for token in tokens:
        if token in _POSITIVE_KEYWORDS:
            score += 1
        elif token in _NEGATIVE_KEYWORDS:
            score -= 1
    joined = " ".join(tokens)
    for phrase in _POSITIVE_KEYWORDS:
        if " " in phrase and phrase in joined:
            score += 1
    for phrase in _NEGATIVE_KEYWORDS:
        if " " in phrase and phrase in joined:
            score -= 1
    return score


class RuleBasedSentimentAnalyzer:
    """Deterministic keyword-based sentiment scorer."""

    def __init__(
        self,
        positive_keywords: Iterable[str] | None = None,
        negative_keywords: Iterable[str] | None = None,
    ) -> None:
        if positive_keywords is None:
            self._positive: frozenset[str] = _POSITIVE_KEYWORDS
        else:
            self._positive = frozenset(
                keyword.lower().strip() for keyword in positive_keywords
            )
        if negative_keywords is None:
            self._negative: frozenset[str] = _NEGATIVE_KEYWORDS
        else:
            self._negative = frozenset(
                keyword.lower().strip() for keyword in negative_keywords
            )

    def score_text(self, text: str) -> int:
        """Return the integer sentiment score for a raw text."""
        if not text:
            return 0
        tokens = _tokenize(text)
        score = 0
        for token in tokens:
            if token in self._positive:
                score += 1
            elif token in self._negative:
                score -= 1
        joined = " ".join(tokens)
        for phrase in self._positive:
            if " " in phrase and phrase in joined:
                score += 1
        for phrase in self._negative:
            if " " in phrase and phrase in joined:
                score -= 1
        return score

    def classify_text(self, text: str) -> SentimentLabel:
        """Classify a raw text into a sentiment label."""
        score = self.score_text(text)
        if score > 0:
            return "positive"
        if score < 0:
            return "negative"
        return "neutral"

    def classify_headline(self, headline: NewsHeadline) -> SentimentLabel:
        """Classify a NewsHeadline by title and summary."""
        return self.classify_text(f"{headline.title} {headline.summary}")

    def classify_batch(
        self,
        headlines: Iterable[NewsHeadline],
    ) -> Mapping[str, SentimentLabel]:
        """Classify a batch of headlines, keyed by headline_id."""
        return {
            headline.headline_id: self.classify_headline(headline)
            for headline in headlines
        }

    def annotate(self, headline: NewsHeadline) -> NewsHeadline:
        """Return a new NewsHeadline with ``sentiment`` filled in."""
        label: SentimentLabel | None = self.classify_headline(headline)
        return headline.model_copy(update={"sentiment": label})


def sentiment_summary(headlines: Iterable[NewsHeadline]) -> str:
    """Build a small text summary of sentiment counts.

    Returns a deterministic one-line summary like
    ``"positive=3, negative=1, neutral=2, unknown=0"`` suitable for
    inclusion in research prompts.
    """
    stats: dict[str, int] = {
        "positive": 0,
        "negative": 0,
        "neutral": 0,
        "unknown": 0,
    }
    for headline in headlines:
        label = headline.sentiment
        if label is None:
            stats["unknown"] += 1
        else:
            stats[label] = stats.get(label, 0) + 1
    parts = [
        f"{name}={count}"
        for name, count in stats.items()
        if count > 0
    ]
    if not parts:
        return "no sentiment information"
    return ", ".join(parts)


__all__ = [
    "RuleBasedSentimentAnalyzer",
    "sentiment_summary",
]
