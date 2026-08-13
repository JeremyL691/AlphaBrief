"""Error taxonomy and durable alert lifecycle (M15-W02).

Operational failures are classified deterministically into retry,
freeze, no-trade, or stop behavior (REQ-OPS-003). Alerts persist
severity, dedupe key, first and last occurrence, count,
acknowledgement, escalation, resolution, incident link, and scrubbed
evidence across restart; external sink failure never deletes or
resolves the local alert and repeated equivalent events do not create
an unbounded alert storm (REQ-OPS-004).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from alphabrief_core.observability import redact_observable

ErrorClass = Literal[
    "auth",
    "validation",
    "broker_reject",
    "rate_limit",
    "transient",
    "protocol",
    "data_quality",
    "safety",
]

ERROR_CLASSES: tuple[str, ...] = (
    "auth",
    "validation",
    "broker_reject",
    "rate_limit",
    "transient",
    "protocol",
    "data_quality",
    "safety",
)

Severity = Literal["info", "warning", "critical", "blocker"]


class ErrorClassification(BaseModel):
    """One deterministic error classification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error_class: ErrorClass
    retryable: bool
    severity: Severity
    freeze_execution: bool
    no_trade: bool
    escalate: bool


#: REQ-OPS-003 mapping: error class -> deterministic behavior.
_ERROR_CLASSIFICATION: dict[str, ErrorClassification] = {
    "auth": ErrorClassification(
        error_class="auth",
        retryable=False,
        severity="blocker",
        freeze_execution=True,
        no_trade=True,
        escalate=True,
    ),
    "validation": ErrorClassification(
        error_class="validation",
        retryable=False,
        severity="warning",
        freeze_execution=False,
        no_trade=True,
        escalate=False,
    ),
    "broker_reject": ErrorClassification(
        error_class="broker_reject",
        retryable=False,
        severity="critical",
        freeze_execution=True,
        no_trade=True,
        escalate=True,
    ),
    "rate_limit": ErrorClassification(
        error_class="rate_limit",
        retryable=True,
        severity="warning",
        freeze_execution=False,
        no_trade=True,
        escalate=False,
    ),
    "transient": ErrorClassification(
        error_class="transient",
        retryable=True,
        severity="warning",
        freeze_execution=False,
        no_trade=False,
        escalate=False,
    ),
    "protocol": ErrorClassification(
        error_class="protocol",
        retryable=True,
        severity="warning",
        freeze_execution=False,
        no_trade=True,
        escalate=False,
    ),
    "data_quality": ErrorClassification(
        error_class="data_quality",
        retryable=False,
        severity="critical",
        freeze_execution=False,
        no_trade=True,
        escalate=True,
    ),
    "safety": ErrorClassification(
        error_class="safety",
        retryable=False,
        severity="blocker",
        freeze_execution=True,
        no_trade=True,
        escalate=True,
    ),
}


def classify_error(code: str) -> ErrorClassification:
    """Classify one operational failure deterministically.

    Unknown classes fail closed as a safety blocker: not retryable,
    execution frozen, no-trade, escalated.
    """
    if code in _ERROR_CLASSIFICATION:
        return _ERROR_CLASSIFICATION[code]
    return ErrorClassification(
        error_class="safety",
        retryable=False,
        severity="blocker",
        freeze_execution=True,
        no_trade=True,
        escalate=True,
    )


class AlertRecord(BaseModel):
    """One durable deduplicated alert."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alert_id: str = Field(min_length=1)
    severity: Severity
    dedupe_key: str = Field(min_length=1)
    first_occurrence: str
    last_occurrence: str
    count: int = Field(ge=1)
    acknowledged: bool = False
    escalated: bool = False
    resolved: bool = False
    incident_link: str | None = None
    evidence: dict[str, str] = Field(default_factory=dict)


class AlertStore:
    """Append-only durable alert store backed by an NDJSON file.

    The store survives restarts (records reload from the file), dedupes
    equivalent events by ``dedupe_key`` (repeated events increment the
    count instead of creating a new alert), and never deletes or
    resolves an alert on external sink failure.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
            base = Path(env_dir) if env_dir else Path("~/.alphabrief")
            base = base.expanduser()
            base.mkdir(parents=True, exist_ok=True)
            path = base / "alerts.ndjson"
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, AlertRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = AlertRecord.model_validate(json.loads(line))
            self._records[record.alert_id] = record

    def _append(self, record: AlertRecord) -> None:
        self._records[record.alert_id] = record
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    def raise_alert(
        self,
        *,
        dedupe_key: str,
        severity: Severity,
        evidence: dict[str, Any] | None = None,
        incident_link: str | None = None,
        now: datetime | None = None,
    ) -> AlertRecord:
        """Raise or dedupe one alert.

        An event with an existing ``dedupe_key`` increments the count
        and refreshes ``last_occurrence`` instead of creating a new
        alert — repeated equivalent events never create a storm.
        """
        timestamp = (now or datetime.now(UTC)).isoformat()
        existing = next(
            (
                record
                for record in self._records.values()
                if record.dedupe_key == dedupe_key
            ),
            None,
        )
        if existing is not None:
            updated = existing.model_copy(
                update={
                    "count": existing.count + 1,
                    "last_occurrence": timestamp,
                }
            )
            self._append(updated)
            return updated
        alert_id = f"alert_{len(self._records) + 1:04d}"
        scrubbed = {
            key: redact_observable(str(value))
            for key, value in (evidence or {}).items()
        }
        record = AlertRecord(
            alert_id=alert_id,
            severity=severity,
            dedupe_key=dedupe_key,
            first_occurrence=timestamp,
            last_occurrence=timestamp,
            count=1,
            incident_link=incident_link,
            evidence=scrubbed,
        )
        self._append(record)
        return record

    def acknowledge(self, alert_id: str) -> AlertRecord:
        record = self._require(alert_id)
        updated = record.model_copy(update={"acknowledged": True})
        self._append(updated)
        return updated

    def escalate(self, alert_id: str) -> AlertRecord:
        record = self._require(alert_id)
        updated = record.model_copy(update={"escalated": True})
        self._append(updated)
        return updated

    def resolve(self, alert_id: str) -> AlertRecord:
        record = self._require(alert_id)
        updated = record.model_copy(update={"resolved": True})
        self._append(updated)
        return updated

    def sink_failure(self, alert_id: str) -> AlertRecord:
        """External sink failure: the local alert is untouched."""
        return self._require(alert_id)

    def get(self, alert_id: str) -> AlertRecord | None:
        return self._records.get(alert_id)

    def list_alerts(self) -> tuple[AlertRecord, ...]:
        return tuple(
            sorted(self._records.values(), key=lambda record: record.alert_id)
        )

    def _require(self, alert_id: str) -> AlertRecord:
        record = self._records.get(alert_id)
        if record is None:
            raise KeyError(f"unknown alert {alert_id!r}")
        return record


__all__ = [
    "ERROR_CLASSES",
    "AlertRecord",
    "AlertStore",
    "ErrorClassification",
    "ErrorClass",
    "Severity",
    "classify_error",
]
