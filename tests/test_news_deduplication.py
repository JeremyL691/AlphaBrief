"""M09-W02: deterministic news deduplication.

- tracking parameters, URL aliases, identical content hashes, and
  bounded title similarity collapse deterministic duplicates into one
  canonical cluster (AC-M09-W02-01);
- reports with materially different claims or viewpoints remain separate
  even when their titles and entities overlap (AC-M09-W02-02).
"""

from __future__ import annotations

from datetime import UTC, datetime

from alphabrief_news.dedup import (
    DedupEvidence,
    canonicalize_url,
    cluster_news,
    dedup_verdict,
    title_similarity,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _item(**overrides: object) -> DedupEvidence:
    payload: dict[str, object] = {
        "item_id": "h-1",
        "url": "https://News.Example.com/ecb-holds?utm_source=rss&utm_medium=web#top",
        "content_hash": "sha256:abc",
        "title": "ECB holds rates steady",
        "summary": "The European Central Bank left rates unchanged.",
        "source": "news-a",
        "published_at": NOW,
    }
    payload.update(overrides)
    return DedupEvidence.model_validate(payload)


# ---------------------------------------------------------------------------
# AC-M09-W02-01: deterministic duplicates collapse
# ---------------------------------------------------------------------------


def test_canonicalize_url_strips_tracking_and_normalizes() -> None:
    assert (
        canonicalize_url(
            "https://News.Example.com/ecb-holds?utm_source=rss&utm_medium=web#top"
        )
        == "https://news.example.com/ecb-holds"
    )
    assert (
        canonicalize_url("https://news.example.com/a/")
        == "https://news.example.com/a"
    )
    assert (
        canonicalize_url("http://news.example.com:80/a")
        == "http://news.example.com/a"
    )
    assert (
        canonicalize_url("https://news.example.com/a?x=1&gclid=zz")
        == "https://news.example.com/a?x=1"
    )


def test_tracking_variants_are_duplicates() -> None:
    verdict = dedup_verdict(
        _item(
            item_id="h-2",
            url="https://news.example.com/ecb-holds?utm_campaign=summer",
            content_hash="sha256:other",
        ),
        _item(),
    )
    assert verdict.duplicate is True
    assert verdict.canonical_of == "h-1"
    assert verdict.rule == "canonical_url"


def test_url_aliases_are_duplicates() -> None:
    verdict = dedup_verdict(
        _item(
            item_id="h-3",
            url="https://news.example.com/ecb-holds/",
            content_hash="sha256:other",
        ),
        _item(),
    )
    assert verdict.duplicate is True
    assert verdict.rule == "canonical_url"


def test_identical_content_hash_is_duplicate() -> None:
    verdict = dedup_verdict(
        _item(item_id="h-4", url="https://other.example.com/story"),
        _item(),
    )
    assert verdict.duplicate is True
    assert verdict.rule == "content_hash"


def test_bounded_title_similarity_with_same_claims_is_duplicate() -> None:
    verdict = dedup_verdict(
        _item(
            item_id="h-5",
            url="https://news.example.com/ecb-holds-analysis",
            content_hash="sha256:other",
            title="ECB holds steady rates",
            summary="The European Central Bank left rates unchanged.",
        ),
        _item(),
    )
    assert verdict.duplicate is True
    assert verdict.rule == "title_similarity"


def test_cluster_news_builds_canonical_clusters() -> None:
    clusters = cluster_news(
        [
            _item(item_id="h-1"),
            _item(
                item_id="h-2",
                url="https://news.example.com/ecb-holds?utm_campaign=x",
                content_hash="sha256:other",
            ),
            _item(
                item_id="h-3",
                url="https://news.example.com/ecb-holds/",
                content_hash="sha256:other2",
            ),
            _item(
                item_id="h-4",
                url="https://news.example.com/gold-rally",
                content_hash="sha256:gold",
                title="Gold rallies on safe-haven demand",
                summary="Gold prices surged.",
            ),
        ]
    )
    by_representative = dict(clusters)
    assert by_representative["h-1"] == ("h-1", "h-2", "h-3")
    assert by_representative["h-4"] == ("h-4",)


# ---------------------------------------------------------------------------
# AC-M09-W02-02: different claims/viewpoints stay separate
# ---------------------------------------------------------------------------


def test_title_similarity_alone_never_merges_different_claims() -> None:
    verdict = dedup_verdict(
        _item(
            item_id="h-6",
            url="https://news.example.com/ecb-holds-opposition",
            content_hash="sha256:different",
            title="ECB holds rates steady: opposition grows",
            summary="Policymakers are split on the next move.",
        ),
        _item(),
    )
    # Same source, near-identical title, overlapping entities — but the
    # claims differ (different summary), so the report stays separate.
    assert verdict.duplicate is False
    assert verdict.rule == "distinct"


def test_overlapping_entities_with_different_viewpoints_stay_separate() -> None:
    clusters = cluster_news(
        [
            _item(item_id="h-1"),
            _item(
                item_id="h-7",
                url="https://news.example.com/ecb-holds-commentary",
                content_hash="sha256:viewpoint",
                title="ECB holds rates steady: market reaction",
                summary="Traders expect a cut next quarter.",
            ),
        ]
    )
    by_representative = dict(clusters)
    assert by_representative["h-1"] == ("h-1",)
    assert by_representative["h-7"] == ("h-7",)


def test_different_sources_with_similar_titles_stay_separate() -> None:
    verdict = dedup_verdict(
        _item(
            item_id="h-8",
            source="news-b",
            url="https://other.example.com/ecb",
            content_hash="sha256:other",
            title="ECB holds rates steady",
            summary="The European Central Bank left rates unchanged.",
        ),
        _item(),
    )
    # Same claims but a different source: not merged by title similarity.
    assert verdict.duplicate is False


def test_title_similarity_is_bounded_and_deterministic() -> None:
    assert title_similarity("ECB holds rates steady", "ECB holds rates steady") == 1.0
    assert title_similarity("ECB holds rates", "ECB cuts rates") < 1.0
    assert title_similarity("", "") == 1.0
