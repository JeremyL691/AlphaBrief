"""Data models for the AI Trading Committee.

These schemas are pure Pydantic validation boundaries. They define the
shape of every artifact the committee produces: committee votes, the
risk committee's veto/override advice, the synthesized trade plan, and
the end-to-end daily-cycle record. They do not call providers, read
databases, place orders, or touch risk / execution code.

Safety contract (mirrors AGENTS.md):

* The committee only ever produces *OrderIntent candidates*. It never
  produces an ``Order``. An intent becomes an order only after a
  deterministic ``RiskDecision`` approves it.
* External news / macro context is untrusted data; the schemas carry it
  as plain strings so it can flow into prompts, but it must never alter
  system rules or bypass the risk layer.
* All timestamps are timezone-aware; all money / quantity values use
  ``Decimal`` (never ``float``).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Literals
# ---------------------------------------------------------------------------

CommitteeRole = Literal[
    "technical",
    "news_sentiment",
    "fundamental",
    "risk",
    "manager",
]
CommitteeTurnPhase = Literal["opening", "challenge", "summary"]
CommitteeStance = Literal["agreement", "contradiction", "dissent", "unknown"]
AnalystView = Literal["bullish", "bearish", "neutral", "uncertain"]
AnalystAction = Literal["buy", "sell", "hold", "watch", "skip"]
ConsensusLevel = Literal["unanimous", "majority", "split", "no_consensus"]
ExecutionBackendName = Literal["local_paper", "external_paper"]
CycleOutcome = Literal[
    "executed",
    "skipped_no_consensus",
    "skipped_no_intent",
    "provider_error",
    "blocked_risk_gate",
    "blocked_human_review",
    "blocked_ethics",
    "blocked_live_trading",
    "blocked_disabled",
    "error",
]
OrderSide = Literal["buy", "sell"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime fields must be timezone-aware")
    return value


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("decimal fields must not be provided as float values")
    return value


def _to_decimal_str(value: Any) -> str:
    """Render a Decimal / number as a string for JSON-safe storage."""
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class _CommitteeSchema(BaseModel):
    """Shared strict schema configuration for committee models."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


class MarketSnapshot(_CommitteeSchema):
    """A compact market snapshot fed into the committee.

    Carries recent OHLCV summary statistics for one symbol plus optional
    untrusted news / macro context strings. The snapshot is read-only
    input; it must never carry system instructions or alter risk rules.
    """

    symbol: str = Field(min_length=1)
    reference_price: Decimal = Field(gt=0)
    recent_return_pct: Decimal | None = None
    recent_volume: Decimal | None = None
    news_context: str | None = None
    macro_context: str | None = None
    data_version: str = Field(default="ai-trader-v1", min_length=1)
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator(
        "reference_price", "recent_return_pct", "recent_volume", mode="before"
    )
    @classmethod
    def _no_float(cls, value: Any) -> Any:
        return _reject_float(value)


