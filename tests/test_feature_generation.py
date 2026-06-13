from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import Bar
from alphabrief_data import (
    FeatureGenerationError,
    FeatureRow,
    generate_basic_features,
    load_ohlcv_csv,
)

BASE_TIME = datetime(2026, 6, 12, 9, 30, tzinfo=UTC)


def _bar(
    *,
    minutes: int,
    close: str,
    volume: str = "1",
    symbol: str = "BTC-USD",
) -> Bar:
    close_value = Decimal(close)
    return Bar(
        symbol=symbol,
        timestamp=BASE_TIME + timedelta(minutes=minutes),
        open=close_value,
        high=close_value,
        low=close_value,
        close=close_value,
        volume=Decimal(volume),
        source="unit-test",
        data_version="fixture-v1",
    )


def test_generate_basic_features_for_returns_and_sma() -> None:
    bars = [
        _bar(minutes=0, close="100", volume="10"),
        _bar(minutes=1, close="110", volume="20"),
        _bar(minutes=2, close="121", volume="30"),
    ]

    rows = generate_basic_features(bars)

    assert all(isinstance(row, FeatureRow) for row in rows)
    assert rows[0].values == {
        "return_1": None,
        "close_sma_3": None,
        "volume_sma_3": None,
    }
    assert rows[1].values["return_1"] == Decimal("0.1")
    assert rows[2].values == {
        "return_1": Decimal("0.1"),
        "close_sma_3": Decimal("110.3333333333333333333333333"),
        "volume_sma_3": Decimal("20"),
    }


def test_history_shortage_returns_none() -> None:
    rows = generate_basic_features(
        [_bar(minutes=0, close="100"), _bar(minutes=1, close="110")],
        return_periods=(2,),
        sma_windows=(3,),
    )

    assert rows[0].values["return_2"] is None
    assert rows[1].values["return_2"] is None
    assert rows[1].values["close_sma_3"] is None
    assert rows[1].values["volume_sma_3"] is None


def test_future_bar_changes_do_not_affect_earlier_features() -> None:
    original_bars = [
        _bar(minutes=0, close="100", volume="10"),
        _bar(minutes=1, close="110", volume="20"),
        _bar(minutes=2, close="120", volume="30"),
        _bar(minutes=3, close="130", volume="40"),
    ]
    changed_future_bars = [
        _bar(minutes=0, close="100", volume="10"),
        _bar(minutes=1, close="110", volume="20"),
        _bar(minutes=2, close="120", volume="30"),
        _bar(minutes=3, close="999", volume="999"),
    ]

    original_rows = generate_basic_features(original_bars)
    changed_rows = generate_basic_features(changed_future_bars)

    assert changed_rows[0].values == original_rows[0].values
    assert changed_rows[1].values == original_rows[1].values
    assert changed_rows[2].values == original_rows[2].values
    assert changed_rows[3].values != original_rows[3].values


def test_return_uses_none_when_previous_close_is_zero() -> None:
    rows = generate_basic_features(
        [_bar(minutes=0, close="0"), _bar(minutes=1, close="10")]
    )

    assert rows[1].values["return_1"] is None


def test_quality_errors_block_feature_generation() -> None:
    bars = [
        _bar(minutes=1, close="100"),
        _bar(minutes=0, close="110"),
    ]

    with pytest.raises(FeatureGenerationError, match="non_increasing_timestamp"):
        generate_basic_features(bars)


def test_mixed_symbol_blocks_feature_generation() -> None:
    bars = [
        _bar(minutes=0, close="100", symbol="BTC-USD"),
        _bar(minutes=1, close="110", symbol="ETH-USD"),
    ]

    with pytest.raises(FeatureGenerationError, match="mixed_symbols"):
        generate_basic_features(bars)


def test_warning_only_quality_issues_do_not_block_generation() -> None:
    bars = [
        _bar(minutes=0, close="100", volume="0"),
        _bar(minutes=1, close="110", volume="10"),
    ]

    rows = generate_basic_features(bars)

    assert len(rows) == 2
    assert rows[1].values["return_1"] == Decimal("0.1")


def test_invalid_feature_parameters_raise_value_error() -> None:
    with pytest.raises(ValueError, match="return_periods"):
        generate_basic_features([_bar(minutes=0, close="100")], return_periods=(0,))

    with pytest.raises(ValueError, match="sma_windows"):
        generate_basic_features([_bar(minutes=0, close="100")], sma_windows=(-1,))


def test_empty_feature_parameter_sequences_are_allowed() -> None:
    rows = generate_basic_features(
        [_bar(minutes=0, close="100")],
        return_periods=(),
        sma_windows=(),
    )

    assert rows[0].values == {}


def test_csv_loader_output_can_generate_features(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-06-12T09:30:00Z,100,100,100,100,10\n"
        "2026-06-12T09:31:00Z,110,110,110,110,20\n"
        "2026-06-12T09:32:00Z,120,120,120,120,30\n",
        encoding="utf-8",
    )
    bars = load_ohlcv_csv(
        csv_path,
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )

    rows = generate_basic_features(bars)

    assert rows[2].values["close_sma_3"] == Decimal("110")
    assert rows[2].values["volume_sma_3"] == Decimal("20")
