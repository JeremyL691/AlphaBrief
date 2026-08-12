"""DuckDB-backed persistent store for news headlines."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import duckdb
from alphabrief_news.providers.rss import _decode_symbols, _encode_symbols
from alphabrief_news.types import NewsCategory, NewsHeadline, SentimentLabel

from alphabrief_api.db.schema import apply_schema, drop_schema

# ---------------------------------------------------------------------------
# Default data directory
# ---------------------------------------------------------------------------

_DEFAULT_DB_DIR = Path.home() / ".alphabrief" / "data"


def _db_dir() -> Path:
    """Return the configured data directory for the DuckDB database."""
    import os

    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return _DEFAULT_DB_DIR


def _db_path() -> Path:
    """Return the full path to the DuckDB database file."""
    db_dir = _db_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "alphabrief.db"


# ---------------------------------------------------------------------------
# NewsStore
# ---------------------------------------------------------------------------


class NewsStore:
    """DuckDB-backed persistent store for news headlines."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_schema(self._conn)

    def insert_headlines(self, headlines: list[NewsHeadline]) -> int:
        """Insert or replace headlines. Returns the number inserted."""
        if not headlines:
            return 0

        rows: list[tuple[object, ...]] = []
        for headline in headlines:
            rows.append(
                (
                    headline.headline_id,
                    headline.published_at,
                    _encode_symbols(headline.symbols),
                    headline.category,
                    headline.source,
                    headline.title,
                    headline.summary,
                    headline.url,
                    headline.sentiment,
                    headline.data_version,
                )
            )

        self._conn.executemany(
            """
            INSERT INTO news_headlines (
                headline_id, published_at, symbols, category, source,
                title, summary, url, sentiment, data_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (headline_id) DO NOTHING
            """,
            rows,
        )
        return len(headlines)

    def get_headline(self, headline_id: str) -> NewsHeadline | None:
        """Return a single headline by id, or ``None`` if not found."""
        row = self._conn.execute(
            """SELECT headline_id, published_at, symbols, category,
                      source, title, summary, url, sentiment, data_version
               FROM news_headlines WHERE headline_id = ?""",
            [headline_id],
        ).fetchone()
        if row is None:
            return None
        return _row_to_headline(row)

    def list_headlines(
        self,
        symbol: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[NewsHeadline]:
        """Return headlines, optionally filtered by symbol and time window."""
        conditions: list[str] = []
        params: list[object] = []

        if symbol is not None:
            conditions.append("symbols LIKE ?")
            params.append(f'%"{symbol}"%')
        if start is not None:
            conditions.append("published_at >= ?")
            params.append(start)
        if end is not None:
            conditions.append("published_at < ?")
            params.append(end)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self._conn.execute(
            f"""SELECT headline_id, published_at, symbols, category,
                       source, title, summary, url, sentiment, data_version
                FROM news_headlines
                {where_clause}
                ORDER BY published_at DESC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()

        return [_row_to_headline(row) for row in rows]

    def clear(self) -> None:
        """Drop and recreate all tables (for test isolation)."""
        drop_schema(self._conn)
        # A fresh connection has a clean catalog: reusing a long-lived
        # connection across drop/recreate cycles can leave DuckDB
        # dependency entries that fail the next transactional commit.
        self._conn.close()
        self._conn = duckdb.connect(str(self._db_path))
        apply_schema(self._conn)

    def close(self) -> None:
        """Close the DuckDB connection."""
        try:
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_headline(row: tuple[object, ...]) -> NewsHeadline:
    """Convert a DuckDB row into a ``NewsHeadline`` domain object."""
    published_at = row[1]
    if isinstance(published_at, datetime):
        published_at = (
            published_at
            if published_at.tzinfo is not None
            else published_at.replace(tzinfo=UTC)
        ).astimezone(UTC)
    else:
        published_at = datetime.fromisoformat(str(published_at))

    symbols_raw = row[2]
    symbols = _decode_symbols(symbols_raw) if isinstance(symbols_raw, str) else []

    return NewsHeadline(
        headline_id=str(row[0]),
        published_at=published_at,
        symbols=symbols,
        category=cast(NewsCategory, str(row[3])),
        source=str(row[4]),
        title=str(row[5]),
        summary=str(row[6]),
        url=str(row[7]) if row[7] is not None else None,
        sentiment=(
            cast("SentimentLabel | None", str(row[8])) if row[8] is not None else None
        ),
        data_version=str(row[9]),
    )


__all__ = ["NewsStore"]
