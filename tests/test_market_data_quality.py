from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import Bar
from alphabrief_data import (
    DataQualityIssue,
    check_bar_quality,
    load_ohlcv_csv,
)

BASE_TIME = datetime(2026, 6, 12, 9, 30, tzinfo=UTC)


def _bar(
    *,
    minutes: int,
    symbol: str = "BTC-USD",
    source: str = "unit-test",
    data_version: str = "fixture-v1",
    volume: str = "1",
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=BASE_TIME + timedelta(minutes=minutes),
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("95"),
        close=Decimal("105"),
        volume=Decimal(volume),
        source=source,
        data_version=data_version,
    )


def _issue_codes(report_issues: list[DataQualityIssue]) -> set[str]:
    return {issue.code for issue in report_issues}


def test_increasing_bars_pass_quality_check() -> None:
    bars = [_bar(minutes=0), _bar(minutes=1), _bar(minutes=2)]

    report = check_bar_quality(bars, expected_interval=timedelta(minutes=1))

    assert report.passed is True
    assert report.issues == []
    assert report.bar_count == 3
    assert report.symbol == "BTC-USD"
    assert report.start_timestamp == bars[0].timestamp
    assert report.end_timestamp == bars[-1].timestamp


def test_empty_dataset_fails_quality_check() -> None:
    report = check_bar_quality([])

    assert report.passed is False
    assert _issue_codes(report.issues) == {"empty_dataset"}
    assert report.bar_count == 0
    assert report.symbol is None


def test_duplicate_timestamp_fails_quality_check() -> None:
    bars = [_bar(minutes=0), _bar(minutes=0)]

    report = check_bar_quality(bars)

    assert report.passed is False
    assert "duplicate_timestamp" in _issue_codes(report.issues)
    assert "non_increasing_timestamp" in _issue_codes(report.issues)


def test_non_increasing_timestamp_fails_quality_check() -> None:
    bars = [_bar(minutes=2), _bar(minutes=1)]

    report = check_bar_quality(bars)

    assert report.passed is False
    assert _issue_codes(report.issues) == {"non_increasing_timestamp"}


def test_mixed_symbol_fails_quality_check() -> None:
    bars = [_bar(minutes=0), _bar(minutes=1, symbol="ETH-USD")]

    report = check_bar_quality(bars)

    assert report.passed is False
    assert "mixed_symbols" in _issue_codes(report.issues)


def test_mixed_source_and_data_version_warn_without_blocking() -> None:
    bars = [
        _bar(minutes=0, source="source-a", data_version="v1"),
        _bar(minutes=1, source="source-b", data_version="v2"),
    ]

    report = check_bar_quality(bars)

    assert report.passed is True
    assert _issue_codes(report.issues) == {"mixed_sources", "mixed_data_versions"}
    assert {issue.severity for issue in report.issues} == {"warning"}


def test_expected_interval_detects_missing_gap() -> None:
    bars = [_bar(minutes=0), _bar(minutes=1), _bar(minutes=4)]

    report = check_bar_quality(bars, expected_interval=timedelta(minutes=1))

    assert report.passed is False
    assert "missing_interval" in _issue_codes(report.issues)


def test_zero_volume_warns_without_blocking() -> None:
    bars = [_bar(minutes=0), _bar(minutes=1, volume="0")]

    report = check_bar_quality(bars)

    assert report.passed is True
    assert _issue_codes(report.issues) == {"zero_volume"}
    assert report.issues[0].severity == "warning"


def test_expected_interval_must_be_positive() -> None:
    with pytest.raises(ValueError, match="expected_interval"):
        check_bar_quality([_bar(minutes=0)], expected_interval=timedelta(0))


def test_csv_loader_output_can_be_checked_explicitly(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-06-12T09:30:00Z,100,110,95,105,1\n"
        "2026-06-12T09:31:00Z,105,112,101,111,1\n",
        encoding="utf-8",
    )
    bars = load_ohlcv_csv(
        csv_path,
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )

    report = check_bar_quality(bars, expected_interval=timedelta(minutes=1))

    assert report.passed is True
    assert report.bar_count == 2
