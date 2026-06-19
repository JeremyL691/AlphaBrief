"""Unit tests for the DuckDB-backed StrategySignalStore."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.db.strategy_signals import StrategySignalStore


def _signal(
    signal_id: str = "sig_1",
    strategy_id: str = "ema_trend_v1",
    symbol: str = "BTC-USD",
    ts: str = "2024-06-01T00:00:00+00:00",
    direction: str = "long",
    confidence: float = 0.8,
    horizon: str = "1d",
) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "timestamp": ts,
        "direction": direction,
        "confidence": confidence,
        "horizon": horizon,
        "rationale": f"rationale for {signal_id}",
    }


@pytest.fixture
def store(tmp_path: Path) -> Generator[StrategySignalStore, None, None]:
    db_path = tmp_path / "test_signals.db"
    s = StrategySignalStore(db_path=str(db_path))
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_store_creates_table_on_init(store: StrategySignalStore) -> None:
    rows = store._conn.execute(
        "SELECT table_name FROM information_schema.tables ORDER BY table_name"
    ).fetchall()
    table_names = {r[0] for r in rows}
    assert "strategy_signals" in table_names


# ---------------------------------------------------------------------------
# save_signal
# ---------------------------------------------------------------------------


def test_save_signal_returns_id(store: StrategySignalStore) -> None:
    sid = store.save_signal(_signal())
    assert sid == "sig_1"


def test_save_signal_persists_full_payload(store: StrategySignalStore) -> None:
    sig = _signal()
    store.save_signal(sig)
    record = store.get_signal("sig_1")
    assert record is not None
    assert record["signal"] == sig


def test_save_signal_default_source_is_other(store: StrategySignalStore) -> None:
    store.save_signal(_signal())
    record = store.get_signal("sig_1")
    assert record is not None
    assert record["source"] == "other"


def test_save_signal_with_source_backtest(store: StrategySignalStore) -> None:
    store.save_signal(_signal(signal_id="b1"), source="backtest")
    record = store.get_signal("b1")
    assert record is not None
    assert record["source"] == "backtest"


def test_save_signal_with_source_manual(store: StrategySignalStore) -> None:
    store.save_signal(_signal(signal_id="m1"), source="manual")
    record = store.get_signal("m1")
    assert record is not None
    assert record["source"] == "manual"


def test_save_signal_rejects_invalid_source(store: StrategySignalStore) -> None:
    with pytest.raises(ValueError, match="source"):
        store.save_signal(_signal(), source="bogus")


def test_save_signal_rejects_empty_signal_id(store: StrategySignalStore) -> None:
    with pytest.raises(ValueError, match="signal_id"):
        store.save_signal(_signal(signal_id=""))


def test_save_signal_rejects_blank_strategy_id(store: StrategySignalStore) -> None:
    with pytest.raises(ValueError, match="strategy_id"):
        store.save_signal(_signal(strategy_id="  "))


def test_save_signal_rejects_blank_symbol(store: StrategySignalStore) -> None:
    with pytest.raises(ValueError, match="symbol"):
        store.save_signal(_signal(symbol=""))


def test_save_signal_rejects_blank_timestamp(store: StrategySignalStore) -> None:
    with pytest.raises(ValueError, match="timestamp"):
        store.save_signal(_signal(ts=""))


def test_save_signal_rejects_blank_direction(store: StrategySignalStore) -> None:
    with pytest.raises(ValueError, match="direction"):
        store.save_signal(_signal(direction=""))


def test_save_signal_rejects_blank_horizon(store: StrategySignalStore) -> None:
    with pytest.raises(ValueError, match="horizon"):
        store.save_signal(_signal(horizon=""))


def test_save_signal_rejects_confidence_out_of_range(
    store: StrategySignalStore,
) -> None:
    with pytest.raises(ValueError, match="confidence"):
        store.save_signal(_signal(confidence=1.5))
    with pytest.raises(ValueError, match="confidence"):
        store.save_signal(_signal(confidence=-0.1))


def test_save_signal_rejects_non_numeric_confidence(store: StrategySignalStore) -> None:
    with pytest.raises(ValueError, match="confidence"):
        store.save_signal({**_signal(), "confidence": "high"})


def test_save_signal_rejects_bool_confidence(store: StrategySignalStore) -> None:
    with pytest.raises(ValueError, match="confidence"):
        store.save_signal({**_signal(), "confidence": True})


def test_save_signal_upserts_existing(store: StrategySignalStore) -> None:
    store.save_signal(_signal(signal_id="u1", confidence=0.5))
    store.save_signal(_signal(signal_id="u1", confidence=0.9))
    record = store.get_signal("u1")
    assert record is not None
    assert record["confidence"] == 0.9


# ---------------------------------------------------------------------------
# get_signal
# ---------------------------------------------------------------------------


def test_get_signal_returns_full_record(store: StrategySignalStore) -> None:
    store.save_signal(_signal())
    record = store.get_signal("sig_1")
    assert record is not None
    assert record["signal_id"] == "sig_1"
    assert record["strategy_id"] == "ema_trend_v1"
    assert record["symbol"] == "BTC-USD"
    assert record["direction"] == "long"
    assert record["confidence"] == 0.8
    assert record["horizon"] == "1d"
    assert "created_at" in record


def test_get_signal_returns_none_for_missing(store: StrategySignalStore) -> None:
    assert store.get_signal("nope") is None


# ---------------------------------------------------------------------------
# list_signals
# ---------------------------------------------------------------------------


def test_list_signals_empty(store: StrategySignalStore) -> None:
    assert store.list_signals() == []


def test_list_signals_returns_summaries(store: StrategySignalStore) -> None:
    store.save_signal(_signal(signal_id="s1"))
    rows = store.list_signals()
    assert len(rows) == 1
    assert "signal" not in rows[0]
    assert "created_at" in rows[0]


def test_list_signals_ordered_by_ts_desc(store: StrategySignalStore) -> None:
    store.save_signal(_signal(signal_id="a", ts="2024-01-01T00:00:00+00:00"))
    store.save_signal(_signal(signal_id="b", ts="2024-06-01T00:00:00+00:00"))
    store.save_signal(_signal(signal_id="c", ts="2024-03-01T00:00:00+00:00"))
    rows = store.list_signals()
    ids = [r["signal_id"] for r in rows]
    assert ids == ["b", "c", "a"]


def test_list_signals_filter_by_strategy(store: StrategySignalStore) -> None:
    store.save_signal(_signal(signal_id="a", strategy_id="s1"))
    store.save_signal(_signal(signal_id="b", strategy_id="s2"))
    rows = store.list_signals(strategy_id="s1")
    assert len(rows) == 1
    assert rows[0]["signal_id"] == "a"


def test_list_signals_filter_by_symbol(store: StrategySignalStore) -> None:
    store.save_signal(_signal(signal_id="a", symbol="BTC-USD"))
    store.save_signal(_signal(signal_id="b", symbol="ETH-USD"))
    rows = store.list_signals(symbol="ETH-USD")
    assert len(rows) == 1
    assert rows[0]["signal_id"] == "b"


def test_list_signals_filter_by_source(store: StrategySignalStore) -> None:
    store.save_signal(_signal(signal_id="a"), source="backtest")
    store.save_signal(_signal(signal_id="b"), source="manual")
    store.save_signal(_signal(signal_id="c"), source="other")
    rows = store.list_signals(source="manual")
    assert len(rows) == 1
    assert rows[0]["signal_id"] == "b"


def test_list_signals_limit(store: StrategySignalStore) -> None:
    for i in range(5):
        store.save_signal(
            _signal(
                signal_id=f"s{i}",
                ts=f"2024-01-0{i + 1}T00:00:00+00:00",
            )
        )
    rows = store.list_signals(limit=2)
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# count_signals
# ---------------------------------------------------------------------------


def test_count_signals(store: StrategySignalStore) -> None:
    assert store.count_signals() == 0
    store.save_signal(_signal(signal_id="a", strategy_id="s1"))
    store.save_signal(_signal(signal_id="b", strategy_id="s1"))
    store.save_signal(_signal(signal_id="c", strategy_id="s2"))
    assert store.count_signals() == 3
    assert store.count_signals(strategy_id="s1") == 2
    assert store.count_signals(strategy_id="s2") == 1
    assert store.count_signals(symbol="BTC-USD") == 3
    assert store.count_signals(source="other") == 3


# ---------------------------------------------------------------------------
# list_strategy_ids
# ---------------------------------------------------------------------------


def test_list_strategy_ids(store: StrategySignalStore) -> None:
    assert store.list_strategy_ids() == []
    store.save_signal(_signal(signal_id="a", strategy_id="s2"))
    store.save_signal(_signal(signal_id="b", strategy_id="s1"))
    store.save_signal(_signal(signal_id="c", strategy_id="s2"))
    assert store.list_strategy_ids() == ["s1", "s2"]


# ---------------------------------------------------------------------------
# delete_signal
# ---------------------------------------------------------------------------


def test_delete_signal(store: StrategySignalStore) -> None:
    store.save_signal(_signal())
    assert store.delete_signal("sig_1") is True
    assert store.get_signal("sig_1") is None


def test_delete_signal_missing(store: StrategySignalStore) -> None:
    assert store.delete_signal("nope") is False


# ---------------------------------------------------------------------------
# clear / persistence
# ---------------------------------------------------------------------------


def test_clear_resets_table(store: StrategySignalStore) -> None:
    store.save_signal(_signal())
    store.clear()
    assert store.count_signals() == 0


def test_close_is_idempotent(store: StrategySignalStore) -> None:
    store.close()
    store.close()  # should not raise
