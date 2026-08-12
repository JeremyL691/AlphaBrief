"""M03-W02: immutable versioned market-data facts.

Covers:
- same symbol+timestamp from different source versions coexist and
  retain lineage (AC-M03-W02-01);
- bar facts are append-only with content-addressed identities
  (AC-M03-W02-02);
- historical snapshots reconstruct identical fact IDs and hashes after
  later ingestion (AC-M03-W02-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_api.db.market_data import (
    MarketDataStore,
    bar_fact_id,
)
from alphabrief_core import Bar


def _bar(symbol: str = "EUR_USD", close: str = "1.10", high: str = "1.11") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        open=Decimal("1.09"),
        high=Decimal(high),
        low=Decimal("1.08"),
        close=Decimal(close),
        volume=Decimal("1000"),
        source="test",
        data_version="v1",
    )


def test_versions_coexist_with_lineage(tmp_path: Path) -> None:
    """AC-M03-W02-01: different source versions of one bar coexist."""
    store = MarketDataStore(db_path=tmp_path / "market.db")
    try:
        bar = _bar()
        store.insert_bars([bar], source="test", data_version="v1")
        store.insert_bars([bar], source="test", data_version="v2")

        facts = store.get_bar_facts(symbol="EUR_USD", timestamp=bar.timestamp)
        assert len(facts) == 2
        assert {fact["data_version"] for fact in facts} == {"v1", "v2"}
        assert {fact["source"] for fact in facts} == {"test"}
        assert facts[0]["fact_id"] != facts[1]["fact_id"]

        # The deduped decision view returns only the latest version.
        models = store.get_bar_models(symbol="EUR_USD")
        assert len(models) == 1
        assert models[0].data_version == "v2"
    finally:
        store.close()


def test_reingesting_identical_facts_is_a_noop(tmp_path: Path) -> None:
    """AC-M03-W02-02: identical facts append once; no overwrite."""
    store = MarketDataStore(db_path=tmp_path / "market.db")
    try:
        bar = _bar()
        first = store.insert_bars([bar], source="test", data_version="v1")
        second = store.insert_bars([bar], source="test", data_version="v1")
        assert first == 1
        assert second == 0
        facts = store.get_bar_facts(symbol="EUR_USD", timestamp=bar.timestamp)
        assert len(facts) == 1
        assert facts[0]["data_version"] == "v1"
    finally:
        store.close()


def test_fact_id_is_deterministic_content_address(tmp_path: Path) -> None:
    """AC-M03-W02-03: identical content produces the identical fact ID."""
    store = MarketDataStore(db_path=tmp_path / "market.db")
    try:
        bar = _bar()
        store.insert_bars([bar], source="test", data_version="v1")
        fact = store.get_bar_facts(symbol="EUR_USD", timestamp=bar.timestamp)[0]

        expected = bar_fact_id(
            symbol="EUR_USD",
            timestamp=bar.timestamp,
            source="test",
            data_version="v1",
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        assert fact["fact_id"] == expected

        # Later ingestion of other facts does not change the stored ID.
        store.insert_bars(
            [_bar(close="1.20", high="1.21")], source="test", data_version="v2"
        )
        again = store.get_bar_facts(symbol="EUR_USD", timestamp=bar.timestamp)[0]
        assert again["fact_id"] == fact["fact_id"]
        assert again["ingested_at"].tzinfo is not None
    finally:
        store.close()


def test_bar_facts_are_utc_stamped(tmp_path: Path) -> None:
    """AC-M03-W02-02: every fact carries a UTC ingestion timestamp."""
    store = MarketDataStore(db_path=tmp_path / "market.db")
    try:
        bar = _bar()
        store.insert_bars([bar], source="test", data_version="v1")
        fact = store.get_bar_facts(symbol="EUR_USD", timestamp=bar.timestamp)[0]
        assert fact["ingested_at"].tzinfo is not None
        assert fact["timestamp"].tzinfo is not None
    finally:
        store.close()
