"""Category-aware instrument sessions, holidays, and tradeability (M05-W04).

Replaces the universal weekday window with per-category session
evidence combined with account catalog state and current OANDA
tradeable status. Every input that cannot be proven open fails closed
for new exposure: broker ``tradeable=False``, inactive catalog state, a
closed session, stale session evidence, and unknown required calendar
state all produce a closed verdict.
"""

from __future__ import annotations

from datetime import UTC, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.oanda.taxonomy import InstrumentCategory

#: Category-aware session windows (UTC-fixed; DST never shifts UTC).
#: Each window is (start_weekday, start_time, end_weekday, end_time);
#: end may wrap past midnight UTC (overnight sessions).
SessionWindow = tuple[int, time, int, time]

_CURRENCY_WINDOW: SessionWindow = (0, time(21, 0), 4, time(21, 0))
_METAL_WINDOW: SessionWindow = (0, time(21, 0), 4, time(21, 0))
_CFD_WINDOW: SessionWindow = (0, time(0, 0), 4, time(21, 0))
_CRYPTO_WINDOW: SessionWindow = (0, time(0, 0), 6, time(23, 59))

#: Per-category session windows; unknown categories get no window and
#: therefore fail closed (explicit unknown calendar state).
CATEGORY_SESSIONS: dict[InstrumentCategory, SessionWindow] = {
    "CURRENCY": _CURRENCY_WINDOW,
    "METAL": _METAL_WINDOW,
    "INDEX_CFD": _CFD_WINDOW,
    "COMMODITY_CFD": _CFD_WINDOW,
    "BOND_CFD": _CFD_WINDOW,
    "EQUITY_CFD": _CFD_WINDOW,
    "CRYPTO_CFD": _CRYPTO_WINDOW,
    "OTHER_CFD": _CFD_WINDOW,
}

#: Default staleness threshold for session evidence (seconds).
DEFAULT_EVIDENCE_MAX_AGE_SECONDS = 24 * 60 * 60


class SessionVerdict(BaseModel):
    """The deterministic session verdict for one category at one moment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    open: bool
    reason: str = Field(min_length=1)
    category: InstrumentCategory
    moment: datetime
    stale: bool = False


class HolidayCalendar(BaseModel):
    """Configured closed dates per category (date -> reason)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    holidays: dict[str, tuple[str, ...]] = Field(default_factory=dict)


def session_verdict(
    category: InstrumentCategory,
    moment: datetime,
    *,
    holidays: HolidayCalendar | None = None,
) -> SessionVerdict:
    """Return the deterministic session verdict for *category* at *moment*.

    UTC-fixed windows make DST transitions deterministic; weekends and
    configured holidays close the session; an unknown category (no
    window) fails closed.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    moment = moment.astimezone(UTC)
    calendar = holidays or HolidayCalendar()

    if category not in CATEGORY_SESSIONS:
        return SessionVerdict(
            open=False,
            reason=f"no session window for unknown category {category!r}",
            category=category,
            moment=moment,
        )

    date_key = moment.date().isoformat()
    closed_dates = calendar.holidays.get(category, ())
    if date_key in closed_dates:
        return SessionVerdict(
            open=False,
            reason=f"configured holiday for {category}",
            category=category,
            moment=moment,
        )

    window = CATEGORY_SESSIONS[category]
    open_here = _within_window(window, moment)
    return SessionVerdict(
        open=open_here,
        reason=(
            "inside category session window"
            if open_here
            else "outside category session window"
        ),
        category=category,
        moment=moment,
    )


_MINUTES_PER_DAY = 24 * 60
_MINUTES_PER_WEEK = 7 * _MINUTES_PER_DAY


def _week_minutes(weekday: int, value: time) -> int:
    return weekday * _MINUTES_PER_DAY + value.hour * 60 + value.minute


def _within_window(window: SessionWindow, moment: datetime) -> bool:
    """Return True when *moment* falls inside the session window.

    Windows are intervals on the week circle in minutes-since-Monday;
    an end at or before the start wraps by a full week (overnight and
    24x7 sessions). UTC-fixed windows make DST transitions
    deterministic.
    """
    start_day, start_time, end_day, end_time = window
    start = _week_minutes(start_day, start_time)
    end = _week_minutes(end_day, end_time)
    if end <= start:
        end += _MINUTES_PER_WEEK
    now = _week_minutes(moment.weekday(), moment.time().replace(microsecond=0))
    return start <= now < end


class ExposureReadiness(BaseModel):
    """The combined fail-closed readiness verdict for new exposure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ready: bool
    reason: str = Field(min_length=1)
    session: SessionVerdict


def evaluate_exposure_readiness(
    category: InstrumentCategory,
    moment: datetime,
    *,
    tradeable: bool,
    catalog_active: bool,
    holidays: HolidayCalendar | None = None,
    evidence_age_seconds: int = 0,
    evidence_max_age_seconds: int = DEFAULT_EVIDENCE_MAX_AGE_SECONDS,
) -> ExposureReadiness:
    """Combine session, tradeability, catalog state, and evidence freshness.

    Any fail-closed input closes new exposure: broker ``tradeable``
    false, inactive catalog state, a closed session, stale session
    evidence, or unknown calendar state.
    """
    verdict = session_verdict(category, moment, holidays=holidays)
    stale = evidence_age_seconds > evidence_max_age_seconds
    verdict = verdict.model_copy(update={"stale": stale})

    if not tradeable:
        return ExposureReadiness(
            ready=False,
            reason="broker reports instrument not tradeable",
            session=verdict,
        )
    if not catalog_active:
        return ExposureReadiness(
            ready=False,
            reason="instrument inactive in the account catalog",
            session=verdict,
        )
    if stale:
        return ExposureReadiness(
            ready=False,
            reason="session evidence is stale",
            session=verdict,
        )
    if not verdict.open:
        return ExposureReadiness(
            ready=False,
            reason="market session is closed",
            session=verdict,
        )
    return ExposureReadiness(
        ready=True,
        reason="session open and instrument tradeable",
        session=verdict,
    )


__all__ = [
    "CATEGORY_SESSIONS",
    "DEFAULT_EVIDENCE_MAX_AGE_SECONDS",
    "ExposureReadiness",
    "HolidayCalendar",
    "SessionVerdict",
    "evaluate_exposure_readiness",
    "session_verdict",
]
