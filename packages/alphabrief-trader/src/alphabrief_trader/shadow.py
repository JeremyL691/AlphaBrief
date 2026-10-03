"""Shadow evaluation (PROJECT_GUIDE 5.11): record, never trade.

Every round records five decisions per symbol side by side:

1. ``committee`` — what the five-role committee decided;
2. ``single_call`` — the same input with one manager-only model call
   (recorded as skipped when the daily budget does not allow it);
3. ``momentum`` — long when the 20-day return is positive, short when
   negative;
4. ``random`` — seeded by ``hash(cycle_id)``, so it is reproducible;
5. ``no_trade`` — the always-flat control.

Each decision is scored 4 and 24 hours later against the OANDA mid price,
net of the spread at scoring time. The statistics carry an explicit
caveat: a 14-day sample cannot establish that any benchmark works.

Everything in this module is deterministic and side-effect free; the
durable store lives in :mod:`alphabrief_trader.shadow_store`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from random import Random
from typing import Literal

#: The five benchmark identifiers, in the guide's order.
SHADOW_BENCHMARKS = (
    "committee",
    "single_call",
    "momentum",
    "random",
    "no_trade",
)

#: Scoring horizons in hours (PROJECT_GUIDE 5.11).
SHADOW_HORIZONS_HOURS = (4, 24)

#: The 20-day momentum window.
MOMENTUM_WINDOW_DAYS = 20

ShadowSide = Literal["long", "short", "flat"]

#: Where a single-call row came from: a real answer, or why there is none.
SINGLE_CALL_SOURCES = ("model", "skipped", "failed")

#: Row sources that are not decisions and must never be scored as samples.
UNSCORED_SOURCES = ("skipped", "failed")

#: The caveat every statistics payload must carry (PROJECT_GUIDE 5.11).
SMALL_SAMPLE_CAVEAT = (
    "14 days of samples is not enough to judge whether any benchmark is "
    "effective; treat these numbers as descriptive only"
)


class ShadowError(ValueError):
    """Raised when a shadow decision or score is malformed."""


@dataclass(frozen=True)
class ShadowDecision:
    """One recorded shadow decision (no order is ever placed)."""

    cycle_id: str
    symbol: str
    benchmark: str
    side: ShadowSide
    source: str
    detail: str
    decided_at: datetime
    entry_mid: Decimal | None = None

    def __post_init__(self) -> None:
        if self.benchmark not in SHADOW_BENCHMARKS:
            raise ShadowError(f"unknown shadow benchmark {self.benchmark!r}")
        if self.side not in ("long", "short", "flat"):
            raise ShadowError(f"unknown shadow side {self.side!r}")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "cycle_id": self.cycle_id,
            "symbol": self.symbol,
            "benchmark": self.benchmark,
            "side": self.side,
            "source": self.source,
            "detail": self.detail,
            "decided_at": self.decided_at.isoformat(),
            "entry_mid": None if self.entry_mid is None else str(self.entry_mid),
        }


@dataclass(frozen=True)
class ShadowScore:
    """One scored shadow decision at a fixed horizon."""

    cycle_id: str
    symbol: str
    benchmark: str
    horizon_hours: int
    return_pct: Decimal
    exit_mid: Decimal
    spread_at_exit: Decimal
    scored_at: datetime


@dataclass(frozen=True)
class ShadowStats:
    """Aggregated results for one benchmark at one horizon."""

    benchmark: str
    horizon_hours: int
    samples: int
    mean_return_pct: Decimal
    win_rate: Decimal
    ci_low_pct: Decimal
    ci_high_pct: Decimal
    caveat: str = SMALL_SAMPLE_CAVEAT

    def to_dict(self) -> dict[str, str | int]:
        return {
            "benchmark": self.benchmark,
            "horizon_hours": self.horizon_hours,
            "samples": self.samples,
            "mean_return_pct": str(self.mean_return_pct),
            "win_rate": str(self.win_rate),
            "ci_low_pct": str(self.ci_low_pct),
            "ci_high_pct": str(self.ci_high_pct),
            "caveat": self.caveat,
        }


def momentum_side(
    closes: Sequence[Decimal], *, window: int = MOMENTUM_WINDOW_DAYS
) -> ShadowSide:
    """Long when the ``window``-day return is positive, short when negative."""
    if window <= 0:
        raise ShadowError("window must be positive")
    if len(closes) < window + 1:
        raise ShadowError(
            f"momentum needs {window + 1} closes, got {len(closes)}"
        )
    first = closes[-window - 1]
    last = closes[-1]
    if first <= 0:
        raise ShadowError("closes must be positive")
    if last > first:
        return "long"
    if last < first:
        return "short"
    return "flat"


def random_side(cycle_id: str, symbol: str) -> ShadowSide:
    """A reproducible side: the seed is the hash of the cycle id."""
    if not cycle_id:
        raise ShadowError("cycle_id is required for the random benchmark")
    seed = int(sha256(cycle_id.encode()).hexdigest(), 16)
    picker = Random(seed)
    return picker.choice(["long", "short"])


def committee_side(
    *, side: str | None, target_position_pct: Decimal | None
) -> ShadowSide:
    """The committee's own directional call for the shadow record."""
    if side not in {"buy", "sell"}:
        return "flat"
    if target_position_pct is not None and target_position_pct <= 0:
        return "flat"
    return "long" if side == "buy" else "short"


