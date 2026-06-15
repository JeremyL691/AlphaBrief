"""Multi-Model Research Committee schemas for AlphaBrief.

These schemas represent a research debate where multiple AI models, each
assigned a different analytical perspective, independently analyze a
research question and produce structured outputs. A consensus is then
aggregated from all responses.

They are pure Pydantic validation boundaries with no side effects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

DebatePerspective = Literal["technical", "fundamental", "risk", "judge"]
ViewType = Literal["bullish", "bearish", "neutral", "uncertain"]
ActionType = Literal["buy", "sell", "hold", "watch", "skip"]
AgreementLevel = Literal["high", "medium", "low", "mixed"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime fields must be timezone-aware")
    return value


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MultiModelSchema(BaseModel):
    """Shared strict schema configuration for MMRC models."""

    model_config = ConfigDict(extra="forbid")


class DebateQuestion(MultiModelSchema):
    """A research question submitted for multi-model analysis."""

    question: str = Field(min_length=1)
    symbol: str | None = None
    time_horizon: str | None = None
    perspectives: list[str] = Field(
        default=["technical", "fundamental", "risk", "judge"],
        min_length=1,
    )
    context: str | None = None

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("question must not be blank")
        return value

    @field_validator("perspectives")
    @classmethod
    def _validate_perspectives(cls, value: list[str]) -> list[str]:
        valid = {"technical", "fundamental", "risk", "judge"}
        for p in value:
            if p not in valid:
                raise ValueError(f"Invalid perspective: {p!r}. Valid: {sorted(valid)}")
        return value


class ModelDebateResponse(MultiModelSchema):
    """A single model's analysis from one perspective."""

    model_name: str = Field(min_length=1)
    perspective: str = Field(min_length=1)
    analysis: str = Field(min_length=1)
    view: ViewType
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    suggested_action: ActionType
    needs_human_review: bool = False

    @field_validator("model_name", "perspective", "analysis")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value


class DebateConsensus(MultiModelSchema):
    """Aggregated consensus from all model responses."""

    num_models: int = Field(ge=0)
    agreement_level: AgreementLevel
    consensus_view: ViewType | None = None
    avg_confidence: float = Field(ge=0, le=1)
    view_distribution: dict[str, int] = Field(default_factory=dict)
    key_evidence: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    suggested_action: str = ""
    needs_human_review: bool = False


class DebateRecord(MultiModelSchema):
    """Complete record of a multi-model research debate."""

    debate_id: str = Field(min_length=1)
    question: DebateQuestion
    responses: list[ModelDebateResponse] = Field(default_factory=list)
    consensus: DebateConsensus | None = None
    created_at: datetime

    @field_validator("debate_id")
    @classmethod
    def _id_not_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("debate_id must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def _created_at_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)


__all__ = [
    "ActionType",
    "AgreementLevel",
    "DebateConsensus",
    "DebatePerspective",
    "DebateQuestion",
    "DebateRecord",
    "ModelDebateResponse",
    "MultiModelSchema",
    "ViewType",
]
