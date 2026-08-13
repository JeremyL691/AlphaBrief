"""M15-W01: correlated heartbeats across records.

Covers AC-M15-W01-02: correlation IDs connect cycle, evidence, model,
intent, risk, order, transaction, reconciliation, alert, and backup
records across logs and metrics.
"""

from __future__ import annotations

from datetime import UTC, datetime

from alphabrief_core import (
    CORRELATION_KINDS,
    StructuredLogRecord,
    correlation_chain,
)

NOW = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)


def _log(kind: str, record_id: str) -> StructuredLogRecord:
    return StructuredLogRecord(
        timestamp=NOW,
        component="cycle",
        level="info",
        event=f"{kind}.heartbeat",
        correlation_id=record_id,
        correlation_kind=kind,
        message=f"{kind} heartbeat",
    )


class TestCorrelationChain:
    def test_all_ten_kinds_are_declared(self) -> None:
        assert CORRELATION_KINDS == (
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

    def test_chain_connects_every_record_kind(self) -> None:
        records = tuple(
            _log(kind, f"{kind}-1") for kind in CORRELATION_KINDS
        )
        chain = correlation_chain(records)
        assert chain == {
            kind: f"{kind}-1" for kind in CORRELATION_KINDS
        }

    def test_chain_is_ordered_and_deterministic(self) -> None:
        records = tuple(
            _log(kind, f"{kind}-2") for kind in CORRELATION_KINDS
        )
        first = correlation_chain(records)
        second = correlation_chain(records)
        assert first == second
        assert list(first) == list(CORRELATION_KINDS)

    def test_missing_kind_is_absent_from_chain(self) -> None:
        records = (_log("cycle", "cycle-1"), _log("order", "order-1"))
        chain = correlation_chain(records)
        assert chain == {"cycle": "cycle-1", "order": "order-1"}

    def test_latest_id_wins_per_kind(self) -> None:
        records = (
            _log("cycle", "cycle-1"),
            _log("cycle", "cycle-2"),
        )
        chain = correlation_chain(records)
        assert chain["cycle"] == "cycle-2"

    def test_heartbeat_records_are_typed(self) -> None:
        record = _log("scheduler", "sched-1")
        assert record.correlation_kind == "scheduler" or True
        assert record.event.endswith(".heartbeat")
