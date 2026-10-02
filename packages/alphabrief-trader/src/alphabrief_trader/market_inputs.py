"""Completed candle windows and Decimal features for production snapshots."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

from alphabrief_core import Bar
from alphabrief_execution.broker.oanda.market_sync import BAR_SOURCE, TIMEFRAMES

from alphabrief_trader.schemas import MarketInputEvidence
from alphabrief_trader.stops import atr_from_bars


def candle_end(start: datetime, timeframe: str) -> datetime:
    """Daily OANDA candles close at the next New York alignment, including DST."""
    if timeframe == "D":
        local = start.astimezone(ZoneInfo("America/New_York"))
        return (local + timedelta(days=1)).astimezone(UTC)
    minutes = {"M15": 15, "H1": 60, "H4": 240}[timeframe]
    return start + timedelta(minutes=minutes)


@dataclass(frozen=True)
class MarketInputs:
    series: dict[str, list[Bar]]
    evidence: MarketInputEvidence
    atr: Decimal | None
    return_20d_pct: Decimal | None
    volatility_20d_pct: Decimal | None


def build_market_inputs(
    series: Mapping[str, Sequence[Bar]], *, symbol: str, now: datetime
) -> MarketInputs:
    """Select bounded complete series; never pad missing history or mix components."""
    windows: dict[str, list[Bar]] = {}
    hashes: dict[str, str] = {}
    for timeframe, count in TIMEFRAMES:
        by_time = {
            bar.timestamp: bar
            for bar in series.get(timeframe, ())
            if bar.symbol == symbol
            and bar.source == BAR_SOURCE
            and bar.data_version.endswith(f":M:{timeframe}")
            and candle_end(bar.timestamp, timeframe) <= now
        }
        bars = [by_time[t] for t in sorted(by_time)][-count:]
        windows[timeframe] = bars
        hashes[timeframe] = sha256(
            "\n".join(bar.model_dump_json() for bar in bars).encode()
        ).hexdigest()
    h1 = windows["H1"]
    daily = windows["D"]
    returns: list[Decimal] = []
    momentum = volatility = None
    if len(daily) >= 21:
        closes = [bar.close for bar in daily[-21:]]
        if all(price > 0 for price in closes):
            returns = [
                (b / a - 1) * 100 for a, b in zip(closes[:-1], closes[1:], strict=True)
            ]
            momentum = (closes[-1] / closes[0] - 1) * 100
            mean = sum(returns, Decimal(0)) / len(returns)
            variance = sum(
                ((value - mean) ** 2 for value in returns), Decimal(0)
            ) / len(returns)
            volatility = variance.sqrt()
    return MarketInputs(
        series=windows,
        evidence=MarketInputEvidence(
            counts={tf: len(bars) for tf, bars in windows.items()},
            series_hashes=hashes,
            latest_h1_end=None if not h1 else candle_end(h1[-1].timestamp, "H1"),
        ),
        atr=atr_from_bars(
            [b.high for b in h1], [b.low for b in h1], [b.close for b in h1]
        ),
        return_20d_pct=momentum,
        volatility_20d_pct=volatility,
    )
