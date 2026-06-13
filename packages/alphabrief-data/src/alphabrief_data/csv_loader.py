"""CSV OHLCV loading for AlphaBrief market data."""

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alphabrief_core import Bar
from pydantic import ValidationError

REQUIRED_OHLCV_COLUMNS = frozenset({"open", "high", "low", "close", "volume"})


class MarketDataLoadError(ValueError):
    """Raised when local market data cannot be loaded into valid bars."""


@dataclass(frozen=True)
class CsvBarLoader:
    """Load single-symbol OHLCV bars from a local CSV file."""

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

        try:
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                _validate_header(reader.fieldnames, self.timestamp_column, path)
                return [
                    self._row_to_bar(
                        row,
                        row_number=row_number,
                        symbol=symbol,
                        source=source,
                        data_version=data_version,
                        timezone=timezone,
                    )
                    for row_number, row in enumerate(reader, start=2)
                ]
        except OSError as exc:
            raise MarketDataLoadError(f"failed to read CSV file {path}: {exc}") from exc

    def _row_to_bar(
        self,
        row: dict[str, str | None],
        *,
        row_number: int,
        symbol: str,
        source: str,
        data_version: str,
        timezone: ZoneInfo,
    ) -> Bar:
        try:
            timestamp = _parse_timestamp(
                _required_cell(row, self.timestamp_column, row_number),
                timezone=timezone,
            )
            values = {
                column: _parse_decimal(_required_cell(row, column, row_number), column)
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


def load_ohlcv_csv(
    path: str | Path,
    *,
    symbol: str,
    source: str,
    data_version: str,
    timestamp_column: str = "timestamp",
    timezone: str = "UTC",
) -> list[Bar]:
    """Load OHLCV bars from a local CSV file."""

    loader = CsvBarLoader(timestamp_column=timestamp_column, timezone=timezone)
    return loader.load(
        path,
        symbol=symbol,
        source=source,
        data_version=data_version,
    )


def _validate_header(
    fieldnames: Iterable[str] | None,
    timestamp_column: str,
    path: Path,
) -> None:
    if fieldnames is None:
        raise MarketDataLoadError(f"CSV file {path} is missing a header row")

    required_columns = REQUIRED_OHLCV_COLUMNS | {timestamp_column}
    missing = sorted(required_columns.difference(fieldnames))
    if missing:
        missing_columns = ", ".join(missing)
        raise MarketDataLoadError(
            f"CSV file {path} is missing columns: {missing_columns}"
        )


def _required_cell(row: dict[str, str | None], column: str, row_number: int) -> str:
    value = row.get(column)
    if value is None or value.strip() == "":
        raise ValueError(f"column {column!r} is empty")
    return value.strip()


def _parse_decimal(value: str, column: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(
            f"column {column!r} has invalid decimal value {value!r}"
        ) from exc


def _parse_timestamp(value: str, *, timezone: ZoneInfo) -> datetime:
    normalized = value
    if value.endswith("Z"):
        normalized = f"{value[:-1]}+00:00"

    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp value {value!r}") from exc

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp.replace(tzinfo=timezone)
    return timestamp


def _load_timezone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise MarketDataLoadError(f"unknown timezone {timezone!r}") from exc
