"""Append-only strategy-admission evidence API.

Admission records document human review. They are not read by RiskGate,
PaperBroker, or any execution path and therefore cannot authorize orders.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alphabrief_api.routes.strategies import _get_strategy_store

AdmissionStatus = Literal["draft", "approved", "rejected", "suspended"]


class AdmissionEvidence(BaseModel):
    """Evidence captured with every immutable strategy-admission record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_version: str = Field(min_length=1)
    in_sample_backtest_report_id: str = Field(min_length=1)
    out_of_sample_backtest_report_id: str = Field(min_length=1)
    fee_bps: Decimal = Field(ge=0)
    slippage_bps: Decimal = Field(ge=0)
    lookahead_check_passed: bool
    risk_review_notes: tuple[str, ...] = Field(min_length=1)
    disabled_conditions: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "data_version",
        "in_sample_backtest_report_id",
        "out_of_sample_backtest_report_id",
    )
    @classmethod
    def strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("evidence strings must not be blank")
        return value

    @field_validator("risk_review_notes", "disabled_conditions")
    @classmethod
    def list_items_must_not_be_blank(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(item.strip() == "" for item in value):
            raise ValueError("evidence lists must not contain blank values")
        return value


class StrategyAdmissionCreateRequest(BaseModel):
    """Request body for creating one immutable admission record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    status: AdmissionStatus
    reviewer_id: str = Field(min_length=1)
    reviewed_at: datetime
    evidence: AdmissionEvidence
    supersedes_admission_id: str | None = Field(default=None, min_length=1)

    @field_validator("strategy_id", "strategy_version", "reviewer_id")
    @classmethod
    def strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("admission strings must not be blank")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def reviewed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def approved_records_require_lookahead_evidence(
        self,
    ) -> StrategyAdmissionCreateRequest:
        if self.status == "approved" and not self.evidence.lookahead_check_passed:
            raise ValueError("approved admissions require a passed lookahead check")
        return self


class StrategyAdmissionResponse(BaseModel):
    """Serialized immutable strategy-admission evidence."""

    model_config = ConfigDict(frozen=True)

    admission_id: str
    strategy_id: str
    strategy_version: str
    status: AdmissionStatus
    reviewer_id: str
    reviewed_at: str
    evidence: AdmissionEvidence
    supersedes_admission_id: str | None
    created_at: str


class StrategyAdmissionListResponse(BaseModel):
    """Response body for listing strategy-admission records."""

    model_config = ConfigDict(frozen=True)

    admissions: list[StrategyAdmissionResponse]


router = APIRouter(prefix="/api/v1/strategy-admissions", tags=["strategy-admissions"])


@router.post("", response_model=StrategyAdmissionResponse, status_code=201)
def create_strategy_admission(
    body: StrategyAdmissionCreateRequest,
) -> StrategyAdmissionResponse:
    """Append reviewed strategy evidence without changing execution authority."""

    store = _get_strategy_store()
    strategy = store.get_spec(body.strategy_id)
    if strategy is None:
        raise HTTPException(
            status_code=404,
            detail=f"strategy {body.strategy_id!r} not found",
        )
    if strategy["version"] != body.strategy_version:
        raise HTTPException(
            status_code=422,
            detail="strategy_version must match the persisted StrategySpec",
        )
    if body.supersedes_admission_id is not None:
        superseded = store.get_admission(body.supersedes_admission_id)
        if superseded is None:
            raise HTTPException(
                status_code=404,
                detail=(f"admission {body.supersedes_admission_id!r} not found"),
            )
        if superseded["strategy_id"] != body.strategy_id:
            raise HTTPException(
                status_code=422,
                detail="superseded admission must belong to the same strategy",
            )

    admission_id = store.create_admission(
        {
            "strategy_id": body.strategy_id,
            "strategy_version": body.strategy_version,
            "status": body.status,
            "reviewer_id": body.reviewer_id,
            "reviewed_at": body.reviewed_at.isoformat(),
            "evidence": body.evidence.model_dump(mode="json"),
            "supersedes_admission_id": body.supersedes_admission_id,
        }
    )
    record = store.get_admission(admission_id)
    if record is None:  # pragma: no cover - defensive persistence invariant
        raise HTTPException(status_code=500, detail="admission persistence failed")
    return _response_from_record(record)


@router.get("", response_model=StrategyAdmissionListResponse)
def list_strategy_admissions(
    strategy_id: str | None = Query(default=None, min_length=1),
    status: AdmissionStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> StrategyAdmissionListResponse:
    """List immutable admission evidence newest first."""

    records = _get_strategy_store().list_admissions(
        strategy_id=strategy_id,
        status=status,
        limit=limit,
    )
    return StrategyAdmissionListResponse(
        admissions=[_response_from_record(record) for record in records]
    )


@router.get("/{admission_id}", response_model=StrategyAdmissionResponse)
def get_strategy_admission(admission_id: str) -> StrategyAdmissionResponse:
    """Return one immutable admission record."""

    record = _get_strategy_store().get_admission(admission_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"admission {admission_id!r} not found",
        )
    return _response_from_record(record)


def _response_from_record(record: dict[str, object]) -> StrategyAdmissionResponse:
    return StrategyAdmissionResponse.model_validate(record)


__all__ = [
    "AdmissionEvidence",
    "StrategyAdmissionCreateRequest",
    "StrategyAdmissionListResponse",
    "StrategyAdmissionResponse",
    "router",
]
