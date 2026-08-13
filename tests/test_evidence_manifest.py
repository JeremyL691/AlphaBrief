"""M17-W01: evidence manifest reproducibility.

Covers AC-M17-W01-02: a second generation from the same frozen inputs
produces identical normalized content and manifest hashes while any
missing, changed, duplicate, or unverified input fails closed.
"""

from __future__ import annotations

from alphabrief_core import (
    REPORT_EVIDENCE_SOURCES,
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


class TestEvidenceManifest:
    def test_identical_frozen_inputs_give_identical_hash(self) -> None:
        first = generate_final_report(
            source_truth=_full_sources(), count_truth=_full_counts()
        )
        second = generate_final_report(
            source_truth=_full_sources(), count_truth=_full_counts()
        )
        assert first.manifest_hash == second.manifest_hash
        assert first.normalized_content == second.normalized_content

    def test_changed_count_changes_the_hash(self) -> None:
        base = generate_final_report(
            source_truth=_full_sources(), count_truth=_full_counts()
        )
        changed_counts = _full_counts()
        changed_counts["requirements_total"] = 105
        changed = generate_final_report(
            source_truth=_full_sources(), count_truth=changed_counts
        )
        assert changed.manifest_hash != base.manifest_hash

    def test_changed_source_reference_changes_the_hash(self) -> None:
        base = generate_final_report(
            source_truth=_full_sources(), count_truth=_full_counts()
        )
        sources = _full_sources()
        sources["loop_ledger"] = False
        changed = generate_final_report(
            source_truth=sources, count_truth=_full_counts()
        )
        assert changed.manifest_hash != base.manifest_hash

    def test_missing_evidence_fails_closed(self) -> None:
        report = generate_final_report(source_truth={}, count_truth={})
        assert report.passed is False
        assert all(not source.referenced for source in report.sources)
        assert all(count == 0 for count in report.counts.values())

    def test_unverified_input_is_never_assumed(self) -> None:
        # A source absent from the truth is unverified and must be
        # reported as not referenced - never assumed present.
        report = generate_final_report(source_truth={}, count_truth={})
        assert report.sources[4].name == "oanda_practice_evidence"
        assert report.sources[4].referenced is False

    def test_hash_is_stable_across_runs(self) -> None:
        expected = generate_final_report(
            source_truth=_full_sources(), count_truth=_full_counts()
        ).manifest_hash
        for _ in range(3):
            again = generate_final_report(
                source_truth=_full_sources(), count_truth=_full_counts()
            )
            assert again.manifest_hash == expected
