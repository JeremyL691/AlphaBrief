from datetime import UTC
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_data import CsvBarLoader, MarketDataLoadError, load_ohlcv_csv


def _write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_load_ohlcv_csv_returns_valid_bars(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "btc.csv",
        "timestamp,open,high,low,close,volume\n"
        "2026-06-12T09:30:00,100,110,95,105,123.45\n"
        "2026-06-12T09:31:00,105,112,101,111,10\n",
    )

    bars = load_ohlcv_csv(
        csv_path,
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )

    assert len(bars) == 2
    assert bars[0].symbol == "BTC-USD"
    assert bars[0].timestamp.utcoffset() == UTC.utcoffset(None)
    assert bars[0].close == Decimal("105")
    assert bars[0].source == "unit-test"
    assert bars[0].data_version == "fixture-v1"


def test_naive_timestamp_uses_configured_timezone(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "bars.csv",
        "timestamp,open,high,low,close,volume\n"
        "2026-06-12T09:30:00,100,110,95,105,1\n",
    )

    bars = CsvBarLoader(timezone="Asia/Shanghai").load(
        csv_path,
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )

    offset = bars[0].timestamp.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 8 * 60 * 60


def test_timezone_aware_timestamp_preserves_offset(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "bars.csv",
        "timestamp,open,high,low,close,volume\n"
        "2026-06-12T09:30:00-04:00,100,110,95,105,1\n",
    )

    bars = load_ohlcv_csv(
        csv_path,
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )

    offset = bars[0].timestamp.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == -4 * 60 * 60


def test_missing_required_column_fails(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "missing.csv",
        "timestamp,open,high,low,close\n"
        "2026-06-12T09:30:00,100,110,95,105\n",
    )

    with pytest.raises(MarketDataLoadError, match="missing columns: volume"):
        load_ohlcv_csv(
            csv_path,
            symbol="BTC-USD",
            source="unit-test",
            data_version="fixture-v1",
        )


def test_invalid_decimal_fails_with_row_number(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "bad_decimal.csv",
        "timestamp,open,high,low,close,volume\n"
        "2026-06-12T09:30:00,not-a-number,110,95,105,1\n",
    )

    with pytest.raises(MarketDataLoadError, match="row 2:.*open"):
        load_ohlcv_csv(
            csv_path,
            symbol="BTC-USD",
            source="unit-test",
            data_version="fixture-v1",
        )


def test_invalid_timestamp_fails_with_row_number(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "bad_time.csv",
        "timestamp,open,high,low,close,volume\n"
        "not-a-timestamp,100,110,95,105,1\n",
    )

    with pytest.raises(MarketDataLoadError, match="row 2:.*timestamp"):
        load_ohlcv_csv(
            csv_path,
            symbol="BTC-USD",
            source="unit-test",
            data_version="fixture-v1",
        )


def test_empty_cell_fails_with_row_number(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "empty_cell.csv",
        "timestamp,open,high,low,close,volume\n"
        "2026-06-12T09:30:00,100,110,,105,1\n",
    )

    with pytest.raises(MarketDataLoadError, match="row 2:.*low.*empty"):
        load_ohlcv_csv(
            csv_path,
            symbol="BTC-USD",
            source="unit-test",
            data_version="fixture-v1",
        )


def test_invalid_ohlcv_is_wrapped_with_row_number(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "bad_ohlcv.csv",
        "timestamp,open,high,low,close,volume\n"
        "2026-06-12T09:30:00,100,99,95,105,1\n",
    )

    with pytest.raises(MarketDataLoadError, match="row 2:"):
        load_ohlcv_csv(
            csv_path,
            symbol="BTC-USD",
            source="unit-test",
            data_version="fixture-v1",
        )


def test_unknown_timezone_fails_before_loading_rows(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "bars.csv",
        "timestamp,open,high,low,close,volume\n"
        "2026-06-12T09:30:00,100,110,95,105,1\n",
    )

    with pytest.raises(MarketDataLoadError, match="unknown timezone"):
        load_ohlcv_csv(
            csv_path,
            symbol="BTC-USD",
            source="unit-test",
            data_version="fixture-v1",
            timezone="No/SuchZone",
        )
