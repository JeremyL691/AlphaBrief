"""DuckDB-backed market data store for AlphaBrief.

``MarketDataStore`` provides persistent storage for OHLCV bars and symbol
metadata, replacing the in-memory dictionary that was used before Phase 7.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from alphabrief_core.domain import Bar

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
# Fact identity
# ---------------------------------------------------------------------------


def bar_fact_id(
    *,
    symbol: str,
    timestamp: datetime,
    source: str,
    data_version: str,
    open: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal,
) -> str:
    """Return the deterministic content address of one bar fact.

    Identical content always produces the same fact ID, so re-ingesting
    an identical fact is a no-op while different versions coexist with
    their own identity and lineage (M03-W02).
    """
    import hashlib

    canonical = (
        f"{symbol}|{_utc_iso(timestamp)}|{source}|{data_version}|"
        f"{open}|{high}|{low}|{close}|{volume}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# MarketDataStore
# ---------------------------------------------------------------------------


class MarketDataStore:
    """DuckDB-backed persistent store for OHLCV market data.

    Usage::

        store = MarketDataStore()
        store.insert_bars(bars, source="local", data_version="0.0.0")
        store.get_symbols()          # -> list[dict]
        store.get_bars("BTC")        # -> list[dict] (paginated)
        store.get_symbol_info("BTC") # -> dict | None
        store.clear()                # drop + recreate tables
        store.close()
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_schema(self._conn)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def insert_bars(
        self,
        bars: list[Bar],
        source: str,
        data_version: str,
    ) -> int:
        """Append immutable, versioned bar facts (M03-W02).

        Every bar becomes a content-addressed fact: the primary key is
        ``(symbol, timestamp, data_version, source)`` and ``fact_id`` is
        the deterministic content hash, so different source versions of
        the same symbol+timestamp coexist and re-ingesting identical
        facts is a no-op instead of an overwrite. Returns the number of
        newly inserted facts.
        """
        if not bars:
            return 0

        symbol = bars[0].symbol
        before = self._count_bars(symbol)

        rows: list[tuple[object, ...]] = []
        for bar in bars:
            rows.append(
                (
                    bar.symbol,
                    bar.timestamp,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    source,
                    data_version,
                    bar_fact_id(
                        symbol=bar.symbol,
                        timestamp=bar.timestamp,
                        source=source,
                        data_version=data_version,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                    ),
                )
            )

        self._conn.executemany(
            """
            INSERT INTO bars (
                symbol, timestamp, open, high, low, close,
                volume, source, data_version, fact_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (symbol, timestamp, data_version, source) DO NOTHING
            """,
            rows,
        )

        # Upsert symbol metadata
        timestamps = sorted(bar.timestamp for bar in bars)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO symbols (
                symbol, source, data_version, bar_count,
                time_start, time_end, loaded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                symbol,
                source,
                data_version,
                len(bars),
                timestamps[0] if timestamps else None,
                timestamps[-1] if timestamps else None,
                datetime.now(UTC),
            ],
        )

        return self._count_bars(symbol) - before

    def _count_bars(self, symbol: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM bars WHERE symbol = ?", [symbol]
        ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Read — symbols
    # ------------------------------------------------------------------

    def get_symbols(self) -> list[dict[str, object]]:
        """Return all loaded symbols with summary metadata."""
        rows = self._conn.execute(
            "SELECT symbol, source, data_version, bar_count FROM symbols"
        ).fetchall()
        return [
            {
                "symbol": row[0],
                "source": row[1],
                "data_version": row[2],
                "bar_count": row[3],
            }
            for row in rows
        ]

    def get_symbol_info(self, symbol: str) -> dict[str, object] | None:
        """Return metadata for *symbol*, or ``None`` if not loaded."""
        row = self._conn.execute(
            """SELECT symbol, source, data_version, bar_count,
                      time_start, time_end
               FROM symbols WHERE symbol = ?""",
            [symbol],
        ).fetchone()
        if row is None:
            return None

        time_start_val = row[4]
        time_end_val = row[5]

        return {
            "symbol": row[0],
            "source": row[1],
            "data_version": row[2],
            "bar_count": row[3],
            "time_start": _isoformat_optional(time_start_val),
            "time_end": _isoformat_optional(time_end_val),
        }

    # ------------------------------------------------------------------
    # Read — bars
    # ------------------------------------------------------------------

    def get_bars(
        self,
        symbol: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        """Return OHLCV bars for *symbol* with pagination.

        The decision view serves the latest data version per timestamp
        (M03-W02); versioned facts remain queryable via
        :meth:`get_bar_facts`.
        """
        rows = self._conn.execute(
            """SELECT symbol, timestamp, open, high, low, close,
                      volume, source, data_version
               FROM bars
               WHERE symbol = ?
               QUALIFY row_number() OVER (
                   PARTITION BY symbol, timestamp
                   ORDER BY data_version DESC, source
               ) = 1
               ORDER BY timestamp
               LIMIT ? OFFSET ?""",
            [symbol, limit, offset],
        ).fetchall()

        return [
            {
                "symbol": row[0],
                "timestamp": _ensure_tz_aware(row[1]),
                "open": _decimal_to_str(row[2]),
                "high": _decimal_to_str(row[3]),
                "low": _decimal_to_str(row[4]),
                "close": _decimal_to_str(row[5]),
                "volume": _decimal_to_str(row[6]),
                "source": row[7],
                "data_version": row[8],
            }
            for row in rows
        ]

    def get_bar_count(self, symbol: str) -> int:
        """Return the number of decision-view bars for *symbol*.

        Counts distinct (symbol, timestamp) pairs — one per timestamp in
        the deduplicated latest-version view (M03-W02).
        """
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT symbol || '|' || timestamp) "
            "FROM bars WHERE symbol = ?",
            [symbol],
        ).fetchone()
        return int(row[0]) if row else 0

    def symbol_exists(self, symbol: str) -> bool:
        """Return ``True`` if *symbol* is in the store."""
        row = self._conn.execute(
            "SELECT 1 FROM symbols WHERE symbol = ?", [symbol]
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def get_bar_models(self, symbol: str) -> list[Bar]:
        """Return OHLCV bars as ``Bar`` domain objects (no pagination).

        When multiple immutable versions of the same bar coexist, the
        latest ``data_version`` wins per ``(symbol, timestamp)`` so
        decision inputs see one bar per timestamp.
        """
        rows = self._conn.execute(
            """SELECT symbol, timestamp, open, high, low, close,
                      volume, source, data_version
               FROM bars
               WHERE symbol = ?
               QUALIFY row_number() OVER (
                   PARTITION BY symbol, timestamp
                   ORDER BY data_version DESC, source
               ) = 1
               ORDER BY timestamp""",
            [symbol],
        ).fetchall()

        return [
            Bar(
                symbol=str(row[0]),
                timestamp=_ensure_dt_tz(row[1]),
                open=Decimal(str(row[2])),
                high=Decimal(str(row[3])),
                low=Decimal(str(row[4])),
                close=Decimal(str(row[5])),
                volume=Decimal(str(row[6])),
                source=str(row[7]),
                data_version=str(row[8]),
            )
            for row in rows
        ]

    def get_bar_facts(
        self,
        symbol: str,
        timestamp: datetime,
    ) -> list[dict[str, Any]]:
        """Return every immutable version of one bar fact.

        Each row carries its content-addressed ``fact_id``, lineage
        (``source``/``data_version``), and UTC ``ingested_at``, ordered
        by data version, so historical snapshots can reconstruct the
        exact facts they referenced (M03-W02).
        """
        rows = self._conn.execute(
            """SELECT symbol, timestamp, open, high, low, close,
                      volume, source, data_version, fact_id, ingested_at
               FROM bars
               WHERE symbol = ? AND timestamp = ?
               ORDER BY data_version, source""",
            [symbol, timestamp],
        ).fetchall()

        return [
            {
                "symbol": str(row[0]),
                "timestamp": _ensure_dt_tz(row[1]),
                "open": _decimal_to_str(row[2]),
                "high": _decimal_to_str(row[3]),
                "low": _decimal_to_str(row[4]),
                "close": _decimal_to_str(row[5]),
                "volume": _decimal_to_str(row[6]),
                "source": str(row[7]),
                "data_version": str(row[8]),
                "fact_id": str(row[9]),
                "ingested_at": _ensure_dt_tz(row[10]),
            }
            for row in rows
        ]

    def get_bar_models_for_symbols(
        self,
        symbols: list[str],
    ) -> dict[str, list[Bar]]:
        """Return ``Bar`` domain objects for each requested symbol.

        Each unique symbol in *symbols* is loaded via the existing
        :meth:`get_bar_models` helper. Symbols that are not loaded or
        have no stored bars map to an empty list; callers are responsible
        for validating the result.
        """
        result: dict[str, list[Bar]] = {}
        for symbol in symbols:
            if symbol not in result:
                result[symbol] = self.get_bar_models(symbol)
        return result

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
            pass  # already closed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _isoformat_optional(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt: datetime = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def _ensure_tz_aware(value: Any) -> str:
    """Return an ISO-formatted UTC string from a DuckDB timestamp."""
    if isinstance(value, datetime):
        dt: datetime = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    return str(value)


def _ensure_dt_tz(value: Any) -> datetime:
    """Return a timezone-aware UTC ``datetime`` from a DuckDB timestamp."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt
    raise TypeError(f"expected datetime or str, got {type(value).__name__}")


def _decimal_to_str(value: Any) -> str:
    """Convert a DuckDB Decimal to a compact string for JSON serialization."""
    if isinstance(value, Decimal):
        s = format(value, "f").rstrip("0").rstrip(".")
        return s if s else "0"
    return str(value)


__all__ = ["MarketDataStore"]
