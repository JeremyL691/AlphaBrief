"""Market data quality checks for AlphaBrief bars."""

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from alphabrief_core import Bar
from pydantic import BaseModel, ConfigDict, Field, computed_field

DataQualitySeverity = Literal["error", "warning"]


class DataQualityIssue(BaseModel):
    """A single data quality issue found in a bar dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: DataQualitySeverity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    timestamp: datetime | None = None


class DataQualityReport(BaseModel):
    """Summary of market data quality checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issues: list[DataQualityIssue]
    bar_count: int = Field(ge=0)
    symbol: str | None = None
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def check_bar_quality(
    bars: Sequence[Bar],
    *,
    expected_interval: timedelta | None = None,
) -> DataQualityReport:
    """Check dataset-level quality for a sequence of bars."""

    issues: list[DataQualityIssue] = []
    bar_count = len(bars)

    if bar_count == 0:
        issues.append(
            DataQualityIssue(
                severity="error",
                code="empty_dataset",
                message="bar dataset is empty",
            )
        )
        return DataQualityReport(issues=issues, bar_count=0)

    if expected_interval is not None and expected_interval <= timedelta(0):
        raise ValueError("expected_interval must be positive")

    _check_identity_consistency(bars, issues)
    _check_timestamp_ordering(bars, issues)
    _check_expected_interval(bars, expected_interval, issues)
    _check_zero_volume(bars, issues)

    return DataQualityReport(
        issues=issues,
        bar_count=bar_count,
        symbol=bars[0].symbol,
        start_timestamp=bars[0].timestamp,
        end_timestamp=bars[-1].timestamp,
    )


def _check_identity_consistency(
    bars: Sequence[Bar],
    issues: list[DataQualityIssue],
) -> None:
    symbols = {bar.symbol for bar in bars}
    if len(symbols) > 1:
        issues.append(
            DataQualityIssue(
                severity="error",
                code="mixed_symbols",
                message="bar dataset contains multiple symbols",
            )
        )

    sources = {bar.source for bar in bars}
    if len(sources) > 1:
        issues.append(
            DataQualityIssue(
                severity="warning",
                code="mixed_sources",
                message="bar dataset contains multiple sources",
            )
        )

    data_versions = {bar.data_version for bar in bars}
    if len(data_versions) > 1:
        issues.append(
            DataQualityIssue(
                severity="warning",
                code="mixed_data_versions",
                message="bar dataset contains multiple data versions",
            )
        )


def _check_timestamp_ordering(
    bars: Sequence[Bar],
    issues: list[DataQualityIssue],
) -> None:
    timestamp_counts = Counter(bar.timestamp for bar in bars)
    duplicate_timestamps = [
        timestamp for timestamp, count in timestamp_counts.items() if count > 1
    ]
    for timestamp in duplicate_timestamps:
        issues.append(
            DataQualityIssue(
                severity="error",
                code="duplicate_timestamp",
                message="bar dataset contains duplicate timestamps",
                timestamp=timestamp,
            )
        )

    for previous, current in zip(bars, bars[1:], strict=False):
        if current.timestamp <= previous.timestamp:
            issues.append(
                DataQualityIssue(
                    severity="error",
                    code="non_increasing_timestamp",
                    message="bar timestamps must be strictly increasing",
                    timestamp=current.timestamp,
                )
            )


def _check_expected_interval(
    bars: Sequence[Bar],
    expected_interval: timedelta | None,
    issues: list[DataQualityIssue],
) -> None:
    if expected_interval is None:
        return

    for previous, current in zip(bars, bars[1:], strict=False):
        gap = current.timestamp - previous.timestamp
        if gap > expected_interval:
            issues.append(
                DataQualityIssue(
                    severity="error",
                    code="missing_interval",
                    message=(
                        "bar timestamp gap exceeds expected interval "
                        f"{expected_interval}"
                    ),
                    timestamp=current.timestamp,
                )
            )


def _check_zero_volume(
    bars: Sequence[Bar],
    issues: list[DataQualityIssue],
) -> None:
    for bar in bars:
        if bar.volume == 0:
            issues.append(
                DataQualityIssue(
                    severity="warning",
                    code="zero_volume",
                    message="bar volume is zero",
                    timestamp=bar.timestamp,
                )
            )
