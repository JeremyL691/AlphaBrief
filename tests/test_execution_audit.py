"""Unit tests for the execution audit log."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from alphabrief_execution.audit import ExecutionAuditEntry, ExecutionAuditLog
from pydantic import ValidationError


def test_append_assigns_event_id_in_order() -> None:
    log = ExecutionAuditLog()
    first = log.append(event_type="order_created", message="first")
    second = log.append(event_type="fill_created", message="second")
    assert first.event_id == "audit_1"
    assert second.event_id == "audit_2"


def test_append_passes_risk_context() -> None:
    log = ExecutionAuditLog()
    entry = log.append(
        event_type="risk_decision_recorded",
        message="with context",
        risk_context_decision_id="rcx-1",
        risk_context_tags=("news_volatility",),
        risk_context_multiplier=0.5,
    )
    assert entry.risk_context_decision_id == "rcx-1"
    assert entry.risk_context_tags == ("news_volatility",)
    assert entry.risk_context_multiplier == 0.5


def test_audit_entry_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        ExecutionAuditEntry(
            event_id="audit_x",
            event_type="order_created",
            message="bad",
            created_at=datetime(2026, 6, 20),
        )


def test_audit_entry_accepts_timezone_aware() -> None:
    entry = ExecutionAuditEntry(
        event_id="audit_x",
        event_type="order_created",
        message="ok",
        created_at=datetime(2026, 6, 20, tzinfo=UTC),
    )
    assert entry.created_at.tzinfo is not None


def test_audit_log_uses_injected_clock() -> None:
    fixed = datetime(2026, 6, 20, 13, 30, tzinfo=UTC)
    log = ExecutionAuditLog(clock=lambda: fixed)
    entry = log.append(event_type="order_created", message="x")
    assert entry.created_at == fixed


def test_audit_log_entries_are_isolated() -> None:
    log = ExecutionAuditLog()
    log.append(event_type="order_created", message="a")
    log.append(event_type="order_rejected", message="b")
    types = [e.event_type for e in log.entries]
    assert types == ["order_created", "order_rejected"]
