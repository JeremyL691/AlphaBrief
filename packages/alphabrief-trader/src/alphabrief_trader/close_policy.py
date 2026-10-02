"""Deterministic close triggers (PROJECT_GUIDE 5.10).

A position is closed when the committee says so, when it has been held for
``max_hold_hours``, when the weekend close-out time arrives, or when a
protective order fills at the broker. This module owns the two
time-based triggers as pure functions so the runtime (and its tests) can
decide identically.

The weekend trigger exists to avoid holding exposure across the Sunday
gap: from Friday 19:00 UTC nothing may stay open, and nothing may be
opened after 13:00 UTC (rule 13 in the entry rules).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

#: Friday close-out time (UTC): every position must be flat by then.
WEEKEND_CLOSE_HOUR = 19

#: Longest a position may be held before it is closed.
DEFAULT_MAX_HOLD_HOURS = 48


@dataclass(frozen=True)
class CloseDecision:
    """Why one position must be closed (or not)."""

    instrument: str
    should_close: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "instrument": self.instrument,
            "should_close": self.should_close,
            "reason": self.reason,
        }


def is_weekend_close_window(now: datetime) -> bool:
    """True from Friday 19:00 UTC through the weekend."""
    moment = now.astimezone(UTC)
    weekday = moment.weekday()
    if weekday == 4 and moment.hour >= WEEKEND_CLOSE_HOUR:
        return True
    return weekday >= 5


def evaluate_close(
    *,
    instrument: str,
    open_time: datetime | None,
    now: datetime,
    max_hold_hours: int = DEFAULT_MAX_HOLD_HOURS,
) -> CloseDecision:
    """Decide whether one open position must be closed now."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("close policy clock must be timezone aware")
    if (
        isinstance(max_hold_hours, bool)
        or not isinstance(max_hold_hours, int)
        or max_hold_hours <= 0
    ):
        raise ValueError("holding limit must be a positive integer")
    if is_weekend_close_window(now):
        return CloseDecision(
            instrument=instrument,
            should_close=True,
            reason="weekend close-out (Friday 19:00 UTC onward)",
        )
    if (
        open_time is None
        or open_time.tzinfo is None
        or open_time.utcoffset() is None
        or open_time > now
    ):
        # Without an open time the hold age is unknown: fail closed and
        # close rather than carry an unbounded position through the gap.
        return CloseDecision(
            instrument=instrument,
            should_close=True,
            reason="position open time is unknown",
        )
    age = now.astimezone(UTC) - open_time.astimezone(UTC)
    if age >= timedelta(hours=max_hold_hours):
        held_hours = int(age.total_seconds() // 3600)
        return CloseDecision(
            instrument=instrument,
            should_close=True,
            reason=f"held {held_hours}h (limit {max_hold_hours}h)",
        )
    return CloseDecision(
        instrument=instrument,
        should_close=False,
        reason="within the holding limit",
    )


def positions_due_for_close(
    positions: Iterable[tuple[str, datetime | None]],
    *,
    now: datetime,
    max_hold_hours: int = DEFAULT_MAX_HOLD_HOURS,
) -> tuple[CloseDecision, ...]:
    """Return the decisions for every open position, due ones first."""
    decisions = [
        evaluate_close(
            instrument=instrument,
            open_time=open_time,
            now=now,
            max_hold_hours=max_hold_hours,
        )
        for instrument, open_time in positions
    ]
    return tuple(
        sorted(
            decisions,
            key=lambda decision: (not decision.should_close, decision.instrument),
        )
    )


__all__ = [
    "DEFAULT_MAX_HOLD_HOURS",
    "WEEKEND_CLOSE_HOUR",
    "CloseDecision",
    "evaluate_close",
    "is_weekend_close_window",
    "positions_due_for_close",
]