def single_call_decision(
    *,
    cycle_id: str,
    symbol: str,
    decided_at: datetime,
    entry_mid: Decimal | None,
    source: str,
    side: ShadowSide,
    detail: str,
) -> ShadowDecision:
    """The single-call benchmark row (PROJECT_GUIDE 5.11).

    ``source`` is ``model`` for a real, parsed manager answer, ``skipped``
    when the budget or channel did not allow the call, and ``failed`` when a
    call produced no usable answer. Only ``model`` carries a real side: a
    skipped or failed baseline is flat and is never scored as a sample, so it
    cannot pass for the model choosing ``no_trade``.
    """
    if source not in SINGLE_CALL_SOURCES:
        raise ShadowError(f"unknown single-call source {source!r}")
    if source != "model" and side != "flat":
        raise ShadowError("a skipped or failed single call cannot carry a side")
    return ShadowDecision(
        cycle_id=cycle_id,
        symbol=symbol,
        benchmark="single_call",
        side=side,
        source=source,
        detail=detail,
        decided_at=decided_at,
        entry_mid=entry_mid,
    )


def build_shadow_decisions(
    *,
    cycle_id: str,
    symbol: str,
    decided_at: datetime,
    entry_mid: Decimal | None,
    committee: ShadowSide,
    committee_detail: str,
    momentum: ShadowSide | None,
    momentum_detail: str,
    single_call: ShadowSide | None = None,
    single_call_detail: str = "not attempted",
    include_single_call: bool = True,
    committee_source: str = "committee",
) -> tuple[ShadowDecision, ...]:
    """Build the shadow decisions for one symbol in one round.

    All five by default. The daily cycle passes ``include_single_call=False``
    because that baseline needs a budgeted model call that only runs after
    the round's committee calls, so its row is written separately.
    """
    decisions = (
        ShadowDecision(
            cycle_id=cycle_id,
            symbol=symbol,
            benchmark="committee",
            side=committee,
            source=committee_source,
            detail=committee_detail,
            decided_at=decided_at,
            entry_mid=entry_mid,
        ),
        single_call_decision(
            cycle_id=cycle_id,
            symbol=symbol,
            decided_at=decided_at,
            entry_mid=entry_mid,
            source="model" if single_call is not None else "skipped",
            side=single_call if single_call is not None else "flat",
            detail=single_call_detail,
        ),
        ShadowDecision(
            cycle_id=cycle_id,
            symbol=symbol,
            benchmark="momentum",
            side=momentum if momentum is not None else "flat",
            source="momentum" if momentum is not None else "skipped",
            detail=momentum_detail,
            decided_at=decided_at,
            entry_mid=entry_mid,
        ),
        ShadowDecision(
            cycle_id=cycle_id,
            symbol=symbol,
            benchmark="random",
            side=random_side(cycle_id, symbol),
            source="random",
            detail="seeded by hash(cycle_id)",
            decided_at=decided_at,
            entry_mid=entry_mid,
        ),
        ShadowDecision(
            cycle_id=cycle_id,
            symbol=symbol,
            benchmark="no_trade",
            side="flat",
            source="control",
            detail="always flat",
            decided_at=decided_at,
            entry_mid=entry_mid,
        ),
    )
    if include_single_call:
        return decisions
    return tuple(item for item in decisions if item.benchmark != "single_call")


