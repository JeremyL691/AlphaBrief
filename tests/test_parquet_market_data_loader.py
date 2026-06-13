from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_data import (
    MarketDataLoadError,
    ParquetBarLoader,
    load_ohlcv_parquet,
)

PARQUET_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def _patch_rows(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
    *,
    columns: tuple[str, ...] = PARQUET_COLUMNS,
) -> None:
    def read_rows(
        self: ParquetBarLoader,
        path: Path,
    ) -> tuple[tuple[str, ...], list[dict[str, object]]]:
        return columns, rows

    monkeypatch.setattr(ParquetBarLoader, "_read_rows", read_rows)


def test_load_ohlcv_parquet_returns_valid_bars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(
        monkeypatch,
        [
            {
                "timestamp": "2026-06-12T09:30:00",
                "open": "100",
                "high": Decimal("110"),
                "low": 95,
                "close": "105",
                "volume": "123.45",
            }
        ],
    )

    bars = load_ohlcv_parquet(
        tmp_path / "bars.parquet",
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )

    assert len(bars) == 1
    assert bars[0].symbol == "BTC-USD"
    assert bars[0].timestamp.utcoffset() == UTC.utcoffset(None)
    assert bars[0].close == Decimal("105")
    assert bars[0].source == "unit-test"
    assert bars[0].data_version == "fixture-v1"


def test_parquet_naive_datetime_uses_configured_timezone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(
        monkeypatch,
        [
            {
                "timestamp": datetime(2026, 6, 12, 9, 30),
                "open": "100",
                "high": "110",
                "low": "95",
                "close": "105",
                "volume": "1",
            }
        ],
    )

    bars = ParquetBarLoader(timezone="Asia/Shanghai").load(
        tmp_path / "bars.parquet",
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )

    offset = bars[0].timestamp.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 8 * 60 * 60


def test_parquet_aware_datetime_preserves_offset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp = datetime.fromisoformat("2026-06-12T09:30:00-04:00")
    _patch_rows(
        monkeypatch,
        [
            {
                "timestamp": timestamp,
                "open": "100",
                "high": "110",
                "low": "95",
                "close": "105",
                "volume": "1",
            }
        ],
    )

    bars = load_ohlcv_parquet(
        tmp_path / "bars.parquet",
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )

    offset = bars[0].timestamp.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == -4 * 60 * 60


def test_parquet_missing_required_column_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(
        monkeypatch,
        [],
        columns=("timestamp", "open", "high", "low", "close"),
    )

    with pytest.raises(MarketDataLoadError, match="missing columns: volume"):
        load_ohlcv_parquet(
            tmp_path / "missing.parquet",
            symbol="BTC-USD",
            source="unit-test",
            data_version="fixture-v1",
        )


def test_parquet_float_decimal_is_rejected_with_row_number(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(
        monkeypatch,
        [
            {
                "timestamp": "2026-06-12T09:30:00",
                "open": 100.0,
                "high": "110",
                "low": "95",
                "close": "105",
                "volume": "1",
            }
        ],
    )

    with pytest.raises(MarketDataLoadError, match="row 1:.*float"):
        load_ohlcv_parquet(
            tmp_path / "float.parquet",
            symbol="BTC-USD",
            source="unit-test",
            data_version="fixture-v1",
        )


def test_parquet_invalid_timestamp_fails_with_row_number(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(
        monkeypatch,
        [
            {
                "timestamp": object(),
                "open": "100",
                "high": "110",
                "low": "95",
                "close": "105",
                "volume": "1",
            }
        ],
    )

    with pytest.raises(MarketDataLoadError, match="row 1:.*timestamp"):
        load_ohlcv_parquet(
            tmp_path / "bad_time.parquet",
            symbol="BTC-USD",
            source="unit-test",
            data_version="fixture-v1",
        )


def test_parquet_invalid_ohlcv_is_wrapped_with_row_number(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(
        monkeypatch,
        [
            {
                "timestamp": "2026-06-12T09:30:00",
                "open": "100",
                "high": "99",
                "low": "95",
                "close": "105",
                "volume": "1",
            }
        ],
    )

    with pytest.raises(MarketDataLoadError, match="row 1:"):
        load_ohlcv_parquet(
            tmp_path / "bad_ohlcv.parquet",
            symbol="BTC-USD",
            source="unit-test",
            data_version="fixture-v1",
        )


def test_parquet_missing_engine_has_clear_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_import(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr("alphabrief_data.parquet_loader.import_module", fail_import)

    with pytest.raises(MarketDataLoadError, match="requires pandas"):
        ParquetBarLoader().load(
            tmp_path / "bars.parquet",
            symbol="BTC-USD",
            source="unit-test",
            data_version="fixture-v1",
        )
