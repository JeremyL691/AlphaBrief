"""M15-W06: tracked secret scan.

Covers AC-M15-W06-01 secret-scan gate: tracked secrets are detected by
the deterministic scan, and committed artifacts carry none.
"""

from __future__ import annotations

from pathlib import Path

from alphabrief_core import scan_files_for_secrets

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestSecretScanGate:
    def test_runtime_sources_have_no_tracked_secrets(self) -> None:
        findings = scan_files_for_secrets([REPO_ROOT / "packages"])
        assert findings == ()

    def test_api_sources_have_no_tracked_secrets(self) -> None:
        findings = scan_files_for_secrets([REPO_ROOT / "apps"])
        assert findings == ()

    def test_configuration_has_no_tracked_secrets(self) -> None:
        config = REPO_ROOT / "config"
        if config.exists():
            findings = scan_files_for_secrets([config])
            assert findings == ()

    def test_docs_artifacts_have_no_tracked_secrets(self) -> None:
        findings = scan_files_for_secrets([REPO_ROOT / "docs"])
        assert findings == ()

    def test_scan_is_deterministic(self) -> None:
        sources = [REPO_ROOT / "packages", REPO_ROOT / "apps"]
        first = scan_files_for_secrets(sources)
        second = scan_files_for_secrets(sources)
        assert first == second
