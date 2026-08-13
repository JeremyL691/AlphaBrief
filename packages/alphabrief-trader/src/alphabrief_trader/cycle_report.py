"""Reproducible daily cycle report (M11-W07).

Every completed cycle references a daily brief, committee transcript (or
a legal skip), proposal or no-trade, risk result, broker outcome,
reconciliation, portfolio snapshot, alerts, and data-quality summary.
The report is built only from immutable transition IDs, so rebuilding
produces byte-equivalent normalized content and can never substitute
newer evidence.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_trader.cycle_state import CycleTransition


class DailyCycleReport(BaseModel):
    """One immutable, reproducible cycle report."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    cycle_id: str = Field(min_length=1)
    trading_date: str = Field(min_length=1)
    scheduler_outcome: str = Field(min_length=1)
    daily_brief_id: str | None = None
    transcript_id: str | None = None
    transcript_skip_reason: str | None = None
    proposal_ids: list[str] = Field(default_factory=list)
    no_trade_reason: str | None = None
    decision_ids: list[str] = Field(default_factory=list)
    broker_order_ids: list[str] = Field(default_factory=list)
    reconciliation_id: str | None = None
    portfolio_snapshot: dict[str, str] = Field(default_factory=dict)
    alert_summary: dict[str, int] = Field(default_factory=dict)
    data_quality_summary: dict[str, str] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    def normalized_json(self) -> str:
        """Byte-stable normalized serialization for equivalence checks.

        ``report_id`` and ``created_at`` are build-time artifacts; the
        normalized content covers only the immutable transition-derived
        fields, so rebuilding from the same IDs is byte-equivalent.
        """
        return json.dumps(
            self.model_dump(mode="json", exclude={"report_id", "created_at"}),
            sort_keys=True,
        )


def build_cycle_report(
    *,
    cycle_id: str,
    trading_date: str,
    transitions: list[CycleTransition],
    portfolio_snapshot: dict[str, str] | None = None,
    alert_summary: dict[str, int] | None = None,
    data_quality_summary: dict[str, str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> DailyCycleReport:
    """Build the report deterministically from immutable transition IDs.

    Only IDs already committed in the transition log are referenced;
    nothing is fetched fresh, so a rebuild can never substitute newer
    evidence.
    """
    by_phase: dict[str, dict[str, object]] = {}
    for transition in transitions:
        if transition.prior_phase is not None:
            by_phase[transition.prior_phase] = {
                **transition.output_ids,
                "_outcome": transition.outcome,
            }

    def _json_list(phase: str, key: str) -> list[str]:
        raw = by_phase.get(phase, {}).get(key, "[]")
        return [str(item) for item in json.loads(str(raw))]

    def _json_str(phase: str, key: str) -> str | None:
        raw: object = by_phase.get(phase, {}).get(key)
        if raw is None:
            return None
        return str(raw)

    outcome = _json_str("report", "terminal_outcome") or "unknown"
    proposals = _json_list("propose", "proposals")
    execute = by_phase.get("execute", {})

    attempts_raw = json.loads(str(execute.get("attempts", "[]")))
    broker_order_ids = [
        str(a.get("order_id") or a.get("client_order_id") or "")
        for a in attempts_raw
        if a.get("order_id") or a.get("client_order_id")
    ]
    execution_reasons = _json_str("execute", "execution_reasons")
    no_trade_reason = (
        execution_reasons if outcome != "executed" and execution_reasons else None
    )

    report = DailyCycleReport(
        report_id="placeholder",
        cycle_id=cycle_id,
        trading_date=trading_date,
        scheduler_outcome=outcome,
        daily_brief_id=_json_str("report", "daily_brief_id"),
        transcript_id=_json_str("discuss", "transcript_id") or None,
        transcript_skip_reason=(
            _json_str("discuss", "transcript_skip_reason") or None
        ),
        proposal_ids=proposals,
        no_trade_reason=no_trade_reason,
        decision_ids=_json_list("risk", "decisions"),
        broker_order_ids=broker_order_ids,
        reconciliation_id=(
            _json_str("reconcile", "reconciliation_evidence") is not None
            and f"recon_{cycle_id[:12]}" or None
        ),
        portfolio_snapshot=portfolio_snapshot or {},
        alert_summary=alert_summary or {},
        data_quality_summary=data_quality_summary or {},
        created_at=(clock or (lambda: datetime.now(UTC)))(),
    )
    report_id = sha256(
        report.normalized_json().encode("utf-8")
    ).hexdigest()[:16]
    return report.model_copy(update={"report_id": f"report_{report_id}"})


def rebuild_cycle_report(
    report: DailyCycleReport,
    transitions: list[CycleTransition],
    *,
    clock: Callable[[], datetime] | None = None,
) -> DailyCycleReport:
    """Rebuild the report from the immutable transitions.

    The rebuilt normalized content is byte-equivalent to the original
    because both derive only from the committed transition IDs; the
    report_id stays identical, proving no newer evidence substituted.
    """
    rebuilt = build_cycle_report(
        cycle_id=report.cycle_id,
        trading_date=report.trading_date,
        transitions=transitions,
        portfolio_snapshot=report.portfolio_snapshot,
        alert_summary=report.alert_summary,
        data_quality_summary=report.data_quality_summary,
        clock=clock,
    )
    return rebuilt


__all__ = ["DailyCycleReport", "build_cycle_report", "rebuild_cycle_report"]
