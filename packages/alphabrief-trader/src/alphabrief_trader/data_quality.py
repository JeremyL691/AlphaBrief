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
QUALITY_POLICY_VERSION = "2026-10-02.3"
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
    if snapshot.market_evidence is not None:
        from alphabrief_execution.broker.oanda.market_sync import TIMEFRAMES

        evidence_market = snapshot.market_evidence
        reasons.extend(
            f"market_{timeframe}_refresh_failed"
            for timeframe in sorted(evidence_market.refresh_errors)
        )
        for timeframe, count in TIMEFRAMES:
            if evidence_market.counts.get(timeframe, 0) != count:
                reasons.append(f"completed_{timeframe}_count_not_{count}")
            if not evidence_market.series_hashes.get(timeframe):
                reasons.append(f"{timeframe}_series_hash_missing")
        end = evidence_market.latest_h1_end
        if end is None:
            reasons.append("completed_H1_end_missing")
        elif not 0 <= (now - end).total_seconds() <= max_age_seconds:
            reasons.append("completed_H1_end_stale_or_future")
        if snapshot.atr is None or snapshot.atr <= 0:
            reasons.append("atr_missing_or_not_positive")
        if snapshot.momentum_20d_pct is None:
            reasons.append("return_20d_missing")
        if snapshot.volatility_20d_pct is None:
            reasons.append("volatility_20d_missing")
    if snapshot.broker_evidence is not None:
        broker = snapshot.broker_evidence
        if broker.symbol != snapshot.symbol:
            reasons.append("broker_input_symbol_mismatch")
        reasons.extend(
            f"broker_{source}_unavailable" for source in sorted(broker.errors)
        )
        for field, limit in (
            ("quote_captured_at", 15), ("account_captured_at", 60),
            ("positions_captured_at", 60), ("reconciliation_captured_at", 60),
        ):
            captured = getattr(broker, field)
            if captured is None:
                reasons.append(f"{field}_missing")
            elif not 0 <= (now - captured).total_seconds() <= limit:
                reasons.append(f"{field}_stale_or_future")
        for field in ("bid", "ask", "quote_to_home", "quote_position_to_home", "nav"):
            value = getattr(broker, field)
            if value is None or value <= 0:
                reasons.append(f"{field}_missing_or_not_positive")
        if broker.spread is None or broker.spread < 0:
            reasons.append("spread_missing_or_negative")
        elif broker.bid is not None and broker.ask is not None:
            if broker.ask < broker.bid or broker.spread != broker.ask - broker.bid:
                reasons.append("quote_spread_inconsistent")
        for field in (
            "margin_available", "position_units", "position_unrealized_pnl",
            "daily_open_count",
        ):
            if getattr(broker, field) is None:
                reasons.append(f"{field}_missing")
    if snapshot.signal_evidence is not None:
        from alphabrief_execution.broker.oanda.market_sync import (
            SIGNAL_INSTRUMENTS,
            SIGNAL_TIMEFRAMES,
        )

        signals = snapshot.signal_evidence
        configured = set(SIGNAL_INSTRUMENTS)
        supplied, excluded = set(signals.signals), set(signals.excluded)
        if (supplied | excluded) != configured or supplied & excluded:
            reasons.append("signal_coverage_missing_or_invalid")
        if not 0 <= (now - signals.observed_at).total_seconds() <= max_age_seconds:
            reasons.append("signal_observation_stale_or_future")
        reasons.extend(f"signal_fetch_failed:{key}" for key in sorted(signals.errors))
        for symbol, facts in sorted(signals.signals.items()):
            prefix = f"signal:{symbol}:"
            for timeframe, count in SIGNAL_TIMEFRAMES:
                if facts.counts.get(timeframe) != count:
                    reasons.append(prefix + f"{timeframe}_count_not_{count}")
                if not facts.series_hashes.get(timeframe):
                    reasons.append(prefix + f"{timeframe}_hash_missing")
            if facts.latest_h1_end is None or not 0 <= (
                now - facts.latest_h1_end
            ).total_seconds() <= max_age_seconds:
                reasons.append(prefix + "H1_stale_or_future")
            if facts.latest_daily_end is None or facts.latest_daily_end > now:
                reasons.append(prefix + "D_end_missing_or_future")
            if facts.h1_return_pct is None or facts.daily_return_pct is None:
                reasons.append(prefix + "returns_missing")
            if (facts.correlation_20d is None or facts.correlation_samples != 20
                    or not facts.correlation_input_hash or facts.correlation_reason):
                reasons.append(prefix + "correlation_20d_unavailable")
    if snapshot.news_evidence is not None:
        from alphabrief_news.providers.rss import SOURCE_FAMILIES

        evidence = snapshot.news_evidence
        fresh_families = {
            family for family, fetched_at in evidence.family_fetched_at.items()
            if family in SOURCE_FAMILIES
            and 0 <= (now - fetched_at).total_seconds() <= 6 * 60 * 60
        }
        if len(fresh_families) < 2:
            reasons.append("news_successful_families_below_2")
        if not evidence.related_published_at:
            reasons.append("related_news_missing")
        else:
            latest = max(evidence.related_published_at.values())
            age = (now - latest).total_seconds()
            if age < 0:
                reasons.append("related_news_in_the_future")
            elif age > 6 * 60 * 60:
                reasons.append(f"related_news_stale_{int(age)}s")
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
