"""Parquet OHLCV loading for AlphaBrief market data."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from importlib import import_module
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from alphabrief_core import Bar
from pydantic import ValidationError

from alphabrief_data.csv_loader import (
    REQUIRED_OHLCV_COLUMNS,
    MarketDataLoadError,
    _load_timezone,
    _parse_timestamp,
)


@dataclass(frozen=True)
class ParquetBarLoader:
    """Load single-symbol OHLCV bars from a local Parquet file."""

    timestamp_column: str = "timestamp"
    timezone: str = "UTC"

    def load(
        self,
        path: str | Path,
        *,
        symbol: str,
        source: str,
        data_version: str,
    ) -> list[Bar]:
        path = Path(path)
        timezone = _load_timezone(self.timezone)
        columns, rows = self._read_rows(path)
        _validate_columns(columns, self.timestamp_column, path)

        return [
            self._row_to_bar(
                row,
                row_number=row_number,
                symbol=symbol,
                source=source,
                data_version=data_version,
                timezone=timezone,
            )
            for row_number, row in enumerate(rows, start=1)
        ]

    def _read_rows(
        self,
        path: Path,
    ) -> tuple[Iterable[str], Iterable[Mapping[str, object]]]:
        try:
            pandas: Any = import_module("pandas")
        except ImportError as exc:
            raise MarketDataLoadError(
                "Parquet loading requires pandas with pyarrow or fastparquet"
            ) from exc

        try:
            frame = pandas.read_parquet(path)
        except (ImportError, OSError, ValueError) as exc:
            raise MarketDataLoadError(
                f"failed to read Parquet file {path}: {exc}"
            ) from exc

        return frame.columns, frame.to_dict("records")

    def _row_to_bar(
        self,
        row: Mapping[str, object],
        *,
        row_number: int,
        symbol: str,
        source: str,
        data_version: str,
        timezone: ZoneInfo,
    ) -> Bar:
        try:
            timestamp = _parse_timestamp_value(
                _required_value(row, self.timestamp_column, row_number),
                timezone=timezone,
            )
            values = {
                column: _parse_decimal_value(
                    _required_value(row, column, row_number),
                    column,
                )
                for column in REQUIRED_OHLCV_COLUMNS
            }
            return Bar(
                symbol=symbol,
                timestamp=timestamp,
                open=values["open"],
                high=values["high"],
                low=values["low"],
                close=values["close"],
                volume=values["volume"],
                source=source,
                data_version=data_version,
            )
        except (InvalidOperation, ValueError, ValidationError) as exc:
            raise MarketDataLoadError(f"row {row_number}: {exc}") from exc


def load_ohlcv_parquet(
    path: str | Path,
    *,
    symbol: str,
    source: str,
    data_version: str,
    timestamp_column: str = "timestamp",
    timezone: str = "UTC",
) -> list[Bar]:
    """Load OHLCV bars from a local Parquet file."""

    loader = ParquetBarLoader(timestamp_column=timestamp_column, timezone=timezone)
    return loader.load(
        path,
        symbol=symbol,
        source=source,
        data_version=data_version,
    )


def _validate_columns(
    columns: Iterable[str],
    timestamp_column: str,
    path: Path,
) -> None:
    required_columns = REQUIRED_OHLCV_COLUMNS | {timestamp_column}
    missing = sorted(required_columns.difference(columns))
    if missing:
        missing_columns = ", ".join(missing)
        raise MarketDataLoadError(
            f"Parquet file {path} is missing columns: {missing_columns}"
        )


def _required_value(
    row: Mapping[str, object],
    column: str,
    row_number: int,
) -> object:
    value = row.get(column)
    if _is_missing(value):
        raise ValueError(f"column {column!r} is empty")
    return value


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    try:
        return bool(value != value)
    except TypeError:
        return False


def _parse_decimal_value(value: object, column: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"column {column!r} has invalid decimal value {value!r}")
    if isinstance(value, float):
        raise ValueError(
            f"column {column!r} must not be loaded from a float value"
        )
    if isinstance(value, Decimal):
        return value

    try:
        return Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(
            f"column {column!r} has invalid decimal value {value!r}"
        ) from exc


def _parse_timestamp_value(value: object, *, timezone: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone)
        return value

    if isinstance(value, str):
        return _parse_timestamp(value.strip(), timezone=timezone)

    raise ValueError(f"invalid timestamp value {value!r}")
