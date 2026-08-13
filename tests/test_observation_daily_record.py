"""M16-W02: daily observation evidence record.

Covers AC-M16-W02-01: Days 1 through 7 each contain preflight, data,
news, sentiment, committee or valid skip, intent or no-trade, risk,
execution outcome, reconciliation, portfolio, alerts, heartbeat,
backup, and hashed daily manifest evidence.
"""

from __future__ import annotations

from alphabrief_core import (
    DAILY_EVIDENCE_KINDS,
    ObservationDayRecord,
    build_daily_record,
)


def _full_truth() -> dict[str, bool]:
    return {kind: True for kind in DAILY_EVIDENCE_KINDS}


class TestDailyRecord:
    def test_all_fourteen_evidence_kinds_are_declared(self) -> None:
        assert DAILY_EVIDENCE_KINDS == (
            "preflight",
            "data",
            "news",
            "sentiment",
            "committee_or_skip",
            "intent_or_no_trade",
            "risk",
            "execution_outcome",
            "reconciliation",
            "portfolio",
            "alerts",
            "heartbeat",
            "backup",
            "daily_manifest_hash",
        )

    def test_complete_day_with_manifest_hash(self) -> None:
        record = build_daily_record(
            day=1,
            calendar_date="2026-08-15",
            evidence_truth=_full_truth(),
            daily_manifest_hash="hash-1",
        )
        assert isinstance(record, ObservationDayRecord)
        assert record.complete is True
        assert record.daily_manifest_hash == "hash-1"

    def test_missing_evidence_kind_marks_incomplete(self) -> None:
        truth = _full_truth()
        del truth["reconciliation"]
        record = build_daily_record(
            day=1,
            calendar_date="2026-08-15",
            evidence_truth=truth,
            daily_manifest_hash="hash-1",
        )
        assert record.complete is False
        assert record.evidence["reconciliation"] is False

    def test_missing_manifest_hash_marks_incomplete(self) -> None:
        record = build_daily_record(
            day=1,
            calendar_date="2026-08-15",
            evidence_truth=_full_truth(),
            daily_manifest_hash=None,
        )
        assert record.complete is False

    def test_evidence_is_never_fabricated(self) -> None:
        record = build_daily_record(
            day=1,
            calendar_date="2026-08-15",
            evidence_truth={},
            daily_manifest_hash=None,
        )
        assert all(not value for value in record.evidence.values())
        assert record.complete is False

    def test_deterministic(self) -> None:
        first = build_daily_record(
            day=1,
            calendar_date="2026-08-15",
            evidence_truth=_full_truth(),
            daily_manifest_hash="hash-1",
        )
        second = build_daily_record(
            day=1,
            calendar_date="2026-08-15",
            evidence_truth=_full_truth(),
            daily_manifest_hash="hash-1",
        )
        assert first.model_dump() == second.model_dump()
