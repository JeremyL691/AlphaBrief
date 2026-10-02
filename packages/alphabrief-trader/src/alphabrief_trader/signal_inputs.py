"""Read-only cross-market evidence, with exact daily interval alignment."""

import json
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal

from alphabrief_core import Bar
from alphabrief_execution.broker.oanda.market_sync import SignalCandleObservation

from alphabrief_trader.market_inputs import build_market_inputs, candle_end
from alphabrief_trader.schemas import SignalInputEvidence, SignalMarketEvidence


def _return(previous: Bar, current: Bar) -> Decimal | None:
    if previous.close <= 0 or current.close <= 0:
        return None
    return (current.close / previous.close - 1) * 100


def _daily_returns(bars: list[Bar]) -> dict[tuple[datetime, datetime], Decimal]:
    # Pair BOTH boundaries: a two-day gap must not be compared to a one-day move.
    result = {}
    for previous, current in zip(bars[:-1], bars[1:], strict=True):
        value = _return(previous, current)
        if value is not None:
            result[
                (
                    candle_end(previous.timestamp, "D"),
                    candle_end(current.timestamp, "D"),
                )
            ] = value
    return result


def build_signal_inputs(
    observation: SignalCandleObservation,
    *,
    daily: list[Bar],
    now: datetime,
) -> SignalInputEvidence:
    """Never pad, forward-fill or substitute unrelated dates for 20 daily returns."""
    target = _daily_returns(daily[-21:])
    signals = {}
    for symbol, series in observation.series.items():
        inputs = build_market_inputs(series, symbol=symbol, now=now)
        h1, days = inputs.series["H1"], inputs.series["D"]
        signal_returns = _daily_returns(days)
        intervals = sorted(target.keys() & signal_returns.keys())
        pairs = [(target[key], signal_returns[key]) for key in intervals]
        digest = sha256(
            json.dumps(
                [
                    (start.isoformat(), end.isoformat(), str(x), str(y))
                    for (start, end), (x, y) in zip(intervals, pairs, strict=True)
                ]
            ).encode()
        ).hexdigest()
        correlation = None
        reason: (
            Literal[
                "insufficient_aligned_returns", "daily_end_mismatch", "zero_variance"
            ]
            | None
        ) = None
        if len(pairs) != 20:
            reason = "insufficient_aligned_returns"
        elif not days or not daily or days[-1].timestamp != daily[-1].timestamp:
            reason = "daily_end_mismatch"
        else:
            mean_x = sum((x for x, _ in pairs), Decimal(0)) / 20
            mean_y = sum((y for _, y in pairs), Decimal(0)) / 20
            xx = sum(((x - mean_x) ** 2 for x, _ in pairs), Decimal(0))
            yy = sum(((y - mean_y) ** 2 for _, y in pairs), Decimal(0))
            if xx == 0 or yy == 0:
                reason = "zero_variance"
            else:
                xy = sum(((x - mean_x) * (y - mean_y) for x, y in pairs), Decimal(0))
                # Decimal round-off at perfect +/-1 must not invalidate the fact.
                correlation = min(Decimal(1), max(Decimal(-1), xy / (xx * yy).sqrt()))
        signals[symbol] = SignalMarketEvidence(
            counts={tf: inputs.evidence.counts[tf] for tf in ("H1", "D")},
            series_hashes={tf: inputs.evidence.series_hashes[tf] for tf in ("H1", "D")},
            latest_h1_end=inputs.evidence.latest_h1_end,
            latest_daily_end=None if not days else candle_end(days[-1].timestamp, "D"),
            h1_return_pct=None if len(h1) < 2 else _return(h1[-2], h1[-1]),
            daily_return_pct=None if len(days) < 2 else _return(days[-2], days[-1]),
            correlation_20d=correlation,
            correlation_samples=len(pairs),
            correlation_input_hash=digest,
            correlation_reason=reason,
        )
    return SignalInputEvidence(
        signals=signals,
        excluded=observation.excluded,
        errors=observation.errors,
        observed_at=observation.observed_at,
    )
