"""M17-W01: evidence-derived final acceptance report.

Covers AC-M17-W01-01: reports derive every requirement, work item,
acceptance result, quality count, safety invariant, observation metric,
incident, and known limitation from referenced immutable evidence
rather than handwritten totals.
"""

from __future__ import annotations

from alphabrief_core import (
    REPORT_COUNT_FIELDS,
    REPORT_EVIDENCE_SOURCES,
    FinalReport,
    ReportSource,
    generate_final_report,
)


def _full_sources() -> dict[str, bool]:
    return {name: True for name in REPORT_EVIDENCE_SOURCES}


def _full_counts() -> dict[str, int]:
    return {
        "requirements_total": 104,
        "work_items_total": 112,
        "acceptance_passed": 338,
        "acceptance_total": 338,
        "quality_passed": 6,
        "quality_total": 6,
        "safety_invariants_zero": 5,
        "safety_invariants_total": 5,
        "observation_days_qualified": 30,
        "observation_days_total": 30,
        "incidents_open": 0,
        "known_limitations": 2,
    }


class TestFinalReport:
    def test_all_six_sources_are_declared(self) -> None:
        assert REPORT_EVIDENCE_SOURCES == (
            "requirements_map",
            "database_facts",
            "loop_ledger",
            "test_results",
            "oanda_practice_evidence",
            "observation_artifact_hashes",
        )

    def test_all_twelve_count_fields_are_declared(self) -> None:
        assert REPORT_COUNT_FIELDS == (
            "requirements_total",
            "work_items_total",
            "acceptance_passed",
            "acceptance_total",
            "quality_passed",
            "quality_total",
            "safety_invariants_zero",
            "safety_invariants_total",
            "observation_days_qualified",
            "observation_days_total",
            "incidents_open",
            "known_limitations",
        )

    def test_full_evidence_passes(self) -> None:
        report = generate_final_report(
            source_truth=_full_sources(), count_truth=_full_counts()
        )
        assert isinstance(report, FinalReport)
        assert report.passed is True
        assert report.counts["requirements_total"] == 104
        assert report.counts["observation_days_qualified"] == 30

    def test_missing_source_fails_closed(self) -> None:
        report = generate_final_report(
            source_truth={}, count_truth=_full_counts()
        )
        assert report.passed is False
        assert all(not source.referenced for source in report.sources)
        # Handwritten totals are never accepted: without any supplied
        # evidence counts stay zero (covered by the empty-truth case
        # in the evidence-manifest suite).

    def test_no_supplied_evidence_means_zero_counts(self) -> None:
        report = generate_final_report(source_truth={}, count_truth={})
        assert report.passed is False
        assert all(count == 0 for count in report.counts.values())

    def test_partial_sources_fail_the_report(self) -> None:
        sources = _full_sources()
        sources["oanda_practice_evidence"] = False
        report = generate_final_report(
            source_truth=sources, count_truth=_full_counts()
        )
        assert report.passed is False

    def test_counts_are_typed_and_frozen(self) -> None:
        report = generate_final_report(
            source_truth=_full_sources(), count_truth=_full_counts()
        )
        assert isinstance(report.sources[0], ReportSource)

    def test_deterministic(self) -> None:
        first = generate_final_report(
            source_truth=_full_sources(), count_truth=_full_counts()
        )
        second = generate_final_report(
            source_truth=_full_sources(), count_truth=_full_counts()
        )
        assert first.model_dump() == second.model_dump()
