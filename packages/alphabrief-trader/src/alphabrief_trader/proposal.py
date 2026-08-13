"""Evidence-grounded research proposal builder and validator (M10-W04).

The committee produces votes and a transcript; this module converts that
output into a strict :class:`ResearchProposal` that separates thesis,
anti-thesis, confidence, horizon, entry rationale, invalidation,
suggested exposure, evidence citations, dissent, data freshness,
uncertainty, and an explicit ``no_trade`` outcome.

Grounding rules (REQ-AI-005/006, REQ-PLAT-009):

- every citation resolves to an evidence ID that exists in the exact
  snapshot the committee used (``CommitteeInput.evidence_ids``);
- unsupported citations, stale critical evidence, contradictory exposure
  fields, or missing dissent fail :func:`validate_proposal_grounding` —
  a failed proposal is not executable and produces no OrderIntent;
- the builder is deterministic: identical votes/transcript/input produce
  identical proposals.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from alphabrief_trader.committee import CommitteeResult
from alphabrief_trader.schemas import (
    CommitteeInput,
    CommitteeVote,
    EvidenceCitation,
    ResearchProposal,
    TradePlan,
)

DEFAULT_MAX_EVIDENCE_AGE_SECONDS = 86400


class ProposalBuildError(ValueError):
    """Raised when a proposal cannot be built from committee output."""


def _split_citation(
    entry: str,
    available_evidence_ids: Sequence[str],
) -> EvidenceCitation | None:
    """Split one model evidence entry into (evidence_id, claim) or None.

    An entry counts as a grounded citation only when it starts with an
    available evidence ID followed by ``:`` or a space, or equals the ID.
    Anything else is unsupported and never emitted.
    """
    for evidence_id in available_evidence_ids:
        if entry == evidence_id:
            return EvidenceCitation(evidence_id=evidence_id, claim=entry)
        if entry.startswith(f"{evidence_id}:"):
            claim = entry[len(evidence_id) + 1 :].strip()
            return EvidenceCitation(
                evidence_id=evidence_id,
                claim=claim or entry,
            )
        if entry.startswith(f"{evidence_id} "):
            claim = entry[len(evidence_id) + 1 :].strip()
            return EvidenceCitation(
                evidence_id=evidence_id,
                claim=claim or entry,
            )
    return None


def _collect_citations(
    committee_result: CommitteeResult,
    available_evidence_ids: Sequence[str],
) -> list[EvidenceCitation]:
    """Collect grounded citations from votes and transcript turns."""
    citations: dict[str, EvidenceCitation] = {}
    entries: list[str] = []
    for vote in committee_result.votes:
        entries.extend(vote.evidence)
    if committee_result.transcript is not None:
        for turn in committee_result.transcript.turns:
            entries.extend(turn.cited_evidence_ids)
    for entry in entries:
        citation = _split_citation(entry, available_evidence_ids)
        if citation is not None:
            citations[citation.evidence_id] = citation
    return [citations[key] for key in sorted(citations)]


def _dissent_summary(committee_result: CommitteeResult) -> str:
    """Summarize recorded dissent from the transcript, deterministically."""
    if committee_result.transcript is None:
        return "no dissent recorded"
    parts: list[str] = []
    for turn in committee_result.transcript.turns:
        if turn.phase == "challenge" and turn.stance in {
            "contradiction",
            "dissent",
        }:
            parts.append(f"{turn.role}: {turn.analysis[:200]}")
    if not parts:
        return "no dissent recorded"
    return " | ".join(parts)


def _manager_vote(committee_result: CommitteeResult) -> CommitteeVote | None:
    for vote in committee_result.votes:
        if vote.role == "manager":
            return vote
    return None


def _risk_vote(committee_result: CommitteeResult) -> CommitteeVote | None:
    for vote in committee_result.votes:
        if vote.role == "risk":
            return vote
    return None


def build_research_proposal(
    committee_result: CommitteeResult,
    payload: CommitteeInput,
    *,
    plan: TradePlan | None = None,
    proposal_id: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ResearchProposal:
    """Build one deterministic, evidence-grounded proposal.

    Raises :class:`ProposalBuildError` when the committee produced no
    votes (there is nothing to ground a proposal on).
    """
    if not committee_result.votes:
        raise ProposalBuildError(
            "cannot build a proposal from a committee run with no votes"
        )
    manager_vote = _manager_vote(committee_result)
    if manager_vote is None:
        raise ProposalBuildError(
            "cannot build a proposal without a manager vote"
        )
    risk_vote = _risk_vote(committee_result)

    if plan is not None:
        confidence = plan.confidence
        entry_rationale = plan.rationale
        exposure = plan.target_position_pct
        no_trade = plan.blocked_by_ethics or plan.target_position_pct <= 0
    else:
        confidence = manager_vote.confidence
        entry_rationale = manager_vote.analysis
        exposure = Decimal("0")
        no_trade = True

    invalidation = (
        risk_vote.risks[0]
        if risk_vote is not None and risk_vote.risks
        else (
            manager_vote.risks[0]
            if manager_vote.risks
            else "no invalidation defined"
        )
    )
    anti_thesis = _dissent_summary(committee_result)
    if anti_thesis == "no dissent recorded" and risk_vote is not None:
        anti_thesis = risk_vote.analysis

    return ResearchProposal(
        proposal_id=proposal_id or f"proposal_{uuid4().hex[:12]}",
        symbol=payload.snapshot.symbol,
        thesis=manager_vote.analysis,
        anti_thesis=anti_thesis,
        confidence=confidence,
        horizon=payload.time_horizon,
        entry_rationale=entry_rationale,
        invalidation=invalidation,
        suggested_exposure=exposure,
        citations=_collect_citations(committee_result, payload.evidence_ids),
        dissent=_dissent_summary(committee_result),
        data_freshness=payload.snapshot.captured_at,
        uncertainty=round(1.0 - float(confidence), 4),
        no_trade=no_trade,
        created_at=(clock or (lambda: datetime.now(UTC)))(),
    )


def validate_proposal_grounding(
    proposal: ResearchProposal,
    *,
    available_evidence_ids: Sequence[str],
    max_evidence_age_seconds: int = DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
    now: datetime | None = None,
) -> list[str]:
    """Return grounding violations; an empty list means the proposal passes.

    A proposal with any violation is not executable: it must not produce
    an OrderIntent or reach the broker.
    """
    violations: list[str] = []

    supported = frozenset(available_evidence_ids)
    for citation in proposal.citations:
        if citation.evidence_id not in supported:
            violations.append(
                f"unsupported_citation:{citation.evidence_id}"
            )

    current = now or datetime.now(UTC)
    age_seconds = (current - proposal.data_freshness).total_seconds()
    if age_seconds > max_evidence_age_seconds:
        violations.append(
            f"stale_critical_evidence:{int(age_seconds)}s"
        )

    if proposal.no_trade and proposal.suggested_exposure > 0:
        violations.append("contradictory_exposure:no_trade_with_exposure")
    if not proposal.no_trade and proposal.suggested_exposure <= 0:
        violations.append("contradictory_exposure:trade_without_exposure")

    if not proposal.dissent.strip():
        violations.append("missing_dissent")

    return violations


__all__ = [
    "DEFAULT_MAX_EVIDENCE_AGE_SECONDS",
    "ProposalBuildError",
    "build_research_proposal",
    "validate_proposal_grounding",
]
