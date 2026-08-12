from pathlib import Path

from alphabrief_acceptance import build_acceptance_report, build_preflight_report

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
        "docs.blueprint_current",
        "quality.tooling_configured",
        "paper.preflight",
    }


def test_acceptance_report_fails_when_required_doc_missing(tmp_path: Path) -> None:
    report = build_acceptance_report(tmp_path)

    assert report.passed is False
    docs_check = next(
        check for check in report.checks if check.check_id == "docs.required"
    )
    assert docs_check.status == "failed"
    assert "missing" in docs_check.evidence


def test_preflight_passes_current_repo() -> None:
    report = build_preflight_report(ROOT, scope="paper")

    assert report.passed is True
    assert report.failed_count == 0
    assert {check.check_id for check in report.checks} == {"paper.preflight"}
    preflight = report.checks[0]
    assert preflight.status == "passed"
    assert "ready" in preflight.title.lower()


def test_preflight_fails_when_runbook_missing(tmp_path: Path) -> None:
    _seed_minimal_repo(tmp_path)
    (tmp_path / "docs" / "oanda_30_day_runbook.md").unlink()

    report = build_preflight_report(tmp_path, scope="paper")

    assert report.passed is False
    preflight = report.checks[0]
    assert preflight.status == "failed"
    assert preflight.check_id == "paper.preflight"
    assert "oanda_30_day_runbook.md" in (preflight.detail or "")


def test_preflight_fails_when_env_var_name_missing(tmp_path: Path) -> None:
    _seed_minimal_repo(tmp_path)
    (tmp_path / ".env.example").write_text(
        "ALPHABRIEF_ENV=local\n", encoding="utf-8"
    )

    report = build_preflight_report(tmp_path, scope="paper")

    assert report.passed is False
    preflight = report.checks[0]
    assert preflight.status == "failed"
    assert "ALPHABRIEF_OANDA_TOKEN" in (preflight.detail or "")
    assert "ALPHABRIEF_OANDA_ACCOUNT_ID" in (preflight.detail or "")


def test_preflight_fails_when_paper_policy_missing(tmp_path: Path) -> None:
    _seed_minimal_repo(tmp_path)
    (tmp_path / "config" / "paper_execution_policy.yaml").unlink()

    report = build_preflight_report(tmp_path, scope="paper")

    assert report.passed is False
    preflight = report.checks[0]
    assert preflight.status == "failed"
    assert "paper_execution_policy" in (preflight.detail or "")


def test_preflight_unknown_scope_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown acceptance scope"):
        build_preflight_report(ROOT, scope="nope")


def _seed_minimal_repo(tmp_path: Path) -> None:
    """Create just enough files at ``tmp_path`` for pre-flight to partially work."""

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "oanda_30_day_runbook.md").write_text(
        "# OANDA 30-Day Runbook\n", encoding="utf-8"
    )
    (tmp_path / ".env.example").write_text(
        "ALPHABRIEF_OANDA_TOKEN=\nALPHABRIEF_OANDA_ACCOUNT_ID=\n",
        encoding="utf-8",
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "paper_execution_policy.yaml").write_text(
        "\n".join(
            [
                "mode: paper",
                "provider: oanda_paper",
                "market: fx",
                "symbols: [EUR_USD]",
                "order_types: [market]",
                "timezone: America/New_York",
                "trading_days: [mon, tue, wed, thu, fri]",
                "session_start: '00:00'",
                "session_end: '23:59'",
                "require_human_review: true",
                "automated_execution: false",
                "max_order_notional: \"100\"",
                "max_total_exposure: \"300\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "oanda_paper.yaml").write_text(
        "base_url: https://api-fxpractice.oanda.com\n"
        "request_timeout_seconds: 5.0\n"
        "max_order_attempts: 3\n"
        "retry_backoff_seconds: 0.25\n",
        encoding="utf-8",
    )
