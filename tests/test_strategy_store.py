"""Unit tests for the DuckDB-backed StrategySpecStore."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.db.strategies import StrategySpecStore


def _spec(
    strategy_id: str = "ema_trend_v1",
    name: str = "EMA Trend v1",
    version: str = "1.0.0",
) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "name": name,
        "version": version,
        "universe": {"symbols": ["BTC-USD"]},
        "timeframe": "1d",
        "entry": {"condition": "close > ema_50"},
        "exit": {"condition": "close < ema_50"},
        "risk": {"max_position_pct": "0.2"},
        "costs": {"fee_bps": "5", "slippage_bps": "10"},
        "evaluation": {
            "train_period": {"start": "2024-01-01", "end": "2024-12-31"},
            "test_period": {"start": "2025-01-01", "end": "2025-12-31"},
        },
    }


@pytest.fixture
def store(tmp_path: Path) -> Generator[StrategySpecStore, None, None]:
    db_path = tmp_path / "test_strategies.db"
    s = StrategySpecStore(db_path=str(db_path))
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_store_creates_table_on_init(store: StrategySpecStore) -> None:
    rows = store._conn.execute(
        "SELECT table_name FROM information_schema.tables ORDER BY table_name"
    ).fetchall()
    table_names = {r[0] for r in rows}
    assert "strategy_specs" in table_names


# ---------------------------------------------------------------------------
# save_spec
# ---------------------------------------------------------------------------


def test_save_spec_returns_strategy_id(store: StrategySpecStore) -> None:
    sid = store.save_spec(_spec())
    assert sid == "ema_trend_v1"


def test_save_spec_default_enabled_is_false(store: StrategySpecStore) -> None:
    store.save_spec(_spec())
    record = store.get_spec("ema_trend_v1")
    assert record is not None
    assert record["enabled"] is False


def test_save_spec_with_enabled_true(store: StrategySpecStore) -> None:
    store.save_spec(_spec(), enabled=True)
    record = store.get_spec("ema_trend_v1")
    assert record is not None
    assert record["enabled"] is True


def test_save_spec_persists_full_spec_payload(store: StrategySpecStore) -> None:
    spec = _spec()
    store.save_spec(spec)
    record = store.get_spec("ema_trend_v1")
    assert record is not None
    assert record["spec"] == spec


def test_save_spec_rejects_empty_strategy_id(store: StrategySpecStore) -> None:
    bad = _spec(strategy_id="")
    with pytest.raises(ValueError, match="strategy_id"):
        store.save_spec(bad)


def test_save_spec_rejects_blank_name(store: StrategySpecStore) -> None:
    bad = _spec(name="   ")
    with pytest.raises(ValueError, match="name"):
        store.save_spec(bad)


def test_save_spec_rejects_blank_version(store: StrategySpecStore) -> None:
    bad = _spec(version="")
    with pytest.raises(ValueError, match="version"):
        store.save_spec(bad)


def test_save_spec_upserts_existing(store: StrategySpecStore) -> None:
    store.save_spec(_spec(), enabled=False)
    store.save_spec(_spec(name="EMA Trend Updated", version="1.1.0"), enabled=True)
    record = store.get_spec("ema_trend_v1")
    assert record is not None
    assert record["name"] == "EMA Trend Updated"
    assert record["version"] == "1.1.0"
    assert record["enabled"] is True


def test_save_spec_upsert_preserves_enabled_when_not_provided(
    store: StrategySpecStore,
) -> None:
    store.save_spec(_spec(), enabled=True)
    store.save_spec(_spec(name="Updated"))
    record = store.get_spec("ema_trend_v1")
    assert record is not None
    assert record["enabled"] is True


# ---------------------------------------------------------------------------
# set_enabled
# ---------------------------------------------------------------------------


def test_set_enabled_true(store: StrategySpecStore) -> None:
    store.save_spec(_spec())
    assert store.set_enabled("ema_trend_v1", True) is True
    record = store.get_spec("ema_trend_v1")
    assert record is not None
    assert record["enabled"] is True


def test_set_enabled_false(store: StrategySpecStore) -> None:
    store.save_spec(_spec(), enabled=True)
    assert store.set_enabled("ema_trend_v1", False) is True
    record = store.get_spec("ema_trend_v1")
    assert record is not None
    assert record["enabled"] is False


def test_set_enabled_missing_returns_false(store: StrategySpecStore) -> None:
    assert store.set_enabled("does_not_exist", True) is False


def test_set_enabled_requires_bool(store: StrategySpecStore) -> None:
    store.save_spec(_spec())
    with pytest.raises(ValueError, match="bool"):
        store.set_enabled("ema_trend_v1", "true")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_spec / exists / count
# ---------------------------------------------------------------------------


def test_get_spec_missing_returns_none(store: StrategySpecStore) -> None:
    assert store.get_spec("nope") is None


def test_exists(store: StrategySpecStore) -> None:
    store.save_spec(_spec())
    assert store.exists("ema_trend_v1") is True
    assert store.exists("nope") is False


def test_count(store: StrategySpecStore) -> None:
    assert store.count() == 0
    store.save_spec(_spec(strategy_id="s1"))
    store.save_spec(_spec(strategy_id="s2"))
    assert store.count() == 2


# ---------------------------------------------------------------------------
# list_specs
# ---------------------------------------------------------------------------


def test_list_specs_empty(store: StrategySpecStore) -> None:
    assert store.list_specs() == []


def test_list_specs_returns_summaries(store: StrategySpecStore) -> None:
    store.save_spec(_spec(strategy_id="s1", name="S1"))
    store.save_spec(_spec(strategy_id="s2", name="S2"))
    rows = store.list_specs()
    assert len(rows) == 2
    ids = {r["strategy_id"] for r in rows}
    assert ids == {"s1", "s2"}
    for row in rows:
        assert "spec" not in row  # summaries exclude full spec payload
        assert "name" in row
        assert "version" in row
        assert "enabled" in row
        assert "created_at" in row
        assert "updated_at" in row


def test_list_specs_enabled_only(store: StrategySpecStore) -> None:
    store.save_spec(_spec(strategy_id="s1"), enabled=True)
    store.save_spec(_spec(strategy_id="s2"), enabled=False)
    rows = store.list_specs(enabled_only=True)
    assert len(rows) == 1
    assert rows[0]["strategy_id"] == "s1"


def test_list_specs_ordered_by_id(store: StrategySpecStore) -> None:
    store.save_spec(_spec(strategy_id="b"))
    store.save_spec(_spec(strategy_id="a"))
    store.save_spec(_spec(strategy_id="c"))
    rows = store.list_specs()
    assert [r["strategy_id"] for r in rows] == ["a", "b", "c"]


def test_list_enabled_strategy_ids(store: StrategySpecStore) -> None:
    store.save_spec(_spec(strategy_id="a"), enabled=True)
    store.save_spec(_spec(strategy_id="b"), enabled=False)
    store.save_spec(_spec(strategy_id="c"), enabled=True)
    assert store.list_enabled_strategy_ids() == ["a", "c"]


# ---------------------------------------------------------------------------
# delete_spec
# ---------------------------------------------------------------------------


def test_delete_spec(store: StrategySpecStore) -> None:
    store.save_spec(_spec())
    assert store.delete_spec("ema_trend_v1") is True
    assert store.get_spec("ema_trend_v1") is None


def test_delete_spec_missing_returns_false(store: StrategySpecStore) -> None:
    assert store.delete_spec("nope") is False


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_clear_drops_table(store: StrategySpecStore) -> None:
    store.save_spec(_spec())
    store.clear()
    assert store.count() == 0
    assert store.get_spec("ema_trend_v1") is None


def test_reopen_persists_data(tmp_path: Path) -> None:
    db_path = tmp_path / "reopen.db"
    s1 = StrategySpecStore(db_path=str(db_path))
    s1.save_spec(_spec(), enabled=True)
    s1.close()

    s2 = StrategySpecStore(db_path=str(db_path))
    try:
        record = s2.get_spec("ema_trend_v1")
        assert record is not None
        assert record["enabled"] is True
    finally:
        s2.close()


def test_close_is_idempotent(store: StrategySpecStore) -> None:
    store.close()
    store.close()  # must not raise