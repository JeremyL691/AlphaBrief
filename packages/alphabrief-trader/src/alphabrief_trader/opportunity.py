"""Deterministic opportunity scan for the unattended runtime (GUIDE 5.1).

Forex trades continuously from Monday 21:00 UTC to Friday 21:00 UTC. The
runtime must therefore look for an opportunity every 1-5 minutes during
that window, but a five-role committee round costs roughly 39 model calls
and the free channel is capped at 1000 calls per UTC day. Running the
committee every five minutes would burn the allowance in about two hours
and then sit blocked for the rest of the day.

The scan separates the two concerns:

* **Cheap and always on** - :func:`scan_opportunities` looks only at data
  the runtime already holds (stored candles, strategy signals, the
  broker's own quote and position facts). It calls no model, places no
  order, and writes nothing.
* **Expensive and rare** - only an escalating verdict may run the full
  committee. The guards below (daily round cap, minimum spacing, model
  budget availability) bound that escalation so the day's model spend
  stays inside the documented budget.

Every verdict carries a stable reason code. The runtime persists it with
the round record, so an operator can always answer "why did nothing
happen at 14:35" from facts instead of inference.

The module is pure: the same inputs always produce the same verdict, and
the caller's snapshots are never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from alphabrief_trader.schemas import MarketSnapshot

#: Why the scan did or did not escalate. Persisted with the round, so the
#: strings are a stable audit vocabulary: never rename one without a
#: migration note in STATUS.
ScanReason = Literal[
    "signal_above_threshold",
    "signal_against_position",
    "no_signal",
    "flat_signal",
    "confidence_below_floor",
    "already_positioned_same_direction",
    "market_closed",
    "quote_unusable",
    "data_unusable",
    "daily_round_cap_reached",
    "round_too_soon",
    "model_budget_unavailable",
]

#: Guide bounds for the check cadence (PROJECT_GUIDE 5.1: every 1-5 min).
_MIN_SCAN_SECONDS = 60
_MAX_SCAN_SECONDS = 300

#: Rough cost of one committee round in model calls: four analysis roles
#: plus the manager, times three symbols, plus repair headroom. It is a
#: planning number, not a limit; the gateway still enforces the real caps.
CALLS_PER_ROUND_ESTIMATE = 39

#: The free channel allows 1000 calls per UTC day. Fifteen rounds keeps
#: the worst case (15 x 39 = 585) comfortably inside it while leaving room
#: for repair calls, the single-call shadow baseline and the other tasks.
_DEFAULT_MAX_ROUNDS_PER_DAY = 15

#: Ten minutes between committee rounds. Together with the round cap this
#: bound what a market with a persistently non-flat signal can spend.
_DEFAULT_MIN_SPACING_SECONDS = 600

#: Below this confidence a strategy opinion is noise; the committee's own
#: determinism floor is 0.55, so a slightly higher bar gates escalation.
_DEFAULT_ESCALATION_MIN_CONFIDENCE = Decimal("0.60")

#: When nothing escalates, report the most informative reason present.
#: A signal that was too weak tells an operator more than "no signal".
NON_ESCALATING_PRIORITY: tuple[ScanReason, ...] = (
    "confidence_below_floor",
    "already_positioned_same_direction",
    "quote_unusable",
    "flat_signal",
    "no_signal",
)


@dataclass(frozen=True)
class OpportunityLimits:
    """The reviewed escalation boundary (written into config)."""

    scan_interval_seconds: int = 180
    max_rounds_per_day: int = _DEFAULT_MAX_ROUNDS_PER_DAY
    min_spacing_seconds: int = _DEFAULT_MIN_SPACING_SECONDS
    escalation_min_confidence: Decimal = _DEFAULT_ESCALATION_MIN_CONFIDENCE

    def __post_init__(self) -> None:
        if not _MIN_SCAN_SECONDS <= self.scan_interval_seconds <= _MAX_SCAN_SECONDS:
            raise ValueError(
                "opportunity.scan_interval_seconds must be between "
                f"{_MIN_SCAN_SECONDS} and {_MAX_SCAN_SECONDS} (GUIDE 5.1)"
            )
        if self.max_rounds_per_day <= 0:
            raise ValueError("opportunity.max_rounds_per_day must be positive")
        if self.min_spacing_seconds < 0:
            raise ValueError("opportunity.min_spacing_seconds must not be negative")
        confidence = self.escalation_min_confidence
        if not isinstance(confidence, Decimal) or not confidence.is_finite():
            raise ValueError(
                "opportunity.escalation_min_confidence must be a finite Decimal"
            )
        if not Decimal(0) <= confidence <= Decimal(1):
            raise ValueError(
                "opportunity.escalation_min_confidence must be within [0, 1]"
            )


@dataclass(frozen=True)
class SymbolOpportunity:
    """One symbol's verdict inside a scan."""

    symbol: str
    escalate: bool
    reason: ScanReason
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "escalate": self.escalate,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class OpportunityScan:
    """The whole universe's verdict for one check."""

    escalate: bool
    reason: ScanReason
    symbols: list[SymbolOpportunity] = field(default_factory=list)
    #: How many committee rounds the runtime had already recorded today.
    rounds_today: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalate": self.escalate,
            "reason": self.reason,
            "rounds_today": self.rounds_today,
            "symbols": [symbol.to_dict() for symbol in self.symbols],
        }

    def summary(self) -> str:
        """One line for the cycle record and the log."""
        escalating = [s.symbol for s in self.symbols if s.escalate]
        if self.escalate:
            return f"escalate ({self.reason}): {', '.join(escalating)}"
        return f"no round ({self.reason})"


