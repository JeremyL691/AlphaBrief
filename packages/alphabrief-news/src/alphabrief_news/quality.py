"""In-memory quality checks for news headline and macro indicator collections.

These checks are explicit and read-only. They do not repair data, drop rows,
infer values, or alter the input objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from alphabrief_news.types import MacroIndicator, NewsHeadline


@dataclass(frozen=True)
class HeadlineQualityIssue:
    """A single issue discovered while checking headline collections."""

    code: str
    message: str


@dataclass(frozen=True)
class HeadlineQualityReport:
    """Result of running quality checks over a list of headlines."""

    passed: bool
    issues: list[HeadlineQualityIssue] = field(default_factory=list)
    headline_count: int = 0
    symbols: frozenset[str] = field(default_factory=frozenset)
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None


@dataclass(frozen=True)
class IndicatorQualityIssue:
    """A single issue discovered while checking indicator collections."""

    code: str
    message: str


@dataclass(frozen=True)
class IndicatorQualityReport:
    """Result of running quality checks over a list of indicators."""

    passed: bool
    issues: list[IndicatorQualityIssue] = field(default_factory=list)
    indicator_count: int = 0
    names: frozenset[str] = field(default_factory=frozenset)
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None


def check_headline_quality(headlines: list[NewsHeadline]) -> HeadlineQualityReport:
    """Validate a list of headlines and return a quality report.

    Errors (report.passed == False):
      - empty input
      - mixed data_version values
      - blank headline title
      - duplicate headline_id
      - non-increasing published_at timestamps
    """
    issues: list[HeadlineQualityIssue] = []

    if not headlines:
        issues.append(
            HeadlineQualityIssue(code="empty", message="headline list is empty")
        )
        return HeadlineQualityReport(passed=False, issues=issues)

    data_versions = {h.data_version for h in headlines}
    if len(data_versions) > 1:
        issues.append(
            HeadlineQualityIssue(
                code="mixed_data_version",
                message=f"mixed data versions: {sorted(data_versions)}",
            )
        )

    seen_ids: set[str] = set()
    for headline in headlines:
        if headline.title.strip() == "":
            issues.append(
                HeadlineQualityIssue(
                    code="blank_title",
                    message=f"headline {headline.headline_id} has a blank title",
                )
            )
        if headline.headline_id in seen_ids:
            issues.append(
                HeadlineQualityIssue(
                    code="duplicate_id",
                    message=f"duplicate headline_id: {headline.headline_id}",
                )
            )
        seen_ids.add(headline.headline_id)

    sorted_by_time = sorted(headlines, key=lambda h: h.published_at)
    for prev, curr in zip(sorted_by_time, sorted_by_time[1:], strict=False):
        if curr.published_at < prev.published_at:
            issues.append(
                HeadlineQualityIssue(
                    code="non_increasing_timestamps",
                    message=(
                        f"headline {curr.headline_id} published at "
                        f"{curr.published_at} is before "
                        f"{prev.headline_id} at {prev.published_at}"
                    ),
                )
            )
            break

    symbols = frozenset(
        symbol for headline in headlines for symbol in headline.symbols
    )

    return HeadlineQualityReport(
        passed=len(issues) == 0,
        issues=issues,
        headline_count=len(headlines),
        symbols=symbols,
        start_timestamp=sorted_by_time[0].published_at,
        end_timestamp=sorted_by_time[-1].published_at,
    )


def check_indicator_quality(
    indicators: list[MacroIndicator],
) -> IndicatorQualityReport:
    """Validate a list of macro indicators and return a quality report.

    Errors (report.passed == False):
      - empty input
      - mixed data_version values
      - missing / non-finite value
      - duplicate indicator_id
      - non-increasing released_at timestamps
    """
    issues: list[IndicatorQualityIssue] = []

    if not indicators:
        issues.append(
            IndicatorQualityIssue(code="empty", message="indicator list is empty")
        )
        return IndicatorQualityReport(passed=False, issues=issues)

    data_versions = {i.data_version for i in indicators}
    if len(data_versions) > 1:
        issues.append(
            IndicatorQualityIssue(
                code="mixed_data_version",
                message=f"mixed data versions: {sorted(data_versions)}",
            )
        )

    seen_ids: set[str] = set()
    for indicator in indicators:
        if indicator.value is None or not indicator.value.is_finite():
            issues.append(
                IndicatorQualityIssue(
                    code="invalid_value",
                    message=(
                        f"indicator {indicator.indicator_id} has an invalid value"
                    ),
                )
            )
        if indicator.indicator_id in seen_ids:
            issues.append(
                IndicatorQualityIssue(
                    code="duplicate_id",
                    message=f"duplicate indicator_id: {indicator.indicator_id}",
                )
            )
        seen_ids.add(indicator.indicator_id)

    sorted_by_time = sorted(indicators, key=lambda i: i.released_at)
    for prev, curr in zip(sorted_by_time, sorted_by_time[1:], strict=False):
        if curr.released_at < prev.released_at:
            issues.append(
                IndicatorQualityIssue(
                    code="non_increasing_timestamps",
                    message=(
                        f"indicator {curr.indicator_id} released at "
                        f"{curr.released_at} is before "
                        f"{prev.indicator_id} at {prev.released_at}"
                    ),
                )
            )
            break

    names = frozenset(indicator.name for indicator in indicators)

    return IndicatorQualityReport(
        passed=len(issues) == 0,
        issues=issues,
        indicator_count=len(indicators),
        names=names,
        start_timestamp=sorted_by_time[0].released_at,
        end_timestamp=sorted_by_time[-1].released_at,
    )


__all__ = [
    "HeadlineQualityIssue",
    "HeadlineQualityReport",
    "IndicatorQualityIssue",
    "IndicatorQualityReport",
    "check_headline_quality",
    "check_indicator_quality",
]