def directional_return_pct(
    *,
    side: ShadowSide,
    entry_mid: Decimal,
    exit_mid: Decimal,
    spread_at_exit: Decimal,
) -> Decimal:
    """Directional return from entry to exit, net of the exit spread.

    The guide scores with mid prices and charges the spread in force at
    scoring time, so a flat decision scores exactly zero and a spread
    wider than the move can turn a correct direction negative.
    """
    if entry_mid <= 0 or exit_mid <= 0:
        raise ShadowError("prices must be positive")
    if spread_at_exit < 0:
        raise ShadowError("spread must not be negative")
    if side == "flat":
        return Decimal("0")
    move = (exit_mid - entry_mid) / entry_mid
    if side == "short":
        move = -move
    spread_cost = spread_at_exit / exit_mid
    return (move - spread_cost) * Decimal("100")


def summarize(
    returns: Sequence[Decimal],
    *,
    benchmark: str,
    horizon_hours: int,
    bootstrap_samples: int = 1000,
    seed: int | None = None,
) -> ShadowStats:
    """Sample count, mean, win rate and a 95% bootstrap confidence interval.

    The bootstrap is seeded deterministically (from the sample content
    unless a seed is given), so the same evidence always yields the same
    interval — a report that changes on re-run would be unauditable.
    """
    if bootstrap_samples <= 0:
        raise ShadowError("bootstrap_samples must be positive")
    if not returns:
        return ShadowStats(
            benchmark=benchmark,
            horizon_hours=horizon_hours,
            samples=0,
            mean_return_pct=Decimal("0"),
            win_rate=Decimal("0"),
            ci_low_pct=Decimal("0"),
            ci_high_pct=Decimal("0"),
        )
    values = list(returns)
    count = len(values)
    mean = sum(values, Decimal("0")) / Decimal(count)
    wins = sum(1 for value in values if value > 0)
    win_rate = Decimal(wins) / Decimal(count)
    picker = Random(
        seed
        if seed is not None
        else int(
            sha256("|".join(str(value) for value in values).encode()).hexdigest(),
            16,
        )
    )
    means: list[Decimal] = []
    for _ in range(bootstrap_samples):
        sample = [values[picker.randrange(count)] for _ in range(count)]
        means.append(sum(sample, Decimal("0")) / Decimal(count))
    means.sort()
    low_index = max(0, int(0.025 * bootstrap_samples) - 1)
    high_index = min(bootstrap_samples - 1, int(0.975 * bootstrap_samples))
    return ShadowStats(
        benchmark=benchmark,
        horizon_hours=horizon_hours,
        samples=count,
        mean_return_pct=mean,
        win_rate=win_rate,
        ci_low_pct=means[low_index],
        ci_high_pct=means[high_index],
    )


__all__ = [
    "MOMENTUM_WINDOW_DAYS",
    "SHADOW_BENCHMARKS",
    "SHADOW_HORIZONS_HOURS",
    "SINGLE_CALL_SOURCES",
    "SMALL_SAMPLE_CAVEAT",
    "UNSCORED_SOURCES",
    "ShadowDecision",
    "ShadowError",
    "ShadowScore",
    "ShadowSide",
    "ShadowStats",
    "build_shadow_decisions",
    "committee_side",
    "directional_return_pct",
    "momentum_side",
    "random_side",
    "single_call_decision",
    "summarize",
]
