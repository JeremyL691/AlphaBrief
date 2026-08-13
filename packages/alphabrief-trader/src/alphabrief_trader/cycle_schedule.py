"""Deterministic daily cycle keys and catch-up policy (M11-W05).

Repeating the same trading date and snapshot key returns the existing
terminal cycle; a missed cycle runs only inside its configured catch-up
window and records ``expired_without_chase`` after the window closes —
retries and missed schedules never duplicate or chase obsolete trades.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256


def daily_cycle_key(trading_date: str, snapshot_key: str) -> str:
    """Deterministic key for one (trading date, snapshot) pair."""
    raw = f"daily:{trading_date}:{snapshot_key}"
    return f"daily_{sha256(raw.encode('utf-8')).hexdigest()[:16]}"


@dataclass(frozen=True)
class CatchUpVerdict:
    """Whether a missed cycle may still run, or has expired."""

    allowed: bool
    reason: str
    age_seconds: int = 0


class CatchUpPolicy:
    """Deterministic catch-up window over an injected clock."""

    def __init__(
        self,
        *,
        window_hours: int = 24,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if window_hours <= 0:
            raise ValueError("window_hours must be positive")
        self._window = timedelta(hours=window_hours)
        self._clock = clock or (lambda: datetime.now(UTC))

    def evaluate(self, scheduled_at: datetime) -> CatchUpVerdict:
        """Return whether a cycle scheduled at *scheduled_at* may run now."""
        now = self._clock()
        age = (now - scheduled_at).total_seconds()
        if age <= 0:
            return CatchUpVerdict(
                allowed=True, reason="on_time", age_seconds=max(0, int(age))
            )
        if age <= self._window.total_seconds():
            return CatchUpVerdict(
                allowed=True,
                reason="within_catchup_window",
                age_seconds=int(age),
            )
        return CatchUpVerdict(
            allowed=False,
            reason="expired_without_chase",
            age_seconds=int(age),
        )


__all__ = ["CatchUpPolicy", "CatchUpVerdict", "daily_cycle_key"]
