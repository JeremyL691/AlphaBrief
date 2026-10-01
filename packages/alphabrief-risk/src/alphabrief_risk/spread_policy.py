"""Rule 4: the spread must not be wide against its own recent median.

PROJECT_GUIDE 5.7 rule 4: reject an entry when the current spread exceeds
**twice the median of the same instrument's last 20 samples for the same
period** (``SPREAD_WIDE``).

The rule is pure: the caller supplies the current spread and the sample
history it already read from the durable sample store (see
:mod:`alphabrief_data.quote_samples`). Two deliberate choices:

* **fail closed without history** — with fewer than
  ``DEFAULT_MIN_SPREAD_SAMPLES`` same-period samples there is no median to
  compare against, so the entry is rejected with the reason recorded
  rather than assumed safe;
* **median, not mean** — a single spike in the sample history must not
  widen the tolerance for everyone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

#: The multiplier from the guide: spread <= 2 x median.
SPREAD_MEDIAN_MULTIPLIER = Decimal("2")

#: Minimum same-period samples before the rule can judge a spread.
DEFAULT_MIN_SPREAD_SAMPLES = 5

#: The sample window the guide names.
SPREAD_SAMPLE_WINDOW = 20


@dataclass(frozen=True)
class SpreadVerdict:
    """One deterministic spread verdict for an entry."""

    allowed: bool
    current_spread: Decimal
    median_spread: Decimal | None
    samples: int
    limit: Decimal | None
    reason: str
    code: str

    def to_dict(self) -> dict[str, str | bool | int | None]:
        return {
            "allowed": self.allowed,
            "current_spread": str(self.current_spread),
            "median_spread": (
                None if self.median_spread is None else str(self.median_spread)
            ),
            "samples": self.samples,
            "limit": None if self.limit is None else str(self.limit),
            "reason": self.reason,
            "code": self.code,
        }


def median(values: Sequence[Decimal]) -> Decimal:
    """The median of a non-empty sequence (mean of the middle pair)."""
    if not values:
        raise ValueError("median of an empty sequence is undefined")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def evaluate_spread(
    *,
    current_spread: Decimal,
    recent_spreads: Sequence[Decimal],
    multiplier: Decimal = SPREAD_MEDIAN_MULTIPLIER,
    min_samples: int = DEFAULT_MIN_SPREAD_SAMPLES,
) -> SpreadVerdict:
    """Compare the current spread against its own recent same-period median."""
    if current_spread < 0:
        raise ValueError("current_spread must not be negative")
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    if min_samples < 1:
        raise ValueError("min_samples must be at least 1")
    for value in recent_spreads:
        if value < 0:
            raise ValueError("sample spreads must not be negative")

    samples = len(recent_spreads)
    if samples < min_samples:
        return SpreadVerdict(
            allowed=False,
            current_spread=current_spread,
            median_spread=None,
            samples=samples,
            limit=None,
            reason=(
                f"only {samples} same-period spread sample(s) available; "
                f"{min_samples} are required to judge the spread"
            ),
            code="SPREAD_WIDE",
        )

    median_spread = median(recent_spreads)
    limit = median_spread * multiplier
    if current_spread > limit:
        return SpreadVerdict(
            allowed=False,
            current_spread=current_spread,
            median_spread=median_spread,
            samples=samples,
            limit=limit,
            reason=(
                f"spread {current_spread} exceeds {multiplier} x the median "
                f"{median_spread} of the last {samples} samples"
            ),
            code="SPREAD_WIDE",
        )
    return SpreadVerdict(
        allowed=True,
        current_spread=current_spread,
        median_spread=median_spread,
        samples=samples,
        limit=limit,
        reason=(
            f"spread {current_spread} is within {multiplier} x the median "
            f"{median_spread} of the last {samples} samples"
        ),
        code="",
    )


__all__ = [
    "DEFAULT_MIN_SPREAD_SAMPLES",
    "SPREAD_MEDIAN_MULTIPLIER",
    "SPREAD_SAMPLE_WINDOW",
    "SpreadVerdict",
    "evaluate_spread",
    "median",
]
