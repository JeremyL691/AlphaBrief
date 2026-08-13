"""Multi-role AI Trading Committee orchestrator.

The committee accepts a :class:`CommitteeInput`, routes it to four
``ModelGateway`` calls (one per role), validates each model response
against a strict partial schema, and returns a deterministic
:class:`TradePlan`. The plan is then handed to the daily cycle, which
turns it into an ``OrderIntent`` candidate and pushes it through the
deterministic ``RiskGate`` — the committee itself never places an
order and never inspects ``RiskLimitConfig``.

The orchestrator is model-agnostic. It only knows about
``ModelGateway``; it does not import any provider SDK, does not hard-
code any vendor or model name, and does not pass provider secrets
through the model call boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import uuid4

from alphabrief_models import (
    ModelGateway,
    ModelRequest,
    parse_structured_output,
    repair_structured_output,
)
from alphabrief_models.repair import RepairVerdict
from alphabrief_models.structured_output import StructuredOutputResult
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_trader.committee_prompts import (
    PROMPT_VERSION,
    build_challenge_prompt,
    build_committee_prompt,
    build_summary_prompt,
    default_roles,
)
from alphabrief_trader.rules import DisciplineConfig, DisciplineGate
from alphabrief_trader.schemas import (
    AnalystView,
    CommitteeInput,
    CommitteeRole,
    CommitteeStance,
    CommitteeTranscript,
    CommitteeTurn,
    CommitteeVote,
    TradePlan,
)

# ---------------------------------------------------------------------------
# Partial schema (model output, before metadata is attached)
# ---------------------------------------------------------------------------


class _PartialCommitteeVote(BaseModel):
    """Strict schema for one role's opening model output (no metadata)."""

    model_config = ConfigDict(extra="forbid")

    analysis: str = Field(min_length=1)
    view: AnalystView
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    suggested_action: Literal["buy", "sell", "hold", "watch", "skip"]
    target_position_pct: float = Field(ge=0.0, le=1.0)
    veto: bool = False
    needs_human_review: bool = False


class _PartialChallengeOutput(BaseModel):
    """Strict schema for challenge and summary turn model output."""

    model_config = ConfigDict(extra="forbid")

    analysis: str = Field(min_length=1)
    view: AnalystView
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    stance: CommitteeStance = "unknown"
    challenged_claim: str | None = None


# ---------------------------------------------------------------------------
# Result wrappers
# ---------------------------------------------------------------------------


