"""Shared versioned read contracts for API and CLI surfaces (M13-W01).

Every read surface — instruments, prices, candles, news, sentiment,
committee, risk, orders, trades, positions, cycles, scheduler, alerts,
observation — returns one versioned envelope with UTC timestamps,
stable IDs, provenance, freshness, pagination, and an explicit
complete/empty/partial state. API JSON and CLI JSON normalize to the
same domain payload and ordering. Unknown filters, malformed cursors,
invalid identifiers, and unavailable sources produce typed errors that
never carry fake or silently truncated data (REQ-UI-001, REQ-PLAT-008,
REQ-PLAT-009).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Bump when any read envelope field or validation rule changes.
READ_SCHEMA_VERSION = "read-v1"

ReadDomain = Literal[
    "instruments",
    "prices",
    "candles",
    "news",
    "sentiment",
    "committee",
    "risk",
    "orders",
    "trades",
    "positions",
    "cycles",
    "scheduler",
    "alerts",
    "observation",
]

READ_DOMAINS: frozenset[str] = frozenset(
    {
        "instruments",
        "prices",
        "candles",
        "news",
        "sentiment",
        "committee",
        "risk",
        "orders",
        "trades",
        "positions",
        "cycles",
        "scheduler",
        "alerts",
        "observation",
    }
)

ReadState = Literal["complete", "empty", "partial"]


class Provenance(BaseModel):
    """Where the read payload came from and at which data version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1)
    data_version: str = Field(min_length=1)
    retrieved_at: datetime

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_at_must_be_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "retrieved_at")


class FreshnessVerdict(BaseModel):
    """One explicit freshness verdict for the read payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["fresh", "stale", "unknown"]
    age_seconds: int | None = None
    max_age_seconds: int | None = None

    @model_validator(mode="after")
    def freshness_fields_must_be_consistent(self) -> FreshnessVerdict:
        if self.status in ("fresh", "stale") and (
            self.age_seconds is None or self.max_age_seconds is None
        ):
            raise ValueError(
                "fresh and stale verdicts require age and max age seconds"
            )
        if self.status == "unknown" and self.age_seconds is not None:
            raise ValueError("unknown verdicts must not carry an age")
        return self


class PageCursor(BaseModel):
    """One explicit pagination contract (cursor-based)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = None
    next_cursor: str | None = None
    has_more: bool = False
    limit: int = Field(ge=1)
    count: int = Field(ge=0)

    @model_validator(mode="after")
    def has_more_must_match_next_cursor(self) -> PageCursor:
        if self.has_more and self.next_cursor is None:
            raise ValueError("has_more requires a next_cursor")
        if not self.has_more and self.next_cursor is not None:
            raise ValueError("next_cursor requires has_more")
        return self


class VersionedReadEnvelope(BaseModel):
    """One versioned response schema for every read surface.

    Items are normalized payload rows that always carry a stable
    ``id``; the builder sorts them by id so API and CLI serialization
    share one deterministic ordering.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = READ_SCHEMA_VERSION
    domain: ReadDomain
    resource: str = Field(min_length=1)
    generated_at: datetime
    state: ReadState
    provenance: Provenance
    freshness: FreshnessVerdict
    pagination: PageCursor
    items: tuple[dict[str, Any], ...] = Field(default_factory=tuple)

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "generated_at")

    @model_validator(mode="after")
    def state_must_match_items(self) -> VersionedReadEnvelope:
        if not self.items and self.state != "empty":
            raise ValueError("an empty payload must declare state 'empty'")
        if self.items and self.state == "empty":
            raise ValueError("a non-empty payload must not declare state 'empty'")
        return self


def _require_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be UTC (offset 0)")
    return value


def _stable_id(item: dict[str, Any]) -> str:
    identifier = item.get("id")
    if not isinstance(identifier, str) or identifier.strip() == "":
        raise ValueError("every read item must carry a non-blank stable 'id'")
    return identifier


def build_read_envelope(
    *,
    domain: ReadDomain,
    resource: str,
    items: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    provenance: Provenance,
    freshness: FreshnessVerdict,
    pagination: PageCursor,
    state: ReadState | None = None,
    generated_at: datetime | None = None,
) -> VersionedReadEnvelope:
    """Build one versioned read envelope deterministically.

    Items are validated for stable ids and sorted by id so every
    consumer observes the same ordering.
    """
    if domain not in READ_DOMAINS:
        raise ValueError(f"unknown read domain {domain!r}")
    for item in items:
        _stable_id(item)
    ordered = tuple(sorted(items, key=_stable_id))
    resolved_state = state or ("empty" if not ordered else "complete")
    return VersionedReadEnvelope(
        schema_version=READ_SCHEMA_VERSION,
        domain=domain,
        resource=resource,
        generated_at=generated_at or datetime.now(UTC),
        state=resolved_state,
        provenance=provenance,
        freshness=freshness,
        pagination=pagination,
        items=ordered,
    )


def normalize_read_payload(envelope: VersionedReadEnvelope) -> dict[str, Any]:
    """The canonical domain payload shared by API and CLI JSON.

    Serializes with sorted keys and compact separators so identical
    envelopes always normalize to identical bytes and ordering.
    """
    payload = envelope.model_dump(mode="json")
    return cast(
        dict[str, Any],
        json.loads(json.dumps(payload, sort_keys=True, separators=(",", ":"))),
    )


ReadErrorCode = Literal[
    "unknown_filter",
    "malformed_cursor",
    "invalid_identifier",
    "unavailable_source",
    "invalid_request",
]


class ReadErrorResponse(BaseModel):
    """One typed read error. Never carries fake or truncated items."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = READ_SCHEMA_VERSION
    error_code: ReadErrorCode
    message: str = Field(min_length=1)
    resource: str | None = None


def unknown_filter_error(resource: str, filter_name: str) -> ReadErrorResponse:
    return ReadErrorResponse(
        error_code="unknown_filter",
        message=f"filter {filter_name!r} is not supported for {resource}",
        resource=resource,
    )


def malformed_cursor_error(resource: str, cursor: str) -> ReadErrorResponse:
    return ReadErrorResponse(
        error_code="malformed_cursor",
        message=f"cursor {cursor!r} is malformed for {resource}",
        resource=resource,
    )


def invalid_identifier_error(resource: str, identifier: str) -> ReadErrorResponse:
    return ReadErrorResponse(
        error_code="invalid_identifier",
        message=f"identifier {identifier!r} is invalid for {resource}",
        resource=resource,
    )


def unavailable_source_error(resource: str, source: str) -> ReadErrorResponse:
    return ReadErrorResponse(
        error_code="unavailable_source",
        message=f"source {source!r} is unavailable for {resource}",
        resource=resource,
    )


__all__ = [
    "READ_DOMAINS",
    "READ_SCHEMA_VERSION",
    "FreshnessVerdict",
    "PageCursor",
    "Provenance",
    "ReadDomain",
    "ReadErrorCode",
    "ReadErrorResponse",
    "ReadState",
    "VersionedReadEnvelope",
    "build_read_envelope",
    "invalid_identifier_error",
    "malformed_cursor_error",
    "normalize_read_payload",
    "unavailable_source_error",
    "unknown_filter_error",
]
