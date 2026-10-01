"""Deterministic input-quality evaluation for the trading cycle.

PROJECT_GUIDE 5.3 requires every decision input to be fresh and complete,
and 5.7 rule 5 requires the risk gate to receive the *real* result of that
check — ``data_quality_passed`` must never be hardcoded.

This module evaluates the inputs the cycle actually holds (the market
snapshot) against explicit, versioned limits. Anything that cannot be
judged fails closed: a missing timestamp, a non-positive price, or an age
beyond the limit is a rejection, never an assumption.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from alphabrief_trader.schemas import MarketSnapshot

#: Version of the quality rules; bump when a limit changes.
QUALITY_POLICY_VERSION = "2026-10-01.1"
NO_TRADE_DATA_STALE: Literal["NO_TRADE_DATA_STALE"] = "NO_TRADE_DATA_STALE"

#: Maximum age of a snapshot's capture time (PROJECT_GUIDE 5.3: the latest
#: completed H1 candle must be at most 2 hours old during the session).
DEFAULT_MAX_AGE_SECONDS = 2 * 60 * 60

#: Maximum age of the account context (PROJECT_GUIDE 5.3: 60 seconds).
DEFAULT_MAX_ACCOUNT_AGE_SECONDS = 60


@dataclass(frozen=True)
class DataQualityVerdict:
    """One deterministic input-quality verdict."""

    passed: bool
    reasons: tuple[str, ...]
    policy_version: str = QUALITY_POLICY_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "reasons": list(self.reasons),
            "policy_version": self.policy_version,
        }


def evaluate_snapshot_quality(
    snapshot: MarketSnapshot,
    *,
    now: datetime,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> DataQualityVerdict:
    """Judge one snapshot's freshness and completeness.

    The verdict is fail-closed: any defect makes ``passed`` false and adds
    a stable reason string that is persisted with the decision.
    """
    reasons: list[str] = []
    if snapshot.reference_price <= 0:
        reasons.append("reference_price_not_positive")
    if not snapshot.data_version.strip():
        reasons.append("data_version_missing")
    captured_at = snapshot.captured_at
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        reasons.append("captured_at_not_timezone_aware")
    else:
        age = (now - captured_at.astimezone(UTC)).total_seconds()
        if age < -60:
            # A capture time in the future means the clock or the input is
            # wrong; that is a data-quality failure, not a rounding issue.
            reasons.append("captured_at_in_the_future")
        elif age > max_age_seconds:
            reasons.append(f"snapshot_stale_{int(age)}s")
    return DataQualityVerdict(passed=not reasons, reasons=tuple(reasons))


def evaluate_snapshots(
    snapshots: dict[str, MarketSnapshot],
    *,
    now: datetime,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    symbols: Sequence[str] | None = None,
) -> dict[str, DataQualityVerdict]:
    """Judge every snapshot in one cycle; missing symbols fail closed."""
    verdicts: dict[str, DataQualityVerdict] = {}
    for symbol in snapshots if symbols is None else symbols:
        snapshot = snapshots.get(symbol)
        if snapshot is None:
            verdicts[symbol] = DataQualityVerdict(False, ("snapshot_missing",))
        elif snapshot.symbol != symbol:
            verdicts[symbol] = DataQualityVerdict(False, ("snapshot_symbol_mismatch",))
        else:
            verdicts[symbol] = evaluate_snapshot_quality(
                snapshot, now=now, max_age_seconds=max_age_seconds
            )
    return verdicts


def quality_clock(
    clock: Callable[[], datetime] | None = None,
) -> Callable[[], datetime]:
    """Return the cycle clock (injected in tests, wall clock in production)."""
    return clock or (lambda: datetime.now(UTC))


__all__ = [
    "DEFAULT_MAX_ACCOUNT_AGE_SECONDS",
    "DEFAULT_MAX_AGE_SECONDS",
    "QUALITY_POLICY_VERSION",
    "NO_TRADE_DATA_STALE",
    "DataQualityVerdict",
    "evaluate_snapshot_quality",
    "evaluate_snapshots",
    "quality_clock",
]
