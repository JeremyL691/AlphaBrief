"""Expected opportunity rounds must follow the FX session, not a weekday.

The soak evaluator decides whether a day had complete opportunity-round
coverage by comparing the rounds the scheduler recorded against the
rounds it *should* have run. That expectation used to be "every 300s on a
weekday", which contradicts the actual FX calendar: the CURRENCY session
runs Monday 21:00 UTC to Friday 21:00 UTC. A correct backend therefore
records no rounds on Monday 00:00-21:00 or Friday 21:00-24:00, and a naive
weekday expectation would report hundreds of "missed" rounds every week
and turn every day into an extension - the 14 qualified days could never
be reached even with a perfectly healthy runtime.

These tests pin the expectation to the same session verdict the runtime
uses to decide whether to check at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from alphabrief_execution.broker.oanda.sessions import session_verdict
from alphabrief_trader.soak_evaluator import expected_round_instants

#: October 2026: the 19th is a Monday, the 23rd a Friday.
MONDAY = datetime(2026, 10, 19, tzinfo=UTC)
FRIDAY = datetime(2026, 10, 23, tzinfo=UTC)
SATURDAY = datetime(2026, 10, 24, tzinfo=UTC)


def _day(day: datetime) -> tuple[datetime, datetime]:
    return day, day + timedelta(days=1)


def test_monday_before_the_open_expects_no_rounds() -> None:
    """The FX week starts Monday 21:00 UTC, not Monday 00:00."""
    start, end = _day(MONDAY)

    instants = expected_round_instants(start, end, interval_seconds=300)

    assert instants
    assert all(i.hour >= 21 for i in instants), (
        "the evaluator expected opportunity rounds before the FX week opened"
    )


def test_weekend_expects_no_rounds() -> None:
    start, end = _day(SATURDAY)

    assert expected_round_instants(start, end, interval_seconds=300) == []


def test_friday_after_the_close_expects_no_rounds() -> None:
    """The FX week ends Friday 21:00 UTC; nothing trades after that."""
    start, end = _day(FRIDAY)

    instants = expected_round_instants(start, end, interval_seconds=300)

    assert instants
    assert all(i.hour < 21 for i in instants)


def test_a_full_open_weekday_is_covered_end_to_end() -> None:
    """A normal mid-week day is entirely inside the session."""
    start, end = _day(datetime(2026, 10, 21, tzinfo=UTC))

    instants = expected_round_instants(start, end, interval_seconds=300)

    assert instants[0] == start
    assert instants[-1] < end
    # 24h / 5min = 288 buckets.
    assert len(instants) == 288


def test_instants_respect_the_configured_interval() -> None:
    """The cadence comes from the scheduler, so the count must follow it."""
    start, end = _day(datetime(2026, 10, 21, tzinfo=UTC))

    five_minutes = expected_round_instants(start, end, interval_seconds=300)
    three_minutes = expected_round_instants(start, end, interval_seconds=180)

    assert len(three_minutes) > len(five_minutes)
    gaps = {
        (b - a).total_seconds()
        for a, b in zip(three_minutes, three_minutes[1:], strict=False)
    }
    assert gaps == {180.0}


@pytest.mark.parametrize("interval", [0, -1])
def test_non_positive_interval_expects_nothing(interval: float) -> None:
    """A nonsensical cadence must not invent hundreds of missed rounds."""
    start, end = _day(datetime(2026, 10, 21, tzinfo=UTC))

    assert expected_round_instants(start, end, interval_seconds=interval) == []


def test_expectation_agrees_with_the_runtime_session_verdict() -> None:
    """The evaluator and the runtime must never disagree about "open"."""
    start, end = _day(MONDAY)

    instants = expected_round_instants(start, end, interval_seconds=300)

    for instant in instants:
        assert session_verdict("CURRENCY", instant).open is True
    # And the hours it skipped really are closed.
    closed_probe = MONDAY.replace(hour=12)
    assert session_verdict("CURRENCY", closed_probe).open is False
