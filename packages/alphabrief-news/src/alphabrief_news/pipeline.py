"""News ingestion pipeline: sanitize, record provenance, deduplicate.

One deterministic pass over freshly fetched headlines (PROJECT_GUIDE S4-5):

1. **Sanitize** (``untrusted.py``): every title and summary is marked
   untrusted, bounded, and its instruction-like content is neutralized.
   A headline whose text actually carried injection patterns is *not*
   handed on for model use; only its content hash is kept, so the event
   is recorded without letting the text through.
2. **Record provenance** (``ingestion.py``): each surviving item becomes
   an :class:`IngestedNewsItem` with canonical URL, content hash, fetch
   outcome, and the metadata-only retention policy (no licensed full
   text, bounded summary).
3. **Deduplicate** (``dedup.py``): canonical-URL and content-hash
   duplicates, plus bounded title-similarity matches inside the same
   fetch window, collapse to one representative per cluster.

The function is pure apart from the injected clock: the same batch always
produces the same survivors, the same provenance records, and the same
drop list.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from alphabrief_news.dedup import DedupEvidence, cluster_news
from alphabrief_news.ingestion import (
    DEFAULT_METADATA_ONLY_SUMMARY_CHARS,
    IngestedNewsItem,
    NewsIngestionResult,
    SourceLicensePolicy,
    ingested_item_from_headline,
)
from alphabrief_news.types import NewsHeadline
from alphabrief_news.untrusted import sanitize_external_text


def _headline_content_hash(headline: NewsHeadline) -> str:
    """One deterministic content hash for dedup identity."""
    return ingested_item_from_headline(
        headline,
        fetched_at=headline.published_at,
        correlation_id="dedup",
    ).content_hash

#: The retention policy for third-party news: metadata and a bounded
#: summary only, never the licensed full text.
DEFAULT_NEWS_LICENSE_POLICY = SourceLicensePolicy(
    metadata_only=True,
    max_summary_chars=DEFAULT_METADATA_ONLY_SUMMARY_CHARS,
)


@dataclass(frozen=True)
class DroppedHeadline:
    """One headline withheld from model use, with its audit hashes."""

    headline_id: str
    source: str
    content_hash: str
    reason: str
    neutralized_instructions: int


@dataclass(frozen=True)
class PreparedBatch:
    """The outcome of one pipeline pass."""

    headlines: list[NewsHeadline] = field(default_factory=list)
    ingestion: NewsIngestionResult | None = None
    dropped: list[DroppedHeadline] = field(default_factory=list)
    duplicates: int = 0

    @property
    def survivors(self) -> int:
        return len(self.headlines)


def prepare_headlines(
    headlines: Sequence[NewsHeadline],
    *,
    source: str,
    correlation_id: str,
    clock: Callable[[], datetime] | None = None,
    license_policy: SourceLicensePolicy | None = None,
) -> PreparedBatch:
    """Sanitize, record, and deduplicate one fetched batch of headlines."""
    if not source.strip():
        raise ValueError("source must not be empty")
    policy = license_policy or DEFAULT_NEWS_LICENSE_POLICY
    now = (clock or (lambda: datetime.now(UTC)))()
    survivors: list[NewsHeadline] = []
    items: list[IngestedNewsItem] = []
    dropped: list[DroppedHeadline] = []

    for headline in headlines:
        sanitized = sanitize_external_text(
            f"{headline.title}\n{headline.summary}".strip(),
            source=headline.source,
        )
        if sanitized.neutralized_instructions > 0:
            # The text tried to instruct the system: keep the hash record,
            # withhold the content (PROJECT_GUIDE 5.4).
            dropped.append(
                DroppedHeadline(
                    headline_id=headline.headline_id,
                    source=headline.source,
                    content_hash=sanitized.content_hash,
                    reason="prompt_injection",
                    neutralized_instructions=sanitized.neutralized_instructions,
                )
            )
            continue
        bounded_summary = headline.summary.strip()
        if policy.max_summary_chars is not None:
            bounded_summary = bounded_summary[: policy.max_summary_chars]
        clean = headline.model_copy(
            update={
                "title": sanitized.sanitized_text.splitlines()[0][:500],
                "summary": bounded_summary,
            }
        )
        survivors.append(clean)
        items.append(
            ingested_item_from_headline(
                clean,
                fetched_at=now,
                correlation_id=correlation_id,
                license_policy=policy,
            )
        )

    clusters = cluster_news(
        [
            DedupEvidence(
                item_id=headline.headline_id,
                url=headline.url or f"urn:alphabrief:{headline.headline_id}",
                content_hash=_headline_content_hash(headline),
                title=headline.title,
                summary=headline.summary,
                source=headline.source,
                published_at=headline.published_at,
            )
            for headline in survivors
        ]
    )
    representatives = {representative for representative, _ in clusters}
    deduped = [
        headline
        for headline in survivors
        if headline.headline_id in representatives
    ]
    duplicates = len(survivors) - len(deduped)
    kept_ids = {headline.headline_id for headline in deduped}
    return PreparedBatch(
        headlines=deduped,
        ingestion=NewsIngestionResult(
            source=source,
            correlation_id=correlation_id,
            fetch_outcome="success" if deduped else "empty",
            items=tuple(item for item in items if item.item_id in kept_ids),
            fetched_at=now,
        ),
        dropped=dropped,
        duplicates=duplicates,
    )


__all__ = [
    "DEFAULT_NEWS_LICENSE_POLICY",
    "DroppedHeadline",
    "PreparedBatch",
    "prepare_headlines",
]
