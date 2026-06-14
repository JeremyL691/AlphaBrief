"""Execution audit log for paper trading."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AuditEventType = Literal[
    "risk_decision_recorded",
    "order_created",
    "order_rejected",
    "fill_created",
    "portfolio_updated",
]


class ExecutionAuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    event_type: AuditEventType
    intent_id: str | None = None
    risk_decision_id: str | None = None
    order_id: str | None = None
    fill_id: str | None = None
    message: str = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class ExecutionAuditLog:
    """In-memory append-only audit log for MVP paper execution."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self.entries: list[ExecutionAuditEntry] = []

    def append(
        self,
        *,
        event_type: AuditEventType,
        message: str,
        intent_id: str | None = None,
        risk_decision_id: str | None = None,
        order_id: str | None = None,
        fill_id: str | None = None,
    ) -> ExecutionAuditEntry:
        entry = ExecutionAuditEntry(
            event_id=f"audit_{len(self.entries) + 1}",
            event_type=event_type,
            intent_id=intent_id,
            risk_decision_id=risk_decision_id,
            order_id=order_id,
            fill_id=fill_id,
            message=message,
            created_at=self._clock(),
        )
        self.entries.append(entry)
        return entry
