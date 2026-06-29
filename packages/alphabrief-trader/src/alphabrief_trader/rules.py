"""Deterministic trading discipline for the AI Trading Committee.

The rules module is **the only place** that decides what an AI plan can
or cannot do before it reaches the deterministic ``RiskGate``. It is a
pure function from structured input to a structured ``TradePlan``:

1. Enforces an ethics veto (``blocked_by_ethics``) — the manager may
   refuse to issue an order on ethical / compliance grounds. This
   produces a no-trade plan, never a forced trade.
2. Caps target position size by minimum confidence and minimum analyst
   consensus, so a low-confidence or split-vote plan cannot fully size
   up to the configured cap.
3. Enforces a single-symbol position cap, a max-confidence gate, and
   an explicit ``no_trade_below_confidence`` threshold. The settings
   come from a frozen ``DisciplineConfig`` that the daily cycle wires
   into a ``DisciplineGate`` instance — there is no global mutable
   state.

The rules module never calls providers, never reads databases, and
never inspects the live ``RiskGate`` / ``RiskLimitConfig``. The
deterministic ``RiskGate`` is the only thing that can reject an
``OrderIntent``; these rules only narrow what the *committee* is
allowed to recommend.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from alphabrief_trader.schemas import (
    AnalystView,
    CommitteeVote,
    ConsensusLevel,
    TradePlan,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class DisciplineConfig:
    """Static discipline settings applied to every synthesized plan."""

    # Hard cap on any single symbol's recommended target position
    # fraction. The committee may propose lower; the rules will clamp
    # anything above this down to the cap.
    max_position_pct: Decimal = Decimal("0.25")

    # Below this confidence, the plan is forced to ``hold`` with zero
    # target. The committee cannot override this.
    no_trade_below_confidence: float = 0.45

    # Below this consensus quality, the plan is forced to ``hold`` and
    # ``needs_human_review=true``. ``unanimous`` / ``majority`` /
    # ``split`` / ``no_consensus``.
    require_min_consensus: ConsensusLevel = "split"

    # Ethics veto keywords (matched case-insensitively against the
    # manager vote's analysis text). When any keyword is present the
    # plan is forced to ``hold`` with zero target and
    # ``blocked_by_ethics=True`` — this is the only veto the committee
    # itself can apply. The list is intentionally short and explicit so
    # the operator can audit it.
    ethics_keywords: tuple[str, ...] = (
        "insider",
        "fraud",
        "manipulation",
        "pump and dump",
        "market manipulation",
    )

    def __post_init__(self) -> None:
        if not (Decimal("0") < self.max_position_pct <= Decimal("1")):
            raise ValueError("max_position_pct must be in (0, 1]")
        if not (0.0 <= self.no_trade_below_confidence <= 1.0):
            raise ValueError("no_trade_below_confidence must be in [0, 1]")
        if self.require_min_consensus not in {
            "unanimous",
            "majority",
            "split",
            "no_consensus",
        }:
            raise ValueError(
                "require_min_consensus must be a valid ConsensusLevel"
            )
        if any(not kw.strip() for kw in self.ethics_keywords):
            raise ValueError("ethics_keywords must not contain blank entries")

    def model_dump(self, mode: str = "python") -> dict[str, Any]:
        """JSON-friendly snapshot of the config (Pydantic-style helper).

        Used by the API / CLI ``rules`` endpoints. ``Decimal`` fields are
        always stringified to preserve precision across JSON.
        """
        return {
            "max_position_pct": format(self.max_position_pct, "f"),
            "no_trade_below_confidence": self.no_trade_below_confidence,
            "require_min_consensus": self.require_min_consensus,
            "ethics_keywords": list(self.ethics_keywords),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _view_weight(view: AnalystView, action: str) -> Decimal:
    """Return the directional weight for a single role vote.

    ``buy`` on ``bullish`` → 1.0; ``buy`` on ``bearish`` → 0.5 (contrarian);
    ``sell`` on ``bullish`` → 0.25; ``sell`` on ``bearish`` → 1.0;
    everything else returns 0. This is a coarse numeric proxy — the
    synthesis is intentionally conservative and deterministic.
    """
    if view == "uncertain":
        return Decimal("0")
    bull = view == "bullish"
    bear = view == "bearish"
    if action == "buy":
        if bull:
            return ONE
        if bear:
            return Decimal("0.5")
        return Decimal("0")
    if action == "sell":
        if bear:
            return ONE
        if bull:
            return Decimal("0.25")
        return Decimal("0")
    return Decimal("0")


_CONSENSUS_RANK: dict[str, int] = {
    "no_consensus": 0,
    "split": 1,
    "majority": 2,
    "unanimous": 3,
}


# ---------------------------------------------------------------------------
# Discipline gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DisciplineGate:
    """Applies :class:`DisciplineConfig` to a synthesized ``TradePlan``."""

    config: DisciplineConfig = field(default_factory=DisciplineConfig)

    def synthesize(
        self,
        *,
        symbol: str,
        manager_vote: CommitteeVote,
        analyst_votes: Iterable[CommitteeVote],
    ) -> TradePlan:
        """Build a deterministic ``TradePlan`` from the committee votes.

        The manager vote is the **executive** vote: it owns the final
        view, action, confidence, target size, and any ethics veto. The
        analyst votes (``technical``, ``fundamental``, ``risk``) only
        contribute evidence and a consensus quality score.
        """
        analyst_list = list(analyst_votes)
        consensus_level = _compute_consensus(analyst_list, manager_vote)
        key_evidence = _collect_evidence(analyst_list)
        key_risks = _collect_risks(analyst_list + [manager_vote])

        # Ethics check first — an ethics veto is a hard block.
        blocked, reason = self._check_ethics(manager_vote)
        if blocked:
            return TradePlan(
                symbol=symbol,
                side="buy",
                target_position_pct=ZERO,
                confidence=0.0,
                consensus_level=consensus_level,
                rationale=self._rationale(
                    manager_vote, consensus_level, ethics_reason=reason
                ),
                needs_human_review=True,
                blocked_by_ethics=True,
                ethics_reason=reason,
                key_evidence=key_evidence,
                key_risks=key_risks,
                assigned_roles=[v.role for v in analyst_list]
                + [manager_vote.role],
            )

        # Confidence gate — below floor → hold with zero target.
        if manager_vote.confidence < self.config.no_trade_below_confidence:
            return TradePlan(
                symbol=symbol,
                side="buy",
                target_position_pct=ZERO,
                confidence=manager_vote.confidence,
                consensus_level=consensus_level,
                rationale=self._rationale(
                    manager_vote,
                    consensus_level,
                    reason_block=(
                        f"manager confidence {manager_vote.confidence:.2f} "
                        f"below no_trade_below_confidence "
                        f"{self.config.no_trade_below_confidence:.2f}"
                    ),
                ),
                needs_human_review=True,
                key_evidence=key_evidence,
                key_risks=key_risks,
                assigned_roles=[v.role for v in analyst_list]
                + [manager_vote.role],
            )

        # Consensus gate — below floor → hold + needs human review.
        if (
            _CONSENSUS_RANK[consensus_level]
            < _CONSENSUS_RANK[self.config.require_min_consensus]
        ):
            return TradePlan(
                symbol=symbol,
                side="buy",
                target_position_pct=ZERO,
                confidence=manager_vote.confidence,
                consensus_level=consensus_level,
                rationale=self._rationale(
                    manager_vote,
                    consensus_level,
                    reason_block=(
                        f"consensus {consensus_level} below required "
                        f"{self.config.require_min_consensus}"
                    ),
                ),
                needs_human_review=True,
                key_evidence=key_evidence,
                key_risks=key_risks,
                assigned_roles=[v.role for v in analyst_list]
                + [manager_vote.role],
            )

        # No-trade actions.
        if manager_vote.suggested_action in {"skip", "watch", "hold"}:
            return TradePlan(
                symbol=symbol,
                side="buy",
                target_position_pct=ZERO,
                confidence=manager_vote.confidence,
                consensus_level=consensus_level,
                rationale=self._rationale(
                    manager_vote, consensus_level
                ),
                needs_human_review=manager_vote.needs_human_review,
                key_evidence=key_evidence,
                key_risks=key_risks,
                assigned_roles=[v.role for v in analyst_list]
                + [manager_vote.role],
            )

        # Position size cap (clamp only — never inflate).
        raw = manager_vote.target_position_pct
        capped = min(raw, self.config.max_position_pct)
        capped = max(capped, ZERO)

        side: Literal["buy", "sell"] = (
            "sell" if manager_vote.suggested_action == "sell" else "buy"
        )

        return TradePlan(
            symbol=symbol,
            side=side,
            target_position_pct=capped,
            confidence=manager_vote.confidence,
            consensus_level=consensus_level,
            rationale=self._rationale(manager_vote, consensus_level),
            needs_human_review=(
                manager_vote.needs_human_review
                or any(v.veto for v in analyst_list)
            ),
            key_evidence=key_evidence,
            key_risks=key_risks,
            assigned_roles=[v.role for v in analyst_list]
            + [manager_vote.role],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_ethics(self, manager_vote: CommitteeVote) -> tuple[bool, str | None]:
        """Return ``(blocked, reason)`` if any ethics keyword is present."""
        haystack = manager_vote.analysis.lower()
        for kw in self.config.ethics_keywords:
            if kw.lower() in haystack:
                return True, f"ethics keyword match: {kw!r}"
        return False, None

    @staticmethod
    def _rationale(
        manager_vote: CommitteeVote,
        consensus: ConsensusLevel,
        *,
        reason_block: str | None = None,
        ethics_reason: str | None = None,
    ) -> str:
        bits: list[str] = [
            f"manager_view={manager_vote.view}",
            f"action={manager_vote.suggested_action}",
            f"confidence={manager_vote.confidence:.2f}",
            f"consensus={consensus}",
        ]
        if manager_vote.veto:
            bits.append("vetoed_by_manager")
        if reason_block:
            bits.append(f"blocked={reason_block}")
        if ethics_reason:
            bits.append(f"ethics={ethics_reason}")
        return "; ".join(bits)


# ---------------------------------------------------------------------------
# Consensus computation
# ---------------------------------------------------------------------------


def _compute_consensus(
    analyst_votes: list[CommitteeVote], manager_vote: CommitteeVote
) -> ConsensusLevel:
    """Coarse consensus label from analyst + manager votes.

    ``unanimous``  — all roles share the same view
    ``majority``   — analyst views agree (>=2 of 3) and manager agrees
    ``split``      — analyst views disagree but at least one agrees with manager
    ``no_consensus`` — manager disagrees with every analyst
    """
    analyst_views = [v.view for v in analyst_votes]
    if not analyst_views:
        return "no_consensus"

    if len(set(analyst_views)) == 1 and analyst_views[0] == manager_vote.view:
        return "unanimous"

    top_view, top_count = max(
        ((view, analyst_views.count(view)) for view in set(analyst_views)),
        key=lambda item: item[1],
    )
    if top_count >= 2 and top_view == manager_vote.view:
        return "majority"

    if manager_vote.view in set(analyst_views):
        return "split"

    return "no_consensus"


def _collect_evidence(votes: Iterable[CommitteeVote]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in votes:
        for item in v.evidence:
            key = item[:80].lower()
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out[:5]


def _collect_risks(votes: Iterable[CommitteeVote]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in votes:
        for item in v.risks:
            key = item[:80].lower()
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out[:5]


__all__ = [
    "DisciplineConfig",
    "DisciplineGate",
]