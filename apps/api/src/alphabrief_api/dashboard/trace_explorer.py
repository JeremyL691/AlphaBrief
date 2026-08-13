"""End-to-end decision and execution trace explorer (M14-W05).

A single immutable trace from a daily cycle through market and content
evidence, committee discussion, OrderIntent, RiskDecision, OANDA
lifecycle events, reconciliation, and portfolio outcome. Every segment
links bidirectionally through persisted correlation identifiers;
missing, stale, conflicting, or partial segments are visibly
classified and never collapsed into a successful execution story. The
redacted view exposes evidence versions, citations, inputs hash,
rule-by-rule outcomes, broker references, timestamps, and
reconciliation disposition without secrets or full account IDs
(REQ-UI-006, REQ-UI-007).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

SegmentKind = Literal[
    "cycle",
    "evidence",
    "transcript",
    "intent",
    "risk_decision",
    "order",
    "trade",
    "transaction",
    "reconciliation",
    "portfolio",
]

SegmentStatus = Literal["complete", "missing", "stale", "conflicting", "partial"]

Disposition = Literal["complete", "partial", "missing", "conflicting", "stale"]

#: Correlation identifiers a trace may carry; every displayed pair
#: must resolve in both directions.
CORRELATION_KEYS: tuple[str, ...] = (
    "cycle_id",
    "intent_id",
    "risk_decision_id",
    "order_id",
    "transaction_id",
    "reconciliation_id",
    "portfolio_event_id",
)


class TraceSegment(BaseModel):
    """One immutable trace segment with persisted correlation links."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SegmentKind
    segment_id: str = Field(min_length=1)
    status: SegmentStatus = "complete"
    correlation_ids: dict[str, str] = Field(default_factory=dict)
    timestamp: str | None = None
    detail: dict[str, str] = Field(default_factory=dict)


class TraceExplorerView(BaseModel):
    """The complete explorer state for one cycle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cycle_id: str = Field(min_length=1)
    segments: tuple[TraceSegment, ...]
    disposition: Disposition


class RedactedTraceView(BaseModel):
    """The redacted explorer: evidence, citations, hashes, outcomes,
    broker references, timestamps, and reconciliation disposition —
    with secrets and full account IDs removed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cycle_id: str
    segments: tuple[TraceSegment, ...]
    disposition: Disposition
    redaction_applied: bool = True


def classify_segment(*, present: bool, stale: bool = False,
                     conflicting: bool = False,
                     partial: bool = False) -> SegmentStatus:
    """One deterministic segment classification."""
    if not present:
        return "missing"
    if conflicting:
        return "conflicting"
    if stale:
        return "stale"
    if partial:
        return "partial"
    return "complete"


def build_trace_explorer(
    *,
    cycle_id: str,
    segments: list[dict[str, Any]],
) -> TraceExplorerView:
    """Shape the explorer from persisted trace truth.

    ``segments`` are trace rows carrying their kind, id, correlation
    ids, and status flags; the disposition is the worst visible
    classification — a missing or conflicting segment can never be
    silently collapsed into a successful story.
    """
    rows: list[TraceSegment] = []
    for raw in segments:
        status = classify_segment(
            present=bool(raw.get("present", True)),
            stale=bool(raw.get("stale", False)),
            conflicting=bool(raw.get("conflicting", False)),
            partial=bool(raw.get("partial", False)),
        )
        correlation_raw = raw.get("correlation_ids") or {}
        correlation = {
            key: str(correlation_raw[key])
            for key in CORRELATION_KEYS
            if correlation_raw.get(key) is not None
        }
        rows.append(
            TraceSegment(
                kind=cast(SegmentKind, str(raw.get("kind", "cycle"))),
                segment_id=str(raw.get("segment_id", "")),
                status=status,
                correlation_ids=correlation,
                timestamp=(
                    str(raw["timestamp"]) if raw.get("timestamp") else None
                ),
                detail={
                    key: str(value)
                    for key, value in raw.get("detail", {}).items()
                },
            )
        )

    ordered = tuple(sorted(rows, key=lambda segment: segment.segment_id))
    disposition = _disposition(ordered)
    return TraceExplorerView(
        cycle_id=cycle_id,
        segments=ordered,
        disposition=disposition,
    )


