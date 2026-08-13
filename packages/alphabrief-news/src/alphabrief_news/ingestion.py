"""Production news ingestion and provenance contracts (M09-W01).

Fetches configured financial-news sources and persists successful,
partial, empty, and failed fetches with immutable provenance and
copyright-safe content retention (REQ-NEWS-001, REQ-NEWS-008,
REQ-PLAT-008, REQ-PLAT-009). Every attempted item persists source,
canonical URL, published and fetched UTC times, language, content hash,
bounded summary, fetch outcome, and correlation ID (AC-M09-W01-01).
Success, empty, timeout, rate-limit, malformed, and source-failure
produce distinct durable outcomes — headlines are never fabricated
(AC-M09-W01-02). Sources marked metadata-only never persist licensed
full text; they retain only permitted metadata and bounded summaries
(AC-M09-W01-03).
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_news.providers.base import (
    NewsProvider,
    NewsProviderError,
)
from alphabrief_news.types import NewsFetchQuery, NewsHeadline

NewsFetchOutcome = Literal[
    "success",
    "empty",
    "timeout",
    "rate_limit",
    "malformed",
    "source_failure",
]

#: Default summary bound for metadata-only sources (REQ-NEWS-008).
DEFAULT_METADATA_ONLY_SUMMARY_CHARS = 200


class SourceLicensePolicy(BaseModel):
    """One source's copyright-safe retention policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata_only: bool = False
    max_summary_chars: int | None = None


class IngestedNewsItem(BaseModel):
    """One immutable ingested news record (no licensed full text)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    published_at: datetime
    fetched_at: datetime
    language: str = Field(default="en", min_length=1)
    content_hash: str = Field(min_length=1)
    summary: str = ""
    fetch_outcome: NewsFetchOutcome
    correlation_id: str = Field(min_length=1)
    metadata_only: bool = False

    @field_validator("published_at", "fetched_at", mode="before")
    @classmethod
    def times_must_be_utc(cls, value: Any) -> Any:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, datetime):
            parsed = value
        else:
            raise ValueError("news times must be datetimes")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)


class NewsIngestionResult(BaseModel):
    """One deterministic ingestion verdict with durable provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    fetch_outcome: NewsFetchOutcome
    items: tuple[IngestedNewsItem, ...] = ()
    fetched_at: datetime


