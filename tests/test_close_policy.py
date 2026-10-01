"""Tests for the time-based close triggers (PROJECT_GUIDE 5.10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from alphabrief_trader.close_policy import (
    DEFAULT_MAX_HOLD_HOURS,
    evaluate_close,
    is_weekend_close_window,
    positions_due_for_close,
)

#: Wednesday noon UTC: mid-week, no trigger applies.
WEDNESDAY = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


class TestWeekendWindow:
    def test_midweek_is_not_the_window(self) -> None:
        assert is_weekend_close_window(WEDNESDAY) is False

    def test_friday_before_close_out_is_not_the_window(self) -> None:
        friday = datetime(2026, 10, 2, 18, 59, tzinfo=UTC)

        assert is_weekend_close_window(friday) is False

    def test_friday_close_out_is_the_window(self) -> None:
        friday = datetime(2026, 10, 2, 19, 0, tzinfo=UTC)

        assert is_weekend_close_window(friday) is True

    def test_saturday_and_sunday_are_the_window(self) -> None:
        saturday = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
        sunday = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)

        assert is_weekend_close_window(saturday) is True
        assert is_weekend_close_window(sunday) is True


class TestEvaluateClose:
    def test_fresh_position_stays_open(self) -> None:
        decision = evaluate_close(
            instrument="EUR_USD",
            open_time=WEDNESDAY - timedelta(hours=2),
            now=WEDNESDAY,
        )

        assert decision.should_close is False
        assert decision.reason == "within the holding limit"

    def test_position_past_the_hold_limit_closes(self) -> None:
        decision = evaluate_close(
            instrument="EUR_USD",
            open_time=WEDNESDAY - timedelta(hours=DEFAULT_MAX_HOLD_HOURS),
            now=WEDNESDAY,
        )

        assert decision.should_close is True
        assert "48h" in decision.reason

    def test_unknown_open_time_fails_closed(self) -> None:
        decision = evaluate_close(
            instrument="EUR_USD", open_time=None, now=WEDNESDAY
        )

        assert decision.should_close is True
        assert "unknown" in decision.reason

    def test_weekend_closes_even_a_fresh_position(self) -> None:
        friday_evening = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
        decision = evaluate_close(
            instrument="EUR_USD",
            open_time=friday_evening - timedelta(minutes=5),
            now=friday_evening,
        )

        assert decision.should_close is True
        assert "weekend" in decision.reason

    def test_custom_hold_limit_is_respected(self) -> None:
        decision = evaluate_close(
            instrument="EUR_USD",
            open_time=WEDNESDAY - timedelta(hours=6),
            now=WEDNESDAY,
            max_hold_hours=4,
        )

        assert decision.should_close is True


class TestBatch:
    def test_due_positions_come_first(self) -> None:
        decisions = positions_due_for_close(
            [
                ("EUR_USD", WEDNESDAY - timedelta(hours=1)),
                ("USD_JPY", WEDNESDAY - timedelta(hours=72)),
                ("GBP_USD", None),
            ],
            now=WEDNESDAY,
        )

        assert [decision.instrument for decision in decisions] == [
            "GBP_USD",
            "USD_JPY",
            "EUR_USD",
        ]
        assert [decision.should_close for decision in decisions] == [
            True,
            True,
            False,
        ]
