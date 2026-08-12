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
from typing import Any, Literal
from uuid import uuid4

from alphabrief_models import (
    ModelGateway,
    ModelRequest,
    parse_structured_output,
)
from alphabrief_models.structured_output import StructuredOutputResult
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_trader.committee_prompts import (
    PROMPT_VERSION,
    build_committee_prompt,
    default_roles,
)
from alphabrief_trader.rules import DisciplineConfig, DisciplineGate
from alphabrief_trader.schemas import (
    AnalystView,
    CommitteeInput,
    CommitteeRole,
    CommitteeVote,
    TradePlan,
)

# ---------------------------------------------------------------------------
# Partial schema (model output, before metadata is attached)
# ---------------------------------------------------------------------------


class _PartialCommitteeVote(BaseModel):
    """Strict schema for one role's model output (no metadata fields)."""

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
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool = False
    plan: TradePlan | None = None
    votes: list[CommitteeVote] = Field(default_factory=list)
    error_message: str | None = None
    error_role: CommitteeRole | None = None
    role_errors: list[str] = Field(default_factory=list)


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
    ) -> None:
        if gateway is None:
            raise TypeError("gateway is required")
        self._gateway = gateway
        self._discipline = DisciplineGate(
            config=discipline or DisciplineConfig()
        )
        self._roles: list[CommitteeRole] = list(roles or default_roles())
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def roles(self) -> list[CommitteeRole]:
        return list(self._roles)

    def run(self, payload: CommitteeInput) -> CommitteeResult:
        """Run the committee and return a synthesized plan (or failure)."""
        snapshot = payload.snapshot
        roles = payload.roles or self._roles
        votes: list[CommitteeVote] = []
        request_id = f"ait_{uuid4().hex[:12]}"
        role_errors: list[str] = []

        for role in roles:
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
            parsed: StructuredOutputResult[_PartialCommitteeVote] = (
                parse_structured_output(
                    result.response, target=_PartialCommitteeVote
                )
            )
            if not parsed.ok or parsed.parsed is None:
                code = parsed.error_code or "structured_output_parse_failed"
                role_errors.append(f"{role}: {code}")
                continue

            p = parsed.parsed
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
                created_at=self._clock(),
            )
            votes.append(vote)

        if not votes:
            return CommitteeResult(
                ok=False,
                error_message="no_committee_votes",
                error_role=None,
                role_errors=role_errors,
            )

        manager_vote = _select_manager(votes)
        if manager_vote is None:
            return CommitteeResult(
                ok=False,
                votes=votes,
                error_message="missing_manager_vote",
                error_role="manager",
            )

        analyst_votes = [v for v in votes if v.role != "manager"]
        plan = self._discipline.synthesize(
            symbol=snapshot.symbol,
            manager_vote=manager_vote,
            analyst_votes=analyst_votes,
        )
        return CommitteeResult(ok=True, plan=plan, votes=votes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _select_manager(votes: list[CommitteeVote]) -> CommitteeVote | None:
    """Pick the manager vote from a list of votes."""
    for v in votes:
        if v.role == "manager":
            return v
    return None


def _as_decimal(value: float) -> Decimal:
    """Convert a model-supplied ``float`` percentage to a Decimal safely."""
    return Decimal(str(value))


__all__ = [
    "CommitteeResult",
    "TradingCommittee",
]