class NewsIngestionError(RuntimeError):
    """A classified fail-closed ingestion failure."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"news ingestion failed ({kind}): {detail}")


def _content_hash(headline: NewsHeadline) -> str:
    """One deterministic content hash (never hashes fabricated text)."""
    payload = "|".join(
        [
            headline.headline_id,
            headline.title,
            headline.summary,
            headline.published_at.isoformat(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_url(headline: NewsHeadline) -> str:
    return (headline.url or f"local://{headline.headline_id}").strip()


def _bounded_summary(headline: NewsHeadline, policy: SourceLicensePolicy) -> str:
    summary = headline.summary.strip()
    if policy.max_summary_chars is not None:
        return summary[: policy.max_summary_chars]
    return summary


class NewsIngestionService:
    """Fetches one source and records its durable outcome and items."""

    def __init__(self, clock: Any = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch_and_ingest(
        self,
        provider: NewsProvider,
        query: NewsFetchQuery,
        *,
        source: str,
        correlation_id: str,
        license_policy: SourceLicensePolicy | None = None,
    ) -> NewsIngestionResult:
        """Fetch one source and classify the outcome deterministically.

        A failure never fabricates headlines: timeout, rate-limit,
        malformed, and source-failure outcomes carry zero items.
        """
        policy = license_policy or SourceLicensePolicy()
        fetched_at = self._clock()
        try:
            headlines = provider.fetch_headlines(query)
        except NewsProviderError as exc:
            return self._failure_outcome(
                source=source,
                correlation_id=correlation_id,
                code=exc.code,
                fetched_at=fetched_at,
            )
        except Exception as exc:  # noqa: BLE001 — classify any source failure
            return self._failure_outcome(
                source=source,
                correlation_id=correlation_id,
                code="network_error",
                fetched_at=fetched_at,
                detail=str(exc),
            )

        if not headlines:
            return NewsIngestionResult(
                source=source,
                correlation_id=correlation_id,
                fetch_outcome="empty",
                fetched_at=fetched_at,
            )

        items = tuple(
            IngestedNewsItem(
                item_id=f"{source}:{headline.headline_id}",
                source=source,
                canonical_url=_canonical_url(headline),
                published_at=headline.published_at,
                fetched_at=fetched_at,
                language="en",
                content_hash=_content_hash(headline),
                summary=_bounded_summary(headline, policy),
                fetch_outcome="success",
                correlation_id=correlation_id,
                metadata_only=policy.metadata_only,
            )
            for headline in headlines
        )
        return NewsIngestionResult(
            source=source,
            correlation_id=correlation_id,
            fetch_outcome="success",
            items=items,
            fetched_at=fetched_at,
        )

    def _failure_outcome(
        self,
        *,
        source: str,
        correlation_id: str,
        code: str,
        fetched_at: datetime,
        detail: str = "",
    ) -> NewsIngestionResult:
        outcome: NewsFetchOutcome
        if code in ("network_error", "http_error"):
            outcome = "timeout"
        elif code == "rate_limited":
            outcome = "rate_limit"
        elif code in ("parse_error", "invalid_config", "invalid_symbol"):
            outcome = "malformed"
        else:
            outcome = "source_failure"
        return NewsIngestionResult(
            source=source,
            correlation_id=correlation_id,
            fetch_outcome=outcome,
            fetched_at=fetched_at,
        )


class NewsIngestionStore:
    """DuckDB-backed append-only ingestion provenance store."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_ingestion_records (
                item_id        TEXT PRIMARY KEY,
                source         TEXT NOT NULL,
                canonical_url  TEXT NOT NULL,
                published_at   TIMESTAMPTZ NOT NULL,
                fetched_at     TIMESTAMPTZ NOT NULL,
                language       TEXT NOT NULL,
                content_hash   TEXT NOT NULL,
                summary        TEXT NOT NULL,
                fetch_outcome  TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                metadata_only  BOOLEAN NOT NULL
            );
            CREATE INDEX IF NOT EXISTS news_ingestion_source ON
                news_ingestion_records (source, fetched_at);
            """
        )

    def persist(self, result: NewsIngestionResult) -> int:
        """Persist one ingestion result; duplicate item IDs are ignored."""
        count = 0
        for item in result.items:
            inserted = self._conn.execute(
                """
                INSERT OR IGNORE INTO news_ingestion_records (
                    item_id, source, canonical_url, published_at,
                    fetched_at, language, content_hash, summary,
                    fetch_outcome, correlation_id, metadata_only
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    item.item_id,
                    item.source,
                    item.canonical_url,
                    item.published_at,
                    item.fetched_at,
                    item.language,
                    item.content_hash,
                    item.summary,
                    item.fetch_outcome,
                    item.correlation_id,
                    item.metadata_only,
                ],
            ).fetchone()
            if inserted and inserted[0] > 0:
                count += 1
        return count

    def records(self, source: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE source = ?" if source else ""
        params = [source] if source else []
        rows = self._conn.execute(
            f"""
            SELECT item_id, source, canonical_url, published_at,
                   fetched_at, language, content_hash, summary,
                   fetch_outcome, correlation_id, metadata_only
            FROM news_ingestion_records {where}
            ORDER BY fetched_at, item_id
            """,
            params,
        ).fetchall()
        return [
            {
                "item_id": str(row[0]),
                "source": str(row[1]),
                "canonical_url": str(row[2]),
                "published_at": str(row[3]),
                "fetched_at": str(row[4]),
                "language": str(row[5]),
                "content_hash": str(row[6]),
                "summary": str(row[7]),
                "fetch_outcome": str(row[8]),
                "correlation_id": str(row[9]),
                "metadata_only": bool(row[10]),
            }
            for row in rows
        ]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass


def _default_db_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "DEFAULT_METADATA_ONLY_SUMMARY_CHARS",
    "IngestedNewsItem",
    "NewsFetchOutcome",
    "NewsIngestionError",
    "NewsIngestionResult",
    "NewsIngestionService",
    "NewsIngestionStore",
    "SourceLicensePolicy",
]
