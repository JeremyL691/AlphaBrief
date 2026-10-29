"""Freshness must use the newest *completed* H1 candle, never a forming one.

The newest stored bar is usually the candle still forming, so its end lies in
the future. Reporting that end made ``data_quality`` reject the round with
``signal:<symbol>:H1_stale_or_future``, because the window requires
``0 <= age <= max_age`` and a future instant fails outright.

The effect was precise and daily: every round between 00:00 and 01:00 UTC -
the only window in which the runtime escalated after the UTC-day reset - was
skipped as stale, so no committee round ever produced a decision.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphabrief_core import Bar
from alphabrief_trader.market_inputs import _latest_completed_h1_end


def _bar(start: datetime) -> Bar:
    return Bar(
        symbol="BCO_USD",
        timestamp=start,
        open=Decimal("80"),
        high=Decimal("81"),
        low=Decimal("79"),
        close=Decimal("80.5"),
        volume=Decimal("100"),
        source="oanda_practice",
        data_version="v1",
    )


def test_the_forming_candle_does_not_produce_a_future_end() -> None:
    """A candle that has not closed yet is not evidence of fresh data."""
    now = datetime.now(UTC).replace(minute=5, second=0, microsecond=0)
    forming_start = now.replace(minute=0)
    completed_start = forming_start - timedelta(hours=1)

    end = _latest_completed_h1_end([_bar(completed_start), _bar(forming_start)])

    assert end == forming_start, (
        "the forming candle's end was reported as current data, which the "
        "freshness window then rejected as a future instant"
    )
    assert end <= datetime.now(UTC)


def test_a_completed_candle_is_reported() -> None:
    now = datetime.now(UTC)
    start = (now - timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)

    end = _latest_completed_h1_end([_bar(start)])

    assert end == start + timedelta(hours=1)


def test_no_completed_candle_yields_none() -> None:
    """Better to report nothing than a fabricated end."""
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

    assert _latest_completed_h1_end([_bar(now)]) is None


def test_an_empty_series_yields_none() -> None:
    assert _latest_completed_h1_end([]) is None
