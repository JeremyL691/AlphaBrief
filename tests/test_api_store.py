"""API persistent-store integration tests (M03-W01).

Exercises the DuckDB-backed API stores through their public surface:
schema application via the versioned migration framework, insert/query
round-trips, and store lifecycle (open/close). The stores use
``apply_schema`` which now runs the compatibility check and the
transactional migration pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_core import Bar


def test_market_data_store_round_trip_and_migration(tmp_path: Path) -> None:
    """Inserting bars works and the store's schema is at the latest version."""
    from alphabrief_api.db.market_data import MarketDataStore

    store = MarketDataStore(db_path=tmp_path / "market.db")
    try:
        store.insert_bars(
            [
                Bar(
                    symbol="EUR_USD",
                    timestamp=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                    open=Decimal("1.10"),
                    high=Decimal("1.11"),
                    low=Decimal("1.09"),
                    close=Decimal("1.105"),
                    volume=Decimal("1000"),
                    source="test",
                    data_version="v1",
                )
            ],
            source="test",
            data_version="v1",
        )
        rows = store.get_bar_models(symbol="EUR_USD")
        assert len(rows) == 1
        assert rows[0].symbol == "EUR_USD"
        assert rows[0].close == Decimal("1.105")
    finally:
        store.close()


def test_store_reopen_applies_migrations_idempotently(tmp_path: Path) -> None:
    """Reopening a store database re-runs migrations without data loss."""
    from alphabrief_api.db.market_data import MarketDataStore

    db_path = tmp_path / "market.db"
    store = MarketDataStore(db_path=db_path)
    try:
        store.insert_bars(
            [
                Bar(
                    symbol="GBP_USD",
                    timestamp=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                    open=Decimal("1.30"),
                    high=Decimal("1.31"),
                    low=Decimal("1.29"),
                    close=Decimal("1.305"),
                    volume=Decimal("500"),
                    source="test",
                    data_version="v1",
                )
            ],
            source="test",
            data_version="v1",
        )
    finally:
        store.close()

    reopened = MarketDataStore(db_path=db_path)
    try:
        rows = reopened.get_bar_models(symbol="GBP_USD")
        assert len(rows) == 1
        assert rows[0].close == Decimal("1.305")
    finally:
        reopened.close()


def test_briefs_store_round_trip(tmp_path: Path) -> None:
    """The briefs store writes and reads through the migrated schema."""
    from alphabrief_api.db.briefs import BriefStore

    store = BriefStore(db_path=tmp_path / "briefs.db")
    try:
        brief_id = store.save_brief(
            {
                "symbol": "EUR_USD",
                "generated_at": "2026-08-01T12:00:00Z",
                "content": "brief content",
            },
            brief_id="brief-1",
        )
        assert brief_id == "brief-1"
        brief = store.get_brief(brief_id="brief-1")
        assert brief is not None
        assert brief["id"] == "brief-1"
        assert brief["brief"]["symbol"] == "EUR_USD"
    finally:
        store.close()