class CommitteeResult(BaseModel):
    """Outcome of one committee run for one symbol.

    The daily cycle inspects ``ok``, ``plan`` (when ok), and the raw
    ``votes`` for the audit record. ``error_message`` is a stable
    string code the operator can branch on; it is never the raw
    provider error text. ``role_errors`` lists the roles that failed
    and why (stable codes, no raw provider text), so an all-failed
    cycle can be told apart from a genuine no-consensus outcome.
    ``transcript`` preserves the full bounded discussion: opening,
    challenge, and summary turns with role identity, timestamps, model
    call IDs, stances, and cited evidence IDs.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool = False
    plan: TradePlan | None = None
    votes: list[CommitteeVote] = Field(default_factory=list)
    error_message: str | None = None
    error_role: CommitteeRole | None = None
    role_errors: list[str] = Field(default_factory=list)
    transcript: CommitteeTranscript | None = None
    repair_attempts: list[RepairVerdict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Committee
# ---------------------------------------------------------------------------


class TradingCommittee:
    """Multi-role trading committee.

    The committee accepts an input for one symbol and returns either a
    synthesized :class:`TradePlan` or a typed failure. It owns no
    mutable state: every input produces a deterministic, auditable
    output bound to the configured ``ModelGateway`` and
    :class:`DisciplineGate`.
    """

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        discipline: DisciplineConfig | None = None,
        roles: Sequence[CommitteeRole] | None = None,
        clock: Any = None,
        max_turns: int = 10,
        challenge_rounds: int = 1,
        repair_attempts: int = 0,
    ) -> None:
        if gateway is None:
            raise TypeError("gateway is required")
        if max_turns < 5:
            raise ValueError("max_turns must be at least 5")
        if challenge_rounds < 0:
            raise ValueError("challenge_rounds must be non-negative")
        if repair_attempts < 0:
            raise ValueError("repair_attempts must be non-negative")
        self._gateway = gateway
        self._discipline = DisciplineGate(
            config=discipline or DisciplineConfig()
        )
        self._roles: list[CommitteeRole] = list(roles or default_roles())
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_turns = max_turns
        self._challenge_rounds = challenge_rounds
        self._repair_attempts = repair_attempts

    @property
    def roles(self) -> list[CommitteeRole]:
        return list(self._roles)

    def run(self, payload: CommitteeInput) -> CommitteeResult:
        """Run the bounded multi-turn discussion and synthesize a plan.

        Turn order is bounded and deterministic: opening turns for every
        role, one challenge round per analyst, and a final moderator
        summary turn. Every turn records role identity, a UTC timestamp,
        the originating model-call ID, cited evidence IDs, and (for
        challenge and summary turns) an explicit stance. The transcript
        is never flattened; the plan is synthesized only from the opening
        votes through the deterministic ``DisciplineGate``.
        """
        snapshot = payload.snapshot
        roles = payload.roles or self._roles
        votes: list[CommitteeVote] = []
        turns: list[CommitteeTurn] = []
        repair_attempts: list[RepairVerdict] = []
        request_id = f"ait_{uuid4().hex[:12]}"
        role_errors: list[str] = []
        completed = False
        analyst_roles = [role for role in roles if role != "manager"]

        for role in roles:
            if len(turns) >= self._max_turns:
                break
            prompt = build_committee_prompt(role, payload)
            request = ModelRequest(
                request_id=f"{request_id}_{role}",
                task_type="symbol_research",
                prompt_version=PROMPT_VERSION,
                input_text=prompt,
                required_capabilities=["structured_output"],
                metadata={
                    "committee_role": role,
                    "symbol": snapshot.symbol,
                },
            )
            result = self._gateway.invoke(request)
            if result.response is None or result.record.status != "succeeded":
                role_errors.append(f"{role}: provider_call_failed")
                continue
            opening_parsed: StructuredOutputResult[_PartialCommitteeVote] = (
                parse_structured_output(
                    result.response, target=_PartialCommitteeVote
                )
            )
            failure_reason: str | None = None
            if not opening_parsed.ok or opening_parsed.parsed is None:
                code = opening_parsed.error_code or "structured_output_parse_failed"
                failure_reason = f"schema_validation_failed:{code}"
            else:
                violations = _vote_grounding_violations(
                    opening_parsed.parsed, payload
                )
                if violations:
                    failure_reason = "grounding_failed:" + ",".join(violations)

            if failure_reason is not None:
                if self._repair_attempts <= 0:
                    role_errors.append(f"{role}: {failure_reason}")
                    continue
                def _grounding(parsed: _PartialCommitteeVote) -> list[str]:
                    return _vote_grounding_violations(parsed, payload)

                repaired = repair_structured_output(
                    gateway=self._gateway,
                    request=request,
                    target=_PartialCommitteeVote,
                    raw_output=result.response.output_text,
                    failure_reason=failure_reason,
                    max_attempts=self._repair_attempts,
                    grounding_check=_grounding,
                    clock=self._clock,
                )
                repair_attempts.extend(repaired.attempts)
                if not repaired.ok or repaired.parsed is None:
                    role_errors.append(f"{role}: repair_exhausted")
                    continue
                opening_parsed = StructuredOutputResult(
                    ok=True,
                    parsed=cast(_PartialCommitteeVote, repaired.parsed),
                    error_code=None,
                )

            p = opening_parsed.parsed
            assert p is not None
            cited = _extract_cited_evidence_ids(p.evidence, payload.evidence_ids)
            vote = CommitteeVote(
                role=role,
                model_name=result.response.model or "unknown",
                analysis=p.analysis,
                view=p.view,
                confidence=p.confidence,
                evidence=p.evidence,
                risks=p.risks,
                suggested_action=p.suggested_action,
                target_position_pct=_as_decimal(p.target_position_pct),
                veto=p.veto,
                needs_human_review=p.needs_human_review,
                model_call_id=result.record.call_id,
                cited_evidence_ids=cited,
                created_at=self._clock(),
            )
            votes.append(vote)
            turns.append(
                CommitteeTurn(
                    turn_id=f"turn_{len(turns) + 1}",
                    turn_number=len(turns) + 1,
                    phase="opening",
                    role=role,
                    model_call_id=result.record.call_id,
                    analysis=p.analysis,
                    view=p.view,
                    confidence=p.confidence,
                    cited_evidence_ids=cited,
                    created_at=self._clock(),
                )
            )

        if not votes:
            transcript = CommitteeTranscript(
                turns=turns, max_turns=self._max_turns, completed=False
            )
            return CommitteeResult(
                ok=False,
                error_message="no_committee_votes",
                error_role=None,
                role_errors=role_errors,
                transcript=transcript,
                repair_attempts=repair_attempts,
            )

        # Bounded challenge round: every analyst may contest earlier
        # claims exactly once, preserving stance and dissent.
        for _round in range(self._challenge_rounds):
            for role in analyst_roles:
                if len(turns) >= self._max_turns:
                    break
                if role not in {vote.role for vote in votes}:
                    continue
                transcript_so_far = CommitteeTranscript(
                    turns=list(turns), max_turns=self._max_turns
                )
                prompt = build_challenge_prompt(role, payload, transcript_so_far)
                request = ModelRequest(
                    request_id=f"{request_id}_{role}_challenge",
                    task_type="symbol_research",
                    prompt_version=PROMPT_VERSION,
                    input_text=prompt,
                    required_capabilities=["structured_output"],
                    metadata={
                        "committee_role": role,
                        "phase": "challenge",
                        "symbol": snapshot.symbol,
                    },
                )
                result = self._gateway.invoke(request)
                if result.response is None or result.record.status != "succeeded":
                    continue
                challenge_parsed: StructuredOutputResult[
                    _PartialChallengeOutput
                ] = (
                    parse_structured_output(
                        result.response, target=_PartialChallengeOutput
                    )
                )
                if not challenge_parsed.ok or challenge_parsed.parsed is None:
                    continue
                cp = challenge_parsed.parsed
                cited = _extract_cited_evidence_ids(cp.evidence, payload.evidence_ids)
                turns.append(
                    CommitteeTurn(
                        turn_id=f"turn_{len(turns) + 1}",
                        turn_number=len(turns) + 1,
                        phase="challenge",
                        role=role,
                        model_call_id=result.record.call_id,
                        analysis=cp.analysis,
                        view=cp.view,
                        confidence=cp.confidence,
                        cited_evidence_ids=cited,
                        stance=cp.stance,
                        challenged_claim=cp.challenged_claim,
                        created_at=self._clock(),
                    )
                )

        # Final bounded moderator summary turn.
        if len(turns) < self._max_turns:
            transcript_so_far = CommitteeTranscript(
                turns=list(turns), max_turns=self._max_turns
            )
            prompt = build_summary_prompt(payload, transcript_so_far)
            request = ModelRequest(
                request_id=f"{request_id}_manager_summary",
                task_type="symbol_research",
                prompt_version=PROMPT_VERSION,
                input_text=prompt,
                required_capabilities=["structured_output"],
                metadata={
                    "committee_role": "manager",
                    "phase": "summary",
                    "symbol": snapshot.symbol,
                },
            )
            result = self._gateway.invoke(request)
            if result.response is not None and result.record.status == "succeeded":
                summary_parsed: StructuredOutputResult[
                    _PartialChallengeOutput
                ] = (
                    parse_structured_output(
                        result.response, target=_PartialChallengeOutput
                    )
                )
                if summary_parsed.ok and summary_parsed.parsed is not None:
                    sp = summary_parsed.parsed
                    cited = _extract_cited_evidence_ids(
                        sp.evidence, payload.evidence_ids
                    )
                    turns.append(
                        CommitteeTurn(
                            turn_id=f"turn_{len(turns) + 1}",
                            turn_number=len(turns) + 1,
                            phase="summary",
                            role="manager",
                            model_call_id=result.record.call_id,
                            analysis=sp.analysis,
                            view=sp.view,
                            confidence=sp.confidence,
                            cited_evidence_ids=cited,
                            stance=sp.stance,
                            created_at=self._clock(),
                        )
                    )
                    completed = True

        transcript = CommitteeTranscript(
            turns=turns,
            max_turns=self._max_turns,
            completed=completed,
        )

        manager_vote = _select_manager(votes)
        if manager_vote is None:
            return CommitteeResult(
                ok=False,
                votes=votes,
                error_message="missing_manager_vote",
                error_role="manager",
                role_errors=role_errors,
                transcript=transcript,
                repair_attempts=repair_attempts,
            )

        analyst_votes = [v for v in votes if v.role != "manager"]
        plan = self._discipline.synthesize(
            symbol=snapshot.symbol,
            manager_vote=manager_vote,
            analyst_votes=analyst_votes,
        )
        return CommitteeResult(
            ok=True,
            plan=plan,
            votes=votes,
            transcript=transcript,
            repair_attempts=repair_attempts,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _select_manager(votes: list[CommitteeVote]) -> CommitteeVote | None:
    """Pick the manager vote from a list of votes."""
    for v in votes:
        if v.role == "manager":
            return v
    return None


def _vote_grounding_violations(
    parsed: _PartialCommitteeVote,
    payload: CommitteeInput,
) -> list[str]:
    """Return grounding violations for one parsed vote, deterministically.

    An evidence entry that looks like a citation (``ev-...`` prefix) but
    does not resolve to an available evidence ID is a nonexistent
    citation and triggers bounded repair.
    """
    available = set(payload.evidence_ids)
    violations: list[str] = []
    for entry in parsed.evidence:
        token = entry.split(":")[0].strip().split(" ")[0].strip()
        if token.startswith("ev-") and token not in available:
            violations.append(f"nonexistent_citation:{token}")
    return violations


def _extract_cited_evidence_ids(
    evidence: list[str],
    available_evidence_ids: Sequence[str],
) -> list[str]:
    """Extract the evidence IDs a turn actually cited, deterministically.

    An evidence entry counts as a citation of an available ID when it
    equals the ID or starts with the ID followed by ``:`` or a space
    (e.g. ``ev-abc: earnings beat``). Citations are sorted and
    deduplicated so the transcript is stable for identical input.
    """
    cited: set[str] = set()
    for entry in evidence:
        for evidence_id in available_evidence_ids:
            if (
                entry == evidence_id
                or entry.startswith(f"{evidence_id}:")
                or entry.startswith(f"{evidence_id} ")
            ):
                cited.add(evidence_id)
    return sorted(cited)


def _as_decimal(value: float) -> Decimal:
    """Convert a model-supplied ``float`` percentage to a Decimal safely."""
    return Decimal(str(value))


__all__ = [
    "CommitteeResult",
    "TradingCommittee",
]
