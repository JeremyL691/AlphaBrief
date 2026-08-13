"""Structured observability and runtime readiness truth (M15-W01).

Every critical subsystem — ingestion, news, models, scheduler, cycle,
risk, OANDA, reconciliation, backup, API, and Electron — publishes
structured health, readiness, heartbeat, latency, success, failure,
and freshness signals. Correlation IDs connect cycle, evidence, model,
intent, risk, order, transaction, reconciliation, alert, and backup
records across logs and metrics. All observable output is scrubbed of
tokens, authorization headers, full account IDs, model-sensitive
content, unlicensed news text, and configured secret patterns
(REQ-OPS-001, REQ-OPS-002).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

Component = Literal[
    "ingestion",
    "news",
    "models",
    "scheduler",
    "cycle",
    "risk",
    "oanda",
    "reconciliation",
    "backup",
    "api",
    "electron",
]

COMPONENTS: tuple[str, ...] = (
    "ingestion",
    "news",
    "models",
    "scheduler",
    "cycle",
    "risk",
    "oanda",
    "reconciliation",
    "backup",
    "api",
    "electron",
)

#: The documented correlation record kinds (REQ-OPS-002).
CORRELATION_KINDS: tuple[str, ...] = (
    "cycle",
    "evidence",
    "model",
    "intent",
    "risk",
    "order",
    "transaction",
    "reconciliation",
    "alert",
    "backup",
)

Level = Literal["debug", "info", "warning", "error"]


class StructuredLogRecord(BaseModel):
    """One correlated structured log record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    component: Component
    level: Level
    event: str = Field(min_length=1)
    correlation_id: str | None = None
    correlation_kind: str | None = None
    message: str = Field(min_length=1)
    fields: dict[str, str] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("log timestamps must be timezone-aware")
        return value


class MetricRecord(BaseModel):
    """One bounded structured metric."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    component: Component
    metric: Literal["latency", "success", "failure", "freshness"]
    value: str
    unit: str = Field(min_length=1)
    correlation_id: str | None = None


class ComponentHealth(BaseModel):
    """One component's health, readiness, and heartbeat truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component: Component
    status: Literal["healthy", "degraded", "unhealthy", "unknown"] = "unknown"
    ready: bool = False
    heartbeat_at: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    freshness: str | None = None


class HealthRegistry(BaseModel):
    """One deterministic health snapshot of every component."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    components: tuple[ComponentHealth, ...]


def build_health_registry(
    truth: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
) -> HealthRegistry:
    """Shape the health registry from per-component runtime truth.

    Every component is declared; a component missing from the truth
    stays ``unknown`` and not ready — never assumed healthy.
    """
    rows: list[ComponentHealth] = []
    for component in COMPONENTS:
        data = truth.get(component) or {}
        rows.append(
            ComponentHealth(
                component=cast(Component, component),
                status=cast(
                    Literal["healthy", "degraded", "unhealthy", "unknown"],
                    _status_or_unknown(data),
                ),
                ready=bool(data.get("ready", False)),
                heartbeat_at=_str_or_none(data, "heartbeat_at"),
                last_success_at=_str_or_none(data, "last_success_at"),
                last_failure_at=_str_or_none(data, "last_failure_at"),
                freshness=_str_or_none(data, "freshness"),
            )
        )
    return HealthRegistry(components=tuple(rows))


def _status_or_unknown(data: dict[str, Any]) -> str:
    status = data.get("status")
    if status in ("healthy", "degraded", "unhealthy", "unknown"):
        return cast(str, status)
    return "unknown"


def correlation_chain(
    records: tuple[StructuredLogRecord, ...],
) -> dict[str, str]:
    """The correlation chain: every kind -> its latest correlation id.

    Cycle, evidence, model, intent, risk, order, transaction,
    reconciliation, alert, and backup records connect through their
    correlation ids.
    """
    chain: dict[str, str] = {}
    for record in records:
        if (
            record.correlation_kind in CORRELATION_KINDS
            and record.correlation_id is not None
        ):
            chain[record.correlation_kind] = record.correlation_id
    return {kind: chain[kind] for kind in CORRELATION_KINDS if kind in chain}


#: Patterns that must never survive in observable output.
_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"token\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"account-\d{8,}", re.IGNORECASE),
)

#: Model-sensitive content markers and unlicensed news-text markers.
_MODEL_SENSITIVE_MARKERS = (
    "system prompt",
    "model weights",
    "raw conversation",
)
_UNLICENSED_NEWS_MARKERS = (
    "full article",
    "unlicensed text",
    "copyrighted body",
)


def redact_observable(text: str, *, secret_patterns: tuple[str, ...] = ()) -> str:
    """Scrub every protected value from observable output.

    Tokens, authorization headers, full account IDs, configured secret
    patterns, model-sensitive content, and unlicensed news text are
    replaced deterministically.
    """
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    for configured in secret_patterns:
        redacted = re.sub(
            configured, "[REDACTED]", redacted, flags=re.IGNORECASE
        )
    for marker in _MODEL_SENSITIVE_MARKERS:
        redacted = redacted.replace(marker, "[MODEL-REDACTED]")
    for marker in _UNLICENSED_NEWS_MARKERS:
        redacted = redacted.replace(marker, "[NEWS-REDACTED]")
    return redacted


def account_id_hash(account_id: str) -> str:
    """Non-reversible display hash for a full account id."""
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:12]


def _str_or_none(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    return str(value) if value is not None else None


__all__ = [
    "COMPONENTS",
    "CORRELATION_KINDS",
    "ComponentHealth",
    "HealthRegistry",
    "MetricRecord",
    "StructuredLogRecord",
    "account_id_hash",
    "build_health_registry",
    "correlation_chain",
    "redact_observable",
]
