"""Durable quote-spread samples (PROJECT_GUIDE 5.7 rule 4).

Rule 4 rejects an entry when the current spread is more than twice the
median of the same instrument's recent samples **for the same hour of
day**. That comparison needs a real sample history, so every quote the
runtime fetches is appended here:

* one row per ``(symbol, captured_at)``, idempotent on the timestamp;
* bid, ask, spread and mid are stored as ``TEXT`` decimals to preserve
  precision, with the capture time in UTC;
* the median is computed over the most recent ``limit`` samples for the
  same symbol **and the same UTC hour**, which is what "same period"
  means operationally — a 02:00 spread must not be judged against the
  London open.

The store lives in the data plane (own DDL, like the broker recon store),
so neither the risk gate nor the execution adapter needs an application
import.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
from alphabrief_core import paths as _paths

#: How many same-hour samples the rule compares against.
SPREAD_MEDIAN_SAMPLE_LIMIT = 20

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS quote_spread_samples (
    symbol      TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    bid         TEXT NOT NULL,
    ask         TEXT NOT NULL,
    spread      TEXT NOT NULL,
    mid         TEXT NOT NULL,
    source      TEXT NOT NULL,
    PRIMARY KEY (symbol, captured_at)
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_quote_spread_symbol_time
    ON quote_spread_samples (symbol, captured_at DESC)
"""


@dataclass(frozen=True)
class QuoteSample:
    """One stored quote observation."""

    symbol: str
    captured_at: datetime
    bid: Decimal
    ask: Decimal
    spread: Decimal
    mid: Decimal
    source: str = "oanda_practice"

    def __post_init__(self) -> None:
        if self.ask < self.bid:
            raise ValueError("ask must not be below bid")
        if self.spread < 0:
            raise ValueError("spread must not be negative")


class QuoteSampleStore:
    """Append-only quote samples plus the same-hour median query."""

    def __init__(
        self, db_path: Path | str | None = None, *, read_only: bool = False
    ) -> None:
        self._db_path = Path(db_path) if db_path is not None else _paths.db_path()
        self._conn = duckdb.connect(str(self._db_path), read_only=read_only)
        if not read_only:
            self._conn.execute(_CREATE_TABLE_SQL)
            self._conn.execute(_CREATE_INDEX_SQL)

    def record(self, sample: QuoteSample) -> bool:
        """Append one sample; returns False when that instant already exists."""
        existing = self._conn.execute(
            """
            SELECT 1 FROM quote_spread_samples
            WHERE symbol = ? AND captured_at = ?
            """,
            [sample.symbol, sample.captured_at.astimezone(UTC)],
        ).fetchone()
        if existing is not None:
            return False
        self._conn.execute(
            """
            INSERT INTO quote_spread_samples (
                symbol, captured_at, bid, ask, spread, mid, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                sample.symbol,
                sample.captured_at.astimezone(UTC),
                str(sample.bid),
                str(sample.ask),
                str(sample.spread),
                str(sample.mid),
                sample.source,
            ],
        )
        return True

    def recent_spreads(
        self,
        symbol: str,
        *,
        hour: int,
        limit: int = SPREAD_MEDIAN_SAMPLE_LIMIT,
    ) -> list[Decimal]:
        """The most recent spreads for the symbol in the same UTC hour."""
        if not 0 <= hour <= 23:
            raise ValueError("hour must be within 0..23")
        rows = self._conn.execute(
            """
            SELECT spread FROM quote_spread_samples
            WHERE symbol = ?
              AND CAST(EXTRACT(hour FROM captured_at AT TIME ZONE 'UTC') AS INTEGER) = ?
            ORDER BY captured_at DESC
            LIMIT ?
            """,
            [symbol, hour, limit],
        ).fetchall()
        return [Decimal(str(row[0])) for row in rows]

    def count(self, symbol: str | None = None) -> int:
        if symbol is None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM quote_spread_samples"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM quote_spread_samples WHERE symbol = ?",
                [symbol],
            ).fetchone()
        return int(row[0]) if row else 0

    def clear(self) -> None:
        """Drop the sample table (test isolation only)."""
        self._conn.execute("DROP TABLE IF EXISTS quote_spread_samples")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "SPREAD_MEDIAN_SAMPLE_LIMIT",
    "QuoteSample",
    "QuoteSampleStore",
]
