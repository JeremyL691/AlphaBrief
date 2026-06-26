from pathlib import Path

from alphabrief_acceptance import build_acceptance_report

ROOT = Path(__file__).resolve().parents[1]


def test_acceptance_report_passes_current_repo() -> None:
    report = build_acceptance_report(ROOT)

    assert report.passed is True
    assert report.failed_count == 0
    assert report.total == len(report.checks)
    assert {check.check_id for check in report.checks} >= {
        "docs.required",
        "runtime.imports",
        "config.paper_only_default",
        "execution.paper_policy",
        "risk.live_lock",
        "models.kronos_advisory",
        "safety.reference_isolation",
        "safety.provider_sdk_imports",
        "docs.final_report_current",
        "quality.tooling_configured",
    }


def test_acceptance_report_fails_when_required_doc_missing(tmp_path: Path) -> None:
    report = build_acceptance_report(tmp_path)

    assert report.passed is False
    docs_check = next(
        check for check in report.checks if check.check_id == "docs.required"
    )
    assert docs_check.status == "failed"
    assert "missing" in docs_check.evidence
