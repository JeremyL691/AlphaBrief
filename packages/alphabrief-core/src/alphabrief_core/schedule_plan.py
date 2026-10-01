"""The clock-based trading schedule (PROJECT_GUIDE 5.1).

The runtime decides what to run from the wall clock, not from an interval:
decision rounds at 00:30, 07:30 and 13:00 UTC (Monday–Friday), the Friday
19:00 close-out, the 21:30 daily report, and the 22:00 backup.

Rules the planner implements:

* a missed round may run **within 90 minutes** of its scheduled time;
* after that it is recorded as ``MISSED_WINDOW`` and never runs late — an
  order must not be placed in the wrong session;
* weekends skip decision rounds (the report records that the market was
  closed) while sync, reconciliation, report and backup still run;
* an event already run at or after its scheduled instant is not due again,
  so a restart cannot repeat a completed round.

The planner is pure: callers pass ``now`` and the last-run instants.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal

#: Default catch-up window (PROJECT_GUIDE 5.1).
DEFAULT_CATCH_UP_MINUTES = 90

EventKind = Literal["decision_round", "close_out", "report", "backup"]

#: Why an event is or is not due.
DueReason = Literal[
    "due",
    "catch_up",
    "not_yet",
    "already_ran",
    "missed_window",
    "market_closed",
]


@dataclass(frozen=True)
class PlannedEvent:
    """One entry of the daily schedule."""

    name: str
    kind: EventKind
    at_utc: time
    weekdays_only: bool = False
    friday_only: bool = False
    #: Weekend behaviour: decision rounds skip, everything else runs.
    skip_weekends: bool = False


#: The reviewed schedule (PROJECT_GUIDE 5.1).
DEFAULT_SCHEDULE: tuple[PlannedEvent, ...] = (
    PlannedEvent(
        name="decision_round_tokyo",
        kind="decision_round",
        at_utc=time(0, 30),
        weekdays_only=True,
        skip_weekends=True,
    ),
    PlannedEvent(
        name="decision_round_london",
        kind="decision_round",
        at_utc=time(7, 30),
        weekdays_only=True,
        skip_weekends=True,
    ),
    PlannedEvent(
        name="decision_round_newyork",
        kind="decision_round",
        at_utc=time(13, 0),
        weekdays_only=True,
        skip_weekends=True,
    ),
    PlannedEvent(
        name="weekend_close_out",
        kind="close_out",
        at_utc=time(19, 0),
        friday_only=True,
    ),
    PlannedEvent(name="daily_report", kind="report", at_utc=time(21, 30)),
    PlannedEvent(name="backup", kind="backup", at_utc=time(22, 0)),
)


@dataclass(frozen=True)
class DueEvent:
    """One event's verdict for the current instant."""

    name: str
    kind: EventKind
    scheduled_at: datetime
    due: bool
    reason: DueReason
    detail: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "name": self.name,
            "kind": self.kind,
            "scheduled_at": self.scheduled_at.isoformat(),
            "due": self.due,
            "reason": self.reason,
            "detail": self.detail,
        }


def _scheduled_at(event: PlannedEvent, day: datetime) -> datetime:
    return datetime.combine(day.date(), event.at_utc, tzinfo=UTC)


def _is_weekend(day: datetime) -> bool:
    return day.astimezone(UTC).weekday() >= 5


def _is_friday(day: datetime) -> bool:
    return day.astimezone(UTC).weekday() == 4


def evaluate_schedule(
    *,
    now: datetime,
    last_runs: Mapping[str, datetime] | None = None,
    schedule: Sequence[PlannedEvent] = DEFAULT_SCHEDULE,
    catch_up_minutes: int = DEFAULT_CATCH_UP_MINUTES,
) -> tuple[DueEvent, ...]:
    """Which events are due right now, and why the others are not."""
    if catch_up_minutes <= 0:
        raise ValueError("catch_up_minutes must be positive")
    observed_at = now.astimezone(UTC)
    runs = dict(last_runs or {})
    verdicts: list[DueEvent] = []

    for event in schedule:
        scheduled_at = _scheduled_at(event, observed_at)
        last_run = runs.get(event.name)
        if last_run is not None and last_run.astimezone(UTC) >= scheduled_at:
            verdicts.append(
                DueEvent(
                    name=event.name,
                    kind=event.kind,
                    scheduled_at=scheduled_at,
                    due=False,
                    reason="already_ran",
                    detail=f"last ran {last_run.astimezone(UTC).isoformat()}",
                )
            )
            continue

        if event.friday_only and not _is_friday(observed_at):
            verdicts.append(
                DueEvent(
                    name=event.name,
                    kind=event.kind,
                    scheduled_at=scheduled_at,
                    due=False,
                    reason="not_yet",
                    detail="Friday-only event",
                )
            )
            continue

        if event.skip_weekends and _is_weekend(observed_at):
            verdicts.append(
                DueEvent(
                    name=event.name,
                    kind=event.kind,
                    scheduled_at=scheduled_at,
                    due=False,
                    reason="market_closed",
                    detail="the weekend opens no decision round",
                )
            )
            continue

        if event.weekdays_only and _is_weekend(observed_at):
            verdicts.append(
                DueEvent(
                    name=event.name,
                    kind=event.kind,
                    scheduled_at=scheduled_at,
                    due=False,
                    reason="market_closed",
                    detail="weekday-only event",
                )
            )
            continue

        age = observed_at - scheduled_at
        if age < timedelta(0):
            verdicts.append(
                DueEvent(
                    name=event.name,
                    kind=event.kind,
                    scheduled_at=scheduled_at,
                    due=False,
                    reason="not_yet",
                    detail=f"scheduled at {scheduled_at.isoformat()}",
                )
            )
            continue
        if age <= timedelta(minutes=catch_up_minutes):
            reason: DueReason = "due" if age < timedelta(minutes=1) else "catch_up"
            verdicts.append(
                DueEvent(
                    name=event.name,
                    kind=event.kind,
                    scheduled_at=scheduled_at,
                    due=True,
                    reason=reason,
                    detail=(
                        f"scheduled {scheduled_at.isoformat()}; "
                        f"{int(age.total_seconds() // 60)}m late"
                        if reason == "catch_up"
                        else f"scheduled {scheduled_at.isoformat()}"
                    ),
                )
            )
            continue
        verdicts.append(
            DueEvent(
                name=event.name,
                kind=event.kind,
                scheduled_at=scheduled_at,
                due=False,
                reason="missed_window",
                detail=(
                    f"scheduled {scheduled_at.isoformat()} and missed by "
                    f"{int(age.total_seconds() // 60)}m (window "
                    f"{catch_up_minutes}m); never run late"
                ),
            )
        )
    return tuple(verdicts)


def due_events(
    *,
    now: datetime,
    last_runs: Mapping[str, datetime] | None = None,
    schedule: Sequence[PlannedEvent] = DEFAULT_SCHEDULE,
    catch_up_minutes: int = DEFAULT_CATCH_UP_MINUTES,
) -> tuple[DueEvent, ...]:
    """Only the events that should run now."""
    return tuple(
        verdict
        for verdict in evaluate_schedule(
            now=now,
            last_runs=last_runs,
            schedule=schedule,
            catch_up_minutes=catch_up_minutes,
        )
        if verdict.due
    )


__all__ = [
    "DEFAULT_CATCH_UP_MINUTES",
    "DEFAULT_SCHEDULE",
    "DueEvent",
    "DueReason",
    "EventKind",
    "PlannedEvent",
    "due_events",
    "evaluate_schedule",
]
