"""M16-W02: daily observation evidence record.

Covers AC-M16-W02-01: Days 1 through 7 each contain preflight, data,
news, sentiment, committee or valid skip, intent or no-trade, risk,
execution outcome, reconciliation, portfolio, alerts, heartbeat,
backup, and hashed daily manifest evidence.
"""

from __future__ import annotations

from alphabrief_core import (
    APPLICABILITY_EVIDENCE_KINDS,
    DAILY_EVIDENCE_KINDS,
    DailyApplicabilityEvidence,
    ObservationDayRecord,
    build_applicability_evidence,
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


class TestApplicabilityEvidence:
    """AC-M16-W03-01: Days 8-14 explicit applicability evidence."""

    def test_all_six_applicability_kinds_are_declared(self) -> None:
        assert APPLICABILITY_EVIDENCE_KINDS == (
            "weekend",
            "session",
            "financing",
            "macro_window",
            "provider_degradation",
            "no_trade",
        )

    def test_full_applicability_chain_with_reasons(self) -> None:
        evidence = build_applicability_evidence(
            day=8,
            calendar_date="2026-08-22",
            applicability_truth={
                "weekend": True,
                "session": True,
                "financing": True,
                "macro_window": True,
                "provider_degradation": False,
                "no_trade": True,
            },
            reasons={
                "weekend": "Saturday; market closed",
                "session": "no OANDA session for the instrument",
                "financing": "weekend financing applied",
                "macro_window": "macro event window active",
                "no_trade": "no opportunity",
            },
        )
        assert isinstance(evidence, DailyApplicabilityEvidence)
        assert evidence.complete is True
        assert evidence.applicability["weekend"] is True
        assert evidence.applicability["provider_degradation"] is False
        assert evidence.reasons["no_trade"] == "no opportunity"

    def test_missing_truth_is_never_fabricated(self) -> None:
        evidence = build_applicability_evidence(
            day=9,
            calendar_date="2026-08-23",
            applicability_truth={},
            reasons={},
        )
        assert all(not value for value in evidence.applicability.values())
        assert evidence.reasons == {}
        assert evidence.complete is True

    def test_true_verdict_requires_complete_reason(self) -> None:
        evidence = build_applicability_evidence(
            day=10,
            calendar_date="2026-08-24",
            applicability_truth={"no_trade": True},
            reasons={},
        )
        assert evidence.applicability["no_trade"] is False
        assert "no_trade" not in evidence.reasons

    def test_applicability_is_deterministic(self) -> None:
        first = build_applicability_evidence(
            day=11,
            calendar_date="2026-08-25",
            applicability_truth={"session": True},
            reasons={"session": "overnight session"},
        )
        second = build_applicability_evidence(
            day=11,
            calendar_date="2026-08-25",
            applicability_truth={"session": True},
            reasons={"session": "overnight session"},
        )
        assert first.model_dump() == second.model_dump()

    def test_day_range_covers_second_real_week(self) -> None:
        for day in range(8, 15):
            evidence = build_applicability_evidence(
                day=day,
                calendar_date=f"2026-08-{day:02d}",
                applicability_truth={},
                reasons={},
            )
            assert evidence.complete is True
