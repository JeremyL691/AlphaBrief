"""Production candle completeness, series separation and Decimal features."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db.market_data import MarketDataStore
from alphabrief_core import Bar
from alphabrief_execution.broker.oanda.market_sync import TIMEFRAMES
from alphabrief_trader.daily_cycle import _snapshot_fingerprint
from alphabrief_trader.data_quality import evaluate_snapshot_quality
from alphabrief_trader.market_inputs import build_market_inputs, candle_end
from alphabrief_trader.schemas import MarketInputEvidence, MarketSnapshot

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
DURATIONS = {
    "M15": timedelta(minutes=15),
    "H1": timedelta(hours=1),
    "H4": timedelta(hours=4),
    "D": timedelta(days=1),
}


def bar(timeframe: str, start: datetime, close: Decimal = Decimal("1")) -> Bar:
    return Bar(
        symbol="EUR_USD",
        timestamp=start,
        open=close,
        high=close + Decimal("0.01"),
        low=close - Decimal("0.01"),
        close=close,
        volume=Decimal("100"),
        source="oanda_practice",
        data_version=f"test:M:{timeframe}",
    )


def windows() -> dict[str, list[Bar]]:
    return {
        tf: [bar(tf, NOW - DURATIONS[tf] * (count - i)) for i in range(count)]
        for tf, count in TIMEFRAMES
    }


def snapshot(series: dict[str, list[Bar]]) -> MarketSnapshot:
    inputs = build_market_inputs(series, symbol="EUR_USD", now=NOW)
    return MarketSnapshot(
        symbol="EUR_USD",
        reference_price=Decimal("1"),
        captured_at=NOW,
        atr=inputs.atr,
        momentum_20d_pct=inputs.return_20d_pct,
        volatility_20d_pct=inputs.volatility_20d_pct,
        market_evidence=inputs.evidence,
    )


def test_complete_windows_compute_decimal_features_and_h1_end() -> None:
    loaded = snapshot(windows())
    assert loaded.market_evidence is not None
    assert loaded.market_evidence.counts == dict(TIMEFRAMES)
    assert loaded.market_evidence.latest_h1_end == NOW
    assert loaded.atr == Decimal("0.02")
    assert loaded.momentum_20d_pct == loaded.volatility_20d_pct == Decimal(0)
    assert evaluate_snapshot_quality(loaded, now=NOW).passed


@pytest.mark.parametrize("timeframe,count", TIMEFRAMES)
def test_each_short_window_is_rejected(timeframe: str, count: int) -> None:
    series = windows()
    series[timeframe] = series[timeframe][1:]
    verdict = evaluate_snapshot_quality(snapshot(series), now=NOW)
    assert not verdict.passed
    assert f"completed_{timeframe}_count_not_{count}" in verdict.reasons


@pytest.mark.parametrize(
    "field,reason",
    [
        ("atr", "atr_missing_or_not_positive"),
        ("momentum_20d_pct", "return_20d_missing"),
        ("volatility_20d_pct", "volatility_20d_missing"),
    ],
)
def test_missing_features_fail_before_model_quality(field: str, reason: str) -> None:
    loaded = snapshot(windows()).model_copy(update={field: None})
    assert reason in evaluate_snapshot_quality(loaded, now=NOW).reasons


def test_incomplete_duplicate_wrong_component_and_source_do_not_fill_window() -> None:
    series = windows()
    series["H1"] = series["H1"][1:]
    original = series["H1"][0]
    series["H1"] += [
        original,
        bar("H1", NOW),
        original.model_copy(update={"data_version": "test:B:H1"}),
        original.model_copy(update={"source": "other"}),
        original.model_copy(update={"symbol": "GBP_USD"}),
    ]
    inputs = build_market_inputs(series, symbol="EUR_USD", now=NOW)
    assert inputs.evidence.counts["H1"] == 119
    assert (
        "completed_H1_count_not_120"
        in evaluate_snapshot_quality(snapshot(series), now=NOW).reasons
    )


def test_bounded_windows_and_daily_return_volatility() -> None:
    series = windows()
    series["H1"].insert(0, bar("H1", NOW - timedelta(hours=121)))
    daily = series["D"]
    for i in range(21):
        daily[-21 + i] = bar("D", daily[-21 + i].timestamp, Decimal(2) ** i)
    inputs = build_market_inputs(series, symbol="EUR_USD", now=NOW)
    assert inputs.evidence.counts["H1"] == 120
    assert inputs.return_20d_pct == (Decimal(2) ** 20 - 1) * 100
    assert inputs.volatility_20d_pct == Decimal(0)  # Twenty 100% daily returns.
    daily[-1] = bar("D", daily[-1].timestamp, Decimal(2) ** 19)
    assert build_market_inputs(
        series, symbol="EUR_USD", now=NOW
    ).volatility_20d_pct == (
        Decimal(475).sqrt()  # Nineteen 100% returns and one 0% return.
    )


def test_h1_end_two_hour_boundary_rechecked_with_current_clock() -> None:
    loaded = snapshot(windows())
    assert evaluate_snapshot_quality(loaded, now=NOW + timedelta(hours=2)).passed
    assert (
        "completed_H1_end_stale_or_future"
        in evaluate_snapshot_quality(
            loaded, now=NOW + timedelta(hours=2, microseconds=1)
        ).reasons
    )


def test_daily_end_handles_new_york_dst_without_24_hour_guess() -> None:
    assert candle_end(datetime(2026, 3, 7, 22, tzinfo=UTC), "D") == datetime(
        2026, 3, 8, 21, tzinfo=UTC
    )
    assert candle_end(datetime(2026, 10, 31, 21, tzinfo=UTC), "D") == datetime(
        2026, 11, 1, 22, tzinfo=UTC
    )


def test_store_selects_series_before_timestamp_deduplication(tmp_path: Path) -> None:
    store = MarketDataStore(tmp_path / "market.duckdb")
    try:
        for tf, _ in TIMEFRAMES:
            item = bar(tf, NOW - timedelta(days=1))
            store.insert_bars(
                [item], source=item.source, data_version=item.data_version
            )
        for tf, _ in TIMEFRAMES:
            selected = store.get_bar_models(
                "EUR_USD", data_version_suffix=f":M:{tf}", source="oanda_practice"
            )
            assert len(selected) == 1
            assert selected[0].data_version == f"test:M:{tf}"
    finally:
        store.close()


def test_actual_ohlc_series_changes_input_fingerprint() -> None:
    original = snapshot(windows())
    series = windows()
    changed = series["M15"][0].model_copy(update={"volume": Decimal("101")})
    series["M15"][0] = changed
    assert _snapshot_fingerprint({"EUR_USD": original}) != _snapshot_fingerprint(
        {"EUR_USD": snapshot(series)}
    )


def test_evidence_rejects_naive_end_and_volatility_rejects_float() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        MarketInputEvidence(latest_h1_end=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        MarketSnapshot.model_validate({
            "symbol": "EUR_USD", "reference_price": Decimal(1),
            "captured_at": NOW, "volatility_20d_pct": 0.1,
    })


def test_production_loader_uses_h1_summary_without_mixing_timeframes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from alphabrief_api.db import NewsStore
    from alphabrief_cli import cycle_commands
    from alphabrief_news.ingestion import NewsIngestionStore

    monkeypatch.setattr(cycle_commands, "datetime", SimpleNamespace(now=lambda tz: NOW))
    database = tmp_path / "inputs.duckdb"
    store, news, health = (
        MarketDataStore(database), NewsStore(database), NewsIngestionStore(database)
    )
    try:
        for tf, bars in windows().items():
            prepared = [b.model_copy(update={
                "volume": Decimal(100 if tf == "H1" else 999),
            }) for b in bars]
            store.insert_bars(prepared, source="oanda_practice",
                              data_version=f"test:M:{tf}")
        loaded = cycle_commands._snapshot_loader(store, news, health)("EUR_USD")
        assert loaded is not None and loaded.market_evidence is not None
        assert loaded.market_evidence.counts == dict(TIMEFRAMES)
        assert loaded.captured_at == NOW
        assert loaded.recent_volume == Decimal(100)
        assert loaded.atr == Decimal("0.02")
    finally:
        health.close()
        news.close()
        store.close()