def _disposition(segments: tuple[TraceSegment, ...]) -> Disposition:
    """The worst visible classification across all segments."""
    for status in ("missing", "conflicting", "stale", "partial"):
        if any(segment.status == status for segment in segments):
            return status
    return "complete"


def verify_bidirectional_links(view: TraceExplorerView) -> tuple[str, ...]:
    """Every correlation id must resolve to a segment of the linked
    kind in both directions; missing pairs are reported."""
    issues: list[str] = []
    by_kind: dict[str, set[str]] = {}
    for segment in view.segments:
        by_kind.setdefault(segment.kind, set()).add(segment.segment_id)

    for segment in view.segments:
        for key, value in segment.correlation_ids.items():
            linked_kind = _kind_for_key(key)
            if linked_kind is None:
                continue
            targets = by_kind.get(linked_kind, set())
            if value not in targets:
                issues.append(
                    f"{segment.kind}:{segment.segment_id} links to "
                    f"{linked_kind}:{value} which has no segment"
                )
            # The linked segment must link back to this segment when
            # this segment's kind has a correlation key (leaf segments
            # like evidence and transcript link forward only).
            key_for_self = _key_for_kind(segment.kind)
            if key_for_self is None:
                continue
            for other in view.segments:
                if other.kind != linked_kind or other.segment_id != value:
                    continue
                back = other.correlation_ids.get(key_for_self)
                if back != segment.segment_id:
                    issues.append(
                        f"{linked_kind}:{value} does not link back to "
                        f"{segment.kind}:{segment.segment_id}"
                    )
    return tuple(sorted(issues))


def _kind_for_key(key: str) -> str | None:
    mapping = {
        "cycle_id": "cycle",
        "intent_id": "intent",
        "risk_decision_id": "risk_decision",
        "order_id": "order",
        "transaction_id": "transaction",
        "reconciliation_id": "reconciliation",
        "portfolio_event_id": "portfolio",
    }
    return mapping.get(key)


def _key_for_kind(kind: str) -> str | None:
    mapping = {
        "cycle": "cycle_id",
        "intent": "intent_id",
        "risk_decision": "risk_decision_id",
        "order": "order_id",
        "transaction": "transaction_id",
        "reconciliation": "reconciliation_id",
        "portfolio": "portfolio_event_id",
    }
    return mapping.get(kind)


#: Detail keys whose values are always secrets (redacted whole).
_SENSITIVE_DETAIL_KEYS: frozenset[str] = frozenset(
    {"token", "authorization", "account_id", "secret"}
)

#: Value-level patterns that must never survive redaction.
_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"token\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"account[_-]?id\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"account-\d{8,}", re.IGNORECASE),
)


def redact_explorer(view: TraceExplorerView) -> RedactedTraceView:
    """One deterministic redacted view of the explorer.

    Evidence versions, citations, inputs hash, rule-by-rule outcomes,
    broker references, timestamps, and reconciliation disposition are
    kept; secrets and full account IDs are removed.
    """
    segments: list[TraceSegment] = []
    for segment in view.segments:
        detail: dict[str, str] = {}
        for key, value in segment.detail.items():
            if key.lower() in _SENSITIVE_DETAIL_KEYS:
                detail[key] = "[REDACTED]"
            else:
                detail[key] = _redact_value(value)
        segments.append(
            segment.model_copy(update={"detail": detail})
        )
    return RedactedTraceView(
        cycle_id=view.cycle_id,
        segments=tuple(segments),
        disposition=view.disposition,
    )


def _redact_value(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def account_id_hash(account_id: str) -> str:
    """Non-reversible hash for display; never the full account id."""
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:12]


__all__ = [
    "CORRELATION_KEYS",
    "Disposition",
    "RedactedTraceView",
    "SegmentKind",
    "SegmentStatus",
    "TraceExplorerView",
    "TraceSegment",
    "account_id_hash",
    "build_trace_explorer",
    "classify_segment",
    "redact_explorer",
    "verify_bidirectional_links",
]