def _decimal(value: Any) -> Decimal | None:
    """Read a Decimal from untrusted signal JSON without using float."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ArithmeticError):
            return None
        return parsed if parsed.is_finite() else None
    return None


def _strongest_signal(
    snapshot: MarketSnapshot,
) -> tuple[str, Decimal] | Literal["flat"] | None:
    """The highest-confidence directional opinion, ``"flat"``, or ``None``.

    ``None`` means no strategy expressed an opinion at all; ``"flat"``
    means at least one did and every one of them said "no view". Both
    refuse escalation, but they are different audit facts.

    When several strategies disagree the strongest one wins, which only
    ever makes the scan *more* willing to spend a round on a genuine
    disagreement; the committee still decides.
    """
    best: tuple[str, Decimal] | None = None
    saw_signal = False
    for _strategy_id, signal in sorted((snapshot.strategy_signals or {}).items()):
        if not isinstance(signal, dict):
            continue
        saw_signal = True
        direction = str(signal.get("direction") or "").strip().lower()
        if direction not in {"long", "short"}:
            continue
        confidence = _decimal(signal.get("confidence"))
        if confidence is None or not Decimal(0) <= confidence <= Decimal(1):
            continue
        if best is None or confidence > best[1]:
            best = (direction, confidence)
    if best is None:
        return "flat" if saw_signal else None
    return best


def _quote_usable(snapshot: MarketSnapshot) -> bool:
    """A round needs a real, positive, consistent quote to reason about."""
    facts = snapshot.broker_evidence
    if facts is None:
        # Minimal fixtures without broker facts keep their old scope; the
        # production snapshot always carries them.
        return snapshot.reference_price > 0
    if facts.bid is None or facts.ask is None:
        return False
    if facts.bid <= 0 or facts.ask <= 0 or facts.ask < facts.bid:
        return False
    return True


def _position_direction(snapshot: MarketSnapshot) -> int:
    """1 long, -1 short, 0 flat; an unusable fact counts as flat."""
    facts = snapshot.broker_evidence
    if facts is None or facts.position_units is None:
        return 0
    units = facts.position_units
    if not units.is_finite() or units == 0:
        return 0
    return 1 if units > 0 else -1


def _evaluate_symbol(
    snapshot: MarketSnapshot,
    *,
    limits: OpportunityLimits,
    session_open: bool,
) -> SymbolOpportunity:
    """One symbol's verdict, in the order the reasons matter."""
    symbol = snapshot.symbol
    if not session_open:
        return SymbolOpportunity(symbol, False, "market_closed", "outside FX session")
    if not _quote_usable(snapshot):
        return SymbolOpportunity(symbol, False, "quote_unusable", "no usable quote")
    strongest = _strongest_signal(snapshot)
    if strongest is None:
        return SymbolOpportunity(symbol, False, "no_signal", "no directional signal")
    if strongest == "flat":
        return SymbolOpportunity(
            symbol, False, "flat_signal", "every strategy reported flat"
        )
    direction, confidence = strongest
    if confidence < limits.escalation_min_confidence:
        return SymbolOpportunity(
            symbol,
            False,
            "confidence_below_floor",
            f"confidence {confidence} < {limits.escalation_min_confidence}",
        )
    held = _position_direction(snapshot)
    wanted = 1 if direction == "long" else -1
    if held == wanted:
        return SymbolOpportunity(
            symbol,
            False,
            "already_positioned_same_direction",
            f"already {direction}: no new exposure to consider",
        )
    if held != 0:
        # The committee may close or hold; that is a real decision.
        return SymbolOpportunity(
            symbol,
            True,
            "signal_against_position",
            f"signal {direction} is against the held position",
        )
    return SymbolOpportunity(
        symbol,
        True,
        "signal_above_threshold",
        f"{direction} at confidence {confidence}",
    )


