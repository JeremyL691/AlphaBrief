"""No-lookahead feature generation for AlphaBrief bars."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from alphabrief_core import Bar
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_data.quality import check_bar_quality


class FeatureGenerationError(ValueError):
    """Raised when features cannot be generated from invalid market data."""


class FeatureRow(BaseModel):
    """Feature values for one bar timestamp."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    timestamp: datetime
    source: str = Field(min_length=1)
    data_version: str = Field(min_length=1)
    values: dict[str, Decimal | None]


def generate_basic_features(
    bars: Sequence[Bar],
    *,
    return_periods: Sequence[int] = (1,),
    sma_windows: Sequence[int] = (3,),
) -> list[FeatureRow]:
    """Generate basic trailing features without looking ahead."""

    _validate_positive_integers(return_periods, name="return_periods")
    _validate_positive_integers(sma_windows, name="sma_windows")

    quality_report = check_bar_quality(bars)
    if not quality_report.passed:
        issue_codes = ", ".join(issue.code for issue in quality_report.issues)
        raise FeatureGenerationError(
            f"cannot generate features from failed quality report: {issue_codes}"
        )

    return [
        FeatureRow(
            symbol=bar.symbol,
            timestamp=bar.timestamp,
            source=bar.source,
            data_version=bar.data_version,
            values=_feature_values_for_index(
                bars,
                index=index,
                return_periods=return_periods,
                sma_windows=sma_windows,
            ),
        )
        for index, bar in enumerate(bars)
    ]


def _feature_values_for_index(
    bars: Sequence[Bar],
    *,
    index: int,
    return_periods: Sequence[int],
    sma_windows: Sequence[int],
) -> dict[str, Decimal | None]:
    values: dict[str, Decimal | None] = {}

    for period in return_periods:
        values[f"return_{period}"] = _trailing_return(bars, index=index, period=period)

    for window in sma_windows:
        values[f"close_sma_{window}"] = _trailing_average(
            [bar.close for bar in bars],
            index=index,
            window=window,
        )
        values[f"volume_sma_{window}"] = _trailing_average(
            [bar.volume for bar in bars],
            index=index,
            window=window,
        )

    return values


def _trailing_return(
    bars: Sequence[Bar],
    *,
    index: int,
    period: int,
) -> Decimal | None:
    previous_index = index - period
    if previous_index < 0:
        return None

    previous_close = bars[previous_index].close
    if previous_close == 0:
        return None

    return (bars[index].close - previous_close) / previous_close


def _trailing_average(
    values: Sequence[Decimal],
    *,
    index: int,
    window: int,
) -> Decimal | None:
    start_index = index - window + 1
    if start_index < 0:
        return None

    window_values = values[start_index : index + 1]
    return sum(window_values, Decimal("0")) / Decimal(window)


def _validate_positive_integers(values: Sequence[int], *, name: str) -> None:
    for value in values:
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must contain only positive integers")