class CommitteeInput(_CommitteeSchema):
    """Everything the daily cycle passes to the committee for one symbol."""

    snapshot: MarketSnapshot
    time_horizon: str = Field(default="5 trading days", min_length=1)
    roles: list[CommitteeRole] = Field(
        default_factory=lambda: cast(
            "list[CommitteeRole]",
            ["technical", "news_sentiment", "fundamental", "risk", "manager"],
        )
    )
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("roles")
    @classmethod
    def _roles_non_empty_unique(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("roles must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("roles must not contain duplicates")
        for role in value:
            if role not in {
                "technical",
                "news_sentiment",
                "fundamental",
                "risk",
                "manager",
            }:
                raise ValueError(f"unknown role: {role!r}")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("evidence_ids must not contain duplicates")
        return value


# ---------------------------------------------------------------------------
# Committee votes
# ---------------------------------------------------------------------------


class CommitteeVote(_CommitteeSchema):
    """One committee role's structured judgment on one symbol.

    ``position_multiplier`` is the role's *advisory* suggested sizing
    fraction of the configured max order value, in ``[0.0, 1.0]``. The
    risk role additionally carries ``veto`` so it can block a trade the
    analysts favor — but a veto only sets ``needs_human_review=True`` on
    the synthesized plan; it never bypasses the deterministic
    ``RiskGate``.
    """

    role: CommitteeRole
    model_name: str = Field(min_length=1)
    analysis: str = Field(min_length=1)
    view: AnalystView
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    suggested_action: AnalystAction
    target_position_pct: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    veto: bool = False
    needs_human_review: bool = False
    model_call_id: str | None = None
    cited_evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("target_position_pct", mode="before")
    @classmethod
    def _no_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("analysis", "model_name")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value


# ---------------------------------------------------------------------------
# Discussion transcript
# ---------------------------------------------------------------------------


class CommitteeTurn(_CommitteeSchema):
    """One bounded discussion turn in the committee transcript.

    ``phase`` is the bounded turn order: ``opening`` (each role's first
    judgment), ``challenge`` (an analyst challenging earlier claims), or
    ``summary`` (the moderator's final synthesis). ``stance`` and
    ``challenged_claim`` are only meaningful for challenge turns; they
    preserve agreement, contradiction, dissent, and unknowns instead of
    flattening them into a single answer. ``cited_evidence_ids`` keeps
    every evidence ID the turn referenced, so grounding is auditable.
    """

    turn_id: str = Field(min_length=1)
    turn_number: int = Field(ge=1)
    phase: CommitteeTurnPhase
    role: CommitteeRole
    model_call_id: str | None = None
    analysis: str = Field(min_length=1)
    view: AnalystView
    confidence: float = Field(ge=0.0, le=1.0)
    cited_evidence_ids: list[str] = Field(default_factory=list)
    stance: CommitteeStance | None = None
    challenged_claim: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("analysis")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("analysis must not be blank")
        return value


class CommitteeTranscript(_CommitteeSchema):
    """The full bounded discussion record for one committee run.

    ``max_turns`` is the configured bound; ``completed`` is True only
    when the run reached its final moderator summary turn. The transcript
    is read-only evidence: it preserves every role's reasoning, stance,
    and dissent rather than flattening them into one answer.
    """

    turns: list[CommitteeTurn] = Field(default_factory=list)
    max_turns: int = Field(ge=1)
    completed: bool = False


# ---------------------------------------------------------------------------
# Grounded research proposal
# ---------------------------------------------------------------------------


class EvidenceCitation(_CommitteeSchema):
    """One factual proposal claim bound to an evidence ID.

    The evidence ID must resolve inside the exact snapshot the committee
    used; a citation is never fabricated by the proposal builder.
    """

    evidence_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)


class ResearchProposal(_CommitteeSchema):
    """The committee's strict evidence-grounded proposal for one symbol.

    Separates thesis, anti-thesis, confidence, horizon, entry rationale,
    invalidation, suggested exposure, evidence citations, dissent, data
    freshness, uncertainty, and an explicit ``no_trade`` outcome. A
    proposal is advisory evidence only — it becomes an ``OrderIntent``
    candidate only after grounding validation and the deterministic
    ``RiskGate``.
    """

    proposal_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    thesis: str = Field(min_length=1)
    anti_thesis: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    horizon: str = Field(min_length=1)
    entry_rationale: str = Field(min_length=1)
    invalidation: str = Field(min_length=1)
    suggested_exposure: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    dissent: str = Field(min_length=1)
    data_freshness: datetime
    uncertainty: float = Field(ge=0.0, le=1.0)
    no_trade: bool = False
    created_at: datetime

    @field_validator("data_freshness", "created_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("dissent")
    @classmethod
    def _dissent_not_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("dissent must not be blank")
        return value

    @field_validator("suggested_exposure", mode="before")
    @classmethod
    def _no_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @model_validator(mode="after")
    def _exposure_matches_no_trade(self) -> ResearchProposal:
        # Contradictory exposure fields are rejected at the schema level:
        # a no-trade proposal must carry zero exposure and a tradeable
        # proposal must carry positive exposure.
        if self.no_trade and self.suggested_exposure > 0:
            raise ValueError(
                "no_trade proposal must not carry positive suggested exposure"
            )
        if not self.no_trade and self.suggested_exposure <= 0:
            raise ValueError(
                "tradeable proposal must carry positive suggested exposure"
            )
        return self


# ---------------------------------------------------------------------------
# Synthesized plan
# ---------------------------------------------------------------------------


class TradePlan(_CommitteeSchema):
    """The committee's synthesized, pre-risk decision for one symbol.

    The plan is an *advisory OrderIntent candidate*. The daily cycle
    turns it into an :class:`OrderIntent`, routes it through the
    deterministic ``RiskGate``, and only then — on an approved,
    non-human-review decision — submits to the paper broker.
    """

    symbol: str = Field(min_length=1)
    side: OrderSide
    target_position_pct: Decimal = Field(ge=0, le=1)
    confidence: float = Field(ge=0.0, le=1.0)
    consensus_level: ConsensusLevel
    rationale: str = Field(min_length=1)
    needs_human_review: bool
    blocked_by_ethics: bool = False
    ethics_reason: str | None = None
    key_evidence: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    assigned_roles: list[CommitteeRole] = Field(default_factory=list)

    @field_validator("target_position_pct", mode="before")
    @classmethod
    def _no_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @model_validator(mode="after")
    def _ethics_block_implies_no_trade(self) -> TradePlan:
        # An ethics veto produces a no-trade plan: target zero, hold
        # action. The cycle materializes *no* OrderIntent at all in this
        # case, but enforcing the invariant on the model itself keeps a
        # stray block from silently producing an order.
        if self.blocked_by_ethics:
            if self.target_position_pct > 0:
                object.__setattr__(
                    self, "target_position_pct", Decimal("0")
                )
        return self


# ---------------------------------------------------------------------------
# Execution attempt + daily record
# ---------------------------------------------------------------------------


class OrderAttempt(_CommitteeSchema):
    """One attempt to push a committee plan through the risk -> paper path.

    Captures the deterministic ``RiskDecision`` and the resulting paper
    fill if any. Mirrors the existing audit shape so an operator can
    replay any cycle decision-by-decision. ``order_intent_json`` /
    ``risk_decision_json`` / ``fill_json`` are JSON-serializable dicts
    (Decimal / datetime stringified) so the DuckDB store can persist them
    verbatim.
    """

    intent_id: str = Field(min_length=1)
    risk_decision_id: str | None = None
    approved: bool
    reason: str = Field(min_length=1)
    requires_human_review: bool
    risk_tags: list[str] = Field(default_factory=list)
    max_quantity: Decimal | None = None
    filled: bool = False
    order_id: str | None = None
    fill_price: Decimal | None = None
    fill_quantity: Decimal | None = None
    execution_backend: ExecutionBackendName | None = None
    client_order_id: str | None = None
    broker_order_id: str | None = None
    broker_status: str | None = None
    outcome: CycleOutcome
    order_intent_json: dict[str, Any]
    risk_decision_json: dict[str, Any] | None = None
    fill_json: dict[str, Any] | None = None
    broker_result_json: dict[str, Any] | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("max_quantity", "fill_price", "fill_quantity", mode="before")
    @classmethod
    def _no_float(cls, value: Any) -> Any:
        return _reject_float(value)


class DailyCycleRecord(_CommitteeSchema):
    """The complete, auditable record of one daily trading cycle.

    One cycle = gather a market snapshot for the configured universe ->
    run the committee for each symbol -> synthesize plans -> apply
    trading-discipline rules -> route any candidate through RiskGate ->
    submit approved, non-human-review intents to the paper broker ->
    record every attempt. Nothing here bypasses the deterministic risk
    layer or the live-trading lock.
    """

    cycle_id: str = Field(min_length=1)
    trading_day: str = Field(min_length=1)  # calendar day (YYYY-MM-DD)
    symbols: list[str] = Field(min_length=1)
    plans: list[TradePlan] = Field(default_factory=list)
    votes: list[CommitteeVote] = Field(default_factory=list)
    attempts: list[OrderAttempt] = Field(default_factory=list)
    outcome: CycleOutcome
    enabled: bool
    live_trading_enabled: bool = False
    summary: str = Field(min_length=1)
    cycle_key: str | None = None
    snapshot_fingerprint: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("cycle_id")
    @classmethod
    def _id_non_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("cycle_id must not be blank")
        return value


class DailyCycleSummary(_CommitteeSchema):
    """A lightweight, JSON-safe projection of a cycle for listings."""

    cycle_id: str
    trading_day: str
    symbols: list[str]
    plan_count: int
    attempt_count: int
    executed_count: int
    blocked_count: int
    outcome: CycleOutcome
    enabled: bool
    live_trading_enabled: bool
    created_at: str


__all__ = [
    "AnalystAction",
    "AnalystView",
    "CommitteeInput",
    "CommitteeRole",
    "CommitteeStance",
    "CommitteeTranscript",
    "CommitteeTurn",
    "CommitteeTurnPhase",
    "CommitteeVote",
    "ConsensusLevel",
    "CycleOutcome",
    "DailyCycleRecord",
    "DailyCycleSummary",
    "EvidenceCitation",
    "MarketSnapshot",
    "OrderAttempt",
    "OrderSide",
    "ResearchProposal",
    "TradePlan",
    "_to_decimal_str",
]