def scan_opportunities(
    snapshots: list[MarketSnapshot],
    *,
    session_open: bool,
    limits: OpportunityLimits,
    now: datetime,
    rounds_today: int = 0,
    last_round_at: datetime | None = None,
    budget_available: bool = True,
) -> OpportunityScan:
    """Decide whether one opportunity check should become a committee round.

    ``session_open`` is the deterministic FX session verdict for ``now``;
    ``rounds_today`` and ``last_round_at`` come from the durable cycle
    history so a restart cannot hand the runtime a fresh allowance.
    ``budget_available`` is the model gateway's own daily verdict.
    """
    symbol_verdicts = [
        _evaluate_symbol(snapshot, limits=limits, session_open=session_open)
        for snapshot in snapshots
    ]

    def _result(reason: ScanReason) -> OpportunityScan:
        return OpportunityScan(
            escalate=False,
            reason=reason,
            symbols=symbol_verdicts,
            rounds_today=rounds_today,
        )

    if not session_open:
        return _result("market_closed")

    trigger = next((v for v in symbol_verdicts if v.escalate), None)
    if trigger is None:
        # Report the most informative non-escalating reason: a signal that
        # was too weak is more useful than "no signal at all".
        for reason in NON_ESCALATING_PRIORITY:
            if any(v.reason == reason for v in symbol_verdicts):
                return _result(reason)
        return _result("no_signal")

    if not budget_available:
        return _result("model_budget_unavailable")
    if rounds_today >= limits.max_rounds_per_day:
        return _result("daily_round_cap_reached")
    if last_round_at is not None:
        gap = (now.astimezone(UTC) - last_round_at.astimezone(UTC)).total_seconds()
        if gap < limits.min_spacing_seconds:
            return _result("round_too_soon")
    return OpportunityScan(
        escalate=True,
        reason=trigger.reason,
        symbols=symbol_verdicts,
        rounds_today=rounds_today,
    )


__all__ = [
    "CALLS_PER_ROUND_ESTIMATE",
    "OpportunityLimits",
    "OpportunityScan",
    "ScanReason",
    "SymbolOpportunity",
    "scan_opportunities",
]
