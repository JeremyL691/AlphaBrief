"""Deterministic news deduplication (M09-W02).

Canonicalizes URLs (tracking parameters, fragments, scheme/host case,
trailing slashes), collapses tracking-parameter variants, URL aliases,
identical content hashes, and bounded title similarity into one
canonical cluster — while keeping reports with materially different
claims or viewpoints separate even when their titles and entities
overlap (REQ-NEWS-002, AC-M09-W02-01/02).
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

#: Tracking parameters stripped during URL canonicalization.
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
    }
)

#: Minimum Jaccard title similarity for a bounded title-similarity match.
TITLE_SIMILARITY_THRESHOLD = 0.85

#: Maximum published-time gap (seconds) for a title-similarity match.
MAX_TITLE_MATCH_GAP_SECONDS = 3600

#: The deterministic rule version for every dedup verdict.
DEDUP_RULE_VERSION = "2026-08-13.1"


def canonicalize_url(url: str) -> str:
    """One canonical URL: strip tracking params, fragments, and normalize.

    Deterministic and lossless for identity purposes: scheme and host
    are lower-cased, the default port is dropped, tracking parameters
    and fragments are removed, and a single trailing slash is kept.
    """
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    if ":" in netloc:
        host, _, port = netloc.partition(":")
        if (scheme == "http" and port == "80") or (
            scheme == "https" and port == "443"
        ):
            netloc = host
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in _TRACKING_PARAMS
        ],
        doseq=True,
    )
    path = parsed.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        token.lower()
        for token in text.replace("-", " ").replace("_", " ").split()
        if token
    )


def title_similarity(left: str, right: str) -> float:
    """One deterministic Jaccard similarity over title tokens."""
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens and not right_tokens:
        return 1.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


class DedupEvidence(BaseModel):
    """One dedup candidate: URL, content hash, title, summary, source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = ""
    source: str = Field(min_length=1)
    published_at: datetime


class DedupVerdict(BaseModel):
    """One deterministic duplicate verdict with its matching rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    duplicate: bool
    canonical_of: str | None = None
    rule: str = Field(min_length=1)
    rule_version: str = DEDUP_RULE_VERSION


def dedup_verdict(
    candidate: DedupEvidence,
    representative: DedupEvidence,
    *,
    title_threshold: float = TITLE_SIMILARITY_THRESHOLD,
    max_gap_seconds: int = MAX_TITLE_MATCH_GAP_SECONDS,
) -> DedupVerdict:
    """One deterministic verdict: is the candidate a duplicate?

    Rules, in order:

    1. ``canonical_url`` — same canonical URL (tracking variants and
       aliases collapse);
    2. ``content_hash`` — identical content hash;
    3. ``title_similarity`` — bounded Jaccard title similarity AND the
       same bounded summary (identical claims) AND the same source AND
       a bounded published-time gap.

    Title similarity alone never merges: reports with materially
    different claims or viewpoints stay separate even when titles and
    entities overlap (AC-M09-W02-02).
    """
    if canonicalize_url(candidate.url) == canonicalize_url(representative.url):
        return DedupVerdict(
            duplicate=True,
            canonical_of=representative.item_id,
            rule="canonical_url",
        )
    if candidate.content_hash == representative.content_hash:
        return DedupVerdict(
            duplicate=True,
            canonical_of=representative.item_id,
            rule="content_hash",
        )
    same_summary = candidate.summary.strip() == representative.summary.strip()
    gap = abs(
        (candidate.published_at - representative.published_at).total_seconds()
    )
    if (
        candidate.source == representative.source
        and same_summary
        and gap <= max_gap_seconds
        and title_similarity(candidate.title, representative.title)
        >= title_threshold
    ):
        return DedupVerdict(
            duplicate=True,
            canonical_of=representative.item_id,
            rule="title_similarity",
        )
    return DedupVerdict(
        duplicate=False,
        rule="distinct",
    )


def cluster_news(
    items: list[DedupEvidence],
    *,
    title_threshold: float = TITLE_SIMILARITY_THRESHOLD,
    max_gap_seconds: int = MAX_TITLE_MATCH_GAP_SECONDS,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Deterministic canonical clustering in input order.

    Returns ``(representative_id, member_ids)`` tuples; the first
    occurrence of a cluster is the canonical representative. The result
    is stable for identical input order.
    """
    clusters: dict[str, list[str]] = {}
    representatives: list[str] = []
    for item in items:
        matched: str | None = None
        for representative_id in representatives:
            representative = next(
                candidate
                for candidate in items
                if candidate.item_id == representative_id
            )
            verdict = dedup_verdict(
                item,
                representative,
                title_threshold=title_threshold,
                max_gap_seconds=max_gap_seconds,
            )
            if verdict.duplicate:
                matched = representative_id
                break
        if matched is None:
            clusters[item.item_id] = [item.item_id]
            representatives.append(item.item_id)
        else:
            clusters[matched].append(item.item_id)
    return tuple(
        (representative, tuple(members))
        for representative, members in clusters.items()
    )


__all__ = [
    "DEDUP_RULE_VERSION",
    "DedupEvidence",
    "DedupVerdict",
    "MAX_TITLE_MATCH_GAP_SECONDS",
    "TITLE_SIMILARITY_THRESHOLD",
    "canonicalize_url",
    "cluster_news",
    "dedup_verdict",
    "title_similarity",
]
